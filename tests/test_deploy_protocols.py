import unittest
from pathlib import Path

from scripts import build_deploy_attempt_report, ftp_deploy_memoryendpoints, ftp_deploy_static_site


ROOT = Path(__file__).resolve().parents[1]


class DeployProtocolTests(unittest.TestCase):
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
            self.assertIn("connection_check_passed", script)
            self.assertIn("uploadedCount", script)
            self.assertIn("args.dry_run or args.connection_check", script)

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


if __name__ == "__main__":
    unittest.main()
