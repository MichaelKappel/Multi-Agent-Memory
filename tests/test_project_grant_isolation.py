import copy
import hashlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
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


class ProjectGrantIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="memoryendpoints-project-grant-")
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
            "test-only-project-grant-isolation-pepper-" + ("x" * 64)
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

    def _setup_workspace(self, backend):
        self._select_backend(backend)
        status, payload = call_api(
            "/api/matm/agent-setup/free-account",
            "POST",
            {
                "companyLabel": "Scope Isolation Company " + backend,
                "label": "Scope Isolation Workspace " + backend,
                "projectLabel": "Primary Visible Project " + backend,
            },
        )
        self.assertEqual(201, status, payload)
        return payload

    def _provision_agent(self, setup, agent_id, scope_type, scope_id):
        master = setup["companyMasterTokenSecret"]
        status, requested = call_api(
            "/api/matm/access/agent-name-requests",
            "POST",
            {
                "requestedName": agent_id,
                "displayName": agent_id,
                "requestedGrant": {"scopeType": scope_type, "scopeId": scope_id},
                "assignmentContext": {"testFixture": "project-grant-isolation"},
                "justification": "Verify exact lower-scope isolation boundaries.",
            },
            master,
            idempotency_key="request-%s-%s" % (scope_type, agent_id),
        )
        self.assertEqual(201, status, requested)
        request_id = requested["request"]["requestId"]
        status, approved = call_api(
            "/api/matm/access/agent-name-requests/%s/decision" % request_id,
            "POST",
            {"decision": "approve", "decisionReason": "Approved for isolation verification."},
            master,
            idempotency_key="approve-%s-%s" % (scope_type, agent_id),
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

    def _create_room(self, setup, scope, scope_id, idem):
        status, payload = call_api(
            "/api/matm/meeting-rooms",
            "POST",
            {
                "workspaceId": setup["workspaceId"],
                "scope": scope,
                "scopeId": scope_id,
                "label": "%s isolation room" % scope.title(),
            },
            setup["companyMasterTokenSecret"],
            idempotency_key=idem,
        )
        self.assertEqual(201, status, payload)
        return payload["room"]

    def _assert_scope_error(self, status, payload):
        self.assertEqual(403, status, payload)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["safeNoOp"])
        self.assertEqual("insufficient_scope", payload["error"]["code"])

    def _seed_uai_heads_and_claims(self, workspace_id, project_ids, agent_id):
        store = _store()
        for index, project_id in enumerate(project_ids):
            available_projects = {
                item.get("projectId") for item in store.projects(workspace_id)
            }
            self.assertIn(project_id, available_projects, available_projects)
            result, error, _details = store.acquire_uai_edit_claim(
                workspace_id,
                project_id,
                agent_id,
                ".uai/context-%s.uai" % index,
                "%064x" % (index + 1),
                "Seed one project-scoped collaboration claim.",
                600,
            )
            self.assertIsNone(error)
            completed, error, _details = store.complete_uai_edit_claim(
                workspace_id,
                agent_id,
                result["claim"]["claimId"],
                "%064x" % (index + 11),
                "Complete the seeded collaboration claim.",
            )
            self.assertIsNone(error)
            self.assertEqual("completed", completed["claim"]["status"])

    def _seed_sync_head(self, workspace_id, agent_id, backend):
        store = _store()
        device = store.register_sync_device(
            workspace_id, agent_id, "sibling-device-" + backend, "Sibling sync device"
        )
        result, status = store.submit_sync_mutation(
            workspace_id,
            agent_id,
            {
                "logicalMemoryId": "sibling-logical-memory-" + backend,
                "deviceId": device["deviceId"],
                "deviceEpoch": device["authorityEpoch"],
                "operation": "upsert",
                "title": "Sibling sync head",
                "summary": "Seeded only to prove that lower grants cannot read sync state.",
            },
            "sibling-sync-seed-" + backend,
        )
        self.assertEqual("202 Accepted", status)
        self.assertEqual("applied", result["status"])
        return result["receipt"]["receiptId"]

    def _bulk_clone_sibling_records(
        self, backend, store, sibling_document_id, sibling_link_id, clone_count=500
    ):
        if backend == "file":
            data = store._load()
            document_template = copy.deepcopy(
                data["searchDocuments"][sibling_document_id]
            )
            link_template = copy.deepcopy(data["externalLinks"][sibling_link_id])
            mention_template = copy.deepcopy(
                next(
                    item
                    for item in data["externalLinkMentions"].values()
                    if item.get("externalLinkId") == sibling_link_id
                )
            )
            for index in range(clone_count):
                suffix = "%s-%04d" % (backend, index)
                document_id = "doc-bulk-sibling-" + suffix
                document = copy.deepcopy(document_template)
                document.update(
                    {
                        "searchDocumentId": document_id,
                        "title": "AAA sibling document " + suffix,
                        "routeOrPath": "/knowledge/project/pagination/" + suffix,
                    }
                )
                data["searchDocuments"][document_id] = document

                link_id = "ext-bulk-sibling-" + suffix
                url = "https://example.com/bulk-sibling/" + suffix
                link = copy.deepcopy(link_template)
                link.update(
                    {
                        "externalLinkId": link_id,
                        "url": url,
                        "normalizedUrl": url,
                        "normalizedUrlHash": hashlib.sha256(
                            url.encode("utf-8")
                        ).hexdigest(),
                        "pageUrl": url,
                        "fragment": "",
                        "siteName": "AAA sibling site " + suffix,
                        "pageTitle": "AAA sibling page " + suffix,
                    }
                )
                data["externalLinks"][link_id] = link
                mention_id = "mention-bulk-sibling-" + suffix
                mention = copy.deepcopy(mention_template)
                mention.update(
                    {
                        "externalLinkMentionId": mention_id,
                        "externalLinkId": link_id,
                        "knowledgeDocumentId": sibling_document_id,
                    }
                )
                data["externalLinkMentions"][mention_id] = mention
            store._save(data)
            return

        with closing(
            sqlite3.connect(os.environ["MEMORYENDPOINTS_SQLITE_PATH"])
        ) as connection:
            connection.row_factory = sqlite3.Row
            document_template = dict(
                connection.execute(
                    "SELECT * FROM matm_search_documents WHERE search_document_id = ?",
                    (sibling_document_id,),
                ).fetchone()
            )
            link_template = dict(
                connection.execute(
                    "SELECT * FROM matm_external_links WHERE external_link_id = ?",
                    (sibling_link_id,),
                ).fetchone()
            )
            mention_template = dict(
                connection.execute(
                    "SELECT * FROM matm_external_link_mentions WHERE external_link_id = ? LIMIT 1",
                    (sibling_link_id,),
                ).fetchone()
            )
            document_rows = []
            link_rows = []
            mention_rows = []
            for index in range(clone_count):
                suffix = "%s-%04d" % (backend, index)
                document = dict(document_template)
                document.update(
                    {
                        "search_document_id": "doc-bulk-sibling-" + suffix,
                        "title": "AAA sibling document " + suffix,
                        "route_or_path": "/knowledge/project/pagination/" + suffix,
                    }
                )
                document_rows.append(document)
                link_id = "ext-bulk-sibling-" + suffix
                url = "https://example.com/bulk-sibling/" + suffix
                link = dict(link_template)
                link.update(
                    {
                        "external_link_id": link_id,
                        "url": url,
                        "normalized_url": url,
                        "normalized_url_hash": hashlib.sha256(
                            url.encode("utf-8")
                        ).hexdigest(),
                        "page_url": url,
                        "fragment": "",
                        "site_name": "AAA sibling site " + suffix,
                        "page_title": "AAA sibling page " + suffix,
                    }
                )
                link_rows.append(link)
                mention = dict(mention_template)
                mention.update(
                    {
                        "external_link_mention_id": "mention-bulk-sibling-"
                        + suffix,
                        "external_link_id": link_id,
                    }
                )
                mention_rows.append(mention)

            def insert_rows(table, rows):
                columns = list(rows[0])
                connection.executemany(
                    "INSERT INTO %s (%s) VALUES (%s)"
                    % (
                        table,
                        ", ".join(columns),
                        ", ".join("?" for _column in columns),
                    ),
                    [tuple(row[column] for column in columns) for row in rows],
                )

            insert_rows("matm_search_documents", document_rows)
            insert_rows("matm_external_links", link_rows)
            insert_rows("matm_external_link_mentions", mention_rows)
            connection.commit()

    def test_authorization_precedes_limits_and_hidden_mention_matching(self):
        for backend in ("file", "sqlite"):
            with self.subTest(backend=backend):
                setup = self._setup_workspace(backend)
                workspace_id = setup["workspaceId"]
                primary_project_id = setup["projectId"]
                master = setup["companyMasterTokenSecret"]
                status, sibling = call_api(
                    "/api/matm/projects",
                    "POST",
                    {
                        "workspaceId": workspace_id,
                        "projectId": "pagination-sibling-" + backend,
                        "label": "Pagination Sibling " + backend,
                    },
                    master,
                    idempotency_key="pagination-sibling-create-" + backend,
                )
                self.assertEqual(201, status, sibling)
                sibling_project_id = sibling["project"]["projectId"]
                project_agent = self._provision_agent(
                    setup,
                    "pagination-project-agent-" + backend,
                    "project",
                    primary_project_id,
                )
                token = project_agent["agentTokenSecret"]
                agent_id = project_agent["principal"]["agentId"]
                store = _store()

                def seed_document(project_id, title, source_suffix):
                    document, error = store.upsert_knowledge_document(
                        workspace_id,
                        agent_id,
                        {
                            "scope": "project",
                            "scopeId": project_id,
                            "projectId": project_id,
                            "title": title,
                            "description": "Authorization-before-limit regression evidence.",
                            "keywords": ["authorization", "pagination"],
                            "taxonomyPaths": [["Security", "Pagination"]],
                            "category": "pagination",
                            "sourceUri": "memoryendpoints://tests/" + source_suffix,
                            "routeOrPath": "/knowledge/project/pagination/"
                            + source_suffix,
                            "searchableText": "Public-safe pagination isolation evidence.",
                        },
                    )
                    self.assertIsNone(error)
                    return document

                authorized_document = seed_document(
                    primary_project_id,
                    "ZZZ authorized document " + backend,
                    "authorized-document-" + backend,
                )
                sibling_document = seed_document(
                    sibling_project_id,
                    "AAA sibling document template " + backend,
                    "sibling-document-" + backend,
                )

                def seed_link(url_suffix, site_name, page_title, document_id, context):
                    link, error = store.upsert_external_link(
                        workspace_id,
                        agent_id,
                        {
                            "url": "https://example.com/" + url_suffix,
                            "siteName": site_name,
                            "pageTitle": page_title,
                            "description": "Stored pagination isolation reference.",
                            "keywords": ["pagination", "isolation"],
                            "knowledgeDocumentId": document_id,
                            "relationshipType": "reference",
                            "contextDescription": context,
                        },
                    )
                    self.assertIsNone(error)
                    return link

                authorized_link = seed_link(
                    "zzz-authorized-" + backend,
                    "ZZZ Authorized Site " + backend,
                    "ZZZ Authorized Page " + backend,
                    authorized_document["searchDocumentId"],
                    "Visible authorized citation context.",
                )
                sibling_link = seed_link(
                    "aaa-sibling-template-" + backend,
                    "AAA Sibling Site " + backend,
                    "AAA Sibling Page " + backend,
                    sibling_document["searchDocumentId"],
                    "Sibling-only citation context.",
                )
                shared_link = seed_link(
                    "zzzz-shared-" + backend,
                    "ZZZZ Shared Site " + backend,
                    "ZZZZ Shared Page " + backend,
                    authorized_document["searchDocumentId"],
                    "Visible shared citation context.",
                )
                hidden_query = "HIDDENMENTIONOPAQUE8F4C2A7D"
                shared_link = seed_link(
                    "zzzz-shared-" + backend,
                    "ZZZZ Shared Site " + backend,
                    "ZZZZ Shared Page " + backend,
                    sibling_document["searchDocumentId"],
                    hidden_query,
                )
                self.assertEqual(2, shared_link["mentionCount"])

                self._bulk_clone_sibling_records(
                    backend,
                    store,
                    sibling_document["searchDocumentId"],
                    sibling_link["externalLinkId"],
                )
                self.assertGreaterEqual(
                    len(store.knowledge_documents(workspace_id, _all=True)), 502
                )
                self.assertGreaterEqual(
                    len(store.external_links(workspace_id, _all=True)), 503
                )

                status, documents = call_api(
                    "/api/matm/knowledge-documents",
                    token=token,
                    query="workspace_id=%s&limit=1" % workspace_id,
                )
                self.assertEqual(200, status, documents)
                self.assertEqual(
                    [authorized_document["searchDocumentId"]],
                    [item["searchDocumentId"] for item in documents["items"]],
                )
                status, tree = call_api(
                    "/api/matm/knowledge-tree",
                    token=token,
                    query="workspace_id=" + workspace_id,
                )
                self.assertEqual(200, status, tree)
                self.assertEqual(1, tree["tree"]["documentCount"])

                status, links = call_api(
                    "/api/matm/external-links",
                    token=token,
                    query="workspace_id=%s&limit=1" % workspace_id,
                )
                self.assertEqual(200, status, links)
                self.assertEqual(
                    [authorized_link["externalLinkId"]],
                    [item["externalLinkId"] for item in links["items"]],
                )
                self.assertEqual(1, links["items"][0]["mentionCount"])

                status, shared = call_api(
                    "/api/matm/external-links",
                    token=token,
                    query="workspace_id=%s&external_link_id=%s"
                    % (workspace_id, shared_link["externalLinkId"]),
                )
                self.assertEqual(200, status, shared)
                self.assertEqual(1, shared["count"])
                self.assertEqual(1, shared["items"][0]["mentionCount"])
                self.assertEqual(
                    {primary_project_id},
                    {
                        mention["scopeId"]
                        for mention in shared["items"][0]["mentions"]
                    },
                )
                self.assertNotIn(hidden_query, json.dumps(shared, sort_keys=True))

                status, hidden_search = call_api(
                    "/api/matm/internet-search",
                    token=token,
                    query="workspace_id=%s&q=%s" % (workspace_id, hidden_query),
                )
                self.assertEqual(200, status, hidden_search)
                self.assertEqual([], hidden_search["items"])
                status, hidden_scope_filter = call_api(
                    "/api/matm/external-links",
                    token=token,
                    query=(
                        "workspace_id=%s&external_link_id=%s&scope_id=%s"
                        % (
                            workspace_id,
                            shared_link["externalLinkId"],
                            sibling_project_id,
                        )
                    ),
                )
                self.assertEqual(200, status, hidden_scope_filter)
                self.assertEqual([], hidden_scope_filter["items"])

    def test_lower_grants_cannot_cross_workspace_subresource_boundaries(self):
        for backend in ("file", "sqlite"):
            with self.subTest(backend=backend):
                setup = self._setup_workspace(backend)
                workspace_id = setup["workspaceId"]
                primary_project_id = setup["projectId"]
                master = setup["companyMasterTokenSecret"]
                sibling_project_id = "sibling-hidden-project-" + backend

                status, sibling = call_api(
                    "/api/matm/projects",
                    "POST",
                    {
                        "workspaceId": workspace_id,
                        "projectId": sibling_project_id,
                        "label": "SIBLING_PROJECT_PRIVATE_MARKER_" + backend,
                    },
                    master,
                    idempotency_key="create-sibling-project-" + backend,
                )
                self.assertEqual(201, status, sibling)
                sibling_project_id = sibling["project"]["projectId"]

                goal_id = "authorized-goal-" + backend
                task_id = "authorized-task-" + backend
                self._create_room(setup, "goal", goal_id, "create-goal-room-" + backend)
                self._create_room(setup, "task", task_id, "create-task-room-" + backend)

                project_agent = self._provision_agent(
                    setup,
                    "project-boundary-agent-" + backend,
                    "project",
                    primary_project_id,
                )
                goal_agent = self._provision_agent(
                    setup, "goal-boundary-agent-" + backend, "goal", goal_id
                )
                task_agent = self._provision_agent(
                    setup, "task-boundary-agent-" + backend, "task", task_id
                )
                project_token = project_agent["agentTokenSecret"]
                project_agent_id = project_agent["principal"]["agentId"]

                self._seed_uai_heads_and_claims(
                    workspace_id,
                    (primary_project_id, sibling_project_id),
                    project_agent_id,
                )
                sync_receipt_id = self._seed_sync_head(
                    workspace_id, project_agent_id, backend
                )

                status, master_workspace = call_api(
                    "/api/matm/workspace",
                    token=master,
                    query="workspace_id=" + workspace_id,
                )
                self.assertEqual(200, status, master_workspace)
                self.assertEqual(2, len(master_workspace["workspace"]["projects"]))
                self.assertIn("accounts", master_workspace["workspace"])

                lower_credentials = (
                    (project_agent, "project", {primary_project_id}, {"project", "goal", "task"}),
                    (goal_agent, "goal", set(), {"goal"}),
                    (task_agent, "task", set(), {"task"}),
                )
                for redeemed, expected_scope, visible_projects, visible_room_scopes in lower_credentials:
                    token = redeemed["agentTokenSecret"]
                    agent_id = redeemed["principal"]["agentId"]
                    status, payload = call_api(
                        "/api/matm/workspace",
                        token=token,
                        query="workspace_id=" + workspace_id,
                    )
                    self.assertEqual(200, status, payload)
                    workspace = payload["workspace"]
                    for forbidden_key in (
                        "accountId",
                        "companyId",
                        "company",
                        "accounts",
                        "accountCompanyMemberships",
                    ):
                        self.assertNotIn(forbidden_key, workspace)
                    self.assertTrue(workspace["hierarchyRedacted"])
                    self.assertEqual(expected_scope, workspace["authorizedScope"]["scopeType"])
                    self.assertEqual(
                        visible_projects,
                        {item["projectId"] for item in workspace["projects"]},
                    )
                    self.assertEqual(
                        visible_room_scopes,
                        {item["scope"] for item in workspace["meetingRooms"]},
                    )
                    self.assertNotIn(
                        sibling_project_id,
                        {item["scopeId"] for item in workspace["meetingRooms"]},
                    )
                    self.assertTrue(payload["operatorSummary"]["hierarchyRedacted"])
                    self.assertTrue(
                        {item["level"] for item in payload["operatorSummary"]["hierarchy"]}
                        .isdisjoint({"account", "company"})
                    )

                    status, rooms = call_api(
                        "/api/matm/meeting-rooms",
                        token=token,
                        query="workspace_id=%s&agent_id=%s" % (workspace_id, agent_id),
                    )
                    self.assertEqual(200, status, rooms)
                    self.assertEqual(
                        visible_room_scopes, {item["scope"] for item in rooms["items"]}
                    )
                    self.assertNotIn(
                        sibling_project_id, {item["scopeId"] for item in rooms["items"]}
                    )

                status, heads = call_api(
                    "/api/matm/uai-memory/file-heads",
                    token=project_token,
                    query="workspace_id=" + workspace_id,
                )
                self.assertEqual(200, status, heads)
                self.assertEqual(
                    {primary_project_id}, {item["projectId"] for item in heads["items"]}
                )
                status, claims = call_api(
                    "/api/matm/uai-memory/edit-claims",
                    token=project_token,
                    query="workspace_id=" + workspace_id,
                )
                self.assertEqual(200, status, claims)
                self.assertEqual(
                    {primary_project_id}, {item["projectId"] for item in claims["items"]}
                )
                status, sibling_heads = call_api(
                    "/api/matm/uai-memory/file-heads",
                    token=project_token,
                    query="workspace_id=%s&project_id=%s"
                    % (workspace_id, sibling_project_id),
                )
                self.assertEqual(200, status, sibling_heads)
                self.assertEqual([], sibling_heads["items"])

                status, goal_heads = call_api(
                    "/api/matm/uai-memory/file-heads",
                    token=goal_agent["agentTokenSecret"],
                    query="workspace_id=" + workspace_id,
                )
                self.assertEqual(200, status, goal_heads)
                self.assertEqual([], goal_heads["items"])

                denied_room_id = "ambiguous-project-goal-" + backend
                status, denied_room = call_api(
                    "/api/matm/meeting-rooms",
                    "POST",
                    {
                        "workspaceId": workspace_id,
                        "creatorAgentId": project_agent_id,
                        "scope": "goal",
                        "scopeId": denied_room_id,
                        "label": "Must not infer a project parent",
                    },
                    project_token,
                    idempotency_key="deny-ambiguous-goal-" + backend,
                )
                self._assert_scope_error(status, denied_room)
                snapshot = _store()._load()
                self.assertFalse(
                    any(
                        item.get("scopeId") == denied_room_id
                        for item in snapshot.get("scopeNodes", {}).values()
                    )
                )
                self.assertFalse(
                    any(
                        item.get("scopeId") == denied_room_id
                        for item in snapshot.get("meetingRooms", {}).values()
                    )
                )

                status, existing_room = call_api(
                    "/api/matm/meeting-rooms",
                    "POST",
                    {
                        "workspaceId": workspace_id,
                        "creatorAgentId": project_agent_id,
                        "scope": "goal",
                        "scopeId": goal_id,
                        "label": "Authorized existing goal room",
                    },
                    project_token,
                    idempotency_key="resolve-existing-goal-" + backend,
                )
                self.assertEqual(200, status, existing_room)
                self.assertFalse(existing_room["created"])

                sync_gets = (
                    ("/api/matm/sync/retention", ""),
                    ("/api/matm/sync/receipts", "receipt_id=" + sync_receipt_id),
                    ("/api/matm/sync/changes", "after_sequence=0"),
                    ("/api/matm/sync/heads", ""),
                )
                for path, extra_query in sync_gets:
                    query = "workspace_id=" + workspace_id
                    if extra_query:
                        query += "&" + extra_query
                    status, payload = call_api(
                        path, token=project_token, query=query
                    )
                    self._assert_scope_error(status, payload)

                sync_posts = (
                    (
                        "/api/matm/sync/devices",
                        {
                            "workspaceId": workspace_id,
                            "agentId": project_agent_id,
                            "deviceId": "denied-device-" + backend,
                        },
                    ),
                    (
                        "/api/matm/sync/devices/rotate",
                        {
                            "workspaceId": workspace_id,
                            "agentId": project_agent_id,
                            "deviceId": "sibling-device-" + backend,
                        },
                    ),
                    (
                        "/api/matm/sync/devices/revoke",
                        {
                            "workspaceId": workspace_id,
                            "agentId": project_agent_id,
                            "deviceId": "sibling-device-" + backend,
                        },
                    ),
                    (
                        "/api/matm/sync/mutations",
                        {
                            "workspaceId": workspace_id,
                            "actorAgentId": project_agent_id,
                            "deviceId": "sibling-device-" + backend,
                            "logicalMemoryId": "denied-logical-memory-" + backend,
                            "operation": "upsert",
                            "title": "Denied mutation",
                            "summary": "This must remain a safe no-op.",
                        },
                    ),
                )
                for index, (path, body) in enumerate(sync_posts):
                    status, payload = call_api(
                        path,
                        "POST",
                        body,
                        project_token,
                        idempotency_key="deny-project-sync-%s-%s" % (backend, index),
                    )
                    self._assert_scope_error(status, payload)

                store = _store()
                self.assertIsNone(
                    store.sync_device(workspace_id, "denied-device-" + backend)
                )
                self.assertEqual(
                    [], store.sync_heads(workspace_id, "denied-logical-memory-" + backend)
                )


if __name__ == "__main__":
    unittest.main()
