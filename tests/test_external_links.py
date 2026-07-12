import io
import json
import os
import shutil
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path

from app import application


def call_app(path, method="GET", body=None, headers=None, query=""):
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
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
    environ.update(headers or {})
    text = b"".join(application(environ, start_response)).decode("utf-8")
    return captured["status"], captured["headers"], text


class ExternalLinkTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / "var" / "test-external-links"
        temp_root.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(character if character.isalnum() else "-" for character in self._testMethodName)
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
            body={"label": "Link Search Workspace", "companyLabel": "Link Search Company", "projectLabel": "MemoryEndpoints.com"},
        )
        self.assertEqual("201 Created", status)
        payload = json.loads(text)
        return payload, {"HTTP_AUTHORIZATION": "Bearer " + payload["apiKeySecret"]}

    def create_knowledge_document(self, setup, headers):
        status, _headers, text = call_app(
            "/api/matm/knowledge-documents/upsert",
            method="POST",
            body={
                "workspaceId": setup["workspaceId"],
                "actorAgentId": "MemoryEndpoints-Backend-Agent",
                "scope": "project",
                "scopeId": setup["projectId"],
                "projectId": setup["projectId"],
                "title": "Stateful agent memory evidence",
                "description": "Reviewed project knowledge with a first-class external citation.",
                "keywords": ["stateful agents", "prompt budgets"],
                "taxonomyPaths": [
                    ["AI infrastructure", "agent memory", "stateful systems"],
                    ["AI infrastructure", "tokenization", "prompt optimization"],
                ],
                "category": "memory-architecture",
                "documentType": "reviewed-report-section",
                "sourceUri": "report://external-link-test",
                "routeOrPath": "/knowledge/project/memory-architecture/stateful-agent-memory-evidence",
                "searchableText": "Stateful agents need durable typed memory and bounded prompt assembly.",
            },
            headers=dict(headers, HTTP_IDEMPOTENCY_KEY="external-link-test-document"),
        )
        self.assertEqual("201 Created", status)
        return json.loads(text)["canonicalSearchDocumentId"]

    def test_external_link_is_searchable_and_cited_as_its_own_data_type(self):
        setup, headers = self.setup_workspace()
        document_id = self.create_knowledge_document(setup, headers)
        body = {
            "workspaceId": setup["workspaceId"],
            "actorAgentId": "MemoryEndpoints-Backend-Agent",
            "url": "HTTPS://Example.com:443/guides/stateful-agents?q=memory#typed-memory",
            "siteName": "Example Research",
            "pageTitle": "Stateful Agents and Typed Memory",
            "description": "Research guidance on typed state, bounded prompts, and durable agent recall.",
            "keywords": ["stateful agents", "typed memory", "prompt budget"],
            "reviewStatus": "reviewed",
            "crawlStatus": "not_requested",
            "crawlPolicy": "metadata_only",
            "knowledgeDocumentId": document_id,
            "relationshipType": "citation",
            "anchorText": "Stateful Agents and Typed Memory",
            "contextDescription": "Supports the page's distinction between bounded working context and durable typed memory.",
            "citationLabel": "14",
            "citationOrder": 14,
            "sourceReportName": "Agent Memory Architecture Research.md",
        }
        status, _headers, text = call_app(
            "/api/matm/external-links/upsert",
            method="POST",
            body=body,
            headers=dict(headers, HTTP_IDEMPOTENCY_KEY="external-link-upsert-one"),
        )
        self.assertEqual("201 Created", status)
        payload = json.loads(text)
        self.assertTrue(payload["persisted"])
        self.assertTrue(payload["visibleInInternetSearch"])
        self.assertTrue(payload["visibleOnKnowledgeDocument"])
        self.assertEqual("https://example.com/guides/stateful-agents?q=memory#typed-memory", payload["link"]["normalizedUrl"])
        self.assertEqual("example.com", payload["link"]["host"])
        self.assertEqual("Example Research", payload["link"]["siteName"])
        self.assertEqual(1, payload["link"]["mentionCount"])
        self.assertEqual(document_id, payload["link"]["mentions"][0]["knowledgeDocumentId"])
        self.assertEqual("Agent Memory Architecture Research.md", payload["link"]["mentions"][0]["sourceReportName"])
        self.assertNotIn("sourceReportName", payload["link"]["metadata"])

        status, _headers, text = call_app(
            "/api/matm/internet-search",
            headers=headers,
            query="workspace_id=%s&q=prompt%%20budgets" % setup["workspaceId"],
        )
        self.assertEqual("200 OK", status)
        search = json.loads(text)
        self.assertEqual("database_external_links", search["knowledgeSource"])
        self.assertEqual("curated_external_links", search["searchMode"])
        self.assertEqual(1, search["count"])
        self.assertGreater(search["items"][0]["matchScore"], 0)
        self.assertIn("budget", search["items"][0]["matchedTerms"])

        status, _headers, text = call_app(
            "/api/matm/internet-search",
            headers=headers,
            query="workspace_id=%s&q=Agent%%20Memory%%20Architecture%%20Research" % setup["workspaceId"],
        )
        self.assertEqual("200 OK", status)
        provenance_search = json.loads(text)
        self.assertEqual(1, provenance_search["count"])
        self.assertIn("research", provenance_search["items"][0]["matchedTerms"])

        status, _headers, text = call_app(
            "/api/matm/external-links",
            headers=headers,
            query="workspace_id=%s&document_id=%s" % (setup["workspaceId"], document_id),
        )
        self.assertEqual("200 OK", status)
        self.assertEqual(1, json.loads(text)["count"])

        with closing(sqlite3.connect(str(self.sqlite_path))) as connection:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM matm_external_links").fetchone()[0])
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM matm_external_link_mentions").fetchone()[0])
            self.assertEqual(
                "Agent Memory Architecture Research.md",
                connection.execute("SELECT source_report_name FROM matm_external_link_mentions").fetchone()[0],
            )

    def test_external_link_rejects_credentials_and_private_hosts(self):
        setup, headers = self.setup_workspace()
        base_body = {
            "workspaceId": setup["workspaceId"],
            "actorAgentId": "MemoryEndpoints-Backend-Agent",
            "siteName": "Unsafe Site",
            "pageTitle": "Unsafe Link",
            "description": "This URL must be rejected before persistence.",
            "keywords": ["unsafe link"],
        }
        for index, (url, code) in enumerate(
            (
                ("https://user:password@example.com/private", "external_url_credentials_forbidden"),
                ("https://example.com/page?access_token=secret", "external_url_credentials_forbidden"),
                ("http://127.0.0.1/admin", "external_url_not_public"),
            )
        ):
            status, _headers, text = call_app(
                "/api/matm/external-links/upsert",
                method="POST",
                body=dict(base_body, url=url),
                headers=dict(headers, HTTP_IDEMPOTENCY_KEY="unsafe-external-link-%s" % index),
            )
            self.assertEqual("422 Unprocessable Entity", status)
            self.assertEqual(code, json.loads(text)["error"]["code"])

        with closing(sqlite3.connect(str(self.sqlite_path))) as connection:
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM matm_external_links").fetchone()[0])

    def test_unreviewed_citation_preserves_existing_canonical_review(self):
        setup, headers = self.setup_workspace()
        document_id = self.create_knowledge_document(setup, headers)
        base_body = {
            "workspaceId": setup["workspaceId"],
            "actorAgentId": "MemoryEndpoints-Backend-Agent",
            "url": "https://example.com/guides/reviewed-agent-api",
            "siteName": "Example Research",
            "pageTitle": "Reviewed Agent API Guidance",
            "description": "Canonical reviewed API guidance cited by more than one report section.",
            "keywords": ["agent API", "canonical review"],
            "crawlStatus": "fetched",
            "crawlPolicy": "manual_review",
            "knowledgeDocumentId": document_id,
            "relationshipType": "citation",
            "anchorText": "Reviewed Agent API Guidance",
            "contextDescription": "Primary reviewed evidence for the current contract.",
            "citationLabel": "Primary evidence",
            "citationOrder": 1,
            "sourceReportName": "Primary Architecture Review.md",
        }
        status, _headers, text = call_app(
            "/api/matm/external-links/upsert",
            method="POST",
            body=dict(base_body, reviewStatus="reviewed"),
            headers=dict(headers, HTTP_IDEMPOTENCY_KEY="reviewed-link-first"),
        )
        self.assertEqual("201 Created", status)
        self.assertEqual("reviewed", json.loads(text)["link"]["reviewStatus"])

        source_citation = dict(
            base_body,
            keywords=["later evidence", "agent api"],
            reviewStatus="unreviewed",
            contextDescription="Unreviewed source citation reuses the reviewed canonical page.",
            citationLabel="Works cited 1",
            citationOrder=2,
            sourceReportName="Follow-up Research.md",
        )
        status, _headers, text = call_app(
            "/api/matm/external-links/upsert",
            method="POST",
            body=source_citation,
            headers=dict(headers, HTTP_IDEMPOTENCY_KEY="unreviewed-link-mention"),
        )
        self.assertEqual("201 Created", status)
        payload = json.loads(text)
        self.assertEqual("reviewed", payload["link"]["reviewStatus"])
        self.assertEqual(
            ["agent API", "canonical review", "later evidence"],
            payload["link"]["keywords"],
        )
        self.assertEqual(2, payload["link"]["mentionCount"])
        self.assertEqual(
            {"Primary evidence", "Works cited 1"},
            {item["citationLabel"] for item in payload["link"]["mentions"]},
        )
        self.assertEqual(
            {
                "Primary evidence": "Primary Architecture Review.md",
                "Works cited 1": "Follow-up Research.md",
            },
            {item["citationLabel"]: item["sourceReportName"] for item in payload["link"]["mentions"]},
        )
        self.assertNotIn("sourceReportName", payload["link"]["metadata"])

    def test_existing_external_link_mention_table_is_migrated(self):
        with closing(sqlite3.connect(str(self.sqlite_path))) as connection:
            connection.execute(
                """
                CREATE TABLE matm_external_link_mentions (
                  external_link_mention_id TEXT PRIMARY KEY,
                  workspace_id TEXT NOT NULL,
                  external_link_id TEXT NOT NULL,
                  search_document_id TEXT NOT NULL,
                  relationship_type TEXT NOT NULL DEFAULT 'reference',
                  anchor_text TEXT NOT NULL,
                  context_description TEXT NOT NULL,
                  citation_label TEXT,
                  citation_order INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL
                )
                """
            )
            connection.commit()

        self.setup_workspace()

        with closing(sqlite3.connect(str(self.sqlite_path))) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(matm_external_link_mentions)")}
        self.assertIn("source_report_name", columns)

    def test_external_link_search_is_workspace_isolated(self):
        first, first_headers = self.setup_workspace()
        document_id = self.create_knowledge_document(first, first_headers)
        status, _headers, text = call_app(
            "/api/matm/external-links/upsert",
            method="POST",
            body={
                "workspaceId": first["workspaceId"],
                "actorAgentId": "MemoryEndpoints-Backend-Agent",
                "url": "https://example.org/memory",
                "siteName": "Example Organization",
                "pageTitle": "Agent Memory",
                "description": "Public research indexed for one workspace.",
                "keywords": ["agent memory"],
                "knowledgeDocumentId": document_id,
                "contextDescription": "Evidence for the workspace's memory architecture page.",
            },
            headers=dict(first_headers, HTTP_IDEMPOTENCY_KEY="isolated-external-link"),
        )
        self.assertEqual("201 Created", status)
        external_link_id = json.loads(text)["canonicalExternalLinkId"]

        second, second_headers = self.setup_workspace()
        status, _headers, text = call_app(
            "/api/matm/external-links",
            headers=second_headers,
            query="workspace_id=%s&external_link_id=%s" % (second["workspaceId"], external_link_id),
        )
        self.assertEqual("200 OK", status)
        self.assertEqual(0, json.loads(text)["count"])


if __name__ == "__main__":
    unittest.main()
