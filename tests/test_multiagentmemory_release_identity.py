import hashlib
import json
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

from scripts import multiagentmemory_release_identity as release_identity
from scripts import ftp_deploy_static_site
from scripts import package_multiagentmemory_static_site as site_package
from scripts import verify_static_site


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SITE = ROOT / "sites" / "multiagentmemory.com"


class GitReleaseFixture:
    def __init__(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "source"
        self.remote = self.root / "remote.git"
        self.site_root = self.repository / "sites" / "multiagentmemory.com"
        self._git(
            self.root, "init", "--bare", "--initial-branch=main", str(self.remote)
        )
        self._git(self.root, "init", "--initial-branch=main", str(self.repository))
        self._git(
            self.repository, "config", "user.email", "release-test@example.invalid"
        )
        self._git(self.repository, "config", "user.name", "Release Test")
        (self.repository / "baseline.txt").write_text(
            "previous public source\n", encoding="utf-8"
        )
        self._git(self.repository, "add", "baseline.txt")
        self._git(self.repository, "commit", "-m", "previous source")
        self._git(self.repository, "remote", "add", "origin", str(self.remote))
        self._git(self.repository, "push", "--set-upstream", "origin", "main")
        for relative in site_package.ALLOWED_SITE_FILES:
            destination = self.site_root / Path(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((SOURCE_SITE / relative).read_bytes())
        self._git(self.repository, "add", "--all")
        self._git(self.repository, "commit", "-m", "release source")

    @staticmethod
    def _git(cwd, *arguments):
        completed = subprocess.run(
            ["git", "-C", str(cwd), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode:
            raise AssertionError(completed.stderr.decode("utf-8", errors="replace"))
        return completed.stdout.decode("utf-8", errors="strict").strip()

    @property
    def head(self):
        return self._git(self.repository, "rev-parse", "HEAD")

    @property
    def ledger(self):
        return json.loads(
            (self.site_root / "releases.json").read_text(encoding="utf-8")
        )

    @property
    def snapshot(self):
        return site_package.capture_site_snapshot(self.site_root, require_complete=True)

    def tag_local(self, force=False, target=None, message="MultiAgentMemory.com 1.0.0"):
        arguments = ["tag", "--annotate", "--message", message]
        if force:
            arguments.append("--force")
        arguments.append(release_identity.tag_name_for_version("1.0.0"))
        if target:
            arguments.append(target)
        self._git(self.repository, *arguments)

    def tag_lightweight(self, target=None):
        arguments = ["tag", release_identity.tag_name_for_version("1.0.0")]
        if target:
            arguments.append(target)
        self._git(self.repository, *arguments)

    def install_raw_tag_object(self, header_lines, message="synthetic tag"):
        payload = ("\n".join(header_lines) + "\n\n" + message + "\n").encode("utf-8")
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(self.repository),
                "hash-object",
                "-t",
                "tag",
                "-w",
                "--stdin",
                "--literally",
            ],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode:
            raise AssertionError(completed.stderr.decode("utf-8", errors="replace"))
        object_sha = completed.stdout.decode("ascii", errors="strict").strip()
        self._git(
            self.repository,
            "update-ref",
            release_identity.tag_ref_for_version("1.0.0"),
            object_sha,
        )
        return object_sha

    def canonical_tag_headers(self, **overrides):
        values = {
            "object": self.head,
            "type": "commit",
            "tag": release_identity.tag_name_for_version("1.0.0"),
            "tagger": "Release Test <release-test@example.invalid> 0 +0000",
        }
        values.update(overrides)
        return [f"{key} {values[key]}" for key in ("object", "type", "tag", "tagger")]

    def push_tag(self):
        self._git(
            self.repository,
            "push",
            "origin",
            release_identity.tag_ref_for_version("1.0.0"),
        )

    def delete_local_tag(self):
        self._git(
            self.repository,
            "tag",
            "--delete",
            release_identity.tag_name_for_version("1.0.0"),
        )

    def push_release_source(self):
        self._git(self.repository, "push", "origin", "HEAD:refs/heads/main")

    def commit_control_change(self):
        control = self.repository / "release-control.txt"
        control.write_text(self.head + "\n", encoding="utf-8")
        self._git(self.repository, "add", "release-control.txt")
        self._git(self.repository, "commit", "-m", "next source commit")

    def qualify(self, phase=release_identity.PREACTIVATION_PHASE, manifest=None):
        return release_identity.qualify_release_source(
            self.repository,
            self.site_root,
            self.ledger,
            site_package.ALLOWED_SITE_FILES,
            manifest or self.snapshot["manifest"],
            phase=phase,
            expected_repository_git_url=str(self.remote),
        )

    def close(self):
        self.temporary.cleanup()


class MultiAgentMemoryReleaseIdentityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = GitReleaseFixture()

    def tearDown(self):
        self.fixture.close()

    def assert_identity_error(self, code, callback):
        with self.assertRaises(release_identity.ReleaseIdentityError) as caught:
            callback()
        self.assertEqual(code, caught.exception.code)

    def qualifier_patch(self):
        def qualify(*args, **kwargs):
            return release_identity.qualify_release_source(
                *args,
                **kwargs,
                expected_repository_git_url=str(self.fixture.remote),
            )

        return patch.object(site_package, "qualify_release_source", side_effect=qualify)

    def test_preactivation_binds_clean_commit_and_requires_both_tags_absent(self):
        result = self.fixture.qualify()
        source = result["sourceIdentity"]
        qualification = result["qualification"]

        self.assertEqual(self.fixture.head, source["commitSha"])
        self.assertEqual(self.fixture.head, source["requiredTagTargetCommitSha"])
        self.assertEqual(
            "refs/tags/multiagentmemory-site-v1.0.0", source["requiredTagRef"]
        )
        self.assertFalse(qualification["localTagPresent"])
        self.assertFalse(qualification["remoteTagPresent"])
        self.assertFalse(qualification["tagSiteBytesVerified"])

    def test_preactivation_rejects_a_premature_local_tag(self):
        self.fixture.tag_local()
        self.assert_identity_error(
            "source_local_tag_exists_during_preactivation", self.fixture.qualify
        )

    def test_preactivation_rejects_a_premature_remote_tag(self):
        self.fixture.tag_local()
        self.fixture.push_tag()
        self.fixture.delete_local_tag()
        self.assert_identity_error(
            "source_remote_tag_exists_during_preactivation", self.fixture.qualify
        )

    def test_final_requires_local_and_remote_tag_then_proves_exact_targets(self):
        def final():
            return self.fixture.qualify(release_identity.FINAL_PHASE)

        self.assert_identity_error("source_local_tag_missing_at_final", final)
        self.fixture.tag_local()
        self.assert_identity_error("source_remote_tag_missing_at_final", final)
        self.fixture.push_tag()

        result = final()

        self.assertTrue(result["qualification"]["localTagPresent"])
        self.assertTrue(result["qualification"]["remoteTagPresent"])
        self.assertTrue(result["qualification"]["tagSiteBytesVerified"])
        self.assertEqual(
            self.fixture.head,
            result["qualification"]["remoteTagTargetCommitSha"],
        )
        self.fixture.push_release_source()

    def test_final_rejects_wrong_or_moved_tag_targets(self):
        previous = self.fixture._git(self.fixture.repository, "rev-parse", "HEAD^")
        self.fixture.tag_local(target=previous)
        self.assert_identity_error(
            "source_tag_target_mismatch",
            lambda: self.fixture.qualify(release_identity.FINAL_PHASE),
        )
        self.fixture.tag_local(force=True)
        self.fixture.push_tag()
        self.fixture.commit_control_change()
        self.fixture.tag_local(force=True)
        self.assert_identity_error(
            "source_remote_tag_target_mismatch",
            lambda: self.fixture.qualify(release_identity.FINAL_PHASE),
        )

    def test_final_rejects_lightweight_local_and_remote_tags(self):
        self.fixture.tag_lightweight()
        self.fixture.push_tag()
        self.assert_identity_error(
            "source_local_tag_not_annotated",
            lambda: self.fixture.qualify(release_identity.FINAL_PHASE),
        )

        self.fixture.delete_local_tag()
        self.fixture.tag_local()
        self.assert_identity_error(
            "source_remote_tag_not_annotated",
            lambda: self.fixture.qualify(release_identity.FINAL_PHASE),
        )

    def test_final_rejects_tag_object_mismatch_with_same_peeled_commit(self):
        self.fixture.tag_local(message="remote tag object")
        self.fixture.push_tag()
        self.fixture.delete_local_tag()
        self.fixture.tag_local(message="different local tag object")

        self.assert_identity_error(
            "source_tag_object_mismatch",
            lambda: self.fixture.qualify(release_identity.FINAL_PHASE),
        )

    def test_final_rejects_canonical_ref_with_wrong_internal_tag_name(self):
        self.fixture.install_raw_tag_object(
            self.fixture.canonical_tag_headers(tag="different-internal-name")
        )
        self.fixture.push_tag()

        self.assert_identity_error(
            "source_tag_internal_name_mismatch",
            lambda: self.fixture.qualify(release_identity.FINAL_PHASE),
        )

    def test_final_rejects_malformed_or_duplicate_annotated_tag_headers(self):
        cases = {
            "missing-tagger": self.fixture.canonical_tag_headers()[:-1],
            "duplicate-object": [
                *self.fixture.canonical_tag_headers(),
                f"object {self.fixture.head}",
            ],
            "wrong-type": self.fixture.canonical_tag_headers(type="blob"),
            "unknown-header": [
                *self.fixture.canonical_tag_headers(),
                "encoding UTF-8",
            ],
            "malformed-no-space": [
                *self.fixture.canonical_tag_headers(),
                "unexpected",
            ],
            "empty-tagger": self.fixture.canonical_tag_headers(tagger=""),
            "invalid-tagger": self.fixture.canonical_tag_headers(
                tagger="not-a-git-tagger"
            ),
        }
        for name, headers in cases.items():
            with self.subTest(name=name):
                self.fixture.install_raw_tag_object(headers)
                self.assert_identity_error(
                    "source_local_tag_object_invalid",
                    lambda: self.fixture.qualify(release_identity.FINAL_PHASE),
                )

    def test_final_rejects_annotated_tag_object_pointing_at_wrong_commit(self):
        previous = self.fixture._git(self.fixture.repository, "rev-parse", "HEAD^")
        self.fixture.install_raw_tag_object(
            self.fixture.canonical_tag_headers(object=previous)
        )

        self.assert_identity_error(
            "source_tag_target_mismatch",
            lambda: self.fixture.qualify(release_identity.FINAL_PHASE),
        )

    def test_remote_main_race_cannot_move_or_invalidate_the_published_tag(self):
        release_commit = self.fixture.head
        with tempfile.TemporaryDirectory() as tmp, self.qualifier_patch():
            temporary = Path(tmp)
            _snapshot, zip_bytes, manifest, _qualification = (
                site_package.expected_package(
                    self.fixture.site_root, repo_root=self.fixture.repository
                )
            )
            package_path = temporary / "multiagentmemory-site-v1.0.0.zip"
            manifest_path = temporary / "multiagentmemory-site-v1.0.0.manifest.json"
            package_path.write_bytes(zip_bytes)
            manifest_path.write_bytes(site_package.manifest_bytes(manifest))
            self.fixture.tag_local()
            self.fixture.push_tag()
            before = site_package.verify_package(
                package_path,
                manifest_path,
                phase=release_identity.FINAL_PHASE,
                repo_root=self.fixture.repository,
                site_root=self.fixture.site_root,
            )

            competitor = self.fixture.root / "competitor"
            self.fixture._git(
                self.fixture.root, "clone", str(self.fixture.remote), str(competitor)
            )
            self.fixture._git(
                competitor, "config", "user.email", "race@example.invalid"
            )
            self.fixture._git(competitor, "config", "user.name", "Remote Main Race")
            (competitor / "race.txt").write_text(
                "remote main advanced\n", encoding="utf-8"
            )
            self.fixture._git(competitor, "add", "race.txt")
            self.fixture._git(competitor, "commit", "-m", "advance remote main")
            self.fixture._git(competitor, "push", "origin", "main")

            after = site_package.verify_package(
                package_path,
                manifest_path,
                phase=release_identity.FINAL_PHASE,
                repo_root=self.fixture.repository,
                site_root=self.fixture.site_root,
            )
            push_main = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.fixture.repository),
                    "push",
                    "origin",
                    "HEAD:refs/heads/main",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        self.assertNotEqual(0, push_main.returncode)
        self.assertEqual(release_commit, after["releaseIdentity"]["sourceCommitSha"])
        self.assertEqual(
            before["sourceQualification"]["remoteTagObjectSha"],
            after["sourceQualification"]["remoteTagObjectSha"],
        )

    def test_preactivation_package_recheck_rejects_remote_main_lease_change(self):
        with tempfile.TemporaryDirectory() as tmp, self.qualifier_patch():
            temporary = Path(tmp)
            _snapshot, zip_bytes, manifest, _qualification = (
                site_package.expected_package(
                    self.fixture.site_root, repo_root=self.fixture.repository
                )
            )
            package_path = temporary / "multiagentmemory-site-v1.0.0.zip"
            manifest_path = temporary / "multiagentmemory-site-v1.0.0.manifest.json"
            package_path.write_bytes(zip_bytes)
            manifest_path.write_bytes(site_package.manifest_bytes(manifest))

            competitor = self.fixture.root / "lease-competitor"
            self.fixture._git(
                self.fixture.root, "clone", str(self.fixture.remote), str(competitor)
            )
            self.fixture._git(
                competitor, "config", "user.email", "lease@example.invalid"
            )
            self.fixture._git(competitor, "config", "user.name", "Lease Change")
            (competitor / "lease.txt").write_text("lease changed\n", encoding="utf-8")
            self.fixture._git(competitor, "add", "lease.txt")
            self.fixture._git(competitor, "commit", "-m", "change lease")
            self.fixture._git(competitor, "push", "origin", "main")

            self.assert_identity_error(
                "source_remote_main_lease_changed",
                lambda: site_package.verify_package(
                    package_path,
                    manifest_path,
                    phase=release_identity.PREACTIVATION_PHASE,
                    repo_root=self.fixture.repository,
                    site_root=self.fixture.site_root,
                ),
            )

    def test_dirty_source_fails_before_phase_or_package_qualification(self):
        (self.fixture.repository / "untracked-release-input.txt").write_text(
            "dirty\n", encoding="utf-8"
        )
        self.assert_identity_error("source_worktree_dirty", self.fixture.qualify)

    def test_commit_site_drift_fails_closed_without_a_tag(self):
        entries = [dict(entry) for entry in self.fixture.snapshot["files"]]
        entries[0]["bytes"] += b"\nsynthetic drift\n"
        manifest = site_package._manifest_from_entries(entries)
        self.assert_identity_error(
            "source_commit_site_drift",
            lambda: self.fixture.qualify(manifest=manifest),
        )

    def test_rehashed_package_drift_still_fails_against_bound_commit(self):
        with self.qualifier_patch():
            source_snapshot, _valid_zip, manifest, _qualification = (
                site_package.expected_package(
                    self.fixture.site_root,
                    repo_root=self.fixture.repository,
                )
            )
            tampered_entries = [dict(entry) for entry in source_snapshot["files"]]
            index = next(
                entry
                for entry in tampered_entries
                if entry["relativePath"].as_posix() == "index.html"
            )
            index["bytes"] += b"\n<!-- package-drift -->\n"
            tampered_snapshot = {
                "files": tampered_entries,
                "manifest": site_package._manifest_from_entries(tampered_entries),
            }
            tampered_zip = site_package.build_zip_bytes(tampered_snapshot)
            manifest["siteManifest"] = tampered_snapshot["manifest"]
            archive = manifest["packageManifest"]["archive"]
            archive["bytes"] = len(tampered_zip)
            archive["sha256"] = hashlib.sha256(tampered_zip).hexdigest()
            manifest["packageManifestSha256"] = hashlib.sha256(
                release_identity.canonical_json_bytes(manifest["packageManifest"])
            ).hexdigest()
            with tempfile.TemporaryDirectory() as tmp:
                package_path = Path(tmp) / "multiagentmemory-site-v1.0.0.zip"
                manifest_path = Path(tmp) / "multiagentmemory-site-v1.0.0.manifest.json"
                package_path.write_bytes(tampered_zip)
                manifest_path.write_bytes(site_package.manifest_bytes(manifest))
                self.assert_identity_error(
                    "source_commit_site_drift",
                    lambda: site_package.verify_package(
                        package_path,
                        manifest_path,
                        phase=release_identity.PREACTIVATION_PHASE,
                        repo_root=self.fixture.repository,
                        site_root=self.fixture.site_root,
                    ),
                )

    def test_one_manifest_survives_absent_to_final_tag_and_exact_live_verification(
        self,
    ):
        with (
            tempfile.TemporaryDirectory() as tmp,
            self.qualifier_patch(),
            patch("builtins.print"),
        ):
            temporary = Path(tmp)
            _snapshot, zip_bytes, manifest, prequalification = (
                site_package.expected_package(
                    self.fixture.site_root,
                    repo_root=self.fixture.repository,
                )
            )
            original_manifest_bytes = site_package.manifest_bytes(manifest)
            self.assertEqual(release_identity.RELEASE_IDENTITY_FIELDS, set(manifest))
            self.assertEqual(
                ["releases.html"],
                manifest["cutoverPolicy"]["finalRetiredPathDeleteOrder"],
            )
            self.assertEqual(
                ["releases.html"],
                manifest["cutoverPolicy"]["finalRetiredPathVerificationPaths"],
            )
            self.assertEqual(
                sorted(
                    [
                        *site_package.ALLOWED_SITE_FILES,
                        *release_identity.RETIRED_SITE_PATHS,
                    ]
                ),
                manifest["rollbackPolicy"]["managedPaths"],
            )
            self.assertTrue(
                manifest["rollbackPolicy"]["restorePresentBeforeAbsentRequired"]
            )
            self.assertFalse(prequalification["localTagPresent"])
            self.assertEqual(
                self.fixture.head,
                manifest["source"]["requiredTagTargetCommitSha"],
            )
            package_path = temporary / "multiagentmemory-site-v1.0.0.zip"
            manifest_path = temporary / "multiagentmemory-site-v1.0.0.manifest.json"
            report_path = temporary / "live-verification.json"
            package_path.write_bytes(zip_bytes)
            manifest_path.write_bytes(original_manifest_bytes)
            requested = []
            activation_gate = verify_static_site.live_activation_gate

            def fake_fetch(base_url, relative, opener=None):
                self.assertEqual(verify_static_site.CANONICAL_LIVE_BASE_URL, base_url)
                requested.append(relative)
                if relative in release_identity.RETIRED_SITE_PATHS:
                    return {
                        "status": 404,
                        "data": b"not found",
                        "errorType": "HTTPError",
                        "requestedUrl": base_url
                        + verify_static_site.live_route_for(relative),
                        "finalUrl": None,
                        "canonicalFinalUrl": False,
                        "mediaType": None,
                    }
                return {
                    "status": 200,
                    "data": (self.fixture.site_root / relative).read_bytes(),
                    "errorType": None,
                    "requestedUrl": base_url
                    + verify_static_site.live_route_for(relative),
                    "finalUrl": base_url + verify_static_site.live_route_for(relative),
                    "canonicalFinalUrl": True,
                    "mediaType": verify_static_site.EXPECTED_MEDIA_TYPES[relative],
                }

            def current_gate(identity, utc_date=None):
                return activation_gate(identity, "2026-08-29")

            base = [
                "--base-url",
                verify_static_site.CANONICAL_LIVE_BASE_URL,
                "--repo-root",
                str(self.fixture.repository),
                "--site-root",
                str(self.fixture.site_root),
                "--package",
                str(package_path),
                "--package-manifest",
                str(manifest_path),
                "--json-out",
                str(report_path),
            ]
            with (
                patch.object(verify_static_site, "fetch_live", side_effect=fake_fetch),
                patch.object(
                    verify_static_site,
                    "live_activation_gate",
                    side_effect=current_gate,
                ),
            ):
                self.assertEqual(
                    0,
                    verify_static_site.main(
                        [*base, "--phase", release_identity.PREACTIVATION_PHASE]
                    ),
                )
                self.assertEqual(list(verify_static_site.NON_CLAIM_FILES), requested)
                preactivation_report = json.loads(
                    report_path.read_text(encoding="utf-8")
                )
                self.assertEqual(
                    len(verify_static_site.NON_CLAIM_FILES),
                    preactivation_report["fileCount"],
                )
                self.assertEqual(
                    len(verify_static_site.NON_CLAIM_FILES),
                    preactivation_report["nonClaimFileCount"],
                )
                self.assertEqual(0, preactivation_report["claimFileCount"])
                self.assertFalse(preactivation_report["claimsVerified"])
                self.assertFalse(
                    any(
                        path in release_identity.RELEASE_CLAIM_PATHS
                        for path in requested
                    )
                )
                self.fixture.tag_local()
                self.fixture.push_tag()
                self.assertEqual(original_manifest_bytes, manifest_path.read_bytes())
                requested.clear()
                self.assertEqual(
                    0,
                    verify_static_site.main(
                        [*base, "--phase", release_identity.FINAL_PHASE]
                    ),
                )
                self.assertEqual(
                    [
                        *site_package.ALLOWED_SITE_FILES,
                        *release_identity.RETIRED_SITE_PATHS,
                    ],
                    requested,
                )
                final_report = json.loads(report_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    len(site_package.ALLOWED_SITE_FILES),
                    final_report["fileCount"],
                )
                self.assertEqual(6, final_report["claimFileCount"])
                self.assertEqual(1, final_report["retiredRouteCount"])
                self.assertEqual(1, final_report["retiredRouteVerifiedCount"])
                self.assertTrue(final_report["claimsVerified"])
                self.fixture.push_release_source()

    def test_final_live_verifier_rejects_retired_route_content_and_redirects(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            self.qualifier_patch(),
            patch("builtins.print"),
        ):
            temporary = Path(tmp)
            _snapshot, zip_bytes, manifest, _qualification = (
                site_package.expected_package(
                    self.fixture.site_root,
                    repo_root=self.fixture.repository,
                )
            )
            package_path = temporary / "multiagentmemory-site-v1.0.0.zip"
            manifest_path = temporary / "multiagentmemory-site-v1.0.0.manifest.json"
            package_path.write_bytes(zip_bytes)
            manifest_path.write_bytes(site_package.manifest_bytes(manifest))
            self.fixture.tag_local()
            self.fixture.push_tag()
            activation_gate = verify_static_site.live_activation_gate

            def current_gate(identity, utc_date=None):
                return activation_gate(identity, "2026-08-29")

            for name, retired_status, error_type in (
                ("legacy-content", 200, None),
                ("redirect", 301, "HTTPError"),
            ):
                with self.subTest(name=name):
                    report_path = temporary / f"retired-{name}.json"

                    def fake_fetch(base_url, relative, opener=None):
                        route = verify_static_site.live_route_for(relative)
                        if relative in release_identity.RETIRED_SITE_PATHS:
                            return {
                                "status": retired_status,
                                "data": b"legacy or redirect response",
                                "errorType": error_type,
                                "requestedUrl": base_url + route,
                                "finalUrl": (
                                    base_url + "/releases/"
                                    if retired_status == 200
                                    else None
                                ),
                                "canonicalFinalUrl": retired_status == 200,
                                "mediaType": (
                                    "text/html" if retired_status == 200 else None
                                ),
                            }
                        return {
                            "status": 200,
                            "data": (self.fixture.site_root / relative).read_bytes(),
                            "errorType": None,
                            "requestedUrl": base_url + route,
                            "finalUrl": base_url + route,
                            "canonicalFinalUrl": True,
                            "mediaType": verify_static_site.EXPECTED_MEDIA_TYPES[
                                relative
                            ],
                        }

                    with (
                        patch.object(
                            verify_static_site,
                            "fetch_live",
                            side_effect=fake_fetch,
                        ),
                        patch.object(
                            verify_static_site,
                            "live_activation_gate",
                            side_effect=current_gate,
                        ),
                    ):
                        exit_code = verify_static_site.main(
                            [
                                "--base-url",
                                verify_static_site.CANONICAL_LIVE_BASE_URL,
                                "--repo-root",
                                str(self.fixture.repository),
                                "--site-root",
                                str(self.fixture.site_root),
                                "--package",
                                str(package_path),
                                "--package-manifest",
                                str(manifest_path),
                                "--phase",
                                release_identity.FINAL_PHASE,
                                "--json-out",
                                str(report_path),
                            ]
                        )
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                    retired = report["retiredRouteItems"][0]
                    self.assertEqual(1, exit_code)
                    self.assertEqual("live_route_verification_failed", report["status"])
                    self.assertEqual(1, report["retiredRouteCount"])
                    self.assertEqual(0, report["retiredRouteVerifiedCount"])
                    self.assertFalse(retired["ordinaryNotFound"])
                    self.assertFalse(retired["noRedirectVerified"])
                    self.assertFalse(retired["verified"])

    def test_premature_tag_blocks_live_network_before_any_request(self):
        with tempfile.TemporaryDirectory() as tmp, self.qualifier_patch():
            temporary = Path(tmp)
            _snapshot, zip_bytes, manifest, _qualification = (
                site_package.expected_package(
                    self.fixture.site_root,
                    repo_root=self.fixture.repository,
                )
            )
            package_path = temporary / "multiagentmemory-site-v1.0.0.zip"
            manifest_path = temporary / "multiagentmemory-site-v1.0.0.manifest.json"
            report_path = temporary / "report.json"
            package_path.write_bytes(zip_bytes)
            manifest_path.write_bytes(site_package.manifest_bytes(manifest))
            self.fixture.tag_local()
            with (
                patch.object(verify_static_site, "fetch_live") as fetch_live,
                patch("builtins.print"),
            ):
                exit_code = verify_static_site.main(
                    [
                        "--base-url",
                        "https://multiagentmemory.com",
                        "--repo-root",
                        str(self.fixture.repository),
                        "--site-root",
                        str(self.fixture.site_root),
                        "--package",
                        str(package_path),
                        "--package-manifest",
                        str(manifest_path),
                        "--phase",
                        release_identity.PREACTIVATION_PHASE,
                        "--json-out",
                        str(report_path),
                    ]
                )
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(1, exit_code)
        self.assertEqual(
            "source_local_tag_exists_during_preactivation", report["status"]
        )
        fetch_live.assert_not_called()

    def test_live_verifier_rejects_redirect_origin_drift_and_wrong_media_type(self):
        with tempfile.TemporaryDirectory() as tmp, self.qualifier_patch():
            temporary = Path(tmp)
            _snapshot, zip_bytes, manifest, _qualification = (
                site_package.expected_package(
                    self.fixture.site_root,
                    repo_root=self.fixture.repository,
                )
            )
            package_path = temporary / "multiagentmemory-site-v1.0.0.zip"
            manifest_path = temporary / "multiagentmemory-site-v1.0.0.manifest.json"
            package_path.write_bytes(zip_bytes)
            manifest_path.write_bytes(site_package.manifest_bytes(manifest))
            activation_gate = verify_static_site.live_activation_gate

            def current_gate(identity, utc_date=None):
                return activation_gate(identity, "2026-08-29")

            cases = (
                ("same-origin-redirect", 302, False, None),
                ("cross-origin-final-url", 200, False, "application/json"),
                ("wrong-media-type", 200, True, "application/octet-stream"),
                ("missing-media-type", 200, True, None),
            )
            for name, status, canonical_final, media_type in cases:
                with self.subTest(name=name):
                    report_path = temporary / f"{name}.json"

                    def fake_fetch(base_url, relative, opener=None):
                        expected_type = verify_static_site.EXPECTED_MEDIA_TYPES[
                            relative
                        ]
                        is_first = relative == verify_static_site.NON_CLAIM_FILES[0]
                        return {
                            "status": status if is_first else 200,
                            "data": (self.fixture.site_root / relative).read_bytes(),
                            "errorType": "HTTPError"
                            if is_first and status != 200
                            else None,
                            "requestedUrl": base_url
                            + verify_static_site.live_route_for(relative),
                            "finalUrl": (
                                "https://wrong-origin.invalid/redirected"
                                if is_first and not canonical_final
                                else base_url
                                + verify_static_site.live_route_for(relative)
                            ),
                            "canonicalFinalUrl": (
                                canonical_final if is_first else True
                            ),
                            "mediaType": (media_type if is_first else expected_type),
                        }

                    with (
                        patch.object(
                            verify_static_site,
                            "fetch_live",
                            side_effect=fake_fetch,
                        ),
                        patch.object(
                            verify_static_site,
                            "live_activation_gate",
                            side_effect=current_gate,
                        ),
                        patch("builtins.print"),
                    ):
                        exit_code = verify_static_site.main(
                            [
                                "--base-url",
                                verify_static_site.CANONICAL_LIVE_BASE_URL,
                                "--repo-root",
                                str(self.fixture.repository),
                                "--site-root",
                                str(self.fixture.site_root),
                                "--package",
                                str(package_path),
                                "--package-manifest",
                                str(manifest_path),
                                "--phase",
                                release_identity.PREACTIVATION_PHASE,
                                "--json-out",
                                str(report_path),
                            ]
                        )
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                    self.assertEqual(1, exit_code)
                    self.assertEqual("live_route_verification_failed", report["status"])
                    self.assertFalse(report["ok"])
                    self.assertFalse(report["claimsVerified"])

    def test_response_media_type_requires_one_explicit_unambiguous_header(self):
        test_case = self

        class Headers:
            def __init__(self, values):
                self.values = values

            def get_all(self, name, default=None):
                test_case.assertEqual("Content-Type", name)
                return self.values if self.values is not None else default

        class Response:
            def __init__(self, values):
                self.headers = Headers(values)

        self.assertIsNone(verify_static_site._response_media_type(Response(None)))
        self.assertIsNone(
            verify_static_site._response_media_type(
                Response(["text/plain", "application/json"])
            )
        )
        self.assertEqual(
            "text/plain",
            verify_static_site._response_media_type(
                Response(["text/plain; charset=utf-8"])
            ),
        )


class MultiAgentMemoryReleaseRunbookTests(unittest.TestCase):
    @staticmethod
    def published_commands():
        text = (ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")
        section = text.split("## MultiAgentMemory.com Companion Site", 1)[1]
        return [
            line.strip()
            for line in section.splitlines()
            if line.strip().startswith("py -3 scripts\\")
        ]

    def test_published_release_commands_parse_against_current_cli_contracts(self):
        commands = self.published_commands()
        package_commands = [
            line
            for line in commands
            if "package_multiagentmemory_static_site.py" in line
        ]
        deploy_commands = [
            line for line in commands if "ftp_deploy_static_site.py" in line
        ]
        verify_commands = [line for line in commands if "verify_static_site.py" in line]
        self.assertEqual(4, len(package_commands))
        self.assertEqual(6, len(deploy_commands))
        self.assertEqual(3, len(verify_commands))

        package_modes = set()
        package_phases = []
        for command in package_commands:
            arguments = shlex.split(command, posix=False)[3:]
            parsed = site_package.build_parser().parse_args(arguments)
            package_modes.add(
                "inspect"
                if parsed.inspect
                else "write"
                if parsed.write
                else "verify"
                if parsed.verify
                else "check"
            )
            self.assertEqual(".", parsed.repo_root)
            self.assertEqual("sites\\multiagentmemory.com", parsed.site_root)
            package_phases.append(parsed.phase)
        self.assertEqual({"inspect", "write", "verify"}, package_modes)
        self.assertEqual(3, package_phases.count(release_identity.PREACTIVATION_PHASE))
        self.assertEqual(1, package_phases.count(release_identity.FINAL_PHASE))

        deploy_phases = []
        for command in deploy_commands:
            arguments = shlex.split(command, posix=False)[3:]
            parsed = ftp_deploy_static_site.build_parser().parse_args(arguments)
            if parsed.connection_check:
                self.assertFalse(parsed.package)
                self.assertFalse(parsed.package_manifest)
                self.assertIsNone(parsed.phase)
            else:
                self.assertTrue(parsed.package)
                self.assertTrue(parsed.package_manifest)
                self.assertTrue(parsed.rollback_package)
                self.assertTrue(parsed.rollback_manifest)
                self.assertEqual(".", parsed.repo_root)
                deploy_phases.append(parsed.phase)
                if parsed.dry_run:
                    self.assertEqual(release_identity.PREACTIVATION_PHASE, parsed.phase)
        self.assertEqual(
            [
                release_identity.PREACTIVATION_PHASE,
                release_identity.PREACTIVATION_PHASE,
                release_identity.PREACTIVATION_PHASE,
                release_identity.FINAL_PHASE,
                release_identity.FINAL_PHASE,
            ],
            deploy_phases,
        )

        live_phases = set()
        for command in verify_commands:
            arguments = shlex.split(command, posix=False)[3:]
            parsed = verify_static_site.build_parser().parse_args(arguments)
            if parsed.base_url:
                self.assertTrue(parsed.package)
                self.assertTrue(parsed.package_manifest)
                self.assertEqual(".", parsed.repo_root)
                live_phases.add(parsed.phase)
        self.assertEqual(
            {release_identity.PREACTIVATION_PHASE, release_identity.FINAL_PHASE},
            live_phases,
        )

    def test_runbook_has_two_package_bound_live_phases_and_no_obsolete_upload_example(
        self,
    ):
        commands = self.published_commands()
        live_uploads = [
            command
            for command in commands
            if "ftp_deploy_static_site.py" in command
            and "--dry-run" not in command
            and "--connection-check" not in command
            and "--capture-rollback" not in command
            and "--restore-rollback" not in command
        ]
        self.assertEqual(2, len(live_uploads))
        self.assertTrue(all("--package" in line for line in live_uploads))
        self.assertTrue(all("--package-manifest" in line for line in live_uploads))
        self.assertTrue(all("--repo-root ." in line for line in live_uploads))
        self.assertIn("--phase preactivation", live_uploads[0])
        self.assertIn("--phase final", live_uploads[1])
        verification = (ROOT / "docs" / "verification.md").read_text(encoding="utf-8")
        live_verifiers = [
            line.strip()
            for line in verification.splitlines()
            if "verify_static_site.py --base-url https://multiagentmemory.com" in line
        ]
        self.assertEqual(2, len(live_verifiers))
        self.assertTrue(all("--package" in line for line in live_verifiers))
        self.assertTrue(all("--package-manifest" in line for line in live_verifiers))
        self.assertTrue(any("--phase preactivation" in line for line in live_verifiers))
        self.assertTrue(any("--phase final" in line for line in live_verifiers))

    def test_runbook_orders_nonclaims_tag_claims_final_proof_then_main(self):
        section = (
            (ROOT / "docs" / "deployment.md")
            .read_text(encoding="utf-8")
            .split("## MultiAgentMemory.com Companion Site", 1)[1]
        )
        step_headings = (
            "### 1. Render, test, and commit locally only",
            "### 2. Build one immutable package in preactivation",
            "### 3. Prove only the FTPS target",
            "### 4. Capture one target-bound prior state",
            "### 5. Stage only non-claim bytes",
            "### 6. Prove the twelve staged routes over canonical HTTPS",
            "### 7. Requalify immediately before creating the tag",
            "### 8. Publish the exact annotated tag, then prove final identity",
            "### 9. Activate the six claim paths, then retire the old path",
            "### 10. Prove all 18 canonical routes and the retired-route 404",
            "### 11. Advance `main` last",
        )
        positions = [section.index(heading) for heading in step_headings]
        self.assertEqual(sorted(positions), positions)
        self.assertEqual(11, sum(section.count(heading) for heading in step_headings))
        rollback_capture = section.index(
            "ftp_deploy_static_site.py --capture-rollback --phase preactivation"
        )
        preactivation_stage = section.index(
            "ftp_deploy_static_site.py --phase preactivation"
        )
        preactivation_live = section.index(
            "verify_static_site.py --base-url https://multiagentmemory.com --phase preactivation"
        )
        pretag_requalification = section.index(
            "ftp_deploy_static_site.py --dry-run --phase preactivation"
        )
        create_tag = section.index("git tag --annotate $TAG")
        push_tag = section.index('git push origin "${TAG_REF}:${TAG_REF}"')
        final_package = section.index(
            "package_multiagentmemory_static_site.py --verify --phase final"
        )
        final_activation = section.index("ftp_deploy_static_site.py --phase final")
        final_live = section.index(
            "verify_static_site.py --base-url https://multiagentmemory.com --phase final"
        )
        push_main = section.index('git push origin "${SOURCE_COMMIT}:refs/heads/main"')

        self.assertLess(rollback_capture, preactivation_stage)
        self.assertLess(preactivation_stage, preactivation_live)
        self.assertLess(preactivation_live, pretag_requalification)
        self.assertLess(pretag_requalification, create_tag)
        self.assertLess(preactivation_live, create_tag)
        self.assertLess(create_tag, push_tag)
        self.assertLess(push_tag, final_package)
        self.assertLess(final_package, final_activation)
        self.assertLess(final_activation, final_live)
        self.assertLess(final_live, push_main)
        self.assertNotIn("git push origin main", section)
        self.assertIn("A main race must never rewrite", section)
        self.assertIn("no embedded manifest", section)
        self.assertIn("adjacent external release-identity JSON", section)
        self.assertIn("`nonclaims_staged_preactivation`", section)
        self.assertIn("`nonclaims_live_verified_preactivation`", section)
        self.assertIn("`claims_activated_final`", section)
        self.assertIn("`full_live_verified_final`", section)
        self.assertIn("retired `/releases.html`", section)
        self.assertIn("ordinary HTTPS `404`", section)
        self.assertIn("`rollback_prior_state_captured`", section)
        self.assertIn("`rollback_current_state_unrecognized_no_mutation`", section)
        for obsolete_status in (
            "`activated_preactivation`",
            "`preactivation_live_verified`",
            "`uploaded`",
        ):
            self.assertNotIn(obsolete_status, section)
        self.assertEqual(
            (
                "ai-manifest.json",
                "ai.txt",
                "llms.txt",
                "README.md",
                "releases/index.html",
                "releases.json",
            ),
            release_identity.RELEASE_CLAIM_PATHS,
        )

    def test_live_verifier_refuses_network_without_the_closed_package_identity(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(verify_static_site, "fetch_live") as fetch_live,
            patch("builtins.print"),
        ):
            report_path = Path(tmp) / "report.json"
            exit_code = verify_static_site.main(
                [
                    "--base-url",
                    "https://multiagentmemory.com",
                    "--phase",
                    release_identity.PREACTIVATION_PHASE,
                    "--json-out",
                    str(report_path),
                ]
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(1, exit_code)
        self.assertEqual(
            "immutable_package_required_for_live_verification", report["status"]
        )
        self.assertFalse(report["identityCheckedBeforeFetch"])
        fetch_live.assert_not_called()

    def test_live_verifier_refuses_network_without_an_explicit_phase(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(verify_static_site, "fetch_live") as fetch_live,
            patch("builtins.print"),
        ):
            report_path = Path(tmp) / "report.json"
            exit_code = verify_static_site.main(
                [
                    "--base-url",
                    "https://multiagentmemory.com",
                    "--json-out",
                    str(report_path),
                ]
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(1, exit_code)
        self.assertEqual("live_verification_phase_required", report["status"])
        fetch_live.assert_not_called()

    def test_live_verifier_rejects_every_noncanonical_base_before_qualification(self):
        invalid_bases = (
            "http://multiagentmemory.com",
            "https://multiagentmemory.com/",
            "https://www.multiagentmemory.com",
            "https://multiagentmemory.com.evil.invalid",
            "https://multiagentmemory.com.",
            "https://xn--multiagentmemry-9za.com",
            "https://multiagentmemory.com:443",
            "https://multiagentmemory.com:444",
            "https://user@multiagentmemory.com",
            "https://multiagentmemory.com/base",
            "https://multiagentmemory.com?query=1",
            "https://multiagentmemory.com#fragment",
        )
        for index, base_url in enumerate(invalid_bases):
            with self.subTest(base_url=base_url), tempfile.TemporaryDirectory() as tmp:
                report_path = Path(tmp) / f"report-{index}.json"
                with (
                    patch.object(verify_static_site, "verify_package") as verify,
                    patch.object(verify_static_site, "fetch_live") as fetch,
                    patch("builtins.print"),
                ):
                    exit_code = verify_static_site.main(
                        [
                            "--base-url",
                            base_url,
                            "--phase",
                            release_identity.PREACTIVATION_PHASE,
                            "--package",
                            "unused.zip",
                            "--package-manifest",
                            "unused.json",
                            "--json-out",
                            str(report_path),
                        ]
                    )
                report = json.loads(report_path.read_text(encoding="utf-8"))
                self.assertEqual(1, exit_code)
                self.assertEqual("live_base_url_not_canonical", report["status"])
                self.assertFalse(report["requestedBaseUrlAccepted"])
                self.assertIsNone(report["baseUrl"])
                verify.assert_not_called()
                fetch.assert_not_called()

    def test_redirect_handler_rejects_same_and_cross_origin_redirects(self):
        handler = verify_static_site.RejectRedirects()
        request = Request("https://multiagentmemory.com/")
        for target in (
            "https://multiagentmemory.com/index.html",
            "https://wrong-origin.invalid/",
        ):
            with self.subTest(target=target):
                with self.assertRaises(HTTPError) as caught:
                    handler.redirect_request(
                        request,
                        None,
                        302,
                        "Found",
                        {},
                        target,
                    )
                caught.exception.close()

    def test_package_inspection_refuses_an_implicit_phase(self):
        with tempfile.TemporaryDirectory() as tmp, patch("builtins.print"):
            report_path = Path(tmp) / "report.json"
            exit_code = site_package.main(["--inspect", "--json-out", str(report_path)])
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(1, exit_code)
        self.assertEqual("release_phase_required", report["status"])
        self.assertTrue(report["safeNoOp"])
        self.assertFalse(report["written"])


if __name__ == "__main__":
    unittest.main()
