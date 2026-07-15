import hashlib
import io
import json
import os
import shutil
import tempfile
import time
import unittest

from app import application
from tests.governed_test_support import GovernedAgentProvisioner


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
        self.agent_provisioner = GovernedAgentProvisioner(call_app).install()
        self.addCleanup(self.agent_provisioner.restore)
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
        return json.loads(text)

    def provision_agent(self, setup, requested_name, display_name):
        return self.agent_provisioner.provision(
            master_bearer=setup["companyMasterTokenSecret"],
            company_id=setup["companyId"],
            workspace_id=setup["workspaceId"],
            project_id=setup["projectId"],
            requested_name=requested_name,
            display_name=display_name,
            grant_scope_type="workspace",
        )

    def post_message(self, workspace_id, sender, target_agent_id, summary, response_required):
        status, _headers, text = call_app(
            "/api/matm/agent-messages",
            method="POST",
            headers=dict(
                sender.auth_headers,
                HTTP_IDEMPOTENCY_KEY="attention-message-%s-%s"
                % (
                    target_agent_id or "broadcast",
                    hashlib.sha256(summary.encode("utf-8")).hexdigest()[:16],
                ),
            ),
            body={
                "workspaceId": workspace_id,
                "senderAgentId": sender.agent_id,
                "targetAgentId": target_agent_id,
                "safeSummary": summary,
                "responseRequired": response_required,
            },
        )
        self.assertEqual("202 Accepted", status)
        return json.loads(text)

    def read_current_messages(self, workspace_id, agent, limit=None, cursor=None):
        query = "workspace_id=%s&agent_id=%s" % (workspace_id, agent.agent_id)
        if limit is not None:
            query += "&limit=%s" % limit
        if cursor is not None:
            query += "&cursor=%s" % cursor
        status, _headers, text = call_app(
            "/api/matm/current-message", headers=agent.auth_headers, query=query
        )
        self.assertEqual("200 OK", status)
        return json.loads(text)

    def assert_required_response_is_attention_first(self, backend):
        self.configure_backend(backend)
        setup = self.create_workspace()
        workspace_id = setup["workspaceId"]
        backend_agent = self.provision_agent(
            setup, "memoryendpoints-backend-agent", "MemoryEndpoints Backend Agent"
        )
        sender_agent = self.provision_agent(
            setup, "human-verifier-agent", "Human Verifier Agent"
        )

        self.post_message(
            workspace_id,
            sender_agent,
            backend_agent.agent_id,
            "Older message that needs a backend response.",
            True,
        )
        time.sleep(0.01)
        self.post_message(
            workspace_id,
            sender_agent,
            backend_agent.agent_id,
            "Newer acknowledgement-only coordination message.",
            False,
        )

        inbox = self.read_current_messages(workspace_id, backend_agent)
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

        limited = self.read_current_messages(workspace_id, backend_agent, limit=1)
        self.assertEqual(1, limited["unreadCount"])
        self.assertEqual(1, limited["visibleUnreadCount"])
        self.assertEqual(2, limited["totalUnreadCount"])
        self.assertTrue(limited["hasMore"])
        self.assertTrue(limited["nextCursor"].startswith("note-"))
        self.assertEqual("required_response", limited["items"][0]["delivery"]["responseDisposition"])
        self.assertEqual("Older message that needs a backend response.", limited["items"][0]["message"]["safeSummary"])
        self.assertEqual(
            {"required_response": 1, "viewed_acknowledgement": 0},
            limited["operatorSummary"]["responseDispositionCounts"],
        )
        self.assertEqual(
            ["required_response", "viewed_acknowledgement"],
            limited["attentionOrdering"]["priority"],
        )
        self.assertEqual("newest_notification_first", limited["attentionOrdering"]["withinPriority"])
        self.assertEqual(2, limited["operatorSummary"]["totalUnreadCount"])
        self.assertTrue(limited["operatorSummary"]["pagination"]["hasMore"])

        next_page = self.read_current_messages(
            workspace_id, backend_agent, limit=1, cursor=limited["nextCursor"]
        )
        self.assertEqual(1, next_page["unreadCount"])
        self.assertEqual(1, next_page["visibleUnreadCount"])
        self.assertEqual(2, next_page["totalUnreadCount"])
        self.assertFalse(next_page["hasMore"])
        self.assertIsNone(next_page["nextCursor"])
        self.assertEqual(limited["nextCursor"], next_page["cursor"])
        self.assertTrue(next_page["cursorAccepted"])
        self.assertEqual("viewed_acknowledgement", next_page["items"][0]["delivery"]["responseDisposition"])
        self.assertEqual("Newer acknowledgement-only coordination message.", next_page["items"][0]["message"]["safeSummary"])

    def test_required_response_precedes_newer_acknowledgement_across_backends(self):
        for backend in ("file", "sqlite"):
            with self.subTest(backend=backend):
                self.assert_required_response_is_attention_first(backend)
