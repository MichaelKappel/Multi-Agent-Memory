import tempfile
import unittest
from pathlib import Path

from scripts import audit_repository_boundary


class RepositoryBoundaryAuditTests(unittest.TestCase):
    def make_product_root(self, base):
        product = Path(base) / "MemoryEndpoints.com"
        (product / "memoryendpoints").mkdir(parents=True)
        (product / "sites" / "multiagentmemory.com").mkdir(parents=True)
        return product

    def test_clean_product_root_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            drive = Path(tmp)
            product = self.make_product_root(drive)

            report = audit_repository_boundary.build_report(product_root=product, drive_root=drive)

            self.assertTrue(report["ok"])
            self.assertEqual([], report["duplicateProductSiteFoldersFound"])
            self.assertEqual([], report["repositoryRootRuntimeArtifactsFound"])
            self.assertTrue(report["sourcePackageRootIsExpectedRuntimePackage"])

    def test_duplicate_drive_root_site_folders_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            drive = Path(tmp)
            product = self.make_product_root(drive)
            (drive / "MultiAgentMemory.com").mkdir()
            (drive / "MemoryEndpoints.com-Publish").mkdir()

            report = audit_repository_boundary.build_report(product_root=product, drive_root=drive)

            self.assertFalse(report["ok"])
            self.assertEqual(2, len(report["duplicateProductSiteFoldersFound"]))
            self.assertTrue(
                any(path.endswith("MultiAgentMemory.com") for path in report["duplicateProductSiteFoldersFound"])
            )

    def test_repo_root_runtime_artifacts_fail_without_flagging_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            drive = Path(tmp)
            product = self.make_product_root(drive)
            (product / "sqlite-write-check.sqlite3").write_text("", encoding="utf-8")
            (product / "devserver-8088.out.log").write_text("", encoding="utf-8")

            report = audit_repository_boundary.build_report(product_root=product, drive_root=drive)

            self.assertFalse(report["ok"])
            self.assertIn("sqlite-write-check.sqlite3", report["repositoryRootRuntimeArtifactsFound"])
            self.assertIn("devserver-8088.out.log", report["repositoryRootRuntimeArtifactsFound"])
            self.assertTrue(report["sourcePackageRootIsExpectedRuntimePackage"])


if __name__ == "__main__":
    unittest.main()
