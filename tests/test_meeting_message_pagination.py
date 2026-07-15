import io
import json
import os
import shutil
import tempfile
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


class MeetingMessagePaginationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="memoryendpoints-meeting-pagination-")
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
                "companyLabel": "Meeting Pagination Company",
                "label": "Meeting Pagination Workspace",
                "projectLabel": "Meeting Pagination Project",
            },
        )
        self.assertEqual("201 Created", status)
        return json.loads(text)

    def project_room(self, workspace_id, agent):
        status, _headers, text = call_app(
            "/api/matm/meeting-rooms",
            headers=agent.auth_headers,
            query="workspace_id=%s&agent_id=%s" % (workspace_id, agent.agent_id),
        )
        self.assertEqual("200 OK", status)
        rooms = json.loads(text)["items"]
        return [room for room in rooms if room["scope"] == "project"][0]

    def post_message(self, workspace_id, agent, room_id, index):
        status, _headers, text = call_app(
            "/api/matm/meeting-messages",
            method="POST",
            headers=dict(
                agent.auth_headers,
                HTTP_IDEMPOTENCY_KEY="meeting-pagination-message-%d" % index,
            ),
            body={
                "workspaceId": workspace_id,
                "roomId": room_id,
                "senderAgentId": agent.agent_id,
                "safeSummary": "Meeting pagination message %d" % index,
            },
        )
        self.assertEqual("201 Created", status)
        return json.loads(text)["messageId"]

    def read_transcript(self, workspace_id, agent, room_id, limit=2, cursor=None):
        query = "workspace_id=%s&room_id=%s&agent_id=%s&limit=%s" % (
            workspace_id,
            room_id,
            agent.agent_id,
            limit,
        )
        if cursor:
            query += "&cursor=%s" % cursor
        status, _headers, text = call_app(
            "/api/matm/meeting-messages", headers=agent.auth_headers, query=query
        )
        self.assertEqual("200 OK", status)
        return json.loads(text)

    def assert_transcript_pages_older_messages(self, backend):
        self.configure_backend(backend)
        setup = self.create_workspace()
        workspace_id = setup["workspaceId"]
        agent = self.agent_provisioner.provision(
            master_bearer=setup["companyMasterTokenSecret"],
            company_id=setup["companyId"],
            workspace_id=workspace_id,
            project_id=setup["projectId"],
            requested_name="memoryendpoints-backend-agent",
            display_name="MemoryEndpoints Backend Agent",
            grant_scope_type="workspace",
        )
        room = self.project_room(workspace_id, agent)
        posted_ids = [
            self.post_message(workspace_id, agent, room["roomId"], index)
            for index in range(5)
        ]

        page_one = self.read_transcript(workspace_id, agent, room["roomId"], limit=2)
        self.assertEqual(posted_ids[-2:], [item["meetingMessageId"] for item in page_one["items"]])
        self.assertEqual(["Meeting pagination message 3", "Meeting pagination message 4"], [item["safeSummary"] for item in page_one["items"]])
        self.assertEqual(2, page_one["count"])
        self.assertEqual(2, page_one["visibleMessageCount"])
        self.assertEqual(5, page_one["totalMessageCount"])
        self.assertTrue(page_one["hasMore"])
        self.assertEqual(posted_ids[3], page_one["nextCursor"])
        self.assertEqual("older", page_one["pagination"]["cursorDirection"])
        self.assertEqual("latest_messages", page_one["transcriptOrdering"]["window"])
        self.assertEqual("oldest_to_newest_within_visible_window", page_one["transcriptOrdering"]["displayOrder"])
        self.assertEqual(5, page_one["operatorSummary"]["totalMessageCount"])
        self.assertEqual(2, page_one["operatorSummary"]["visibleMessageCount"])
        self.assertTrue(page_one["operatorSummary"]["pagination"]["hasMore"])

        page_two = self.read_transcript(
            workspace_id, agent, room["roomId"], limit=2, cursor=page_one["nextCursor"]
        )
        self.assertEqual(posted_ids[1:3], [item["meetingMessageId"] for item in page_two["items"]])
        self.assertEqual(["Meeting pagination message 1", "Meeting pagination message 2"], [item["safeSummary"] for item in page_two["items"]])
        self.assertEqual(2, page_two["visibleMessageCount"])
        self.assertEqual(5, page_two["totalMessageCount"])
        self.assertTrue(page_two["hasMore"])
        self.assertTrue(page_two["cursorAccepted"])
        self.assertEqual(page_one["nextCursor"], page_two["cursor"])

        page_three = self.read_transcript(
            workspace_id, agent, room["roomId"], limit=2, cursor=page_two["nextCursor"]
        )
        self.assertEqual([posted_ids[0]], [item["meetingMessageId"] for item in page_three["items"]])
        self.assertEqual(["Meeting pagination message 0"], [item["safeSummary"] for item in page_three["items"]])
        self.assertEqual(1, page_three["visibleMessageCount"])
        self.assertEqual(5, page_three["totalMessageCount"])
        self.assertFalse(page_three["hasMore"])
        self.assertIsNone(page_three["nextCursor"])
        self.assertTrue(page_three["cursorAccepted"])

    def test_meeting_transcript_pagination_across_backends(self):
        for backend in ("file", "sqlite"):
            with self.subTest(backend=backend):
                self.assert_transcript_pages_older_messages(backend)
