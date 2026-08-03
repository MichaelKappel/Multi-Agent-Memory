import json
import hashlib
import os
import ssl
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from scripts import (
    build_deploy_attempt_report,
    ftp_deploy_memoryendpoints,
    ftp_deploy_static_site,
    multiagentmemory_release_identity,
    package_memoryendpoints,
    package_multiagentmemory_static_site,
)


ROOT = Path(__file__).resolve().parents[1]


class TruthOrderedFtp:
    def __init__(self, *, readback_drift=None, fail_after_store=None):
        self.readback_drift = readback_drift
        self.fail_after_store = fail_after_store
        self.remote = {}
        self.events = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cwd(self, _path):
        return None

    def mkd(self, _path):
        return None

    def storbinary(self, command, handle):
        name = command.removeprefix("STOR ")
        self.remote[name] = handle.read()
        self.events.append(("STOR", name))
        if name == self.fail_after_store:
            raise OSError("simulated failure after remote consumed held bytes")

    def retrbinary(self, command, callback):
        name = command.removeprefix("RETR ")
        self.events.append(("RETR", name))
        data = self.remote[name]
        callback(data + b"drift" if name == self.readback_drift else data)


class DeployProtocolTests(unittest.TestCase):
    @staticmethod
    def qualified_source_identity(version="1.0.0"):
        commit = "a" * 40
        return {
            "repositoryUrl": multiagentmemory_release_identity.PUBLIC_REPOSITORY_URL,
            "commitSha": commit,
            "requiredTagName": multiagentmemory_release_identity.tag_name_for_version(
                version
            ),
            "requiredTagRef": multiagentmemory_release_identity.tag_ref_for_version(
                version
            ),
            "requiredTagUrl": multiagentmemory_release_identity.tag_url_for_version(
                version
            ),
            "requiredTagTargetCommitSha": commit,
            "remoteName": multiagentmemory_release_identity.REMOTE_NAME,
            "preactivationRemoteMainCommitSha": "c" * 40,
        }

    def setUp(self):
        def qualified_source(
            _repo_root, _site_root, ledger, _allowed_paths, _site_manifest, **kwargs
        ):
            source = self.qualified_source_identity(
                ledger["currentProductionWebsiteVersion"]
            )
            phase = kwargs["phase"]
            final = phase == multiagentmemory_release_identity.FINAL_PHASE
            return {
                "sourceIdentity": source,
                "qualification": {
                    "phase": phase,
                    "localTagPresent": final,
                    "remoteTagPresent": final,
                    "localTagObjectSha": "b" * 40 if final else None,
                    "remoteTagObjectSha": "b" * 40 if final else None,
                    "localTagTargetCommitSha": source["commitSha"] if final else None,
                    "remoteTagTargetCommitSha": source["commitSha"] if final else None,
                    "localTagDeclaredName": (
                        source["requiredTagName"] if final else None
                    ),
                    "annotatedTagNameVerified": final,
                    "remoteMainObservedCommitSha": (
                        None if final else source["preactivationRemoteMainCommitSha"]
                    ),
                    "remoteMainLeaseVerified": not final,
                    "commitSiteBytesVerified": True,
                    "tagSiteBytesVerified": final,
                    "valuesRedacted": True,
                },
            }

        self.release_source_patcher = patch.object(
            package_multiagentmemory_static_site,
            "qualify_release_source",
            side_effect=qualified_source,
        )
        self.release_source_patcher.start()

    def tearDown(self):
        self.release_source_patcher.stop()

    @staticmethod
    def static_profile_fields():
        return (
            {
                "ftp server": "example.invalid",
                "ftp username": "static-user",
                "password": "static-secret",
                "ftp & explicit ftps port": "21",
            },
            {
                "status": "filezilla_site_matched",
                "siteIndex": 1,
                "siteNameFingerprint": "abc123",
                "siteMatch": "multiagentmemory",
                "targetBinding": "profile_name",
                "targetIdentityConfirmed": True,
                "hasRemoteDir": False,
                "valuesRedacted": True,
            },
        )

    def run_release_phase(
        self, temporary, ftp, activation_gate, phase, *, dry_run=False
    ):
        site_root = ROOT / "sites" / "multiagentmemory.com"
        _snapshot, zip_bytes, manifest, _qualification = (
            package_multiagentmemory_static_site.expected_package(site_root)
        )
        package_path = temporary / "multiagentmemory-site-v1.0.0.zip"
        manifest_path = temporary / "multiagentmemory-site-v1.0.0.manifest.json"
        report_path = temporary / "deploy-report.json"
        package_path.write_bytes(zip_bytes)
        manifest_path.write_bytes(
            package_multiagentmemory_static_site.manifest_bytes(manifest)
        )
        with (
            patch.object(
                ftp_deploy_static_site,
                "load_filezilla_site",
                return_value=self.static_profile_fields(),
            ),
            patch.object(
                ftp_deploy_static_site,
                "release_activation_gate",
                side_effect=activation_gate,
            ),
            patch.object(ftp_deploy_static_site, "connect_ftp", return_value=ftp),
        ):
            arguments = [
                "--phase",
                phase,
                "--site-root",
                str(site_root),
                "--package",
                str(package_path),
                "--package-manifest",
                str(manifest_path),
                "--filezilla-site-match",
                "multiagentmemory",
                "--json-out",
                str(report_path),
            ]
            if dry_run:
                arguments.insert(0, "--dry-run")
            exit_code = ftp_deploy_static_site.main(arguments)
        return exit_code, json.loads(report_path.read_text(encoding="utf-8"))

    def stage_then_activate(self, temporary, ftp, activation_gate):
        stage_exit, stage_report = self.run_release_phase(
            temporary, ftp, activation_gate, "preactivation"
        )
        self.assertEqual(0, stage_exit)
        self.assertEqual("nonclaims_staged_preactivation", stage_report["status"])
        final_exit, final_report = self.run_release_phase(
            temporary, ftp, activation_gate, "final"
        )
        return final_exit, final_report

    def test_package_excludes_visual_studio_runtime_state(self):
        self.assertFalse(
            package_memoryendpoints.should_include_rel(
                Path(".vs") / "solution" / "index.vsidx"
            )
        )

    def test_package_dirty_paths_include_ignored_extra_and_missing_tracked_files(self):
        files = [
            (Path("unused-app"), Path("memoryendpoints/app.py")),
            (Path("unused-env"), Path(".env")),
        ]
        with (
            patch.object(
                package_memoryendpoints,
                "git_tracked_paths",
                return_value={
                    "memoryendpoints/app.py",
                    "scripts/deleted_release_file.py",
                },
            ),
            patch.object(
                package_memoryendpoints,
                "git_status_paths",
                return_value=["memoryendpoints/app.py"],
            ),
        ):
            dirty = package_memoryendpoints.packaged_dirty_paths(files)

        self.assertEqual(
            [".env", "memoryendpoints/app.py", "scripts/deleted_release_file.py"],
            dirty,
        )

    def test_package_main_fails_closed_without_writing_dirty_source(self):
        build_info = {
            "sourceSha": "a" * 40,
            "sourceShaShort": "a" * 12,
            "contentHash": "b" * 64,
            "sourceWorktreeDirty": True,
            "sourceDirtyPathCount": 1,
        }
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "package-report.json"
            package_path = Path(tmp) / "production.zip"
            with (
                patch.object(
                    package_memoryendpoints,
                    "inspect_current_source",
                    return_value={
                        "files": [],
                        "sourceSha": build_info["sourceSha"],
                        "contentHash": build_info["contentHash"],
                        "dirtyPaths": ["memoryendpoints/app.py"],
                    },
                ),
                patch.object(
                    package_memoryendpoints,
                    "write_build_info",
                    return_value=build_info,
                ),
                patch.object(
                    package_memoryendpoints,
                    "iter_files",
                    return_value=iter(()),
                ),
                patch.object(package_memoryendpoints, "PACKAGE", package_path),
            ):
                exit_code = package_memoryendpoints.main(
                    ["--json-out", str(report_path)]
                )
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(1, exit_code)
        self.assertEqual("dirty_packaged_source", report["status"])
        self.assertTrue(report["safeNoOp"])
        self.assertFalse(report["written"])
        self.assertFalse(package_path.exists())

    def test_package_main_fails_closed_when_git_revision_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "package-report.json"
            package_path = Path(tmp) / "production.zip"
            with (
                patch.object(
                    package_memoryendpoints,
                    "inspect_current_source",
                    side_effect=package_memoryendpoints.SourceRevisionError("redacted"),
                ),
                patch.object(package_memoryendpoints, "PACKAGE", package_path),
            ):
                exit_code = package_memoryendpoints.main(
                    ["--json-out", str(report_path)]
                )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertFalse(package_path.exists())

        self.assertEqual(1, exit_code)
        self.assertEqual("source_revision_unavailable", report["status"])
        self.assertTrue(report["safeNoOp"])
        self.assertNotIn("redacted", str(report))

    def test_dirty_build_info_is_reported_without_rewriting_generated_marker(self):
        source = {
            "sourceSha": "a" * 40,
            "contentHash": "b" * 64,
            "dirtyPaths": ["memoryendpoints/app.py"],
        }
        with (
            patch.object(
                package_memoryendpoints,
                "inspect_current_source",
                return_value=source,
            ),
            patch.object(
                package_memoryendpoints,
                "write_build_info",
                return_value={"sourceWorktreeDirty": True},
            ) as write_build_info,
        ):
            package_memoryendpoints.write_current_build_info()

        self.assertFalse(write_build_info.call_args.kwargs["write"])

    def test_clean_package_check_accepts_stable_content_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_path = Path(tmp) / "app.py"
            source_path.write_text("print('clean')\n", encoding="utf-8")
            files = [(source_path, Path("app.py"))]
            content_hash = package_memoryendpoints.source_content_hash(files)
            source = {
                "files": files,
                "sourceSha": "a" * 40,
                "contentHash": content_hash,
                "dirtyPaths": [],
            }
            build_info = {
                "sourceSha": source["sourceSha"],
                "sourceShaShort": "a" * 12,
                "contentHash": content_hash,
                "sourceWorktreeDirty": False,
                "sourceDirtyPathCount": 0,
            }
            report_path = Path(tmp) / "package-report.json"
            with (
                patch.object(
                    package_memoryendpoints,
                    "inspect_current_source",
                    return_value=source,
                ),
                patch.object(
                    package_memoryendpoints,
                    "write_build_info",
                    return_value=build_info,
                ),
                patch.object(
                    package_memoryendpoints,
                    "iter_files",
                    return_value=iter(files),
                ),
            ):
                exit_code = package_memoryendpoints.main(
                    ["--check-only", "--json-out", str(report_path)]
                )
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertEqual("ready", report["status"])
        self.assertTrue(report["sourceRevisionVerified"])
        self.assertEqual(content_hash, report["snapshotContentHash"])

    def test_transport_security_labels_are_explicit(self):
        self.assertEqual(
            "explicit_ftps", ftp_deploy_memoryendpoints.transport_security("ftps")
        )
        self.assertEqual(
            "plain_ftp", ftp_deploy_memoryendpoints.transport_security("ftp")
        )
        self.assertEqual(
            "explicit_ftps", ftp_deploy_static_site.transport_security("ftps")
        )
        self.assertEqual("plain_ftp", ftp_deploy_static_site.transport_security("ftp"))

    def test_static_ftps_authenticates_the_server_certificate_and_hostname(self):
        observed = {}

        class FakeTls:
            def __init__(self, context):
                observed["context"] = context

            def connect(self, host, port, timeout):
                observed["connect"] = (host, port, timeout)

            def login(self, user, password):
                observed["login"] = (user, password)

            def prot_p(self):
                observed["protectedData"] = True

        with patch.object(ftp_deploy_static_site.ftplib, "FTP_TLS", FakeTls):
            ftp = ftp_deploy_static_site.connect_ftp(
                "multiagentmemory.com", "user", "test-only-password", 21, "ftps"
            )

        self.assertIsInstance(ftp, FakeTls)
        self.assertEqual(ssl.CERT_REQUIRED, observed["context"].verify_mode)
        self.assertTrue(observed["context"].check_hostname)
        self.assertTrue(observed["protectedData"])

    def test_deploy_scripts_expose_no_upload_connection_check(self):
        endpoint_script = (
            ROOT / "scripts" / "ftp_deploy_memoryendpoints.py"
        ).read_text(encoding="utf-8")
        static_script = (ROOT / "scripts" / "ftp_deploy_static_site.py").read_text(
            encoding="utf-8"
        )
        for script in (endpoint_script, static_script):
            self.assertIn("--connection-check", script)
            self.assertIn("--filezilla-site-match", script)
            self.assertIn("connection_check_passed", script)
            self.assertIn("uploadedCount", script)
            self.assertIn("args.dry_run or args.connection_check", script)

    def test_memoryendpoints_filezilla_callers_bind_their_fixed_domain(self):
        for relative in (
            "scripts/ftp_deploy_memoryendpoints.py",
            "scripts/upload_mysql_secret_config.py",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn(
                'args.filezilla_path, args.filezilla_site_match, "memoryendpoints.com"',
                text,
                msg=relative,
            )

    def test_static_site_section_probe_is_redacted(self):
        handoff = """NeuralWikis.com
FTP Server: example.invalid
FTP Username: neural-user
Password: neural-secret

MemoryEndpoints and MultiAgentMemory
FTP Server: example.invalid
FTP Username: multi-user
Password: multi-secret
"""
        calls = []
        original_connect = ftp_deploy_static_site.connect_ftp

        class FakeFtp:
            def __init__(self, user):
                self.user = user

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def pwd(self):
                return "/redacted-home"

        def fake_connect(host, user, password, port, protocol):
            calls.append((user, protocol))
            if user == "multi-user":
                raise PermissionError("login rejected")
            return FakeFtp(user)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "handoff.txt"
            path.write_text(handoff, encoding="utf-8")
            try:
                ftp_deploy_static_site.connect_ftp = fake_connect
                report = ftp_deploy_static_site.redacted_section_probe(
                    path, "multiagentmemory.com"
                )
            finally:
                ftp_deploy_static_site.connect_ftp = original_connect

        text = str(report)
        self.assertTrue(report["anySectionLoginPassed"])
        self.assertFalse(report["targetSectionLoginPassed"])
        self.assertIn(("neural-user", "ftps"), calls)
        self.assertTrue(all(protocol == "ftps" for _user, protocol in calls))
        self.assertNotIn("neural-secret", text)
        self.assertNotIn("multi-secret", text)
        self.assertNotIn("example.invalid", text)
        self.assertNotIn("multi-user", text)

    def test_static_section_probe_uses_plain_ftp_only_when_explicitly_selected(self):
        handoff = "MultiAgentMemory.com\nFTP Server: example.invalid\nFTP Username: user\nPassword: test-only-secret\n"
        calls = []

        class FakeFtp:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def pwd(self):
                return "/redacted"

        def fake_connect(host, user, password, port, protocol):
            calls.append(protocol)
            return FakeFtp()

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "handoff.txt"
            path.write_text(handoff, encoding="utf-8")
            with patch.object(
                ftp_deploy_static_site, "connect_ftp", side_effect=fake_connect
            ):
                report = ftp_deploy_static_site.redacted_section_probe(
                    path, "multiagentmemory.com", protocol="ftp"
                )

        self.assertEqual(["ftp"], calls)
        self.assertEqual("ftp", report["protocol"])
        self.assertFalse(report["sections"][0]["ftp"]["serverCertificateVerification"])
        self.assertNotIn("ftps", report["sections"][0])

    def test_static_filezilla_target_connection_check_does_not_require_or_parse_handoff(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            site_root = Path(tmp) / "site"
            site_root.mkdir()
            (site_root / "index.html").write_text(
                "<!doctype html><title>safe</title>\n", encoding="utf-8"
            )
            report_path = Path(tmp) / "report.json"
            missing_handoff = Path(tmp) / "absent-handoff.txt"
            with (
                patch.object(
                    ftp_deploy_static_site,
                    "load_filezilla_site",
                    return_value=self.static_profile_fields(),
                ),
                patch.object(ftp_deploy_static_site, "parse_handoff") as parse_handoff,
                patch.object(
                    ftp_deploy_static_site, "parse_handoff_section"
                ) as parse_section,
                patch.object(ftp_deploy_static_site, "connect_ftp") as connect,
            ):
                exit_code = ftp_deploy_static_site.main(
                    [
                        "--connection-check",
                        "--site-root",
                        str(site_root),
                        "--handoff",
                        str(missing_handoff),
                        "--filezilla-site-match",
                        "multiagentmemory",
                        "--json-out",
                        str(report_path),
                    ]
                )
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertEqual("connection_check_passed", report["status"])
        self.assertEqual("filezilla_site_manager", report["credentialSource"])
        self.assertEqual("filezilla_login_root", report["remoteDirSource"])
        self.assertTrue(report["manifestRecheckedBeforeConnection"])
        self.assertEqual(0, report["plannedUploadCount"])
        self.assertTrue(report["safeNoOp"])
        parse_handoff.assert_not_called()
        parse_section.assert_not_called()
        connect.assert_called_once()
        public_text = json.dumps(report)
        self.assertNotIn("static-secret", public_text)
        self.assertNotIn(str(missing_handoff), public_text)
        self.assertNotIn(str(site_root), public_text)

    def test_static_release_dry_run_requires_the_closed_package_identity_before_connection(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            with (
                patch.object(
                    ftp_deploy_static_site,
                    "load_filezilla_site",
                    return_value=self.static_profile_fields(),
                ),
                patch.object(ftp_deploy_static_site, "connect_ftp") as connect,
            ):
                exit_code = ftp_deploy_static_site.main(
                    [
                        "--dry-run",
                        "--phase",
                        "preactivation",
                        "--site-root",
                        str(ROOT / "sites" / "multiagentmemory.com"),
                        "--filezilla-site-match",
                        "multiagentmemory",
                        "--json-out",
                        str(report_path),
                    ]
                )
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(1, exit_code)
        self.assertEqual("immutable_package_required", report["status"])
        self.assertTrue(report["safeNoOp"])
        self.assertEqual(0, report.get("uploadedCount", 0))
        connect.assert_not_called()

    def test_static_target_only_connection_check_rejects_release_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            with (
                patch.object(
                    ftp_deploy_static_site,
                    "load_filezilla_site",
                    return_value=self.static_profile_fields(),
                ),
                patch.object(ftp_deploy_static_site, "connect_ftp") as connect,
            ):
                exit_code = ftp_deploy_static_site.main(
                    [
                        "--connection-check",
                        "--package",
                        str(Path(tmp) / "release.zip"),
                        "--package-manifest",
                        str(Path(tmp) / "release.manifest.json"),
                        "--filezilla-site-match",
                        "multiagentmemory",
                        "--json-out",
                        str(report_path),
                    ]
                )
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(1, exit_code)
        self.assertEqual("connection_check_is_target_only", report["status"])
        self.assertTrue(report["safeNoOp"])
        connect.assert_not_called()

    def test_static_missing_filezilla_profile_does_not_fall_back_to_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            site_root = Path(tmp) / "site"
            site_root.mkdir()
            (site_root / "index.html").write_text("safe\n", encoding="utf-8")
            report_path = Path(tmp) / "report.json"
            with (
                patch.object(
                    ftp_deploy_static_site,
                    "load_filezilla_site",
                    return_value=(
                        None,
                        {"status": "filezilla_site_not_found", "valuesRedacted": True},
                    ),
                ),
                patch.object(ftp_deploy_static_site, "parse_handoff") as parse_handoff,
                patch.object(
                    ftp_deploy_static_site, "parse_handoff_section"
                ) as parse_section,
            ):
                exit_code = ftp_deploy_static_site.main(
                    [
                        "--dry-run",
                        "--phase",
                        "preactivation",
                        "--site-root",
                        str(site_root),
                        "--handoff",
                        str(Path(tmp) / "absent.txt"),
                        "--filezilla-site-match",
                        "multiagentmemory",
                        "--json-out",
                        str(report_path),
                    ]
                )
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(1, exit_code)
        self.assertEqual("filezilla_site_not_found", report["status"])
        self.assertTrue(report["safeNoOp"])
        parse_handoff.assert_not_called()
        parse_section.assert_not_called()

    def test_static_handoff_only_absence_fails_closed_and_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            site_root = Path(tmp) / "site"
            site_root.mkdir()
            (site_root / "index.html").write_text("safe\n", encoding="utf-8")
            report_path = Path(tmp) / "report.json"
            handoff = Path(tmp) / "private-missing-handoff.txt"
            exit_code = ftp_deploy_static_site.main(
                [
                    "--connection-check",
                    "--site-root",
                    str(site_root),
                    "--handoff",
                    str(handoff),
                    "--json-out",
                    str(report_path),
                ]
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(1, exit_code)
        self.assertEqual("handoff_unavailable", report["status"])
        self.assertTrue(report["safeNoOp"])
        self.assertNotIn(str(handoff), json.dumps(report))

    def test_static_section_probe_absence_fails_closed_and_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            handoff = Path(tmp) / "private-missing-handoff.txt"
            report_path = Path(tmp) / "report.json"
            exit_code = ftp_deploy_static_site.main(
                [
                    "--probe-sections",
                    "--handoff",
                    str(handoff),
                    "--json-out",
                    str(report_path),
                ]
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(1, exit_code)
        self.assertEqual("handoff_unavailable", report["status"])
        self.assertEqual([], report["sections"])
        self.assertTrue(report["safeNoOp"])
        self.assertNotIn(str(handoff), json.dumps(report))

    def test_static_explicit_remote_dir_never_waives_handoff_target_identity(self):
        handoff_text = "WrongSite.com\nFTP Server: wrong.invalid\nFTP Username: user\nPassword: test-only-secret\n"
        with tempfile.TemporaryDirectory() as tmp:
            site_root = Path(tmp) / "site"
            site_root.mkdir()
            (site_root / "index.html").write_text("safe\n", encoding="utf-8")
            handoff = Path(tmp) / "handoff.txt"
            handoff.write_text(handoff_text, encoding="utf-8")
            report_path = Path(tmp) / "report.json"
            exit_code = ftp_deploy_static_site.main(
                [
                    "--connection-check",
                    "--site-root",
                    str(site_root),
                    "--handoff",
                    str(handoff),
                    "--remote-dir",
                    ".",
                    "--json-out",
                    str(report_path),
                ]
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(1, exit_code)
        self.assertEqual("target_section_not_confirmed", report["status"])
        self.assertFalse(report["signals"]["selectedSectionMentionsTarget"])
        self.assertTrue(report["safeNoOp"])

    def test_static_handoff_identity_ignores_target_tokens_in_credentials_and_paths(
        self,
    ):
        handoff_text = "WrongSite.com\nFTP Server: wrong.invalid\nFTP Username: multiagentmemory\nPassword: multiagentmemory-secret\nRemote Dir: multiagentmemory\n"
        with tempfile.TemporaryDirectory() as tmp:
            site_root = Path(tmp) / "site"
            site_root.mkdir()
            (site_root / "index.html").write_text("safe\n", encoding="utf-8")
            handoff = Path(tmp) / "handoff.txt"
            handoff.write_text(handoff_text, encoding="utf-8")
            report_path = Path(tmp) / "report.json"
            exit_code = ftp_deploy_static_site.main(
                [
                    "--connection-check",
                    "--site-root",
                    str(site_root),
                    "--handoff",
                    str(handoff),
                    "--json-out",
                    str(report_path),
                ]
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(1, exit_code)
        self.assertEqual("target_section_not_confirmed", report["status"])
        self.assertFalse(report["signals"]["mentionsTarget"])
        self.assertNotIn("multiagentmemory-secret", json.dumps(report))

    def test_static_section_index_zero_is_invalid_and_never_auto_selects(self):
        handoff_text = "MultiAgentMemory.com\nFTP Server: example.invalid\nFTP Username: user\nPassword: test-only-secret\nRemote Dir: .\n"
        with tempfile.TemporaryDirectory() as tmp:
            site_root = Path(tmp) / "site"
            site_root.mkdir()
            (site_root / "index.html").write_text("safe\n", encoding="utf-8")
            handoff = Path(tmp) / "handoff.txt"
            handoff.write_text(handoff_text, encoding="utf-8")
            report_path = Path(tmp) / "report.json"
            exit_code = ftp_deploy_static_site.main(
                [
                    "--dry-run",
                    "--phase",
                    "preactivation",
                    "--site-root",
                    str(site_root),
                    "--handoff",
                    str(handoff),
                    "--section-index",
                    "0",
                    "--json-out",
                    str(report_path),
                ]
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(1, exit_code)
        self.assertEqual("section_index_invalid", report["status"])
        self.assertFalse(report["signals"]["sectionIndexValid"])
        self.assertTrue(report["safeNoOp"])

    def test_static_site_manifest_is_sorted_deterministic_and_detects_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            site_root = Path(tmp)
            (site_root / "robots.txt").write_bytes(b"robots\n")
            (site_root / "index.html").write_bytes(b"index\n")
            first = ftp_deploy_static_site.capture_site_snapshot(site_root)
            second = ftp_deploy_static_site.capture_site_snapshot(site_root)
            lines = "".join(
                f"{item['sha256']}  {item['bytes']}  {item['path']}\n"
                for item in first["manifest"]["files"]
            ).encode("utf-8")
            self.assertEqual(
                ["index.html", "robots.txt"],
                [item["path"] for item in first["manifest"]["files"]],
            )
            self.assertEqual(
                hashlib.sha256(lines).hexdigest(), first["manifest"]["aggregateSha256"]
            )
            self.assertEqual(
                {
                    "regularFilesOnly": True,
                    "symlinksJunctionsReparsePointsAllowed": False,
                    "resolvedWithinSelectedRoot": True,
                },
                first["manifest"]["containment"],
            )
            self.assertTrue(ftp_deploy_static_site.site_snapshot_matches(first, second))
            (site_root / "index.html").write_bytes(b"changed\n")
            third = ftp_deploy_static_site.capture_site_snapshot(site_root)

        self.assertFalse(ftp_deploy_static_site.site_snapshot_matches(first, third))

    def test_static_package_builder_is_reproducible_and_verifiable(self):
        site_root = ROOT / "sites" / "multiagentmemory.com"
        snapshot = package_multiagentmemory_static_site.capture_site_snapshot(
            site_root, require_complete=True
        )
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "multiagentmemory-site-v1.0.0.zip"
            manifest_path = Path(tmp) / "multiagentmemory-site-v1.0.0.manifest.json"
            args = [
                "--write",
                "--phase",
                "preactivation",
                "--site-root",
                str(site_root),
                "--package",
                str(package_path),
                "--manifest",
                str(manifest_path),
                "--expected-site-aggregate-sha256",
                snapshot["manifest"]["aggregateSha256"],
            ]
            self.assertEqual(0, package_multiagentmemory_static_site.main(args))
            first_zip = package_path.read_bytes()
            first_manifest = manifest_path.read_bytes()
            self.assertEqual(
                0,
                package_multiagentmemory_static_site.main(
                    [
                        "--check",
                        "--phase",
                        "preactivation",
                        "--site-root",
                        str(site_root),
                        "--package",
                        str(package_path),
                        "--manifest",
                        str(manifest_path),
                    ]
                ),
            )
            self.assertEqual(
                0,
                package_multiagentmemory_static_site.main(
                    [
                        "--verify",
                        "--phase",
                        "preactivation",
                        "--package",
                        str(package_path),
                        "--manifest",
                        str(manifest_path),
                    ]
                ),
            )
            self.assertEqual(0, package_multiagentmemory_static_site.main(args))
            self.assertEqual(first_zip, package_path.read_bytes())
            self.assertEqual(first_manifest, manifest_path.read_bytes())
            verified = package_multiagentmemory_static_site.verify_package(
                package_path,
                manifest_path,
                snapshot,
                phase=multiagentmemory_release_identity.PREACTIVATION_PHASE,
            )

        self.assertEqual(snapshot["manifest"], verified["manifest"])
        self.assertEqual(
            hashlib.sha256(first_zip).hexdigest(), verified["package"]["sha256"]
        )

    def test_static_package_excludes_cache_and_environment_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            site_root = Path(tmp)
            (site_root / "index.html").write_text("safe\n", encoding="utf-8")
            (site_root / ".env").write_text("PRIVATE=secret\n", encoding="utf-8")
            cache = site_root / "__pycache__"
            cache.mkdir()
            (cache / "state.pyc").write_bytes(b"cache")
            snapshot = package_multiagentmemory_static_site.capture_site_snapshot(
                site_root
            )

        self.assertEqual(
            ["index.html"], [item["path"] for item in snapshot["manifest"]["files"]]
        )

    def test_static_package_rejects_file_and_ancestor_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            external_file = parent / "outside.html"
            external_file.write_text("outside\n", encoding="utf-8")
            file_root = parent / "file-root"
            file_root.mkdir()
            try:
                os.symlink(external_file, file_root / "index.html")
            except NotImplementedError:
                self.skipTest("symlink support unavailable")
            except OSError as exc:
                if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
                    self.skipTest("symlink privilege unavailable")
                raise
            with self.assertRaises(
                package_multiagentmemory_static_site.SitePackageError
            ):
                package_multiagentmemory_static_site.capture_site_snapshot(file_root)

            external_dir = parent / "outside-docs"
            external_dir.mkdir()
            (external_dir / "how-it-works.html").write_text(
                "outside\n", encoding="utf-8"
            )
            directory_root = parent / "directory-root"
            directory_root.mkdir()
            os.symlink(external_dir, directory_root / "docs", target_is_directory=True)
            with self.assertRaises(
                package_multiagentmemory_static_site.SitePackageError
            ):
                package_multiagentmemory_static_site.capture_site_snapshot(
                    directory_root
                )

    def test_static_package_source_enforces_reparse_and_resolved_root_invariants(self):
        source = (
            ROOT / "scripts" / "package_multiagentmemory_static_site.py"
        ).read_text(encoding="utf-8")
        for invariant in (
            "FILE_ATTRIBUTE_REPARSE_POINT",
            "is_junction",
            "stat.S_ISLNK",
            "resolve(strict=True)",
            "os.path.commonpath",
            "site path resolves outside the selected root",
        ):
            self.assertIn(invariant, source)

    def test_static_package_rejects_noncanonical_names_and_version_relationship(self):
        site_root = ROOT / "sites" / "multiagentmemory.com"
        snapshot = package_multiagentmemory_static_site.capture_site_snapshot(
            site_root, require_complete=True
        )
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "multiagentmemory-site-v1.0.0.zip"
            manifest_path = Path(tmp) / "multiagentmemory-site-v1.0.0.manifest.json"
            self.assertEqual(
                0,
                package_multiagentmemory_static_site.main(
                    [
                        "--write",
                        "--phase",
                        "preactivation",
                        "--site-root",
                        str(site_root),
                        "--package",
                        str(package_path),
                        "--manifest",
                        str(manifest_path),
                        "--expected-site-aggregate-sha256",
                        snapshot["manifest"]["aggregateSha256"],
                    ]
                ),
            )
            wrong_package = Path(tmp) / "arbitrary.zip"
            wrong_package.write_bytes(package_path.read_bytes())
            with self.assertRaises(
                package_multiagentmemory_static_site.SitePackageError
            ):
                package_multiagentmemory_static_site.verify_package(
                    wrong_package,
                    manifest_path,
                    phase=multiagentmemory_release_identity.PREACTIVATION_PHASE,
                )
            wrong_manifest = Path(tmp) / "arbitrary.manifest.json"
            wrong_manifest.write_bytes(manifest_path.read_bytes())
            with self.assertRaises(
                package_multiagentmemory_static_site.SitePackageError
            ):
                package_multiagentmemory_static_site.verify_package(
                    package_path,
                    wrong_manifest,
                    phase=multiagentmemory_release_identity.PREACTIVATION_PHASE,
                )
            version_drift = json.loads(manifest_path.read_text(encoding="utf-8"))
            version_drift["websiteVersion"] = "1.0.1"
            manifest_path.write_text(
                json.dumps(version_drift, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(
                package_multiagentmemory_static_site.SitePackageError
            ):
                package_multiagentmemory_static_site.verify_package(
                    package_path,
                    manifest_path,
                    phase=multiagentmemory_release_identity.PREACTIVATION_PHASE,
                )

    def test_static_package_write_rejects_wrong_version_filename_without_output(self):
        site_root = ROOT / "sites" / "multiagentmemory.com"
        snapshot = package_multiagentmemory_static_site.capture_site_snapshot(
            site_root, require_complete=True
        )
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "multiagentmemory-site-v1.0.1.zip"
            manifest_path = Path(tmp) / "multiagentmemory-site-v1.0.1.manifest.json"
            report_path = Path(tmp) / "report.json"
            exit_code = package_multiagentmemory_static_site.main(
                [
                    "--write",
                    "--phase",
                    "preactivation",
                    "--site-root",
                    str(site_root),
                    "--package",
                    str(package_path),
                    "--manifest",
                    str(manifest_path),
                    "--expected-site-aggregate-sha256",
                    snapshot["manifest"]["aggregateSha256"],
                    "--json-out",
                    str(report_path),
                ]
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            package_exists = package_path.exists()

        self.assertEqual(1, exit_code)
        self.assertEqual("verification_failed", report["status"])
        self.assertTrue(report["safeNoOp"])
        self.assertFalse(report["written"])
        self.assertFalse(package_exists)

    def test_static_package_pair_write_rolls_back_if_manifest_publish_fails(self):
        site_root = ROOT / "sites" / "multiagentmemory.com"
        snapshot = package_multiagentmemory_static_site.capture_site_snapshot(
            site_root, require_complete=True
        )
        real_replace = os.replace
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "multiagentmemory-site-v1.0.0.zip"
            manifest_path = Path(tmp) / "multiagentmemory-site-v1.0.0.manifest.json"
            report_path = Path(tmp) / "report.json"

            def fail_manifest_publish(source, destination):
                if (
                    Path(destination).absolute() == manifest_path.absolute()
                    and Path(source).name == manifest_path.name
                ):
                    raise OSError("simulated manifest publication failure")
                return real_replace(source, destination)

            with patch.object(
                package_multiagentmemory_static_site.os,
                "replace",
                side_effect=fail_manifest_publish,
            ):
                exit_code = package_multiagentmemory_static_site.main(
                    [
                        "--write",
                        "--phase",
                        "preactivation",
                        "--site-root",
                        str(site_root),
                        "--package",
                        str(package_path),
                        "--manifest",
                        str(manifest_path),
                        "--expected-site-aggregate-sha256",
                        snapshot["manifest"]["aggregateSha256"],
                        "--json-out",
                        str(report_path),
                    ]
                )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            package_exists = package_path.exists()
            manifest_exists = manifest_path.exists()

        self.assertEqual(1, exit_code)
        self.assertEqual("write_failed_rolled_back", report["status"])
        self.assertFalse(report["partialArtifactState"])
        self.assertTrue(report["safeNoOp"])
        self.assertFalse(report["written"])
        self.assertFalse(package_exists)
        self.assertFalse(manifest_exists)

    def test_static_package_pair_reports_truthfully_if_rollback_cannot_remove_zip(self):
        site_root = ROOT / "sites" / "multiagentmemory.com"
        snapshot = package_multiagentmemory_static_site.capture_site_snapshot(
            site_root, require_complete=True
        )
        real_replace = os.replace
        real_unlink = Path.unlink
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "multiagentmemory-site-v1.0.0.zip"
            manifest_path = Path(tmp) / "multiagentmemory-site-v1.0.0.manifest.json"
            report_path = Path(tmp) / "report.json"

            def fail_manifest_publish(source, destination):
                if (
                    Path(destination).absolute() == manifest_path.absolute()
                    and Path(source).name == manifest_path.name
                ):
                    raise OSError("simulated manifest publication failure")
                return real_replace(source, destination)

            def fail_package_rollback(path, *args, **kwargs):
                if Path(path).absolute() == package_path.absolute():
                    raise OSError("simulated rollback failure")
                return real_unlink(path, *args, **kwargs)

            with (
                patch.object(
                    package_multiagentmemory_static_site.os,
                    "replace",
                    side_effect=fail_manifest_publish,
                ),
                patch.object(Path, "unlink", fail_package_rollback),
            ):
                exit_code = package_multiagentmemory_static_site.main(
                    [
                        "--write",
                        "--phase",
                        "preactivation",
                        "--site-root",
                        str(site_root),
                        "--package",
                        str(package_path),
                        "--manifest",
                        str(manifest_path),
                        "--expected-site-aggregate-sha256",
                        snapshot["manifest"]["aggregateSha256"],
                        "--json-out",
                        str(report_path),
                    ]
                )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            package_exists = package_path.exists()

        self.assertEqual(1, exit_code)
        self.assertEqual("write_failed_partial_possible", report["status"])
        self.assertTrue(report["partialArtifactState"])
        self.assertFalse(report["safeNoOp"])
        self.assertTrue(report["written"])
        self.assertTrue(package_exists)

    def test_static_package_manifest_schema_is_closed_and_private_data_scanned(self):
        site_root = ROOT / "sites" / "multiagentmemory.com"
        snapshot, zip_bytes, manifest, _qualification = (
            package_multiagentmemory_static_site.expected_package(site_root)
        )
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "multiagentmemory-site-v1.0.0.zip"
            manifest_path = Path(tmp) / "multiagentmemory-site-v1.0.0.manifest.json"
            package_path.write_bytes(zip_bytes)
            manifest["privateCredential"] = "embedded-private-field"
            manifest_path.write_bytes(
                package_multiagentmemory_static_site.manifest_bytes(manifest)
            )
            with self.assertRaises(
                (
                    package_multiagentmemory_static_site.SitePackageError,
                    multiagentmemory_release_identity.ReleaseIdentityError,
                )
            ):
                package_multiagentmemory_static_site.verify_package(
                    package_path,
                    manifest_path,
                    snapshot,
                    phase=multiagentmemory_release_identity.PREACTIVATION_PHASE,
                )
            manifest.pop("privateCredential")
            manifest["privatePath"] = r"C:\private\operator\handoff.txt"
            manifest_path.write_bytes(
                package_multiagentmemory_static_site.manifest_bytes(manifest)
            )
            with self.assertRaises(
                (
                    package_multiagentmemory_static_site.SitePackageError,
                    multiagentmemory_release_identity.ReleaseIdentityError,
                )
            ):
                package_multiagentmemory_static_site.verify_package(
                    package_path,
                    manifest_path,
                    snapshot,
                    phase=multiagentmemory_release_identity.PREACTIVATION_PHASE,
                )

    def test_static_package_verify_rejects_self_consistent_projection_drift(self):
        site_root = ROOT / "sites" / "multiagentmemory.com"
        source = package_multiagentmemory_static_site.capture_site_snapshot(
            site_root, require_complete=True
        )
        entries = [dict(entry) for entry in source["files"]]
        for entry in entries:
            if entry["relativePath"].as_posix() == "releases/index.html":
                entry["bytes"] += b"\n<!-- synthetic projection drift -->\n"
        tampered = {
            "files": entries,
            "manifest": package_multiagentmemory_static_site._manifest_from_entries(
                entries
            ),
        }
        zip_bytes = package_multiagentmemory_static_site.build_zip_bytes(tampered)
        ledger_entry = next(
            entry
            for entry in entries
            if entry["relativePath"].as_posix() == "releases.json"
        )
        ledger = json.loads(ledger_entry["bytes"].decode("utf-8"))
        manifest = package_multiagentmemory_static_site.build_package_manifest(
            tampered,
            zip_bytes,
            "multiagentmemory-site-v1.0.0.zip",
            "multiagentmemory-site-v1.0.0.manifest.json",
            ledger,
            hashlib.sha256(ledger_entry["bytes"]).hexdigest(),
            self.qualified_source_identity(),
        )
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "multiagentmemory-site-v1.0.0.zip"
            manifest_path = Path(tmp) / "multiagentmemory-site-v1.0.0.manifest.json"
            package_path.write_bytes(zip_bytes)
            manifest_path.write_bytes(
                package_multiagentmemory_static_site.manifest_bytes(manifest)
            )
            with self.assertRaises(
                package_multiagentmemory_static_site.SitePackageError
            ):
                package_multiagentmemory_static_site.verify_package(
                    package_path,
                    manifest_path,
                    phase=multiagentmemory_release_identity.PREACTIVATION_PHASE,
                )

    def test_release_projection_addition_fails_until_claim_order_is_explicit(self):
        site_root = ROOT / "sites" / "multiagentmemory.com"
        snapshot = package_multiagentmemory_static_site.capture_site_snapshot(
            site_root, require_complete=True
        )
        ledger, drift = package_multiagentmemory_static_site.snapshot_projection_drift(
            snapshot
        )
        self.assertIsNotNone(ledger)
        self.assertEqual([], drift)
        source_files = {
            entry["relativePath"].as_posix(): entry["bytes"]
            for entry in snapshot["files"]
        }
        projected = package_multiagentmemory_static_site.project_release_surfaces(
            source_files, ledger
        )
        projected["future-release-claim.txt"] = b"future claim\n"

        with patch.object(
            package_multiagentmemory_static_site,
            "project_release_surfaces",
            return_value=projected,
        ):
            with self.assertRaisesRegex(
                package_multiagentmemory_static_site.SitePackageError,
                "release projection claim order contract changed",
            ):
                package_multiagentmemory_static_site.snapshot_projection_drift(snapshot)

    def test_static_package_verify_rejects_zip_trailer_even_when_manifest_is_rebound(
        self,
    ):
        site_root = ROOT / "sites" / "multiagentmemory.com"
        snapshot, zip_bytes, manifest, _qualification = (
            package_multiagentmemory_static_site.expected_package(site_root)
        )
        tampered_zip = zip_bytes + b"synthetic-trailer"
        manifest["packageManifest"]["archive"]["bytes"] = len(tampered_zip)
        manifest["packageManifest"]["archive"]["sha256"] = hashlib.sha256(
            tampered_zip
        ).hexdigest()
        manifest["packageManifestSha256"] = hashlib.sha256(
            multiagentmemory_release_identity.canonical_json_bytes(
                manifest["packageManifest"]
            )
        ).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "multiagentmemory-site-v1.0.0.zip"
            manifest_path = Path(tmp) / "multiagentmemory-site-v1.0.0.manifest.json"
            package_path.write_bytes(tampered_zip)
            manifest_path.write_bytes(
                package_multiagentmemory_static_site.manifest_bytes(manifest)
            )
            with self.assertRaises(
                package_multiagentmemory_static_site.SitePackageError
            ):
                package_multiagentmemory_static_site.verify_package(
                    package_path,
                    manifest_path,
                    snapshot,
                    phase=multiagentmemory_release_identity.PREACTIVATION_PHASE,
                )

    def test_static_release_activation_gate_requires_exact_successful_upload_utc_date(
        self,
    ):
        ledger = json.loads(
            (ROOT / "sites" / "multiagentmemory.com" / "releases.json").read_text(
                encoding="utf-8"
            )
        )
        release_identity = {
            "websiteVersion": ledger["currentProductionWebsiteVersion"],
            "activationDate": ledger["releases"][0]["activationDate"],
        }
        ready = ftp_deploy_static_site.release_activation_gate(
            release_identity, "2026-08-03"
        )
        stale = ftp_deploy_static_site.release_activation_gate(
            release_identity, "2026-08-04"
        )

        self.assertTrue(ready["checked"])
        self.assertTrue(ready["ok"])
        self.assertEqual("1.0.0", ready["releaseVersion"])
        self.assertTrue(stale["checked"])
        self.assertFalse(stale["ok"])
        self.assertEqual("2026-08-03", stale["releaseActivationDate"])

    def test_static_live_upload_rejects_stale_deployed_claim_before_connection(self):
        site_root = ROOT / "sites" / "multiagentmemory.com"
        snapshot = package_multiagentmemory_static_site.capture_site_snapshot(
            site_root, require_complete=True
        )
        stale_gate = ftp_deploy_static_site.release_activation_gate(
            {"websiteVersion": "1.0.0", "activationDate": "2026-08-03"},
            "2026-08-04",
        )
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "multiagentmemory-site-v1.0.0.zip"
            manifest_path = Path(tmp) / "multiagentmemory-site-v1.0.0.manifest.json"
            report_path = Path(tmp) / "deploy-report.json"
            self.assertEqual(
                0,
                package_multiagentmemory_static_site.main(
                    [
                        "--write",
                        "--phase",
                        "preactivation",
                        "--site-root",
                        str(site_root),
                        "--package",
                        str(package_path),
                        "--manifest",
                        str(manifest_path),
                        "--expected-site-aggregate-sha256",
                        snapshot["manifest"]["aggregateSha256"],
                    ]
                ),
            )
            with (
                patch.object(
                    ftp_deploy_static_site,
                    "load_filezilla_site",
                    return_value=self.static_profile_fields(),
                ),
                patch.object(
                    ftp_deploy_static_site,
                    "release_activation_gate",
                    return_value=stale_gate,
                ),
                patch.object(ftp_deploy_static_site, "connect_ftp") as connect,
            ):
                exit_code = ftp_deploy_static_site.main(
                    [
                        "--phase",
                        "preactivation",
                        "--site-root",
                        str(site_root),
                        "--package",
                        str(package_path),
                        "--package-manifest",
                        str(manifest_path),
                        "--filezilla-site-match",
                        "multiagentmemory",
                        "--json-out",
                        str(report_path),
                    ]
                )
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(1, exit_code)
        self.assertEqual("activation_date_not_current_utc", report["status"])
        self.assertTrue(report["safeNoOp"])
        self.assertEqual(0, report.get("uploadedCount", 0))
        connect.assert_not_called()

    def test_static_release_dry_run_rejects_stale_activation_date(self):
        gate = ftp_deploy_static_site.release_activation_gate

        def stale_gate(identity, utc_date=None):
            return gate(identity, "2026-08-04")

        ftp = TruthOrderedFtp()
        with tempfile.TemporaryDirectory() as tmp:
            exit_code, report = self.run_release_phase(
                Path(tmp),
                ftp,
                stale_gate,
                "preactivation",
                dry_run=True,
            )

        self.assertEqual(1, exit_code)
        self.assertEqual("activation_date_not_current_utc", report["status"])
        self.assertTrue(report["safeNoOp"])
        self.assertEqual([], ftp.events)

    def test_static_release_dry_run_rechecks_utc_at_completion(self):
        gate = ftp_deploy_static_site.release_activation_gate
        utc_dates = iter(("2026-08-03", "2026-08-04"))

        def changing_gate(identity, utc_date=None):
            return gate(identity, next(utc_dates))

        ftp = TruthOrderedFtp()
        with tempfile.TemporaryDirectory() as tmp:
            exit_code, report = self.run_release_phase(
                Path(tmp),
                ftp,
                changing_gate,
                "preactivation",
                dry_run=True,
            )

        self.assertEqual(1, exit_code)
        self.assertEqual("activation_date_changed_during_dry_run", report["status"])
        self.assertTrue(report["manifestRecheckedAtDryRun"])
        self.assertFalse(report["releaseActivationGateAtDryRunCompletion"]["ok"])
        self.assertTrue(report["safeNoOp"])
        self.assertEqual([], ftp.events)

    def test_static_upload_uses_verified_package_bytes_and_rechecks_binding(self):
        gate = ftp_deploy_static_site.release_activation_gate
        ftp = TruthOrderedFtp()

        def current_gate(identity, utc_date=None):
            return gate(identity, "2026-08-03")

        with tempfile.TemporaryDirectory() as tmp:
            temporary = Path(tmp)
            stage_exit, stage_report = self.run_release_phase(
                temporary, ftp, current_gate, "preactivation"
            )
            stage_events = list(ftp.events)
            final_exit, final_report = self.run_release_phase(
                temporary, ftp, current_gate, "final"
            )

        claim_paths = list(multiagentmemory_release_identity.RELEASE_CLAIM_PATHS)
        non_claim_paths = sorted(
            set(package_multiagentmemory_static_site.ALLOWED_SITE_FILES)
            - set(claim_paths)
        )
        self.assertEqual(0, stage_exit)
        self.assertEqual("nonclaims_staged_preactivation", stage_report["status"])
        self.assertEqual(10, stage_report["uploadedCount"])
        self.assertEqual(10, stage_report["readbackVerifiedCount"])
        self.assertEqual(0, stage_report["claimUploadedCount"])
        self.assertFalse(stage_report["claimsExposed"])
        self.assertEqual(
            [("STOR", path) for path in non_claim_paths]
            + [("RETR", path) for path in non_claim_paths],
            stage_events,
        )
        self.assertFalse(any(path in claim_paths for _verb, path in stage_events))

        self.assertEqual(0, final_exit)
        self.assertEqual("claims_activated_final", final_report["status"])
        self.assertTrue(final_report["sourceTagPublished"])
        self.assertTrue(final_report["sourceTagIdentityVerified"])
        self.assertTrue(final_report["stagedNonClaimReadbackComplete"])
        self.assertEqual(0, final_report["nonClaimUploadedCount"])
        self.assertEqual(10, final_report["nonClaimReadbackCount"])
        self.assertEqual(6, final_report["claimUploadedCount"])
        self.assertEqual(6, final_report["claimReadbackCount"])
        final_events = ftp.events[len(stage_events) :]
        self.assertEqual(
            [("RETR", path) for path in non_claim_paths]
            + [
                event
                for path in claim_paths
                for event in (("STOR", path), ("RETR", path))
            ],
            final_events,
        )
        self.assertEqual(
            [
                ("STOR", "releases/index.html"),
                ("RETR", "releases/index.html"),
                ("STOR", "releases.json"),
                ("RETR", "releases.json"),
            ],
            final_events[-4:],
        )

    def test_static_first_stor_failure_after_send_reports_partial_mutation_not_safe_noop(
        self,
    ):
        class FailingFtp:
            def __init__(self):
                self.remote_received = []

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def cwd(self, _path):
                return None

            def mkd(self, _path):
                return None

            def storbinary(self, command, handle):
                self.remote_received.append((command, handle.read()))
                raise OSError("simulated failure after remote bytes were consumed")

        site_root = ROOT / "sites" / "multiagentmemory.com"
        snapshot = package_multiagentmemory_static_site.capture_site_snapshot(
            site_root, require_complete=True
        )
        activation_gate = ftp_deploy_static_site.release_activation_gate
        failing_ftp = FailingFtp()
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "multiagentmemory-site-v1.0.0.zip"
            manifest_path = Path(tmp) / "multiagentmemory-site-v1.0.0.manifest.json"
            report_path = Path(tmp) / "deploy-report.json"
            self.assertEqual(
                0,
                package_multiagentmemory_static_site.main(
                    [
                        "--write",
                        "--phase",
                        "preactivation",
                        "--site-root",
                        str(site_root),
                        "--package",
                        str(package_path),
                        "--manifest",
                        str(manifest_path),
                        "--expected-site-aggregate-sha256",
                        snapshot["manifest"]["aggregateSha256"],
                    ]
                ),
            )
            with (
                patch.object(
                    ftp_deploy_static_site,
                    "load_filezilla_site",
                    return_value=self.static_profile_fields(),
                ),
                patch.object(
                    ftp_deploy_static_site,
                    "release_activation_gate",
                    side_effect=lambda ledger, utc_date=None: activation_gate(
                        ledger, "2026-08-03"
                    ),
                ),
                patch.object(
                    ftp_deploy_static_site, "connect_ftp", return_value=failing_ftp
                ),
            ):
                exit_code = ftp_deploy_static_site.main(
                    [
                        "--phase",
                        "preactivation",
                        "--site-root",
                        str(site_root),
                        "--package",
                        str(package_path),
                        "--package-manifest",
                        str(manifest_path),
                        "--filezilla-site-match",
                        "multiagentmemory",
                        "--json-out",
                        str(report_path),
                    ]
                )
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(1, exit_code)
        self.assertEqual(
            "nonclaim_stage_upload_failed_partial_possible", report["status"]
        )
        self.assertEqual(0, report["uploadedCount"])
        self.assertEqual(1, report["uploadAttemptedCount"])
        self.assertFalse(report["safeNoOp"])
        self.assertEqual(1, len(failing_ftp.remote_received))
        self.assertGreater(len(failing_ftp.remote_received[0][1]), 0)

    def test_static_preactivation_readback_drift_blocks_all_release_claims(self):
        ftp = TruthOrderedFtp(readback_drift=".well-known/ai-agent.json")
        gate = ftp_deploy_static_site.release_activation_gate
        with tempfile.TemporaryDirectory() as tmp:
            exit_code, report = self.run_release_phase(
                Path(tmp),
                ftp,
                lambda identity, utc_date=None: gate(identity, "2026-08-03"),
                "preactivation",
            )

        self.assertEqual(1, exit_code)
        self.assertEqual(
            "nonclaim_stage_readback_failed_partial_possible", report["status"]
        )
        self.assertFalse(report["stagedNonClaimReadbackComplete"])
        self.assertFalse(report["claimsExposed"])
        self.assertFalse(
            any(
                path in multiagentmemory_release_identity.RELEASE_CLAIM_PATHS
                for _verb, path in ftp.events
            )
        )

    def test_static_preactivation_completion_gate_change_reports_staged_bytes(
        self,
    ):
        ftp = TruthOrderedFtp()
        gate = ftp_deploy_static_site.release_activation_gate
        gate_calls = 0

        def staged_gate(identity, utc_date=None):
            nonlocal gate_calls
            gate_calls += 1
            date = "2026-08-04" if gate_calls == 3 else "2026-08-03"
            return gate(identity, date)

        with tempfile.TemporaryDirectory() as tmp:
            exit_code, report = self.run_release_phase(
                Path(tmp), ftp, staged_gate, "preactivation"
            )

        self.assertEqual(1, exit_code)
        self.assertEqual("nonclaims_staged_activation_date_changed", report["status"])
        self.assertTrue(report["stagedNonClaimReadbackComplete"])
        self.assertFalse(report["claimsExposed"])
        self.assertNotIn(("STOR", "releases/index.html"), ftp.events)

    def test_static_final_retr_drift_after_tag_blocks_every_claim_without_stor(self):
        ftp = TruthOrderedFtp()
        gate = ftp_deploy_static_site.release_activation_gate

        def current_gate(identity, utc_date=None):
            return gate(identity, "2026-08-03")

        with tempfile.TemporaryDirectory() as tmp:
            temporary = Path(tmp)
            stage_exit, _stage_report = self.run_release_phase(
                temporary, ftp, current_gate, "preactivation"
            )
            self.assertEqual(0, stage_exit)
            before_final = len(ftp.events)
            ftp.readback_drift = ".well-known/ai-agent.json"
            exit_code, report = self.run_release_phase(
                temporary, ftp, current_gate, "final"
            )

        self.assertEqual(1, exit_code)
        self.assertEqual("final_staged_nonclaim_readback_failed", report["status"])
        self.assertTrue(report["sourceTagPublished"])
        self.assertFalse(report["claimsExposed"])
        self.assertTrue(report["safeNoOp"])
        self.assertFalse(any(event[0] == "STOR" for event in ftp.events[before_final:]))

    def test_static_final_gate_change_after_stage_retr_blocks_every_claim(self):
        ftp = TruthOrderedFtp()
        gate = ftp_deploy_static_site.release_activation_gate
        gate_calls = 0

        def staged_gate(identity, utc_date=None):
            nonlocal gate_calls
            gate_calls += 1
            date = "2026-08-04" if gate_calls == 6 else "2026-08-03"
            return gate(identity, date)

        with tempfile.TemporaryDirectory() as tmp:
            exit_code, report = self.stage_then_activate(Path(tmp), ftp, staged_gate)

        self.assertEqual(1, exit_code)
        self.assertEqual("final_preclaim_gate_failed_no_claims", report["status"])
        self.assertTrue(report["stagedNonClaimReadbackComplete"])
        self.assertTrue(report["sourceTagPublished"])
        self.assertFalse(report["claimsExposed"])
        self.assertTrue(report["safeNoOp"])

    def test_static_each_claim_failure_reports_its_exact_partial_position(self):
        gate = ftp_deploy_static_site.release_activation_gate
        claim_paths = multiagentmemory_release_identity.RELEASE_CLAIM_PATHS
        for position, failing_path in enumerate(claim_paths):
            with self.subTest(failing_path=failing_path):
                ftp = TruthOrderedFtp(fail_after_store=failing_path)
                with tempfile.TemporaryDirectory() as tmp:
                    exit_code, report = self.stage_then_activate(
                        Path(tmp),
                        ftp,
                        lambda identity, utc_date=None: gate(identity, "2026-08-03"),
                    )

                self.assertEqual(1, exit_code)
                self.assertEqual(
                    "claim_activation_failed_partial_possible", report["status"]
                )
                self.assertTrue(report["stagedNonClaimReadbackComplete"])
                self.assertTrue(report["sourceTagPublished"])
                self.assertTrue(report["claimsExposed"])
                self.assertFalse(report["safeNoOp"])
                self.assertEqual(position, report["claimUploadedCount"])
                self.assertEqual(position, report["claimReadbackCount"])
                self.assertIn(("STOR", failing_path), ftp.events)

    def test_static_completion_gate_failure_reports_activated_bytes_not_safe_noop(self):
        ftp = TruthOrderedFtp()
        gate = ftp_deploy_static_site.release_activation_gate
        gate_calls = 0

        def staged_gate(identity, utc_date=None):
            nonlocal gate_calls
            gate_calls += 1
            date = "2026-08-04" if gate_calls == 7 else "2026-08-03"
            return gate(identity, date)

        with tempfile.TemporaryDirectory() as tmp:
            exit_code, report = self.stage_then_activate(Path(tmp), ftp, staged_gate)

        self.assertEqual(1, exit_code)
        self.assertEqual("claims_activated_activation_date_changed", report["status"])
        self.assertTrue(report["sourceTagPublished"])
        self.assertTrue(report["claimsExposed"])
        self.assertEqual(16, report["readbackVerifiedCount"])
        self.assertFalse(report["safeNoOp"])

    def test_filezilla_site_loader_returns_redacted_report(self):
        site_manager = """<?xml version="1.0" encoding="UTF-8"?>
<FileZilla3>
  <Servers>
    <Server>
      <Host>example.invalid</Host>
      <Port>21</Port>
      <Protocol>0</Protocol>
      <Name>MultiAgentMemory.com</Name>
      <User>multi-user</User>
      <Pass encoding="base64">bXVsdGktc2VjcmV0</Pass>
    </Server>
  </Servers>
</FileZilla3>
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sitemanager.xml"
            path.write_text(site_manager, encoding="utf-8")
            fields, report = ftp_deploy_static_site.load_filezilla_site(
                path, "multiagentmemory", "multiagentmemory.com"
            )

        self.assertEqual("filezilla_site_matched", report["status"])
        self.assertEqual("example.invalid", fields["ftp server"])
        self.assertEqual("multi-user", fields["ftp username"])
        self.assertEqual("multi-secret", fields["password"])
        self.assertTrue(report["valuesRedacted"])
        self.assertTrue(report["targetIdentityConfirmed"])
        self.assertEqual("profile_name", report["targetBinding"])
        self.assertNotIn("multi-secret", str(report))
        self.assertNotIn("multi-user", str(report))
        self.assertNotIn("example.invalid", str(report))

    def test_static_filezilla_loader_rejects_substring_match_in_unrelated_profile(self):
        site_manager = """<?xml version="1.0" encoding="UTF-8"?>
<FileZilla3><Servers><Server>
  <Host>wrong-target.invalid</Host><Port>21</Port>
  <Name>Unrelated production</Name><User>multiagentmemory-admin</User>
  <Pass encoding="base64">d3Jvbmctc2VjcmV0</Pass>
</Server></Servers></FileZilla3>
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sitemanager.xml"
            path.write_text(site_manager, encoding="utf-8")
            fields, report = ftp_deploy_static_site.load_filezilla_site(
                path, "multiagentmemory", "multiagentmemory.com"
            )

        self.assertIsNone(fields)
        self.assertEqual("filezilla_site_not_found", report["status"])
        self.assertFalse(report["targetIdentityConfirmed"])
        self.assertNotIn("wrong-secret", json.dumps(report))

    def test_static_filezilla_selector_must_be_exactly_target_bound(self):
        fields, report = ftp_deploy_static_site.load_filezilla_site(
            Path("unused.xml"), "multiagentmemory-admin", "multiagentmemory.com"
        )

        self.assertIsNone(fields)
        self.assertEqual("filezilla_selector_not_target_bound", report["status"])
        self.assertFalse(report["targetIdentityConfirmed"])

    def test_static_filezilla_loader_rejects_duplicate_exact_target_profiles(self):
        site_manager = """<?xml version="1.0" encoding="UTF-8"?>
<FileZilla3><Servers>
  <Server><Host>stale.invalid</Host><Port>21</Port><Name>MultiAgentMemory.com</Name><User>stale</User><Pass>stale-secret</Pass></Server>
  <Server><Host>current.invalid</Host><Port>21</Port><Name>MultiAgentMemory.com</Name><User>current</User><Pass>current-secret</Pass></Server>
</Servers></FileZilla3>
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sitemanager.xml"
            path.write_text(site_manager, encoding="utf-8")
            fields, report = ftp_deploy_static_site.load_filezilla_site(
                path, "multiagentmemory", "multiagentmemory.com"
            )

        self.assertIsNone(fields)
        self.assertEqual("filezilla_site_ambiguous", report["status"])
        self.assertEqual(2, report["candidateCount"])
        self.assertFalse(report["targetIdentityConfirmed"])
        self.assertNotIn("stale-secret", json.dumps(report))
        self.assertNotIn("current-secret", json.dumps(report))

    def test_static_deployer_rejects_any_noncanonical_target_domain_before_profile_read(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            with (
                patch.object(ftp_deploy_static_site, "load_filezilla_site") as loader,
                patch.object(ftp_deploy_static_site, "connect_ftp") as connect,
            ):
                exit_code = ftp_deploy_static_site.main(
                    [
                        "--dry-run",
                        "--phase",
                        "preactivation",
                        "--target-domain",
                        "attacker.invalid",
                        "--filezilla-site-match",
                        "attacker",
                        "--json-out",
                        str(report_path),
                    ]
                )
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(1, exit_code)
        self.assertEqual("target_domain_not_allowed", report["status"])
        self.assertEqual("multiagentmemory.com", report["targetDomain"])
        self.assertTrue(report["safeNoOp"])
        self.assertNotIn("attacker.invalid", json.dumps(report))
        loader.assert_not_called()
        connect.assert_not_called()

    def test_endpoint_filezilla_dry_run_is_redacted_and_uses_login_root(self):
        original_loader = ftp_deploy_memoryendpoints.load_filezilla_site

        def fake_loader(path, match, target_domain=None):
            self.assertEqual("memoryendpoints.com", target_domain)
            return (
                {
                    "ftp server": "example.invalid",
                    "ftp username": "endpoint-user",
                    "password": "endpoint-secret",
                    "ftp & explicit ftps port": "21",
                },
                {
                    "status": "filezilla_site_matched",
                    "siteIndex": 1,
                    "siteNameFingerprint": "abc123",
                    "siteMatch": match,
                    "hasRemoteDir": False,
                    "valuesRedacted": True,
                },
            )

        with tempfile.TemporaryDirectory() as tmp:
            handoff = Path(tmp) / "handoff.txt"
            report_path = Path(tmp) / "report.json"
            package_path = Path(tmp) / "production.zip"
            handoff.write_text(
                "Stale handoff\nFTP Server: stale.invalid\n", encoding="utf-8"
            )
            package_path.write_bytes(b"test package")
            clean_build = {
                "sourceSha": "a" * 40,
                "sourceShaShort": "a" * 12,
                "contentHash": "b" * 64,
                "sourceWorktreeDirty": False,
                "sourceDirtyPathCount": 0,
            }
            try:
                ftp_deploy_memoryendpoints.load_filezilla_site = fake_loader
                with (
                    patch.object(
                        ftp_deploy_memoryendpoints,
                        "write_current_build_info",
                        return_value=clean_build,
                    ),
                    patch.object(
                        ftp_deploy_memoryendpoints,
                        "capture_exact_revision_snapshot",
                        return_value=(
                            {"files": [], "contentHash": clean_build["contentHash"]},
                            None,
                        ),
                    ),
                ):
                    exit_code = ftp_deploy_memoryendpoints.main(
                        [
                            "--dry-run",
                            "--handoff",
                            str(handoff),
                            "--package",
                            str(package_path),
                            "--filezilla-site-match",
                            "memoryendpoints",
                            "--json-out",
                            str(report_path),
                        ]
                    )
            finally:
                ftp_deploy_memoryendpoints.load_filezilla_site = original_loader
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertEqual("filezilla_site_manager", report["credentialSource"])
        self.assertEqual("filezilla_login_root", report["remoteDirSource"])
        self.assertTrue(report["safeNoOp"])
        text = str(report)
        self.assertNotIn("endpoint-secret", text)
        self.assertNotIn("endpoint-user", text)
        self.assertNotIn("example.invalid", text)

    def test_endpoint_deploy_fails_closed_before_connecting_when_source_is_dirty(self):
        dirty_build = {
            "sourceSha": "a" * 40,
            "sourceShaShort": "a" * 12,
            "contentHash": "b" * 64,
            "sourceWorktreeDirty": True,
            "sourceDirtyPathCount": 1,
        }
        with tempfile.TemporaryDirectory() as tmp:
            handoff = Path(tmp) / "handoff.txt"
            report_path = Path(tmp) / "report.json"
            handoff.write_text(
                "MemoryEndpoints\nFTP Server: example.invalid\nFTP Username: user\nPassword: secret\nRemote Dir: public_html\n",
                encoding="utf-8",
            )
            with (
                patch.object(
                    ftp_deploy_memoryendpoints,
                    "write_current_build_info",
                    return_value=dirty_build,
                ),
                patch.object(
                    ftp_deploy_memoryendpoints,
                    "iter_files",
                    return_value=iter(()),
                ),
                patch.object(ftp_deploy_memoryendpoints, "connect_ftp") as connect,
            ):
                exit_code = ftp_deploy_memoryendpoints.main(
                    ["--handoff", str(handoff), "--json-out", str(report_path)]
                )
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(1, exit_code)
        self.assertEqual("dirty_packaged_source", report["status"])
        self.assertFalse(report["sourceRevisionVerified"])
        self.assertTrue(report["safeNoOp"])
        connect.assert_not_called()

    def test_endpoint_snapshot_rejects_content_hash_mismatch(self):
        build_info = {
            "sourceSha": "a" * 40,
            "contentHash": "b" * 64,
            "sourceWorktreeDirty": False,
        }
        with tempfile.TemporaryDirectory() as tmp:
            source_path = Path(tmp) / "app.py"
            source_path.write_text("print('changed')\n", encoding="utf-8")
            with (
                patch.object(
                    ftp_deploy_memoryendpoints,
                    "iter_files",
                    return_value=iter([(source_path, Path("app.py"))]),
                ),
                patch.object(
                    ftp_deploy_memoryendpoints,
                    "inspect_current_source",
                    return_value={
                        "sourceSha": build_info["sourceSha"],
                        "contentHash": build_info["contentHash"],
                        "dirtyPaths": [],
                    },
                ),
            ):
                snapshot, error = (
                    ftp_deploy_memoryendpoints.capture_exact_revision_snapshot(
                        build_info
                    )
                )

        self.assertIsNone(snapshot)
        self.assertEqual("source_changed_during_deploy_preflight", error)

    def test_deploy_attempt_freshness_matches_package(self):
        freshness = build_deploy_attempt_report.build_freshness(
            {"plannedUploadCount": 78, "build": {"sourceSha": "abc123"}},
            {"fileCount": 78, "build": {"sourceSha": "abc123"}},
        )

        self.assertTrue(freshness["plannedUploadCountMatchesPackage"])
        self.assertTrue(freshness["sourceShaMatchesPackage"])
        self.assertIsNone(build_deploy_attempt_report.freshness_blocker(freshness))

    def test_deploy_attempt_freshness_reports_stale_dry_run(self):
        freshness = build_deploy_attempt_report.build_freshness(
            {"plannedUploadCount": 77, "build": {"sourceSha": "old456"}},
            {"fileCount": 78, "build": {"sourceSha": "new789"}},
        )
        blocker = build_deploy_attempt_report.freshness_blocker(freshness)

        self.assertFalse(freshness["plannedUploadCountMatchesPackage"])
        self.assertFalse(freshness["sourceShaMatchesPackage"])
        self.assertIn("planned upload count", blocker)
        self.assertIn("source SHA", blocker)

    def test_deploy_attempt_requires_live_latest_code_match(self):
        self.assertIsNone(
            build_deploy_attempt_report.live_latest_code_blocker(
                {
                    "expectedSourceSha": "abc123",
                    "observedSourceSha": "abc123",
                    "sourceShaMatchesExpected": True,
                }
            )
        )

        blocker = build_deploy_attempt_report.live_latest_code_blocker(
            {
                "expectedSourceSha": "abc123",
                "observedSourceSha": "old456",
                "sourceShaMatchesExpected": False,
            }
        )
        self.assertIn("live source SHA", blocker)
        self.assertIn("abc123", blocker)
        self.assertIn("old456", blocker)


if __name__ == "__main__":
    unittest.main()
