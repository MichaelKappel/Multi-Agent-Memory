import json
import unittest

from scripts import verify_live_memory_submit_consistency as verifier


def submit_payload(event_id="mem-1", review_id="review-1"):
    return {
        "ok": True,
        "event": {"eventId": event_id, "reviewId": review_id, "status": "active"},
        "canonicalMemoryEventId": event_id,
        "reviewId": review_id,
        "persisted": True,
        "visibleInSearch": True,
        "visibleInReviewQueue": True,
        "visibleInAuditLog": True,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


class LiveMemorySubmitConsistencyTests(unittest.TestCase):
    def test_evaluate_probe_passes_when_response_matches_durable_readback(self):
        check = verifier.evaluate_probe(
            201,
            submit_payload(),
            {"items": [{"eventId": "mem-1"}], "filters": {"eventId": "mem-1"}, "valuesRedacted": True},
            {"items": [{"memoryEventId": "mem-1"}], "statusCounts": {"pending": 1}, "valuesRedacted": True},
            {"items": [{"target": "mem-1"}], "valuesRedacted": True},
        )

        self.assertTrue(check["ok"])
        self.assertEqual({"exactSearchCount": 1, "reviewQueueMatchCount": 1, "auditMatchCount": 1}, check["durableReadback"])
        self.assertEqual([], check["mismatches"])

    def test_evaluate_probe_flags_visibility_claim_without_readback(self):
        check = verifier.evaluate_probe(
            201,
            submit_payload("mem-missing"),
            {"items": [], "filters": {"eventId": "mem-missing"}, "valuesRedacted": True},
            {"items": [], "statusCounts": {}, "valuesRedacted": True},
            {"items": [], "valuesRedacted": True},
        )

        self.assertFalse(check["ok"])
        self.assertIn("response_visible_search_without_exact_readback", check["mismatches"])
        self.assertIn("response_visible_review_without_review_readback", check["mismatches"])
        self.assertIn("response_visible_audit_without_audit_readback", check["mismatches"])

    def test_build_report_does_not_store_raw_secret_or_workspace_id(self):
        probes = [
            verifier.evaluate_probe(
                201,
                submit_payload(),
                {"items": [{"eventId": "mem-1"}], "valuesRedacted": True},
                {"items": [{"memoryEventId": "mem-1"}], "valuesRedacted": True},
                {"items": [{"target": "mem-1"}], "valuesRedacted": True},
            )
        ]

        report = verifier.build_report(
            "https://memoryendpoints.com",
            "source-sha",
            "workspace-secret-id",
            "raw-token-value",
            probes,
        )
        text = json.dumps(report, sort_keys=True)

        self.assertTrue(report["ok"])
        self.assertIn("workspaceIdHash", report)
        self.assertNotIn("workspace-secret-id", text)
        self.assertNotIn("raw-token-value", text)
        self.assertFalse(report["rawCredentialValuesStored"])
        self.assertFalse(report["rawWorkspaceIdStored"])


if __name__ == "__main__":
    unittest.main()
