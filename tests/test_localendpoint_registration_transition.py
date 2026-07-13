import io
import json
import os
import secrets
import shutil
import tempfile
import unittest
from pathlib import Path

from app import application
from memoryendpoints.storage import FileStore, SQLiteStore


def call_api(path, method="GET", body=None, token=None, idempotency_key=None):
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "wsgi.input": io.BytesIO(raw),
        "CONTENT_LENGTH": str(len(raw)),
    }
    if body is not None:
        environ["CONTENT_TYPE"] = "application/json"
    if token:
        environ["HTTP_AUTHORIZATION"] = "Bearer " + token
    if idempotency_key:
        environ["HTTP_IDEMPOTENCY_KEY"] = idempotency_key
    response = b"".join(application(environ, start_response))
    return int(captured["status"].split(" ", 1)[0]), captured["headers"], json.loads(response)


class LocalEndpointRegistrationTransitionContract:
    backend = None

    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="localendpoint-registration-transition-")
        self.saved = {
            key: os.environ.get(key)
            for key in (
                "MEMORYENDPOINTS_STORE_BACKEND",
                "MEMORYENDPOINTS_STORE_PATH",
                "MEMORYENDPOINTS_SQLITE_PATH",
                "MEMORYENDPOINTS_CREDENTIAL_PEPPER",
                "MEMORYENDPOINTS_CREDENTIAL_CONFIG_PATH",
            )
        }
        os.environ.update(
            {
                "MEMORYENDPOINTS_STORE_BACKEND": self.backend,
                "MEMORYENDPOINTS_STORE_PATH": str(Path(self.tempdir) / "store.json"),
                "MEMORYENDPOINTS_SQLITE_PATH": str(Path(self.tempdir) / "store.sqlite3"),
                "MEMORYENDPOINTS_CREDENTIAL_PEPPER": secrets.token_urlsafe(48),
                "MEMORYENDPOINTS_CREDENTIAL_CONFIG_PATH": str(
                    Path(self.tempdir) / "missing-pepper.json"
                ),
            }
        )
        store = (
            SQLiteStore(Path(self.tempdir) / "store.sqlite3")
            if self.backend == "sqlite"
            else FileStore(Path(self.tempdir) / "store.json")
        )
        setup = store.create_free_account(
            "LocalEndpoint Compatibility Workspace",
            "LocalEndpoint Compatibility Company",
            "LocalEndpoint Compatibility Project",
        )
        self.workspace_id, _key_id, self.master_token = setup[:3]

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def body(self, agent_id="localendpoint-agent"):
        return {
            "workspaceId": self.workspace_id,
            "agentId": agent_id,
            "displayName": "Caller-controlled display is ignored",
        }

    def test_exact_canonical_registration_is_idempotent_and_issues_no_token(self):
        key = "localendpoint-transition-idempotency-key"
        first = call_api(
            "/api/matm/agents/register",
            "POST",
            self.body(),
            self.master_token,
            key,
        )
        second = call_api(
            "/api/matm/agents/register",
            "POST",
            self.body(),
            self.master_token,
            key,
        )
        self.assertEqual(201, first[0], first[2])
        self.assertEqual(201, second[0], second[2])
        self.assertFalse(first[2]["idempotentReplay"])
        self.assertTrue(second[2]["idempotentReplay"])
        first_stable = dict(first[2], idempotentReplay=None)
        second_stable = dict(second[2], idempotentReplay=None)
        self.assertEqual(first_stable, second_stable)
        payload = first[2]
        self.assertEqual("localendpoint-agent", payload["agent"]["agentId"])
        self.assertEqual("LocalEndpoint Agent", payload["agent"]["displayName"])
        transition = payload["compatibilityTransition"]
        self.assertEqual("deprecated", transition["status"])
        self.assertTrue(transition["idempotent"])
        self.assertFalse(transition["tokenIssued"])
        self.assertFalse(transition["broaderAuthorityGranted"])
        self.assertEqual(
            "memoryendpoints.connector_pairing.v1", transition["migrateTo"]
        )
        encoded = json.dumps(payload, sort_keys=True).lower()
        self.assertNotIn("tokensecret", encoded)
        self.assertNotIn("credentialsecret", encoded)

    def test_arbitrary_master_selected_agent_remains_invite_only(self):
        status, _headers, payload = call_api(
            "/api/matm/agents/register",
            "POST",
            self.body("arbitrary-master-selected-agent"),
            self.master_token,
        )
        self.assertEqual(409, status, payload)
        self.assertEqual("registration_requires_invite", payload["error"]["code"])
        self.assertTrue(payload["safeNoOp"])

    def test_transition_body_is_exact_and_does_not_accept_actor_extensions(self):
        body = self.body()
        body["actorAgentId"] = "localendpoint-agent"
        status, _headers, payload = call_api(
            "/api/matm/agents/register", "POST", body, self.master_token
        )
        self.assertEqual(422, status, payload)
        self.assertEqual("localendpoint_registration_invalid", payload["error"]["code"])


class FileLocalEndpointRegistrationTransitionTests(
    LocalEndpointRegistrationTransitionContract, unittest.TestCase
):
    backend = "file"


class SQLiteLocalEndpointRegistrationTransitionTests(
    LocalEndpointRegistrationTransitionContract, unittest.TestCase
):
    backend = "sqlite"


if __name__ == "__main__":
    unittest.main()
