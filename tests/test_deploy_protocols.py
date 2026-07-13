import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from scripts import build_deploy_attempt_report, ftp_deploy_memoryendpoints, ftp_deploy_static_site, package_memoryendpoints


ROOT = Path(__file__).resolve().parents[1]


class DeployProtocolTests(unittest.TestCase):
    def test_package_excludes_visual_studio_runtime_state(self):
        self.assertFalse(package_memoryendpoints.should_include_rel(Path(".vs") / "solution" / "index.vsidx"))

    def test_package_dirty_paths_include_ignored_extra_and_missing_tracked_files(self):
        files = [
            (Path("unused-app"), Path("memoryendpoints/app.py")),
            (Path("unused-env"), Path(".env")),
        ]
        with patch.object(
            package_memoryendpoints,
            "git_tracked_paths",
            return_value={"memoryendpoints/app.py", "scripts/deleted_release_file.py"},
        ), patch.object(
            package_memoryendpoints,
            "git_status_paths",
            return_value=["memoryendpoints/app.py"],
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
            with patch.object(
                package_memoryendpoints,
                "inspect_current_source",
                return_value={
                    "files": [],
                    "sourceSha": build_info["sourceSha"],
                    "contentHash": build_info["contentHash"],
                    "dirtyPaths": ["memoryendpoints/app.py"],
                },
            ), patch.object(
                package_memoryendpoints,
                "write_build_info",
                return_value=build_info,
            ), patch.object(
                package_memoryendpoints,
                "iter_files",
                return_value=iter(()),
            ), patch.object(package_memoryendpoints, "PACKAGE", package_path):
                exit_code = package_memoryendpoints.main(["--json-out", str(report_path)])
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
            with patch.object(
                package_memoryendpoints,
                "inspect_current_source",
                side_effect=package_memoryendpoints.SourceRevisionError("redacted"),
            ), patch.object(package_memoryendpoints, "PACKAGE", package_path):
                exit_code = package_memoryendpoints.main(["--json-out", str(report_path)])
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
        with patch.object(
            package_memoryendpoints,
            "inspect_current_source",
            return_value=source,
        ), patch.object(
            package_memoryendpoints,
            "write_build_info",
            return_value={"sourceWorktreeDirty": True},
        ) as write_build_info:
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
            with patch.object(
                package_memoryendpoints,
                "inspect_current_source",
                return_value=source,
            ), patch.object(
                package_memoryendpoints,
                "write_build_info",
                return_value=build_info,
            ), patch.object(
                package_memoryendpoints,
                "iter_files",
                return_value=iter(files),
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
        self.assertEqual("explicit_ftps", ftp_deploy_memoryendpoints.transport_security("ftps"))
        self.assertEqual("plain_ftp", ftp_deploy_memoryendpoints.transport_security("ftp"))
        self.assertEqual("explicit_ftps", ftp_deploy_static_site.transport_security("ftps"))
        self.assertEqual("plain_ftp", ftp_deploy_static_site.transport_security("ftp"))

    def test_deploy_scripts_expose_no_upload_connection_check(self):
        endpoint_script = (ROOT / "scripts" / "ftp_deploy_memoryendpoints.py").read_text(encoding="utf-8")
        static_script = (ROOT / "scripts" / "ftp_deploy_static_site.py").read_text(encoding="utf-8")
        for script in (endpoint_script, static_script):
            self.assertIn("--connection-check", script)
            self.assertIn("--filezilla-site-match", script)
            self.assertIn("connection_check_passed", script)
            self.assertIn("uploadedCount", script)
            self.assertIn("args.dry_run or args.connection_check", script)

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
                report = ftp_deploy_static_site.redacted_section_probe(path, "multiagentmemory.com")
            finally:
                ftp_deploy_static_site.connect_ftp = original_connect

        text = str(report)
        self.assertTrue(report["anySectionLoginPassed"])
        self.assertFalse(report["targetSectionLoginPassed"])
        self.assertIn(("neural-user", "ftps"), calls)
        self.assertNotIn("neural-secret", text)
        self.assertNotIn("multi-secret", text)
        self.assertNotIn("example.invalid", text)
        self.assertNotIn("multi-user", text)

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
            fields, report = ftp_deploy_static_site.load_filezilla_site(path, "multiagentmemory")

        self.assertEqual("filezilla_site_matched", report["status"])
        self.assertEqual("example.invalid", fields["ftp server"])
        self.assertEqual("multi-user", fields["ftp username"])
        self.assertEqual("multi-secret", fields["password"])
        self.assertTrue(report["valuesRedacted"])
        self.assertNotIn("multi-secret", str(report))
        self.assertNotIn("multi-user", str(report))
        self.assertNotIn("example.invalid", str(report))

    def test_endpoint_filezilla_dry_run_is_redacted_and_uses_login_root(self):
        original_loader = ftp_deploy_memoryendpoints.load_filezilla_site

        def fake_loader(path, match):
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
            handoff.write_text("Stale handoff\nFTP Server: stale.invalid\n", encoding="utf-8")
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
                with patch.object(
                    ftp_deploy_memoryendpoints,
                    "write_current_build_info",
                    return_value=clean_build,
                ), patch.object(
                    ftp_deploy_memoryendpoints,
                    "capture_exact_revision_snapshot",
                    return_value=({"files": [], "contentHash": clean_build["contentHash"]}, None),
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
            with patch.object(
                ftp_deploy_memoryendpoints,
                "write_current_build_info",
                return_value=dirty_build,
            ), patch.object(
                ftp_deploy_memoryendpoints,
                "iter_files",
                return_value=iter(()),
            ), patch.object(ftp_deploy_memoryendpoints, "connect_ftp") as connect:
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
            with patch.object(
                ftp_deploy_memoryendpoints,
                "iter_files",
                return_value=iter([(source_path, Path("app.py"))]),
            ), patch.object(
                ftp_deploy_memoryendpoints,
                "inspect_current_source",
                return_value={
                    "sourceSha": build_info["sourceSha"],
                    "contentHash": build_info["contentHash"],
                    "dirtyPaths": [],
                },
            ):
                snapshot, error = ftp_deploy_memoryendpoints.capture_exact_revision_snapshot(build_info)

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
                {"expectedSourceSha": "abc123", "observedSourceSha": "abc123", "sourceShaMatchesExpected": True}
            )
        )

        blocker = build_deploy_attempt_report.live_latest_code_blocker(
            {"expectedSourceSha": "abc123", "observedSourceSha": "old456", "sourceShaMatchesExpected": False}
        )
        self.assertIn("live source SHA", blocker)
        self.assertIn("abc123", blocker)
        self.assertIn("old456", blocker)


if __name__ == "__main__":
    unittest.main()
