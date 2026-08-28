import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install_lan_host_task.ps1"
CERTIFICATE_SETUP = ROOT / "scripts" / "new_lan_tls_certificate.ps1"
CLIENT_TRUST = ROOT / "scripts" / "install_lan_client_trust.ps1"


@unittest.skipUnless(sys.platform == "win32", "Windows scheduled-task scripts")
class LanHostScriptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="multi-agent-memory-lan-task-"
        )
        self.root = Path(self.temporary.name)
        scripts = self.root / "scripts"
        scripts.mkdir()
        shutil.copy2(ROOT / "scripts" / "serve_lan.py", scripts / "serve_lan.py")
        tls = self.root / ".local-secrets" / "tls"
        tls.mkdir(parents=True)
        for name in ("lan-server.pem", "lan-server-key.pem", "lan-ca.pem"):
            (tls / name).write_text("test fixture only\n", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def run_installer_plan(self, *extra, allowed_network="10.1.10.0/24"):
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(INSTALLER),
            "-ProjectRoot",
            str(self.root),
            "-PythonPath",
            sys.executable,
            "-AdvertiseHost",
            "10.1.10.209",
            "-AllowedNetwork",
            allowed_network,
            "-PlanOnly",
            *extra,
        ]
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )

    def test_windows_powershell_plan_is_deterministic_bounded_and_redacted(self):
        first = self.run_installer_plan()
        second = self.run_installer_plan()
        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertEqual(first.stdout, second.stdout)
        plan = json.loads(first.stdout)
        self.assertEqual("multi_agent_memory.lan_host_task_plan.v1", plan["schemaVersion"])
        self.assertEqual("Interactive", plan["principal"]["logonType"])
        self.assertEqual("Limited", plan["principal"]["runLevel"])
        self.assertFalse(plan["principal"]["storedPassword"])
        self.assertEqual(5, plan["settings"]["restartCount"])
        self.assertEqual("PT1M", plan["settings"]["restartInterval"])
        self.assertEqual("IgnoreNew", plan["settings"]["multipleInstances"])
        self.assertIn(str(self.root / "scripts" / "serve_lan.py"), plan["arguments"])
        self.assertIn("--tls-cert-file", plan["arguments"])
        self.assertTrue(plan["secureBaseUrl"].startswith("https://"))
        self.assertTrue(plan["valuesRedacted"])
        self.assertFalse(plan["rawCredentialExposed"])
        self.assertFalse(plan["rawPayloadExposed"])
        self.assertNotIn("Authorization", first.stdout)
        self.assertNotIn("agentTokenSecret", first.stdout)

    def test_installer_rejects_public_allowlist_before_task_mutation(self):
        result = self.run_installer_plan(allowed_network="0.0.0.0/0")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("allowed_network_", result.stderr)

    def test_scripts_parse_in_windows_powershell(self):
        for path in (INSTALLER, CERTIFICATE_SETUP, CLIENT_TRUST):
            escaped = str(path).replace("'", "''")
            expression = (
                "$e=$null;$t=$null;"
                f"[void][Management.Automation.Language.Parser]::ParseFile('{escaped}',[ref]$t,[ref]$e);"
                "if($e.Count){$e|ForEach-Object{$_.Message};exit 1}"
            )
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", expression],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(0, result.returncode, f"{path}: {result.stdout} {result.stderr}")

    def test_installer_source_fails_closed_on_unknown_task_drift(self):
        source = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("scheduled_task_name_collision_or_unrecognized_drift", source)
        self.assertIn("Test-KnownLegacyTask", source)
        self.assertNotIn("-RunLevel Highest", source)
        self.assertNotIn("-UserId 'SYSTEM'", source)

    def test_client_trust_requires_fingerprint_and_current_user_store(self):
        source = CLIENT_TRUST.read_text(encoding="utf-8")
        self.assertIn("ExpectedSha256Fingerprint", source)
        self.assertIn("$difference = $difference -bor", source)
        self.assertIn("X509BasicConstraintsExtension", source)
        self.assertIn("certutil.exe -user", source)
        self.assertIn("Cert:\\CurrentUser\\Root", source)
        self.assertNotIn("LocalMachine", source)


if __name__ == "__main__":
    unittest.main()
