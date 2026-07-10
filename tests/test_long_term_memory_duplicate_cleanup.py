import unittest

from scripts import cleanup_duplicate_long_term_memory as cleanup


class LongTermMemoryDuplicateCleanupTests(unittest.TestCase):
    def test_duplicate_selector_excludes_promoted_canonical_records(self):
        duplicate = {
            "eventId": "mem-duplicate",
            "source": "docs/long-term-memory/system-targets.md",
            "summary": "Deep link: docs/long-term-memory/system-targets.md\n\n# System Targets",
            "tags": ["docs-seed", "dogfood-migration"],
            "reviewStatus": "pending",
            "promotionState": "review_pending",
        }
        canonical = {
            "eventId": "mem-canonical",
            "source": "docs/long-term-memory/system-targets.md",
            "summary": "Purpose: durable target memory.",
            "tags": ["long-term-memory-migration"],
            "reviewStatus": "promoted",
            "promotionState": "promoted",
        }

        self.assertTrue(cleanup.is_duplicate_item(duplicate))
        self.assertFalse(cleanup.is_duplicate_item(canonical))
        self.assertEqual([duplicate], cleanup.duplicate_items([{"items": [canonical, duplicate]}]))

    def test_build_plan_rejects_only_pending_duplicates(self):
        duplicates = [
            {
                "eventId": "mem-a",
                "title": "System Targets",
                "source": "docs/long-term-memory/system-targets.md",
                "tags": ["docs-seed"],
                "reviewStatus": "pending",
                "promotionState": "review_pending",
            },
            {
                "eventId": "mem-b",
                "title": "Already Rejected",
                "source": "docs/long-term-memory/old.md",
                "tags": ["docs-seed"],
                "reviewStatus": "rejected",
                "promotionState": "rejected",
            },
        ]
        reviews = [
            {"reviewId": "review-a", "memoryEventId": "mem-a", "status": "pending"},
            {"reviewId": "review-b", "memoryEventId": "mem-b", "status": "rejected"},
        ]

        plan = cleanup.build_plan(duplicates, reviews)

        self.assertEqual(["reject", "already_rejected"], [item["action"] for item in plan])
        self.assertTrue(all(item["valuesRedacted"] for item in plan))

    def test_duplicate_reviews_are_visible_after_rejection(self):
        reviews = [
            {
                "reviewId": "review-a",
                "memoryEventId": "mem-a",
                "status": "rejected",
                "publicSafeSummary": "Deep link: docs/long-term-memory/system-targets.md\n\n# System Targets",
            }
        ]

        items = cleanup.duplicate_items_from_reviews(reviews)
        plan = cleanup.build_plan(items, reviews)

        self.assertEqual(1, len(items))
        self.assertEqual("docs/long-term-memory/system-targets.md", items[0]["source"])
        self.assertEqual("already_rejected", plan[0]["action"])

    def test_report_fails_if_duplicates_remain(self):
        report = cleanup.build_report(
            "https://memoryendpoints.com",
            "workspace-secret-id",
            "private-api-token",
            "human-verifier-agent",
            "live_apply",
            [{"action": "reject", "valuesRedacted": True}],
            [{"action": "reject", "rejected": True, "valuesRedacted": True}],
            {"remainingDuplicateCount": 1, "remainingDuplicates": [], "valuesRedacted": True},
        )
        text = str(report)

        self.assertFalse(report["ok"])
        self.assertFalse(report["rawCredentialValuesStored"])
        self.assertFalse(report["rawWorkspaceIdStored"])
        self.assertNotIn("private-api-token", text)
        self.assertNotIn("workspace-secret-id", text)

    def test_live_report_succeeds_when_already_clean(self):
        report = cleanup.build_report(
            "https://memoryendpoints.com",
            "workspace-secret-id",
            "private-api-token",
            "human-verifier-agent",
            "live_apply",
            [],
            [],
            {"remainingDuplicateCount": 0, "remainingDuplicates": [], "valuesRedacted": True},
        )

        self.assertTrue(report["ok"])
        self.assertEqual(0, report["targetCount"])


if __name__ == "__main__":
    unittest.main()
