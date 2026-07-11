import io
import json
import os
import shutil
import sqlite3
import unittest
from pathlib import Path
from urllib.parse import urlencode

from app import application
from memoryendpoints.storage import SQLiteStore


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


class KnowledgeWikiTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / "var" / "test-knowledge-wiki"
        temp_root.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(ch if ch.isalnum() else "-" for ch in self._testMethodName)
        self.tempdir = temp_root / ("%s-%s" % (os.getpid(), safe_name))
        shutil.rmtree(str(self.tempdir), ignore_errors=True)
        self.tempdir.mkdir(parents=True, exist_ok=True)
        self.sqlite_path = self.tempdir / "store.sqlite3"
        os.environ["MEMORYENDPOINTS_STORE_BACKEND"] = "sqlite"
        os.environ["MEMORYENDPOINTS_SQLITE_PATH"] = str(self.sqlite_path)

    def tearDown(self):
        shutil.rmtree(str(self.tempdir), ignore_errors=True)
        os.environ.pop("MEMORYENDPOINTS_STORE_BACKEND", None)
        os.environ.pop("MEMORYENDPOINTS_SQLITE_PATH", None)

    def setup_workspace(self):
        status, _headers, text = call_app(
            "/api/matm/agent-setup/free-account",
            method="POST",
            body={"label": "Knowledge Workspace", "companyLabel": "Knowledge Company", "projectLabel": "Primary Project"},
        )
        self.assertEqual("201 Created", status)
        payload = json.loads(text)
        return payload, {"HTTP_AUTHORIZATION": "Bearer " + payload["apiKeySecret"]}

    def test_existing_sqlite_knowledge_schema_adds_lifecycle_columns_before_index(self):
        connection = sqlite3.connect(str(self.sqlite_path))
        try:
            connection.execute(
                """
                CREATE TABLE matm_search_documents (
                  search_document_id TEXT PRIMARY KEY,
                  workspace_id TEXT NOT NULL,
                  memory_id TEXT,
                  source_id TEXT,
                  scope_type TEXT NOT NULL DEFAULT 'workspace',
                  scope_id TEXT,
                  category TEXT,
                  document_type TEXT NOT NULL DEFAULT 'knowledge_document',
                  route_or_path TEXT,
                  title TEXT NOT NULL,
                  description TEXT,
                  keywords_json TEXT,
                  taxonomy_paths_json TEXT,
                  searchable_text TEXT NOT NULL,
                  visibility TEXT NOT NULL,
                  content_hash TEXT NOT NULL DEFAULT '',
                  metadata_json TEXT,
                  created_at TEXT NOT NULL DEFAULT '',
                  updated_at TEXT NOT NULL
                )
                """
            )
            connection.commit()
        finally:
            connection.close()

        self.assertTrue(SQLiteStore(self.sqlite_path).healthcheck())
        connection = sqlite3.connect(str(self.sqlite_path))
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(matm_search_documents)")}
            indexes = {row[1] for row in connection.execute("PRAGMA index_list(matm_search_documents)")}
            self.assertTrue({"knowledge_status", "authority_level", "status_reason", "superseded_by_document_id"}.issubset(columns))
            self.assertIn("ix_sqlite_search_workspace_lifecycle", indexes)
        finally:
            connection.close()

    def test_database_backed_knowledge_wiki_human_and_agent_routes(self):
        setup, headers = self.setup_workspace()
        workspace_id = setup["workspaceId"]

        status, _headers, text = call_app("/knowledge")
        self.assertEqual("200 OK", status)
        self.assertIn("data-knowledge-app", text)

        project_body = {
            "workspaceId": workspace_id,
            "actorAgentId": "MemoryEndpoints-Backend-Agent",
            "projectId": "project-memoryendpoints-com",
            "label": "MemoryEndpoints.com",
        }
        status, _headers, text = call_app(
            "/api/matm/projects",
            method="POST",
            body=project_body,
            headers=dict(headers, HTTP_IDEMPOTENCY_KEY="knowledge-project-upsert"),
        )
        self.assertEqual("201 Created", status)
        self.assertTrue(json.loads(text)["persisted"])

        doc_body = {
            "workspaceId": workspace_id,
            "actorAgentId": "MemoryEndpoints-Backend-Agent",
            "scope": "project",
            "scopeId": "project-memoryendpoints-com",
            "projectId": "project-memoryendpoints-com",
            "title": "MemoryEndpoints Database Wiki Target",
            "description": "Database-backed wiki target for MemoryEndpoints project knowledge.",
            "keywords": ["database wiki", "project memory", "agent recall"],
            "taxonomyPaths": [
                ["AI infrastructure", "agent memory", "crawlable wiki"],
                ["MemoryEndpoints.com", "database architecture", "knowledge documents"],
            ],
            "category": "system-targets",
            "documentType": "strategy-report",
            "sourceUri": "download-archive://memoryendpoints-database-wiki-target",
            "sourceType": "download_archive_markdown_report",
            "routeOrPath": "/knowledge/project/system-targets/memoryendpoints-database-wiki-target",
            "searchableText": "# MemoryEndpoints Database Wiki Target\n\nAll company, workspace, and project knowledge belongs in relational database rows so authenticated humans and agents crawl the same wiki tree.",
            "metadata": {"sourceFileName": "memoryendpoints-database-wiki-target.md", "absoluteSourcePathStored": False},
        }
        status, _headers, text = call_app(
            "/api/matm/knowledge-documents/upsert",
            method="POST",
            body=doc_body,
            headers=dict(headers, HTTP_IDEMPOTENCY_KEY="knowledge-doc-upsert"),
        )
        self.assertEqual("201 Created", status)
        payload = json.loads(text)
        self.assertTrue(payload["persisted"])
        self.assertTrue(payload["visibleInSearch"])
        self.assertTrue(payload["visibleInWikiTree"])
        self.assertIn("/api/matm/knowledge-documents", payload["documentQueryUrl"])

        status, _headers, text = call_app(
            "/api/matm/knowledge-tree",
            headers=headers,
            query="workspace_id=%s" % workspace_id,
        )
        self.assertEqual("200 OK", status)
        tree_payload = json.loads(text)
        self.assertTrue(tree_payload["ok"])
        self.assertFalse(tree_payload["filesystemDocsIncluded"])
        self.assertFalse(tree_payload["tree"]["taskLevelTreeSupported"])
        self.assertEqual(1, tree_payload["tree"]["scopeCounts"]["project"])
        levels = tree_payload["tree"]["levels"]
        self.assertEqual(["project"], [level["scope"] for level in levels])
        self.assertEqual("system-targets", levels[0]["categories"][0]["category"])
        taxonomy = levels[0]["taxonomy"]
        self.assertEqual("AI infrastructure", taxonomy[0]["label"])
        self.assertEqual("MemoryEndpoints.com", taxonomy[1]["label"])

        document_id = payload["canonicalSearchDocumentId"]
        status, _headers, text = call_app(
            "/api/matm/knowledge-documents",
            headers=headers,
            query="workspace_id=%s&document_id=%s&include_text=1" % (workspace_id, document_id),
        )
        self.assertEqual("200 OK", status)
        docs_payload = json.loads(text)
        self.assertEqual(1, docs_payload["count"])
        self.assertIn("relational database rows", docs_payload["items"][0]["searchableText"])
        self.assertEqual("Database-backed wiki target for MemoryEndpoints project knowledge.", docs_payload["items"][0]["description"])
        self.assertIn("database wiki", docs_payload["items"][0]["keywords"])
        self.assertEqual(2, len(docs_payload["items"][0]["taxonomyPaths"]))
        self.assertEqual("database_search_documents", docs_payload["knowledgeSource"])

        status, _headers, text = call_app(
            "/api/matm/knowledge-documents",
            headers=headers,
            query=urlencode(
                {
                    "workspace_id": workspace_id,
                    "route_or_path": doc_body["routeOrPath"],
                    "include_text": "1",
                }
            ),
        )
        self.assertEqual("200 OK", status)
        route_payload = json.loads(text)
        self.assertEqual(1, route_payload["count"])
        self.assertEqual(document_id, route_payload["items"][0]["searchDocumentId"])
        self.assertEqual(doc_body["routeOrPath"], route_payload["filters"]["routeOrPath"])

        status, _headers, text = call_app(
            "/api/matm/knowledge-documents",
            headers=headers,
            query=urlencode(
                {
                    "workspace_id": workspace_id,
                    "route_or_path": "/knowledge/project/system-targets/not-this-page",
                }
            ),
        )
        self.assertEqual("200 OK", status)
        self.assertEqual(0, json.loads(text)["count"])

        status, _headers, text = call_app(
            "/api/matm/knowledge-documents",
            headers=headers,
            query="workspace_id=%s&taxonomy_path=%s" % (workspace_id, "AI%20infrastructure%20%3E%20agent%20memory"),
        )
        self.assertEqual("200 OK", status)
        taxonomy_payload = json.loads(text)
        self.assertEqual(1, taxonomy_payload["count"])

        connection = sqlite3.connect(str(self.sqlite_path))
        try:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM matm_crawl_sources").fetchone()[0])
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM matm_search_documents").fetchone()[0])
            row = connection.execute("SELECT scope_type, scope_id, category, description, keywords_json, taxonomy_paths_json FROM matm_search_documents").fetchone()
            self.assertEqual(("project", "project-memoryendpoints-com", "system-targets"), row[:3])
            self.assertIn("Database-backed wiki target", row[3])
            self.assertIn("database wiki", row[4])
            self.assertIn("AI infrastructure", row[5])
        finally:
            connection.close()

    def test_private_knowledge_shell_and_routes_require_workspace_authentication(self):
        status, _headers, text = call_app("/knowledge")
        self.assertEqual("200 OK", status)
        self.assertIn("Private company knowledge", text)
        self.assertIn("data-knowledge-private hidden", text)
        self.assertNotIn("Company Wiki", text)
        self.assertNotIn("localStorage", (Path(__file__).resolve().parents[1] / "static" / "js" / "knowledge.js").read_text(encoding="utf-8"))
        self.assertNotIn("sessionStorage", (Path(__file__).resolve().parents[1] / "static" / "js" / "knowledge.js").read_text(encoding="utf-8"))

        status, _headers, text = call_app("/api/matm/live-capability-matrix")
        self.assertEqual("200 OK", status)
        contract = json.loads(text)["data"]["knowledgeWiki"]
        self.assertTrue(contract["authenticationRequired"])
        self.assertFalse(contract["anonymousShellContainsKnowledge"])
        self.assertFalse(contract["publicKnowledgeIndex"])
        self.assertEqual(["company", "workspace", "project"], contract["supportedScopes"])
        self.assertEqual([], contract["identityOwnedKnowledgeScopes"])
        self.assertEqual("many_to_many", contract["accountCompanyMembership"])
        self.assertIn("route_or_path", contract["queryFilters"])

        deep_route = "/knowledge/project/architecture/private-deep-link"
        status, _headers, deep_text = call_app(deep_route)
        self.assertEqual("200 OK", status)
        self.assertIn('data-initial-route="%s"' % deep_route, deep_text)
        self.assertIn("data-knowledge-private hidden", deep_text)
        self.assertNotIn("Company Wiki", deep_text)

        for invalid_route in (
            "/knowledge/account/private-deep-link",
            "/knowledge/user/private-deep-link",
            "/knowledge/goal/private-deep-link",
            "/knowledge/task/private-deep-link",
            "/knowledge/project//private-deep-link",
            "/knowledge/project/Architecture/private-deep-link",
            "/knowledge/project/architecture/../private-deep-link",
            "/knowledge/project/architecture/private_page",
            "/knowledge/project/architecture/%2e%2e/private-deep-link",
        ):
            with self.subTest(invalid_route=invalid_route):
                status, _headers, payload = call_app(invalid_route)
                self.assertEqual("404 Not Found", status)
                self.assertEqual("not_found", json.loads(payload)["error"]["code"])

        knowledge_js = (Path(__file__).resolve().parents[1] / "static" / "js" / "knowledge.js").read_text(encoding="utf-8")
        self.assertIn("function isInternalKnowledgeRoute", knowledge_js)
        self.assertIn("route_or_path: routeOrPath", knowledge_js)
        self.assertIn("const linkHref = match[5]", knowledge_js)
        self.assertIn("loadDocumentByRoute(linkHref)", knowledge_js)
        self.assertNotIn("loadDocumentByRoute(match[5])", knowledge_js)
        self.assertIn("if (!payload) return", knowledge_js)
        self.assertIn('window.addEventListener("popstate"', knowledge_js)
        self.assertNotIn("innerHTML", knowledge_js)

        for route in (
            "/api/matm/projects",
            "/api/matm/knowledge-tree",
            "/api/matm/knowledge-documents",
            "/api/matm/external-links",
            "/api/matm/internet-search",
        ):
            with self.subTest(route=route):
                status, _headers, text = call_app(route, query="workspace_id=workspace-anonymous-probe")
                self.assertEqual("401 Unauthorized", status)
                payload = json.loads(text)
                self.assertEqual("auth_required", payload["error"]["code"])
                self.assertTrue(payload["safeNoOp"])
                self.assertNotIn("items", payload)
                self.assertNotIn("tree", payload)

        for route in ("/api/matm/knowledge-documents/upsert", "/api/matm/external-links/upsert"):
            with self.subTest(route=route):
                status, _headers, text = call_app(
                    route,
                    method="POST",
                    body={"workspaceId": "workspace-anonymous-probe"},
                )
                self.assertEqual("401 Unauthorized", status)
                self.assertEqual("auth_required", json.loads(text)["error"]["code"])

    def test_workspace_key_cannot_cross_the_workspace_knowledge_boundary(self):
        first, first_headers = self.setup_workspace()
        second, _second_headers = self.setup_workspace()
        for route in (
            "/api/matm/projects",
            "/api/matm/knowledge-tree",
            "/api/matm/knowledge-documents",
            "/api/matm/external-links",
            "/api/matm/internet-search",
        ):
            with self.subTest(route=route):
                status, _headers, text = call_app(
                    route,
                    headers=first_headers,
                    query="workspace_id=%s" % second["workspaceId"],
                )
                self.assertEqual("401 Unauthorized", status)
                payload = json.loads(text)
                self.assertEqual("auth_required", payload["error"]["code"])
                self.assertNotIn(first["apiKeySecret"], text)

    def test_account_company_membership_is_many_to_many_but_not_a_knowledge_scope(self):
        setup, headers = self.setup_workspace()
        second_account_id = "account-membership-peer"
        second_company_id = "company-membership-peer"
        connection = sqlite3.connect(str(self.sqlite_path))
        try:
            connection.execute(
                "INSERT INTO matm_accounts (account_id, label, status, created_at, updated_at) VALUES (?, ?, ?, ?, NULL)",
                (second_account_id, "Membership Peer", "active", "membership-test"),
            )
            connection.execute(
                "INSERT INTO matm_companies (company_id, label, status, created_at, updated_at) VALUES (?, ?, ?, ?, NULL)",
                (second_company_id, "Membership Peer Company", "active", "membership-test"),
            )
            connection.execute(
                "INSERT INTO matm_account_companies (membership_id, account_id, company_id, role, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, NULL)",
                ("membership-account-second-company", setup["accountId"], second_company_id, "member", "active", "membership-test"),
            )
            connection.execute(
                "INSERT INTO matm_account_companies (membership_id, account_id, company_id, role, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, NULL)",
                ("membership-second-account-company", second_account_id, setup["companyId"], "member", "active", "membership-test"),
            )
            self.assertEqual(
                2,
                connection.execute(
                    "SELECT COUNT(*) FROM matm_account_companies WHERE account_id = ?",
                    (setup["accountId"],),
                ).fetchone()[0],
            )
            self.assertEqual(
                2,
                connection.execute(
                    "SELECT COUNT(*) FROM matm_account_companies WHERE company_id = ?",
                    (setup["companyId"],),
                ).fetchone()[0],
            )
            connection.commit()
        finally:
            connection.close()

        status, _headers, text = call_app(
            "/api/matm/workspace",
            headers=headers,
            query="workspace_id=%s" % setup["workspaceId"],
        )
        self.assertEqual("200 OK", status)
        account_ids = {item["accountId"] for item in json.loads(text)["workspace"]["accounts"]}
        self.assertEqual({setup["accountId"], second_account_id}, account_ids)

    def test_only_company_workspace_and_project_knowledge_scopes_are_allowed(self):
        setup, headers = self.setup_workspace()
        workspace_id = setup["workspaceId"]
        for scope in ("account", "user", "goal", "task"):
            with self.subTest(scope=scope):
                status, _headers, text = call_app(
                    "/api/matm/knowledge-documents/upsert",
                    method="POST",
                    body={
                        "workspaceId": workspace_id,
                        "actorAgentId": "MemoryEndpoints-Backend-Agent",
                        "scope": scope,
                        "scopeId": scope + "-one",
                        "title": "Should Not Persist",
                        "description": "Rejected durable knowledge scope test.",
                        "keywords": [scope + " scope"],
                        "taxonomyPaths": [[scope, "Rejected"]],
                        "searchableText": "Durable knowledge is limited to company, workspace, and project scopes.",
                    },
                    headers=dict(headers, HTTP_IDEMPOTENCY_KEY=scope + "-knowledge-rejected"),
                )
                self.assertEqual("422 Unprocessable Entity", status)
                payload = json.loads(text)
                self.assertEqual("unsupported_knowledge_scope", payload["error"]["code"])

    def test_knowledge_lifecycle_supersession_is_first_class_and_ranking_aware(self):
        setup, headers = self.setup_workspace()
        workspace_id = setup["workspaceId"]
        project_id = setup["projectId"]

        current_body = {
            "workspaceId": workspace_id,
            "actorAgentId": "MemoryEndpoints-Backend-Agent",
            "scope": "project",
            "scopeId": project_id,
            "projectId": project_id,
            "title": "Current Database Architecture Contract",
            "description": "Canonical current replacement for obsolete storage and route proposals.",
            "keywords": ["legacy route contract", "database source of truth"],
            "taxonomyPaths": [["MemoryEndpoints.com", "architecture", "current contract"]],
            "category": "architecture-contract",
            "documentType": "architecture-decision",
            "knowledgeStatus": "current",
            "authorityLevel": "canonical",
            "sourceUri": "implementation://current-database-contract",
            "routeOrPath": "/knowledge/project/architecture/current-database-contract",
            "searchableText": "The relational database is the durable knowledge source of truth.",
        }
        status, _headers, text = call_app(
            "/api/matm/knowledge-documents/upsert",
            method="POST",
            body=current_body,
            headers=dict(headers, HTTP_IDEMPOTENCY_KEY="knowledge-current-contract"),
        )
        self.assertEqual("201 Created", status)
        current = json.loads(text)["document"]

        invalid_body = dict(current_body)
        invalid_body.update(
            {
                "title": "Invalid Superseded Page",
                "sourceUri": "report://invalid-superseded-page",
                "routeOrPath": "/knowledge/project/architecture/invalid-superseded-page",
                "knowledgeStatus": "superseded",
                "authorityLevel": "reviewed",
                "statusReason": "The proposal is obsolete.",
            }
        )
        status, _headers, text = call_app(
            "/api/matm/knowledge-documents/upsert",
            method="POST",
            body=invalid_body,
            headers=dict(headers, HTTP_IDEMPOTENCY_KEY="knowledge-invalid-superseded"),
        )
        self.assertEqual("422 Unprocessable Entity", status)
        self.assertEqual("superseded_by_document_id_required", json.loads(text)["error"]["code"])

        superseded_body = dict(invalid_body)
        superseded_body.update(
            {
                "title": "Legacy Route Contract",
                "sourceUri": "report://legacy-route-contract",
                "routeOrPath": "/knowledge/project/architecture/legacy-route-contract",
                "description": "Historical route proposal retained for provenance.",
                "keywords": ["legacy route contract", "filesystem fallback"],
                "searchableText": "Legacy Route Contract proposed filesystem fallback as durable knowledge.",
                "statusReason": "The deployed database-backed wiki replaced this filesystem proposal.",
                "supersededByDocumentId": current["searchDocumentId"],
            }
        )
        status, _headers, text = call_app(
            "/api/matm/knowledge-documents/upsert",
            method="POST",
            body=superseded_body,
            headers=dict(headers, HTTP_IDEMPOTENCY_KEY="knowledge-valid-superseded"),
        )
        self.assertEqual("201 Created", status)
        superseded = json.loads(text)["document"]
        self.assertEqual("superseded", superseded["knowledgeStatus"])
        self.assertEqual("reviewed", superseded["authorityLevel"])
        self.assertEqual(current["searchDocumentId"], superseded["supersededByDocumentId"])
        self.assertEqual(current["title"], superseded["supersededBy"]["title"])
        self.assertIn("linked replacement", superseded["lifecycleWarning"])

        status, _headers, text = call_app(
            "/api/matm/knowledge-documents",
            headers=headers,
            query="workspace_id=%s&q=legacy%%20route%%20contract&limit=10" % workspace_id,
        )
        self.assertEqual("200 OK", status)
        search = json.loads(text)
        self.assertEqual(current["searchDocumentId"], search["items"][0]["searchDocumentId"])
        self.assertGreater(search["items"][0]["rankingScore"], superseded["rankingScore"])
        self.assertEqual(1, search["operatorSummary"]["knowledgeStatusCounts"]["superseded"])

        status, _headers, text = call_app(
            "/api/matm/knowledge-documents",
            headers=headers,
            query="workspace_id=%s&knowledge_status=superseded" % workspace_id,
        )
        self.assertEqual("200 OK", status)
        filtered = json.loads(text)
        self.assertEqual(1, filtered["count"])
        self.assertEqual(superseded["searchDocumentId"], filtered["items"][0]["searchDocumentId"])

        status, _headers, text = call_app(
            "/api/matm/knowledge-tree",
            headers=headers,
            query="workspace_id=%s" % workspace_id,
        )
        self.assertEqual("200 OK", status)
        tree = json.loads(text)["tree"]
        self.assertEqual("memoryendpoints.knowledge_tree.v2", tree["schemaVersion"])
        self.assertEqual(1, tree["knowledgeStatusCounts"]["current"])
        self.assertEqual(1, tree["knowledgeStatusCounts"]["superseded"])
        self.assertEqual(1, tree["authorityLevelCounts"]["canonical"])

        connection = sqlite3.connect(str(self.sqlite_path))
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(matm_search_documents)")}
            self.assertTrue({"knowledge_status", "authority_level", "status_reason", "superseded_by_document_id"}.issubset(columns))
            row = connection.execute(
                "SELECT knowledge_status, authority_level, status_reason, superseded_by_document_id FROM matm_search_documents WHERE search_document_id = ?",
                (superseded["searchDocumentId"],),
            ).fetchone()
            self.assertEqual(("superseded", "reviewed", superseded_body["statusReason"], current["searchDocumentId"]), row)
        finally:
            connection.close()

    def test_tree_is_not_truncated_by_the_search_result_limit(self):
        setup, headers = self.setup_workspace()
        workspace_id = setup["workspaceId"]
        company_id = setup["companyId"]
        connection = sqlite3.connect(str(self.sqlite_path))
        try:
            connection.execute(
                """
                INSERT INTO matm_crawl_sources (
                  source_id, workspace_id, project_id, source_uri, source_type,
                  crawl_policy, status, last_crawled_at, created_at
                ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "src-scale-test",
                    workspace_id,
                    "report://scale-test",
                    "reviewed_markdown_report",
                    "workspace_private",
                    "active",
                    "",
                    "",
                ),
            )
            connection.executemany(
                """
                INSERT INTO matm_search_documents (
                  search_document_id, workspace_id, source_id, scope_type, scope_id,
                  category, document_type, route_or_path, title, description,
                  keywords_json, taxonomy_paths_json, searchable_text, visibility,
                  content_hash, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "doc-scale-%04d" % index,
                        workspace_id,
                        "src-scale-test",
                        "company",
                        company_id,
                        "scale-test",
                        "reviewed-report-section",
                        "/knowledge/company/scale-test/page-%04d" % index,
                        "Scale page %04d" % index,
                        "Tree completeness test page.",
                        '["tree scale"]',
                        '[["Company knowledge", "Scale validation"]]',
                        "Knowledge page %04d" % index,
                        "workspace_private",
                        "hash-%04d" % index,
                        "{}",
                        "",
                        "",
                    )
                    for index in range(501)
                ],
            )
            connection.commit()
        finally:
            connection.close()

        status, _headers, text = call_app(
            "/api/matm/knowledge-tree",
            headers=headers,
            query="workspace_id=%s" % workspace_id,
        )
        self.assertEqual("200 OK", status)
        payload = json.loads(text)
        self.assertEqual(501, payload["tree"]["documentCount"])
        self.assertEqual(501, payload["tree"]["scopeCounts"]["company"])

        status, _headers, text = call_app(
            "/api/matm/knowledge-documents",
            headers=headers,
            query="workspace_id=%s&limit=1000" % workspace_id,
        )
        self.assertEqual("200 OK", status)
        self.assertEqual(500, json.loads(text)["count"])

    def test_one_canonical_source_can_supply_company_and_project_pages(self):
        setup, headers = self.setup_workspace()
        workspace_id = setup["workspaceId"]
        company_id = setup["companyId"]
        project_id = setup["projectId"]
        source_uri = "report://shared-reviewed-source"

        for scope, scope_id, title, route in (
            ("company", company_id, "Reusable memory principle", "/knowledge/company/architecture/reusable-memory-principle"),
            ("project", project_id, "Project memory application", "/knowledge/project/architecture/project-memory-application"),
        ):
            status, _headers, text = call_app(
                "/api/matm/knowledge-documents/upsert",
                method="POST",
                body={
                    "workspaceId": workspace_id,
                    "actorAgentId": "MemoryEndpoints-Backend-Agent",
                    "scope": scope,
                    "scopeId": scope_id,
                    "projectId": project_id if scope == "project" else None,
                    "title": title,
                    "description": "A separately classified page from one reviewed source.",
                    "keywords": ["shared source", "scope isolation"],
                    "taxonomyPaths": [["AI infrastructure", "agent memory", title]],
                    "category": "architecture",
                    "documentType": "reviewed-report-section",
                    "sourceUri": source_uri,
                    "sourceType": "reviewed_markdown_report",
                    "routeOrPath": route,
                    "searchableText": title + " is stored at its narrowest durable scope.",
                },
                headers=dict(headers, HTTP_IDEMPOTENCY_KEY="shared-source-" + scope),
            )
            self.assertEqual("201 Created", status)
            self.assertTrue(json.loads(text)["persisted"])

        status, _headers, text = call_app(
            "/api/matm/knowledge-documents",
            headers=headers,
            query="workspace_id=%s&source_prefix=%s&limit=10" % (workspace_id, source_uri),
        )
        self.assertEqual("200 OK", status)
        items = json.loads(text)["items"]
        self.assertEqual(2, len(items))
        by_scope = {item["scope"]: item for item in items}
        self.assertIsNone(by_scope["company"]["projectId"])
        self.assertEqual(project_id, by_scope["project"]["projectId"])

        connection = sqlite3.connect(str(self.sqlite_path))
        try:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM matm_crawl_sources").fetchone()[0])
            self.assertIsNone(connection.execute("SELECT project_id FROM matm_crawl_sources").fetchone()[0])
        finally:
            connection.close()

    def test_contextual_search_can_land_on_a_taxonomy_branch_without_exact_phrase_match(self):
        setup, headers = self.setup_workspace()
        workspace_id = setup["workspaceId"]
        status, _headers, text = call_app(
            "/api/matm/knowledge-documents/upsert",
            method="POST",
            body={
                "workspaceId": workspace_id,
                "actorAgentId": "MemoryEndpoints-Backend-Agent",
                "scope": "workspace",
                "title": "Bounded prompt assembly",
                "description": "Context selection guidance for bounded agent prompts.",
                "keywords": ["context selection", "token efficiency"],
                "taxonomyPaths": [["AI infrastructure", "tokenization", "prompt optimization", "context bounding"]],
                "category": "context-management",
                "searchableText": "Retrieve a compact diverse memory backbone before expanding detailed evidence.",
            },
            headers=dict(headers, HTTP_IDEMPOTENCY_KEY="contextual-taxonomy-search-document"),
        )
        self.assertEqual("201 Created", status)

        status, _headers, text = call_app(
            "/api/matm/knowledge-documents",
            headers=headers,
            query="workspace_id=%s&q=prompt%%20budgets" % workspace_id,
        )
        self.assertEqual("200 OK", status)
        payload = json.loads(text)
        self.assertEqual(1, payload["count"])
        self.assertEqual("Bounded prompt assembly", payload["items"][0]["title"])
        self.assertIn("prompt", payload["items"][0]["matchedTerms"])
        self.assertIn("budget", payload["items"][0]["unmatchedTerms"])
        self.assertGreater(payload["items"][0]["matchScore"], 0)


if __name__ == "__main__":
    unittest.main()
