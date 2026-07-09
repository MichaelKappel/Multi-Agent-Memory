import unittest
import tempfile
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
