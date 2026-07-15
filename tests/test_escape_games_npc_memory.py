import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from app import application
from memoryendpoints.app import _store


def call_api(path, method="GET", body=None, token=None, query="", idempotency_key=None):
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "wsgi.input": io.BytesIO(raw),
        "CONTENT_LENGTH": str(len(raw)),
    }
    if token:
        environ["HTTP_AUTHORIZATION"] = "Bearer " + token
    if idempotency_key:
        environ["HTTP_IDEMPOTENCY_KEY"] = idempotency_key
    response = b"".join(application(environ, start_response)).decode("utf-8")
    return int(captured["status"].split(" ", 1)[0]), json.loads(response)


class EscapeGamesNpcMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="memoryendpoints-escape-npc-")
        self.saved_environment = {
            key: os.environ.get(key)
            for key in (
                "MEMORYENDPOINTS_STORE_BACKEND",
                "MEMORYENDPOINTS_STORE_PATH",
                "MEMORYENDPOINTS_SQLITE_PATH",
                "MEMORYENDPOINTS_CREDENTIAL_PEPPER",
                "MEMORYENDPOINTS_CREDENTIAL_CONFIG_PATH",
                "MEMORYENDPOINTS_MYSQL_CONFIG_PATH",
            )
        }
        os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = (
            "test-only-escape-npc-memory-pepper-" + ("y" * 64)
        )
        os.environ["MEMORYENDPOINTS_CREDENTIAL_CONFIG_PATH"] = str(
            Path(self.tempdir) / "missing-credentials.json"
        )
        os.environ["MEMORYENDPOINTS_MYSQL_CONFIG_PATH"] = str(
            Path(self.tempdir) / "missing-mysql.json"
        )

    def tearDown(self):
        for key, value in self.saved_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def _select_backend(self, backend):
        os.environ["MEMORYENDPOINTS_STORE_BACKEND"] = backend
        os.environ["MEMORYENDPOINTS_STORE_PATH"] = str(
            Path(self.tempdir) / (backend + "-store.json")
        )
        os.environ["MEMORYENDPOINTS_SQLITE_PATH"] = str(
            Path(self.tempdir) / (backend + "-store.sqlite3")
        )

    def _setup_workspace(self, backend, purpose="NPC isolation"):
        self._select_backend(backend)
        status, payload = call_api(
            "/api/matm/agent-setup/free-account",
            "POST",
            {
                "companyLabel": "Private intranet " + purpose + " " + backend,
                "label": "MATM workspace " + purpose + " " + backend,
                "projectLabel": "MATM project " + purpose + " " + backend,
            },
        )
        self.assertEqual(201, status, payload)
        self.assertFalse(payload.get("storageUnlimited", False))
        self.assertEqual(200 * 1024 * 1024, payload["storageLimitBytes"])
        return payload

    def _force_storage_limit(self, backend, workspace_id, limit_bytes):
        store = _store()
        if backend == "file":
            data = store._load()
            data["workspaces"][workspace_id]["storageLimitBytes"] = limit_bytes
            store._save(data)
            return
        with store._open_connection() as connection:
            with connection:
                connection.execute(
                    "UPDATE matm_workspaces SET storage_limit_bytes = ? WHERE workspace_id = ?",
                    (limit_bytes, workspace_id),
                )

    def _provision_agent(self, setup, agent_id, scope_type, scope_id):
        master = setup["companyMasterTokenSecret"]
        status, requested = call_api(
            "/api/matm/access/agent-name-requests",
            "POST",
            {
                "requestedName": agent_id,
                "displayName": agent_id,
                "requestedGrant": {"scopeType": scope_type, "scopeId": scope_id},
                "assignmentContext": {
                    "agentClass": "game_npc" if agent_id.startswith("npc-") else "test_agent",
                    "boundary": "in_game_only" if agent_id.startswith("npc-") else "test",
                },
                "justification": "Provision a scoped agent for Escape NPC memory tests.",
            },
            master,
            idempotency_key="request-%s-%s-%s" % (agent_id, scope_type, scope_id),
        )
        self.assertEqual(201, status, requested)
        request_id = requested["request"]["requestId"]
        status, approved = call_api(
            "/api/matm/access/agent-name-requests/%s/decision" % request_id,
            "POST",
            {"decision": "approve", "decisionReason": "Approved for scoped test."},
            master,
            idempotency_key="approve-%s" % request_id,
        )
        self.assertEqual(200, status, approved)
        status, issued = call_api(
            "/api/matm/access/invites",
            "POST",
            {"approvedRequestId": request_id, "expiresInSeconds": 900},
            master,
        )
        self.assertEqual(201, status, issued)
        invite_secret = issued["inviteUrl"].split("#invite=", 1)[1]
        status, redeemed = call_api(
            "/api/matm/access/invites/redeem",
            "POST",
            {"inviteSecret": invite_secret},
        )
        self.assertEqual(201, status, redeemed)
        return redeemed

    def _create_room(self, setup, scope, scope_id, parent_scope_type, parent_scope_id, idem, token=None, agent_id=None):
        body = {
            "workspaceId": setup["workspaceId"],
            "scope": scope,
            "scopeId": scope_id,
            "parentScopeType": parent_scope_type,
            "parentScopeId": parent_scope_id,
            "label": "%s room %s" % (scope.title(), scope_id),
        }
        if agent_id:
            body["creatorAgentId"] = agent_id
        status, payload = call_api(
            "/api/matm/meeting-rooms",
            "POST",
            body,
            token or setup["companyMasterTokenSecret"],
            idempotency_key=idem,
        )
        self.assertIn(status, (200, 201), payload)
        return payload["room"]

    def _project_room(self, setup):
        status, payload = call_api(
            "/api/matm/workspace",
            token=setup["companyMasterTokenSecret"],
            query="workspace_id=" + setup["workspaceId"],
        )
        self.assertEqual(200, status, payload)
        for room in payload["workspace"]["meetingRooms"]:
            if room["scope"] == "project" and room["scopeId"] == setup["projectId"]:
                return room
        self.fail("project room was not present in master workspace readback")

    def test_public_edition_omits_commercial_dogfood_partner_setup(self):
        status, payload = call_api("/api/matm/agent-setup/dogfood-partner-account")
        self.assertEqual(404, status, payload)
        self.assertEqual("not_found", payload["error"]["code"])

        status, inventory = call_api("/api/matm/route-inventory")
        self.assertEqual(200, status, inventory)
        routes = {item["route"] for item in inventory["data"]["routes"]}
        self.assertNotIn("/api/matm/agent-setup/dogfood-partner-account", routes)

        status, openapi = call_api("/api/matm/openapi.json")
        self.assertEqual(200, status, openapi)
        self.assertNotIn(
            "/api/matm/agent-setup/dogfood-partner-account",
            openapi["paths"],
        )

    def test_free_private_intranet_quota_remains_enforced(self):
        for backend in ("file", "sqlite"):
            with self.subTest(backend=backend):
                free = self._setup_workspace(backend, "quota control")
                status, workspace = call_api(
                    "/api/matm/workspace",
                    token=free["companyMasterTokenSecret"],
                    query="workspace_id=" + free["workspaceId"],
                )
                self.assertEqual(200, status, workspace)
                used = workspace["workspace"]["storageUsedBytes"]
                self._force_storage_limit(backend, free["workspaceId"], used + 8192)
                self.assertTrue(
                    _store().has_quota_for(free["workspaceId"], {"blob": "x"})
                )
                self.assertFalse(
                    _store().has_quota_for(free["workspaceId"], {"blob": "x" * 65536})
                )

    def test_npc_credentials_are_game_bounded_and_memory_is_scope_isolated(self):
        for backend in ("file", "sqlite"):
            with self.subTest(backend=backend):
                setup = self._setup_workspace(backend, "NPC isolation")
                master = setup["companyMasterTokenSecret"]
                workspace_id = setup["workspaceId"]
                project_id = setup["projectId"]
                game_id = "escape-ward-game-" + backend
                session_id = "escape-ward-session-" + backend
                sibling_game_id = "escape-sibling-game-" + backend

                status, forbidden = call_api(
                    "/api/matm/access/agent-name-requests",
                    "POST",
                    {
                        "requestedName": "npc-company-snoop-" + backend,
                        "displayName": "npc-company-snoop-" + backend,
                        "requestedGrant": {"scopeType": "company", "scopeId": setup["companyId"]},
                        "assignmentContext": {"agentClass": "game_npc"},
                        "justification": "This should be refused before approval.",
                    },
                    master,
                    idempotency_key="request-forbidden-npc-company-" + backend,
                )
                self.assertEqual(403, status, forbidden)
                self.assertEqual("npc_scope_forbidden", forbidden["error"]["code"])

                game_room = self._create_room(
                    setup,
                    "game",
                    game_id,
                    "project",
                    project_id,
                    "create-game-room-" + backend,
                )
                self._create_room(
                    setup,
                    "game",
                    sibling_game_id,
                    "project",
                    project_id,
                    "create-sibling-game-room-" + backend,
                )
                npc = self._provision_agent(
                    setup,
                    "npc-ward-orderly-" + backend,
                    "project",
                    project_id,
                )
                sibling_npc = self._provision_agent(
                    setup,
                    "npc-sibling-guard-" + backend,
                    "game",
                    sibling_game_id,
                )
                npc_token = npc["agentTokenSecret"]
                npc_id = npc["principal"]["agentId"]

                status, npc_workspace = call_api(
                    "/api/matm/workspace",
                    token=npc_token,
                    query="workspace_id=" + workspace_id,
                )
                self.assertEqual(200, status, npc_workspace)
                self.assertTrue(npc_workspace["workspace"]["hierarchyRedacted"])
                self.assertNotIn("accounts", npc_workspace["workspace"])
                self.assertNotIn("company", npc_workspace["workspace"])
                self.assertTrue(npc_workspace["workspace"]["meetingRooms"])
                self.assertTrue(
                    all(room["scope"] in ("game", "session") for room in npc_workspace["workspace"]["meetingRooms"])
                )

                project_room = self._project_room(setup)
                status, blocked_transcript = call_api(
                    "/api/matm/meeting-messages",
                    token=npc_token,
                    query=(
                        "workspace_id=%s&room_id=%s&agent_id=%s"
                        % (workspace_id, project_room["roomId"], npc_id)
                    ),
                )
                self.assertEqual(403, status, blocked_transcript)
                self.assertEqual("npc_game_scope_required", blocked_transcript["error"]["code"])

                status, blocked_post = call_api(
                    "/api/matm/meeting-messages",
                    "POST",
                    {
                        "workspaceId": workspace_id,
                        "roomId": project_room["roomId"],
                        "senderAgentId": npc_id,
                        "safeSummary": "NPCs must not post outside game/session rooms.",
                    },
                    npc_token,
                    idempotency_key="npc-project-post-blocked-" + backend,
                )
                self.assertEqual(403, status, blocked_post)
                self.assertEqual("npc_game_scope_required", blocked_post["error"]["code"])

                session_room = self._create_room(
                    setup,
                    "session",
                    session_id,
                    "game",
                    game_id,
                    "npc-create-session-room-" + backend,
                    token=npc_token,
                    agent_id=npc_id,
                )
                status, posted = call_api(
                    "/api/matm/meeting-messages",
                    "POST",
                    {
                        "workspaceId": workspace_id,
                        "roomId": session_room["roomId"],
                        "senderAgentId": npc_id,
                        "safeSummary": "Orderly confirms the player has solved the first ward puzzle.",
                    },
                    npc_token,
                    idempotency_key="npc-session-post-" + backend,
                )
                self.assertEqual(201, status, posted)
                self.assertEqual(session_room["roomId"], posted["room"]["roomId"])

                status, memory = call_api(
                    "/api/matm/memory-events/submit",
                    "POST",
                    {
                        "workspaceId": workspace_id,
                        "actorAgentId": npc_id,
                        "scope": "game",
                        "scopeId": game_id,
                        "title": "Player trust with ward orderly",
                        "summary": "The ward orderly remembers that this player solved the first ward puzzle.",
                        "tags": ["npc:npc-ward-orderly", "player:player-a", "game:" + game_id],
                        "source": "escape.gamesfor.me://game/%s/session/%s" % (game_id, session_id),
                        "memoryType": "npc_player_relationship",
                        "subject": "npc-ward-orderly/player:player-a",
                    },
                    npc_token,
                    idempotency_key="npc-player-memory-" + backend,
                )
                self.assertEqual(201, status, memory)
                self.assertEqual("npc_player_relationship", memory["event"]["memoryType"])

                status, visible_search = call_api(
                    "/api/matm/search",
                    token=npc_token,
                    query="workspace_id=%s&tag=%s" % (workspace_id, "player:player-a"),
                )
                self.assertEqual(200, status, visible_search)
                self.assertGreaterEqual(visible_search["count"], 1)

                status, sibling_search = call_api(
                    "/api/matm/search",
                    token=sibling_npc["agentTokenSecret"],
                    query="workspace_id=%s&tag=%s" % (workspace_id, "player:player-a"),
                )
                self.assertEqual(200, status, sibling_search)
                self.assertEqual(0, sibling_search["count"])

                status, company_submit = call_api(
                    "/api/matm/memory-events/submit",
                    "POST",
                    {
                        "workspaceId": workspace_id,
                        "actorAgentId": npc_id,
                        "scope": "company",
                        "scopeId": setup["companyId"],
                        "title": "Forbidden company memory",
                        "summary": "NPCs must not write company memory.",
                        "tags": ["npc-boundary"],
                        "source": "escape.gamesfor.me://forbidden",
                        "memoryType": "npc_world_knowledge",
                    },
                    npc_token,
                    idempotency_key="npc-company-memory-blocked-" + backend,
                )
                self.assertEqual(403, status, company_submit)
                self.assertEqual("insufficient_scope", company_submit["error"]["code"])


if __name__ == "__main__":
    unittest.main()
