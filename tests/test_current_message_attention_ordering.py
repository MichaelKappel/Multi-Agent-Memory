import io
import json
import os
import shutil
import tempfile
import time
import unittest

from app import application


ENV_KEYS = (
    "MEMORYENDPOINTS_STORE_BACKEND",
    "MEMORYENDPOINTS_STORE_PATH",
    "MEMORYENDPOINTS_SQLITE_PATH",
    "MEMORYENDPOINTS_MYSQL_CONFIG_PATH",
    "MEMORYENDPOINTS_ADMIN_DIAGNOSTICS_PATH",
)


def call_app(path, method="GET", body=None, headers=None, query=""):
    raw = b""
    if body is not None:
        raw = json.dumps(body).encode("utf-8")
    captured = {}

    def start_response(status, response_headers):
        captured["status"] = status
        captured["headers"] = dict(response_headers)

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "wsgi.input": io.BytesIO(raw),
        "CONTENT_LENGTH": str(len(raw)),
    }
    for key, value in (headers or {}).items():
        environ[key] = value
    chunks = application(environ, start_response)
    text = b"".join(chunks).decode("utf-8")
    return captured["status"], captured["headers"], text


class CurrentMessageAttentionOrderingTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="memoryendpoints-attention-order-")
        self.previous_env = {key: os.environ.get(key) for key in ENV_KEYS}
        os.environ["MEMORYENDPOINTS_MYSQL_CONFIG_PATH"] = os.path.join(self.tempdir, "missing-mysql.json")
        os.environ["MEMORYENDPOINTS_ADMIN_DIAGNOSTICS_PATH"] = os.path.join(self.tempdir, "missing-admin-diagnostics.json")

    def tearDown(self):
        for key, value in self.previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def configure_backend(self, backend):
        os.environ["MEMORYENDPOINTS_STORE_BACKEND"] = backend
        os.environ["MEMORYENDPOINTS_STORE_PATH"] = os.path.join(self.tempdir, "%s-store.json" % backend)
        os.environ["MEMORYENDPOINTS_SQLITE_PATH"] = os.path.join(self.tempdir, "%s-store.sqlite3" % backend)

    def create_workspace(self):
        status, _headers, text = call_app(
            "/api/matm/agent-setup/free-account",
            method="POST",
            body={
                "companyLabel": "Attention Ordering Company",
                "label": "Attention Ordering Workspace",
                "projectLabel": "Attention Ordering Project",
            },
        )
        self.assertEqual("201 Created", status)
        setup = json.loads(text)
        auth = {"HTTP_AUTHORIZATION": "Bearer " + setup["apiKeySecret"]}
        return setup["workspaceId"], auth

    def register_agents(self, workspace_id, auth):
        for agent_id in ("MemoryEndpoints-Backend-Agent", "human-verifier-agent"):
            status, _headers, _text = call_app(
                "/api/matm/agents/register",
                method="POST",
                headers=auth,
                body={"workspaceId": workspace_id, "agentId": agent_id, "displayName": agent_id},
            )
            self.assertEqual("201 Created", status)

    def post_message(self, workspace_id, auth, summary, response_required):
        status, _headers, text = call_app(
            "/api/matm/agent-messages",
            method="POST",
            headers=auth,
            body={
                "workspaceId": workspace_id,
                "senderAgentId": "human-verifier-agent",
                "targetAgentId": "MemoryEndpoints-Backend-Agent",
                "safeSummary": summary,
                "responseRequired": response_required,
            },
        )
        self.assertEqual("202 Accepted", status)
        return json.loads(text)

    def read_current_messages(self, workspace_id, auth, limit=None):
        query = "workspace_id=%s&agent_id=MemoryEndpoints-Backend-Agent" % workspace_id
        if limit is not None:
            query += "&limit=%s" % limit
        status, _headers, text = call_app("/api/matm/current-message", headers=auth, query=query)
        self.assertEqual("200 OK", status)
        return json.loads(text)

    def assert_required_response_is_attention_first(self, backend):
        self.configure_backend(backend)
        workspace_id, auth = self.create_workspace()
        self.register_agents(workspace_id, auth)

        self.post_message(workspace_id, auth, "Older message that needs a backend response.", True)
        time.sleep(0.01)
        self.post_message(workspace_id, auth, "Newer acknowledgement-only coordination message.", False)

        inbox = self.read_current_messages(workspace_id, auth)
        self.assertEqual(2, inbox["unreadCount"])
        self.assertEqual(
            ["required_response", "viewed_acknowledgement"],
            [item["delivery"]["responseDisposition"] for item in inbox["items"]],
        )
        self.assertEqual("Older message that needs a backend response.", inbox["items"][0]["message"]["safeSummary"])
        self.assertEqual("Newer acknowledgement-only coordination message.", inbox["items"][1]["message"]["safeSummary"])
        self.assertEqual(
            {"required_response": 1, "viewed_acknowledgement": 1},
            inbox["operatorSummary"]["responseDispositionCounts"],
        )

        limited = self.read_current_messages(workspace_id, auth, limit=1)
        self.assertEqual(1, limited["unreadCount"])
        self.assertEqual("required_response", limited["items"][0]["delivery"]["responseDisposition"])
        self.assertEqual("Older message that needs a backend response.", limited["items"][0]["message"]["safeSummary"])
        self.assertEqual(
            {"required_response": 1, "viewed_acknowledgement": 0},
            limited["operatorSummary"]["responseDispositionCounts"],
        )

    def test_required_response_precedes_newer_acknowledgement_across_backends(self):
        for backend in ("file", "sqlite"):
            with self.subTest(backend=backend):
                self.assert_required_response_is_attention_first(backend)
