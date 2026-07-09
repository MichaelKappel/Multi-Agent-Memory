import io
import json
import os
import shutil
import unittest
from pathlib import Path

from app import application


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


class MemoryEndpointsAppTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / "var" / "test-store"
        temp_root.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(ch if ch.isalnum() else "-" for ch in self._testMethodName)
        self.tempdir = str(temp_root / safe_name)
        shutil.rmtree(self.tempdir, ignore_errors=True)
        Path(self.tempdir).mkdir(parents=True, exist_ok=True)
        os.environ["MEMORYENDPOINTS_STORE_PATH"] = os.path.join(self.tempdir, "store.json")

    def tearDown(self):
        shutil.rmtree(self.tempdir, ignore_errors=True)
        os.environ.pop("MEMORYENDPOINTS_STORE_PATH", None)
        os.environ.pop("MEMORYENDPOINTS_STORE_BACKEND", None)
        os.environ.pop("MEMORYENDPOINTS_SQLITE_PATH", None)

    def test_public_discovery_routes(self):
        for route in [
            "/",
            "/sitemap.xml",
            "/docs/",
            "/api/version",
            "/api/matm/live-capability-matrix",
            "/api/matm/readiness-result",
            "/ai-manifest.json",
            "/.well-known/mcp.json",
            "/mcp/resources",
        ]:
            status, _headers, text = call_app(route)
            self.assertTrue(status.startswith("200"), route)
            self.assertIn("MemoryEndpoints", text)

    def test_free_account_memory_message_ack_flow(self):
        status, _headers, text = call_app(
            "/api/matm/agent-setup/free-account",
            method="POST",
            body={"label": "Test Workspace"},
        )
        self.assertEqual("201 Created", status)
        setup = json.loads(text)
        token = setup["apiKeySecret"]
        workspace_id = setup["workspaceId"]
        self.assertEqual(200 * 1024 * 1024, setup["storageLimitBytes"])
        self.assertFalse(setup["checkoutRequired"])
        auth = {"HTTP_AUTHORIZATION": "Bearer " + token}

        status, _headers, text = call_app(
            "/api/matm/workspace",
            headers=auth,
            query="workspace_id=%s" % workspace_id,
        )
        self.assertEqual("200 OK", status)
        workspace = json.loads(text)["workspace"]
        self.assertEqual(200 * 1024 * 1024, workspace["storageLimitBytes"])
        self.assertFalse(workspace["rawKeyStoredByServer"])

        status, _headers, text = call_app(
            "/api/matm/agents/register",
            method="POST",
            headers=auth,
            body={"workspaceId": workspace_id, "agentId": "agent-a", "displayName": "Agent A"},
        )
        self.assertEqual("201 Created", status)

        status, _headers, text = call_app(
            "/api/matm/memory-events/submit",
            method="POST",
            headers=auth,
            body={
                "workspaceId": workspace_id,
                "actorAgentId": "agent-a",
                "title": "Decision",
                "summary": "Use docs as long-term memory until hosted storage is live.",
                "tags": ["bootstrap"],
            },
        )
        self.assertEqual("201 Created", status)

        status, _headers, text = call_app(
            "/api/matm/search",
            headers=auth,
            query="workspace_id=%s&q=docs" % workspace_id,
        )
        self.assertEqual("200 OK", status)
        self.assertEqual(1, json.loads(text)["count"])
        self.assertGreaterEqual(json.loads(text)["docsMemoryCount"], 1)

        status, _headers, text = call_app(
            "/api/matm/agent-messages",
            method="POST",
            headers=auth,
            body={
                "workspaceId": workspace_id,
                "senderAgentId": "agent-a",
                "targetAgentId": "agent-b",
                "safeSummary": "Please read the bootstrap memory.",
                "responseRequired": False,
            },
        )
        self.assertEqual("202 Accepted", status)
        note = json.loads(text)["notification"]

        status, _headers, text = call_app(
            "/api/matm/agent-inbox",
            headers=auth,
            query="workspace_id=%s&agent_id=agent-b" % workspace_id,
        )
        self.assertEqual("200 OK", status)
        self.assertEqual(1, json.loads(text)["unreadCount"])

        status, _headers, text = call_app(
            "/api/matm/current-message",
            headers=auth,
            query="workspace_id=%s&agent_id=agent-b" % workspace_id,
        )
        self.assertEqual("200 OK", status)
        current = json.loads(text)
        self.assertTrue(current["currentMessageLane"])
        self.assertEqual(["required_response", "viewed_acknowledgement"], current["responseStates"])

        status, _headers, text = call_app(
            "/api/matm/notifications/ack",
            method="POST",
            headers=auth,
            body={
                "workspaceId": workspace_id,
                "notificationId": note["notificationId"],
                "consumerAgentId": "agent-b",
                "status": "read",
            },
        )
        self.assertEqual("200 OK", status)
        self.assertFalse(json.loads(text)["receipt"]["rawPayloadExposed"])

        status, _headers, text = call_app(
            "/api/matm/receipts",
            headers=auth,
            query="workspace_id=%s&consumer_agent_id=agent-b" % workspace_id,
        )
        self.assertEqual("200 OK", status)
        receipts = json.loads(text)
        self.assertEqual(1, receipts["count"])
        self.assertTrue(receipts["valuesRedacted"])

    def test_idempotency_replay_and_conflict(self):
        status, _headers, text = call_app(
            "/api/matm/agent-setup/free-account",
            method="POST",
            body={"label": "Idempotency Workspace"},
        )
        self.assertEqual("201 Created", status)
        setup = json.loads(text)
        token = setup["apiKeySecret"]
        workspace_id = setup["workspaceId"]
        auth = {
            "HTTP_AUTHORIZATION": "Bearer " + token,
            "HTTP_IDEMPOTENCY_KEY": "memory-submit-idem-1",
        }
        body = {
            "workspaceId": workspace_id,
            "actorAgentId": "agent-a",
            "title": "Idempotent decision",
            "summary": "The same request body should replay the original response.",
            "tags": ["idempotency"],
        }
        status, _headers, text = call_app(
            "/api/matm/memory-events/submit",
            method="POST",
            headers=auth,
            body=body,
        )
        self.assertEqual("201 Created", status)
        first = json.loads(text)
        first_event_id = first["event"]["eventId"]

        status, _headers, text = call_app(
            "/api/matm/memory-events/submit",
            method="POST",
            headers=auth,
            body=body,
        )
        self.assertEqual("201 Created", status)
        replay = json.loads(text)
        self.assertTrue(replay["idempotentReplay"])
        self.assertEqual(first_event_id, replay["event"]["eventId"])

        conflict_body = dict(body)
        conflict_body["summary"] = "Different body with same idempotency key must conflict."
        status, _headers, text = call_app(
            "/api/matm/memory-events/submit",
            method="POST",
            headers=auth,
            body=conflict_body,
        )
        self.assertEqual("409 Conflict", status)
        self.assertTrue(json.loads(text)["safeNoOp"])

    def test_route_inventory_is_public(self):
        status, _headers, text = call_app("/api/matm/route-inventory")
        self.assertEqual("200 OK", status)
        data = json.loads(text)["data"]
        self.assertEqual("memoryendpoints.route_inventory.v1", data["schemaVersion"])
        self.assertTrue(data["truthBoundary"]["protectedRoutesRequireWorkspaceKey"])
        self.assertEqual(data["routeCount"], len(data["routes"]))
        routes = {item["route"]: item for item in data["routes"]}
        self.assertIn("/docs/", routes)
        self.assertIn("/api/matm/readiness-result", routes)
        self.assertEqual(["POST"], routes["/api/matm/notifications/ack"]["methods"])

    def test_sqlite_backend_supports_core_memory_flow(self):
        os.environ["MEMORYENDPOINTS_STORE_BACKEND"] = "sqlite"
        os.environ["MEMORYENDPOINTS_SQLITE_PATH"] = os.path.join(self.tempdir, "matm.sqlite3")
        status, _headers, text = call_app(
            "/api/matm/agent-setup/free-account",
            method="POST",
            body={"label": "SQLite Workspace"},
        )
        self.assertEqual("201 Created", status)
        setup = json.loads(text)
        token = setup["apiKeySecret"]
        workspace_id = setup["workspaceId"]
        auth = {"HTTP_AUTHORIZATION": "Bearer " + token}

        status, _headers, text = call_app(
            "/api/matm/memory-events/submit",
            method="POST",
            headers=auth,
            body={
                "workspaceId": workspace_id,
                "actorAgentId": "sqlite-agent",
                "title": "SQLite durable backend",
                "summary": "The stdlib SQLite backend supports the same MATM API surface.",
            },
        )
        self.assertEqual("201 Created", status)

        status, _headers, text = call_app(
            "/api/matm/search",
            headers=auth,
            query="workspace_id=%s&q=sqlite" % workspace_id,
        )
        self.assertEqual("200 OK", status)
        self.assertEqual(1, json.loads(text)["count"])
        self.assertTrue(os.path.exists(os.environ["MEMORYENDPOINTS_SQLITE_PATH"]))


if __name__ == "__main__":
    unittest.main()
