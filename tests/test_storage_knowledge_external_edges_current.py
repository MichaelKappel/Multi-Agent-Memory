"""Current storage edge matrix shared by the local FileStore and SQLiteStore."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from memoryendpoints.storage import FileStore, SQLiteStore


class StorageKnowledgeExternalEdgesCurrentTests(unittest.TestCase):
    def test_knowledge_lifecycle_and_filter_rejections_match_across_backends(self):
        previous = os.environ.get("MEMORYENDPOINTS_CREDENTIAL_PEPPER")
        os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = "synthetic-knowledge-edge-pepper-" + ("x" * 48)
        self.addCleanup(
            lambda: os.environ.__setitem__("MEMORYENDPOINTS_CREDENTIAL_PEPPER", previous)
            if previous is not None
            else os.environ.pop("MEMORYENDPOINTS_CREDENTIAL_PEPPER", None)
        )
        for store_type in (FileStore, SQLiteStore):
            with self.subTest(backend=store_type.__name__), tempfile.TemporaryDirectory() as tmp:
                suffix = "store.json" if store_type is FileStore else "store.sqlite3"
                store = store_type(Path(tmp) / suffix)
                workspace_id, _master, _secret, _account, _company, project_id, _recovery = store.create_free_account(
                    "Knowledge Edge Workspace", "Knowledge Edge Company", "Knowledge Edge Project"
                )
                agent_id = "knowledge-edge-agent"
                store.register_agent(workspace_id, agent_id, "Knowledge Edge Agent")

                invalid = (
                    ({"scope": "company-ish", "content": "x"}, "unsupported_scope"),
                    ({"scope": "workspace", "content": " "}, "content_required"),
                    ({"scope": "workspace", "content": "x", "knowledgeStatus": "unknown"}, "unsupported_knowledge_status"),
                    ({"scope": "workspace", "content": "x", "authorityLevel": "unknown"}, "unsupported_authority_level"),
                    ({"scope": "workspace", "content": "x", "knowledgeStatus": "historical"}, "knowledge_status_reason_required"),
                    ({"scope": "workspace", "content": "x", "knowledgeStatus": "superseded", "statusReason": "replaced"}, "superseded_by_document_id_required"),
                    ({"scope": "workspace", "content": "x", "supersededByDocumentId": "missing"}, "superseding_knowledge_document_not_found"),
                    ({"scope": "project", "projectId": "missing", "content": "x"}, "project_not_found"),
                )
                for payload, expected in invalid:
                    with self.subTest(backend=store_type.__name__, expected=expected):
                        self.assertEqual((None, expected), store.upsert_knowledge_document(workspace_id, agent_id, payload))
                self.assertEqual((None, "workspace_not_found"), store.upsert_knowledge_document("missing", agent_id, {"content": "x"}))

                current, error = store.upsert_knowledge_document(
                    workspace_id,
                    agent_id,
                    {
                        "searchDocumentId": "knowledge-current",
                        "scope": "project",
                        "scopeId": project_id,
                        "projectId": project_id,
                        "title": "Current operations guide",
                        "content": "Current operations and recovery guidance.",
                        "category": "Operations",
                        "documentType": "guide",
                        "source": "memoryendpoints://knowledge-edge",
                        "description": "A current guide.",
                        "keywords": ["operations", "recovery"],
                        "taxonomyPaths": [["Operations", "Recovery"]],
                        "authorityLevel": "canonical",
                    },
                )
                self.assertIsNone(error)
                self.assertEqual("knowledge-current", current["searchDocumentId"])
                historical, error = store.upsert_knowledge_document(
                    workspace_id,
                    agent_id,
                    {
                        "searchDocumentId": "knowledge-historical",
                        "content": "Historical operations guidance.",
                        "knowledgeStatus": "historical",
                        "statusReason": "Replaced by the current guide.",
                    },
                )
                self.assertIsNone(error)
                self.assertEqual("historical", historical["knowledgeStatus"])
                superseded, error = store.upsert_knowledge_document(
                    workspace_id,
                    agent_id,
                    {
                        "searchDocumentId": "knowledge-superseded",
                        "content": "Superseded operations guidance.",
                        "knowledgeStatus": "superseded",
                        "statusReason": "Replaced by the current guide.",
                        "supersededByDocumentId": "knowledge-current",
                    },
                )
                self.assertIsNone(error)
                self.assertEqual("knowledge-current", superseded["supersededByDocumentId"])

                filters = (
                    {"q": "operations"},
                    {"scope": "project", "scopeId": project_id},
                    {"category": "operations"},
                    {"documentType": "guide"},
                    {"knowledgeStatus": "historical"},
                    {"authorityLevel": "canonical"},
                    {"sourcePrefix": "memoryendpoints://"},
                    {"searchDocumentId": "knowledge-current"},
                    {"routeOrPath": current["routeOrPath"]},
                    {"taxonomyPath": "Operations > Recovery"},
                    {"q": "does-not-match"},
                )
                for query in filters:
                    with self.subTest(backend=store_type.__name__, query=query):
                        items = store.knowledge_documents(workspace_id, query, _all=True)
                        if query.get("q") == "does-not-match":
                            self.assertEqual([], items)
                        else:
                            self.assertTrue(items)
                self.assertEqual([], store.knowledge_documents(workspace_id, {"scope": "other"}, _all=True))

    def test_external_link_validation_mentions_and_filter_rejections_match_across_backends(self):
        previous = os.environ.get("MEMORYENDPOINTS_CREDENTIAL_PEPPER")
        os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = "synthetic-external-edge-pepper-" + ("x" * 48)
        self.addCleanup(
            lambda: os.environ.__setitem__("MEMORYENDPOINTS_CREDENTIAL_PEPPER", previous)
            if previous is not None
            else os.environ.pop("MEMORYENDPOINTS_CREDENTIAL_PEPPER", None)
        )
        for store_type in (FileStore, SQLiteStore):
            with self.subTest(backend=store_type.__name__), tempfile.TemporaryDirectory() as tmp:
                suffix = "store.json" if store_type is FileStore else "store.sqlite3"
                store = store_type(Path(tmp) / suffix)
                workspace_id, _master, _secret, _account, _company, _project, _recovery = store.create_free_account(
                    "External Edge Workspace", "External Edge Company", "External Edge Project"
                )
                agent_id = "external-edge-agent"
                store.register_agent(workspace_id, agent_id, "External Edge Agent")
                common = {
                    "url": "https://example.com/current-guide",
                    "siteName": "Example",
                    "pageTitle": "Current Guide",
                    "description": "A current external reference.",
                    "keywords": ["operations", "recovery"],
                    "relationshipType": "reference",
                }
                for mutation, expected in (
                    ({"url": "ftp://example.com/file"}, "external_url_scheme_unsupported"),
                    ({"url": "https://user:pass@example.com/file"}, "external_url_credentials_forbidden"),
                    ({"url": "https://localhost/file"}, "external_url_not_public"),
                    ({"relationshipType": "unknown"}, "external_link_relationship_unsupported"),
                    ({"reviewStatus": "unknown"}, "external_link_review_status_unsupported"),
                    ({"crawlStatus": "unknown"}, "external_link_crawl_status_unsupported"),
                ):
                    with self.subTest(backend=store_type.__name__, expected=expected):
                        payload = dict(common, **mutation)
                        self.assertEqual((None, expected), store.upsert_external_link(workspace_id, agent_id, payload))
                self.assertEqual((None, "knowledge_document_not_found"), store.upsert_external_link(
                    workspace_id, agent_id, dict(common, knowledgeDocumentId="missing-document")
                ))

                document, error = store.upsert_knowledge_document(
                    workspace_id, agent_id, {"searchDocumentId": "external-document", "content": "Reference document", "taxonomyPaths": [["Operations", "Recovery"]]}
                )
                self.assertIsNone(error)
                link, error = store.upsert_external_link(
                    workspace_id,
                    agent_id,
                    dict(common, knowledgeDocumentId=document["searchDocumentId"], contextDescription="Why this page is cited", citationOrder=2, citationLabel="Guide"),
                )
                self.assertIsNone(error)
                self.assertTrue(link["mentions"])
                self.assertEqual((None, "external_link_citation_order_invalid"), store.upsert_external_link(
                    workspace_id, agent_id, dict(common, knowledgeDocumentId=document["searchDocumentId"], citationOrder="bad")
                ))
                self.assertTrue(store.external_links(workspace_id, {"host": "example.com"}, _all=True))
                self.assertTrue(store.external_links(workspace_id, {"siteName": "exa"}, _all=True))
                self.assertTrue(store.external_links(workspace_id, {"q": "current recovery"}, _all=True))
                self.assertEqual([], store.external_links(workspace_id, {"q": "not-found"}, _all=True))
                self.assertEqual([], store.external_links(workspace_id, {"documentId": "missing"}, _all=True))
                self.assertEqual([], store.external_links(workspace_id, {"relationshipType": "decision"}, _all=True))
                self.assertEqual([], store.external_links(workspace_id, {"taxonomyPath": "Unknown"}, _all=True))


if __name__ == "__main__":
    unittest.main()
