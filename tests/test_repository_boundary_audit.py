import tempfile
import unittest
from pathlib import Path

from scripts import audit_repository_boundary


class RepositoryBoundaryAuditTests(unittest.TestCase):
    def make_product_root(self, base, name="public-release-v1.0.0-from-deadbeef"):
        product = Path(base) / name
        (product / "memoryendpoints").mkdir(parents=True)
        (product / "sites" / "multiagentmemory.com").mkdir(parents=True)
        for (
            relative_path,
            first_line,
        ) in audit_repository_boundary.REPOSITORY_IDENTITY_MARKERS:
            (product / relative_path).write_text(first_line + "\n", encoding="utf-8")
        return product

    def test_clean_arbitrarily_named_release_worktree_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            drive = Path(tmp)
            product = self.make_product_root(drive)

            report = audit_repository_boundary.build_report(
                product_root=product, drive_root=drive
            )

            self.assertTrue(report["ok"])
            self.assertEqual(
                "multiagentmemory.repository_boundary_audit.v3", report["schemaVersion"]
            )
            self.assertEqual("Multi-Agent-Memory", report["canonicalRepositoryName"])
            self.assertEqual(product.name, report["checkoutDirectoryName"])
            self.assertTrue(report["repositoryIdentityMarkersValid"])
            self.assertEqual([], report["invalidRepositoryIdentityMarkerPaths"])
            self.assertFalse(
                report["truthBoundary"][
                    "repositoryIdentityDependsOnCheckoutDirectoryName"
                ]
            )
            self.assertNotIn("activeProductRoot", report)
            self.assertNotIn("memoryEndpointsSourceOfTruth", report["truthBoundary"])
            self.assertEqual([], report["duplicateProductSiteFoldersFound"])
            self.assertEqual([], report["repositoryRootRuntimeArtifactsFound"])
            self.assertTrue(report["sourcePackageRootIsExpectedRuntimePackage"])

    def test_old_product_basename_cannot_replace_repository_identity_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            drive = Path(tmp)
            product = self.make_product_root(drive, name="MemoryEndpoints.com")
            (product / "README.md").write_text(
                "# MemoryEndpoints.com\n", encoding="utf-8"
            )

            report = audit_repository_boundary.build_report(
                product_root=product, drive_root=drive
            )

            self.assertFalse(report["ok"])
            self.assertFalse(report["repositoryIdentityMarkersValid"])
            self.assertEqual(
                ["README.md"], report["invalidRepositoryIdentityMarkerPaths"]
            )

    def test_missing_repository_identity_marker_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            drive = Path(tmp)
            product = self.make_product_root(drive)
            (product / "NOTICE").unlink()

            report = audit_repository_boundary.build_report(
                product_root=product, drive_root=drive
            )

            self.assertFalse(report["ok"])
            self.assertFalse(report["repositoryIdentityMarkersValid"])
            self.assertEqual(["NOTICE"], report["invalidRepositoryIdentityMarkerPaths"])

    def test_duplicate_drive_root_site_folders_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            drive = Path(tmp)
            product = self.make_product_root(drive)
            (drive / "MultiAgentMemory.com").mkdir()
            (drive / "MemoryEndpoints.com-Publish").mkdir()

            report = audit_repository_boundary.build_report(
                product_root=product, drive_root=drive
            )

            self.assertFalse(report["ok"])
            self.assertEqual(2, len(report["duplicateProductSiteFoldersFound"]))
            self.assertTrue(
                any(
                    path.endswith("MultiAgentMemory.com")
                    for path in report["duplicateProductSiteFoldersFound"]
                )
            )

    def test_repo_root_runtime_artifacts_fail_without_flagging_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            drive = Path(tmp)
            product = self.make_product_root(drive)
            (product / "sqlite-write-check.sqlite3").write_text("", encoding="utf-8")
            (product / "devserver-8088.out.log").write_text("", encoding="utf-8")

            report = audit_repository_boundary.build_report(
                product_root=product, drive_root=drive
            )

            self.assertFalse(report["ok"])
            self.assertIn(
                "sqlite-write-check.sqlite3",
                report["repositoryRootRuntimeArtifactsFound"],
            )
            self.assertIn(
                "devserver-8088.out.log", report["repositoryRootRuntimeArtifactsFound"]
            )
            self.assertTrue(report["sourcePackageRootIsExpectedRuntimePackage"])


if __name__ == "__main__":
    unittest.main()
