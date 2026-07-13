import json
import tempfile
import unittest
from pathlib import Path

from scripts.setup_memoryendpoints_company import (
    PROJECT_SECRET_PATH,
    SetupError,
    create_and_persist_company,
)


class _Response:
    status = 201

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class SetupMemoryEndpointsCompanyTests(unittest.TestCase):
    def payload(self):
        return {
            "ok": True,
            "companyId": "company-test",
            "workspaceId": "workspace-test",
            "projectId": "project-test",
            "humanOwnerCredentialId": "human-test",
            "companyMasterTokenSecret": "master-secret-test-only",
            "humanOwnerRecoverySecret": "recovery-secret-test-only",
        }

    def test_setup_writes_standard_company_file_and_separate_recovery_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_root = root / "project"
            recovery_out = root / "owner" / "recovery.json"
            calls = []

            def open_url(request, timeout):
                calls.append((request, timeout))
                return _Response(self.payload())

            result = create_and_persist_company(
                "Example Company",
                "Example Workspace",
                "Example Project",
                project_root=project_root,
                recovery_out=recovery_out,
                open_url=open_url,
            )

            company_path = project_root / PROJECT_SECRET_PATH
            self.assertTrue(company_path.is_file())
            self.assertTrue(recovery_out.is_file())
            company = json.loads(company_path.read_text(encoding="utf-8"))
            recovery = json.loads(recovery_out.read_text(encoding="utf-8"))
            self.assertEqual("master-secret-test-only", company["companyMasterTokenSecret"])
            self.assertEqual("recovery-secret-test-only", recovery["humanOwnerRecoverySecret"])
            self.assertEqual("memoryendpoints.company_master_credential_file.v1", company["schemaVersion"])
            self.assertTrue(result["credentialsPersisted"])
            self.assertFalse(result["credentialValuesPrinted"])
            redacted_result = json.dumps(result)
            self.assertNotIn("master-secret-test-only", redacted_result)
            self.assertNotIn("recovery-secret-test-only", redacted_result)
            self.assertEqual(1, len(calls))
            request_payload = json.loads(calls[0][0].data.decode("utf-8"))
            self.assertEqual("Example Company", request_payload["companyLabel"])

    def test_existing_target_stops_before_non_idempotent_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            project_root = Path(temporary) / "project"
            company_path = project_root / PROJECT_SECRET_PATH
            company_path.parent.mkdir(parents=True)
            company_path.write_text("{}", encoding="utf-8")
            called = []

            with self.assertRaisesRegex(SetupError, "already exists"):
                create_and_persist_company(
                    "Example Company",
                    "Example Workspace",
                    "Example Project",
                    project_root=project_root,
                    recovery_out=Path(temporary) / "recovery.json",
                    open_url=lambda *_args, **_kwargs: called.append(True),
                )
            self.assertEqual([], called)

    def test_rejects_insecure_remote_origin_before_request(self):
        with self.assertRaisesRegex(SetupError, "must use HTTPS"):
            create_and_persist_company(
                "Example Company",
                "Example Workspace",
                "Example Project",
                base_url="http://example.com",
            )


if __name__ == "__main__":
    unittest.main()
