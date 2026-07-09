import unittest
from pathlib import Path

from scripts import ftp_deploy_memoryendpoints, ftp_deploy_static_site


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


if __name__ == "__main__":
    unittest.main()
