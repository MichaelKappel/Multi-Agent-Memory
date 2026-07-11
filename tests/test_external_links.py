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
            "/api/matm/external-links",
            headers=headers,
            query="workspace_id=%s&document_id=%s" % (setup["workspaceId"], document_id),
        )
        self.assertEqual("200 OK", status)
        self.assertEqual(1, json.loads(text)["count"])

        with closing(sqlite3.connect(str(self.sqlite_path))) as connection:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM matm_external_links").fetchone()[0])
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM matm_external_link_mentions").fetchone()[0])

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
