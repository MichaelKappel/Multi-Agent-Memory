import io
import json
import os
import shutil
import sqlite3
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

    def test_task_scoped_knowledge_tree_is_rejected(self):
        setup, headers = self.setup_workspace()
        workspace_id = setup["workspaceId"]
        status, _headers, text = call_app(
            "/api/matm/knowledge-documents/upsert",
            method="POST",
            body={
                "workspaceId": workspace_id,
                "actorAgentId": "MemoryEndpoints-Backend-Agent",
                "scope": "task",
                "scopeId": "task-one",
                "title": "Should Not Persist",
                "description": "Rejected task-scoped knowledge test.",
                "keywords": ["task scope"],
                "taxonomyPaths": [["Task", "Rejected"]],
                "searchableText": "Task trees are forbidden for durable knowledge.",
            },
            headers=dict(headers, HTTP_IDEMPOTENCY_KEY="task-knowledge-rejected"),
        )
        self.assertEqual("422 Unprocessable Entity", status)
        payload = json.loads(text)
        self.assertEqual("unsupported_knowledge_scope", payload["error"]["code"])


if __name__ == "__main__":
    unittest.main()
