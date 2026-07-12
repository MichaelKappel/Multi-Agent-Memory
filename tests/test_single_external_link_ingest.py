import unittest
from unittest.mock import patch

from memoryendpoints.external_links import stable_external_link_id
from scripts.ingest_one_external_link import (
    canonical_crawl_policy,
    canonical_content_type,
    canonical_language,
    external_link_preflight,
    external_link_readback_matches,
    external_link_request_fingerprint,
    merge_external_link_keywords,
    review_status_readback_satisfies,
)


class SingleExternalLinkIngestTests(unittest.TestCase):
    def body(self):
        return {
            "workspaceId": "workspace-one",
            "actorAgentId": "MemoryEndpoints-Backend-Agent",
            "url": "https://example.com/research/memory",
            "siteName": "Example Research",
            "pageTitle": "Agent Memory",
            "description": "Reviewed evidence about agent memory.",
            "keywords": ["agent memory", "retrieval"],
            "language": "en",
            "contentType": "text/html",
            "reviewStatus": "reviewed",
            "crawlStatus": "not_requested",
            "crawlPolicy": "metadata_only",
            "visibility": "workspace_private",
            "knowledgeDocumentId": "doc-one",
            "relationshipType": "evidence",
            "anchorText": "Agent Memory",
            "contextDescription": "Supports the reviewed retrieval architecture.",
            "citationLabel": "primary",
            "citationOrder": 1,
            "sourceReportName": "Agent Memory Research.md",
            "metadata": {"ingestMode": "single_external_link_reviewed"},
        }

    def persisted_link(self):
        body = self.body()
        return {
            "externalLinkId": stable_external_link_id(body["workspaceId"], body["url"]),
            "normalizedUrl": body["url"],
            "siteName": body["siteName"],
            "pageTitle": body["pageTitle"],
            "description": body["description"],
            "keywords": body["keywords"],
            "language": body["language"],
            "contentType": body["contentType"],
            "reviewStatus": body["reviewStatus"],
            "crawlStatus": body["crawlStatus"],
            "crawlPolicy": body["crawlPolicy"],
            "visibility": body["visibility"],
            "mentionCount": 1,
            "mentions": [
                {
                    "knowledgeDocumentId": body["knowledgeDocumentId"],
                    "relationshipType": body["relationshipType"],
                    "anchorText": body["anchorText"],
                    "contextDescription": body["contextDescription"],
                    "citationLabel": body["citationLabel"],
                    "citationOrder": body["citationOrder"],
                    "sourceReportName": body["sourceReportName"],
                }
            ],
        }

    def test_content_derived_fingerprint_supports_exact_replay_and_reviewed_revision(self):
        body = self.body()
        replay = dict(body, metadata=dict(body["metadata"], requestFingerprint="ignored"))
        revision = dict(body, description="Corrected reviewed evidence.")

        self.assertEqual(external_link_request_fingerprint(body), external_link_request_fingerprint(replay))
        self.assertNotEqual(external_link_request_fingerprint(body), external_link_request_fingerprint(revision))

    def test_language_and_content_type_use_storage_canonical_form(self):
        self.assertEqual("en-us", canonical_language(" en-US "))
        self.assertEqual("und", canonical_language(""))
        self.assertEqual("text/html", canonical_content_type(" Text/HTML "))
        self.assertEqual("manual_source_citation_review", canonical_crawl_policy("Manual source-citation review"))

        body = self.body()
        body["language"] = "en-US"
        body["contentType"] = "Text/HTML"
        link = self.persisted_link()
        link["language"] = "en-us"
        link["contentType"] = "text/html"
        body["crawlPolicy"] = "Manual source-citation review"
        link["crawlPolicy"] = "manual_source_citation_review"

        self.assertEqual(
            {"metadataMatches": True, "citationMatches": True},
            external_link_readback_matches(link, body),
        )

    def test_existing_external_link_keywords_are_preserved_and_extended(self):
        self.assertEqual(
            ["agent memory", "retrieval", "prompt budget"],
            merge_external_link_keywords(
                ["agent memory", "retrieval"],
                ["Agent Memory", "prompt budget"],
            ),
        )

    def test_preflight_finds_canonical_url_and_exact_citation(self):
        body = self.body()
        link = self.persisted_link()
        with patch(
            "scripts.ingest_one_external_link.call_json",
            return_value=(200, {"ok": True, "items": [link]}),
        ) as mocked:
            result = external_link_preflight(
                "https://memoryendpoints.com",
                "secret-not-returned",
                body["workspaceId"],
                body["url"],
                body,
            )

        self.assertTrue(result["sourcePreviouslyIndexed"])
        self.assertTrue(result["citationAlreadyExists"])
        self.assertEqual(1, result["existingCanonicalLinkCount"])
        self.assertIn("external_link_id=", mocked.call_args.kwargs["query"])
        self.assertNotIn("secret-not-returned", mocked.call_args.kwargs["query"])

    def test_readback_requires_exact_metadata_and_citation_context(self):
        body = self.body()
        link = self.persisted_link()

        self.assertEqual(
            {"metadataMatches": True, "citationMatches": True},
            external_link_readback_matches(link, body),
        )
        link["mentions"][0]["contextDescription"] = "Stale context."
        self.assertEqual(
            {"metadataMatches": True, "citationMatches": False},
            external_link_readback_matches(link, body),
        )
        link = self.persisted_link()
        link["mentions"][0]["sourceReportName"] = "Wrong Research.md"
        self.assertEqual(
            {"metadataMatches": True, "citationMatches": False},
            external_link_readback_matches(link, body),
        )

    def test_unreviewed_mention_accepts_preserved_explicit_review_status(self):
        body = self.body()
        body["reviewStatus"] = "unreviewed"
        link = self.persisted_link()

        self.assertTrue(review_status_readback_satisfies("reviewed", "unreviewed"))
        self.assertTrue(review_status_readback_satisfies("quarantined", "unreviewed"))
        self.assertTrue(review_status_readback_satisfies("rejected", "unreviewed"))
        self.assertFalse(review_status_readback_satisfies("unreviewed", "reviewed"))
        self.assertEqual(
            {"metadataMatches": True, "citationMatches": True},
            external_link_readback_matches(link, body),
        )


if __name__ == "__main__":
    unittest.main()
