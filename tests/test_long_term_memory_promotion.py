import unittest

from scripts import promote_long_term_memory_reviews as promotion


class LongTermMemoryPromotionTests(unittest.TestCase):
    def test_build_plan_promotes_only_pending_accepted_long_term_memory(self):
        memory_items = [
            {
                "eventId": "mem-a",
                "title": "System Targets",
                "source": "docs/long-term-memory/system-targets.md",
                "memoryType": "procedure",
                "reviewStatus": "pending",
                "promotionState": "review_pending",
            },
            {
                "eventId": "mem-b",
                "title": "Already Done",
                "source": "docs/long-term-memory/already.md",
                "memoryType": "note",
                "reviewStatus": "promoted",
                "promotionState": "promoted",
            },
        ]
        reviews = [
            {
                "reviewId": "review-a",
                "memoryEventId": "mem-a",
                "status": "pending",
                "firewallDecision": "accepted",
            },
            {
                "reviewId": "review-b",
                "memoryEventId": "mem-b",
                "status": "promoted",
                "firewallDecision": "accepted",
            },
        ]

        plan = promotion.build_plan(memory_items, reviews)

        self.assertEqual(["promote", "already_promoted"], [item["action"] for item in plan])
        self.assertEqual("review-a", plan[0]["reviewId"])
        self.assertTrue(all(item["valuesRedacted"] for item in plan))

    def test_verification_summary_requires_promoted_statuses(self):
        payload = {
            "memorySource": "hosted_workspace_store",
            "filesystemDocsIncluded": False,
            "items": [
                {
                    "eventId": "mem-a",
                    "title": "System Targets",
                    "source": "docs/long-term-memory/system-targets.md",
                    "tags": ["long-term-memory-migration"],
                    "reviewStatus": "promoted",
                    "promotionState": "promoted",
                },
                {
                    "eventId": "mem-other",
                    "title": "Other",
                    "source": "api",
                    "tags": ["long-term-memory-migration"],
                    "reviewStatus": "pending",
                    "promotionState": "review_pending",
                },
            ],
        }

        summary = promotion.verification_summary(payload)

        self.assertTrue(summary["allPromoted"])
        self.assertEqual(1, summary["count"])
        self.assertEqual("hosted_workspace_store", summary["memorySource"])
        self.assertFalse(summary["filesystemDocsIncluded"])

    def test_build_report_redacts_credentials_and_raw_workspace_id(self):
        plan = [{"action": "already_promoted", "eventId": "mem-a", "valuesRedacted": True}]
        verification = {
            "allPromoted": True,
            "memorySource": "hosted_workspace_store",
            "filesystemDocsIncluded": False,
        }

        report = promotion.build_report(
            "https://memoryendpoints.com",
            "workspace-secret-id",
            "private-api-token",
            "human-verifier-agent",
            "live_apply",
            plan,
            plan,
            verification,
        )
        text = str(report)

        self.assertTrue(report["ok"])
        self.assertTrue(report["valuesRedacted"])
        self.assertFalse(report["rawCredentialValuesStored"])
        self.assertFalse(report["rawWorkspaceIdStored"])
        self.assertNotIn("private-api-token", text)
        self.assertNotIn("workspace-secret-id", text)


if __name__ == "__main__":
    unittest.main()
