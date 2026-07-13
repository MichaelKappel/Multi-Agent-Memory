import io
import json
import unittest
from unittest.mock import Mock, patch

from memoryendpoints.app import application
from memoryendpoints.storage import credential_system_available


class SetupMethodGuardTests(unittest.TestCase):
    @staticmethod
    def call_setup(method="GET", body=None, store=None):
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        raw_body = b"" if body is None else json.dumps(body).encode("utf-8")
        environ = {
            "PATH_INFO": "/api/matm/agent-setup/free-account",
            "REQUEST_METHOD": method,
            "QUERY_STRING": "",
            "CONTENT_LENGTH": str(len(raw_body)),
            "wsgi.input": io.BytesIO(raw_body),
        }
        replacement = store if store is not None else Mock()
        with patch("memoryendpoints.app._store", return_value=replacement):
            raw = b"".join(application(environ, start_response))
        return captured, json.loads(raw.decode("utf-8")), replacement

    def test_unsupported_setup_methods_are_safe_no_ops_before_store_access(self):
        for method in ("PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                captured = {}

                def start_response(status, headers):
                    captured["status"] = status
                    captured["headers"] = dict(headers)

                environ = {
                    "PATH_INFO": "/api/matm/agent-setup/free-account",
                    "REQUEST_METHOD": method,
                    "QUERY_STRING": "",
                    "CONTENT_LENGTH": "2",
                    "wsgi.input": io.BytesIO(b"{}"),
                }
                with patch("memoryendpoints.app._store", side_effect=AssertionError("store must not be called")):
                    raw = b"".join(application(environ, start_response))

                payload = json.loads(raw.decode("utf-8"))
                self.assertEqual("405 Method Not Allowed", captured["status"])
                self.assertEqual("GET, POST", captured["headers"]["Allow"])
                self.assertFalse(payload["ok"])
                self.assertTrue(payload["safeNoOp"])
                self.assertTrue(payload["valuesRedacted"])
                self.assertFalse(payload["rawCredentialExposed"])
                self.assertFalse(payload["rawPayloadExposed"])
                self.assertEqual("method_not_allowed", payload["error"]["code"])

    def test_credential_availability_uses_the_governed_pepper_boundary(self):
        with patch("memoryendpoints.storage._credential_pepper", return_value=b"configured"):
            self.assertTrue(credential_system_available())
        with patch(
            "memoryendpoints.storage._credential_pepper",
            side_effect=RuntimeError("credential service unavailable"),
        ):
            self.assertFalse(credential_system_available())

    def test_invalid_setup_shapes_and_labels_do_not_reach_store(self):
        valid = {
            "companyLabel": "Example Company",
            "label": "Example Workspace",
            "projectLabel": "Example Project",
        }
        cases = [
            ([], "setup_object_required"),
            ("workspace", "setup_object_required"),
            (7, "setup_object_required"),
            ({**valid, "companyLabel": []}, "setup_label_invalid"),
            ({**valid, "label": 7}, "setup_label_invalid"),
            ({**valid, "projectLabel": False}, "setup_label_invalid"),
            ({**valid, "companyLabel": " "}, "setup_label_invalid"),
            ({**valid, "label": "x" * 121}, "setup_label_too_long"),
            ({**valid, "projectLabel": "x" * 121}, "setup_label_too_long"),
        ]
        for body, expected_code in cases:
            with self.subTest(body_type=type(body).__name__, expected_code=expected_code):
                captured, payload, store = self.call_setup("POST", body)
                self.assertEqual("422 Unprocessable Entity", captured["status"])
                self.assertEqual("no-store", captured["headers"]["Cache-Control"])
                self.assertEqual(expected_code, payload["error"]["code"])
                self.assertTrue(payload["safeNoOp"])
                self.assertFalse(payload["rawCredentialExposed"])
                store.create_free_account.assert_not_called()

    def test_setup_get_and_post_are_no_store_and_valid_posts_are_distinct(self):
        with patch("memoryendpoints.app.credential_system_available", return_value=True):
            captured, payload, _store = self.call_setup("GET")
        self.assertEqual("200 OK", captured["status"])
        self.assertEqual("no-store", captured["headers"]["Cache-Control"])
        self.assertFalse(payload["idempotencySupported"])
        self.assertTrue(payload["credentialSystemAvailable"])
        guidance = payload["companyMasterStorageGuidance"]
        self.assertEqual(
            "memoryendpoints.company_master_storage_guidance.v1",
            guidance["schemaVersion"],
        )
        self.assertEqual(
            ".local-secrets/memoryendpoints-company-master.json",
            guidance["defaultLocalSecretPath"],
        )
        self.assertEqual("project_root", guidance["pathBase"])
        self.assertIn("companyMasterTokenSecret", guidance["requiredFields"])
        self.assertIn("Ask your AI agent", guidance["humanIfMissing"])
        self.assertIn("Stop safely", guidance["agentIfMissing"])
        self.assertTrue(guidance["persistenceRequiredBeforeSetupComplete"])
        self.assertEqual(
            "scripts/setup_memoryendpoints_company.py",
            guidance["agentSetupHelper"],
        )
        self.assertIn("does not create a local file", guidance["missingFileMeans"])
        self.assertFalse(guidance["rawCredentialIncluded"])

        store = Mock()
        store.create_free_account.side_effect = [
            ("workspace-one", "key-one", "secret-one", "account-one", "company-one", "project-one", "recovery-one"),
            ("workspace-two", "key-two", "secret-two", "account-two", "company-two", "project-two", "recovery-two"),
        ]
        body = {"companyLabel": " Company ", "label": " Workspace ", "projectLabel": " Project "}
        first_headers, first, _store = self.call_setup("POST", body, store)
        second_headers, second, _store = self.call_setup("POST", body, store)

        self.assertEqual("201 Created", first_headers["status"])
        self.assertEqual("201 Created", second_headers["status"])
        self.assertEqual("no-store, no-cache, must-revalidate, private", first_headers["headers"]["Cache-Control"])
        self.assertEqual("no-store, no-cache, must-revalidate, private", second_headers["headers"]["Cache-Control"])
        self.assertFalse(first["idempotencySupported"])
        self.assertFalse(second["idempotencySupported"])
        self.assertNotEqual(first["workspaceId"], second["workspaceId"])
        self.assertNotEqual(first["credentialId"], second["credentialId"])
        self.assertNotEqual(first["companyMasterTokenSecret"], second["companyMasterTokenSecret"])
        self.assertNotEqual(first["humanOwnerRecoverySecret"], second["humanOwnerRecoverySecret"])
        self.assertEqual(
            ".local-secrets/memoryendpoints-company-master.json",
            first["companyMasterStorageGuidance"]["defaultLocalSecretPath"],
        )
        self.assertNotIn(
            first["companyMasterTokenSecret"],
            json.dumps(first["companyMasterStorageGuidance"]),
        )
        self.assertEqual(
            [("Workspace", "Company", "Project"), ("Workspace", "Company", "Project")],
            [call.args for call in store.create_free_account.call_args_list],
        )

    def test_setup_get_reports_credential_service_availability(self):
        with patch("memoryendpoints.app.credential_system_available", return_value=False):
            captured, payload, _store = self.call_setup("GET")

        self.assertEqual("200 OK", captured["status"])
        self.assertEqual("no-store", captured["headers"]["Cache-Control"])
        self.assertFalse(payload["credentialSystemAvailable"])

    def test_missing_credential_configuration_fails_without_issuing_identifiers(self):
        store = Mock()
        store.create_free_account.side_effect = RuntimeError(
            "A protected credential pepper of at least 32 bytes is required."
        )
        body = {
            "companyLabel": "Example Company",
            "label": "Example Workspace",
            "projectLabel": "Example Project",
        }

        captured, payload, _store = self.call_setup("POST", body, store)

        self.assertEqual("503 Service Unavailable", captured["status"])
        self.assertEqual("credential_system_not_configured", payload["error"]["code"])
        self.assertTrue(payload["safeNoOp"])
        self.assertFalse(payload["rawCredentialExposed"])
        self.assertFalse(payload["rawPayloadExposed"])
        for key in (
            "accountId",
            "companyId",
            "workspaceId",
            "projectId",
            "credentialId",
            "companyMasterTokenSecret",
            "humanOwnerRecoverySecret",
        ):
            self.assertNotIn(key, payload)
        store.create_free_account.assert_called_once_with(
            "Example Workspace", "Example Company", "Example Project"
        )

    def test_omitted_labels_preserve_default_account_creation_contract(self):
        store = Mock()
        store.create_free_account.return_value = (
            "workspace-default",
            "key-default",
            "secret-default",
            "account-default",
            "company-default",
            "project-default",
            "recovery-default",
        )

        captured, payload, _store = self.call_setup("POST", {}, store)

        self.assertEqual("201 Created", captured["status"])
        self.assertEqual("no-store, no-cache, must-revalidate, private", captured["headers"]["Cache-Control"])
        self.assertEqual("workspace-default", payload["workspaceId"])
        self.assertEqual("recovery-default", payload["humanOwnerRecoverySecret"])
        store.create_free_account.assert_called_once_with(None, None, None)


if __name__ == "__main__":
    unittest.main()
