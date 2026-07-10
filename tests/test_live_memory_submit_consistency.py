import json
import unittest
from unittest import mock

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
    def test_configure_request_timeout_has_one_second_floor(self):
        original = verifier.REQUEST_TIMEOUT_SECONDS
        try:
            self.assertEqual(1, verifier.configure_request_timeout(0))
            self.assertEqual(1, verifier.REQUEST_TIMEOUT_SECONDS)
            self.assertEqual(7, verifier.configure_request_timeout(7))
            self.assertEqual(7, verifier.REQUEST_TIMEOUT_SECONDS)
        finally:
            verifier.REQUEST_TIMEOUT_SECONDS = original

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

    def test_run_probe_polls_until_durable_readback_matches(self):
        search_attempt = {"count": 0}

        def fake_submit(*_args, **_kwargs):
            return 201, submit_payload("mem-lag", "review-lag"), {}

        def fake_protected_get(_base_url, _token, _workspace_id, path, _params):
            if path == "/api/matm/search":
                search_attempt["count"] += 1
                matches = [{"eventId": "mem-lag"}] if search_attempt["count"] > 1 else []
                return 200, {"items": matches, "filters": {"eventId": "mem-lag"}, "valuesRedacted": True}, {}
            if path == "/api/matm/review-queue":
                matches = [{"memoryEventId": "mem-lag"}] if search_attempt["count"] > 1 else []
                return 200, {"items": matches, "statusCounts": {"pending": len(matches)}, "valuesRedacted": True}, {}
            if path == "/api/matm/audit-log":
                matches = [{"target": "mem-lag"}] if search_attempt["count"] > 1 else []
                return 200, {"items": matches, "valuesRedacted": True}, {}
            raise AssertionError(path)

        with mock.patch.object(verifier, "request_json", side_effect=fake_submit):
            with mock.patch.object(verifier, "protected_get", side_effect=fake_protected_get):
                with mock.patch.object(verifier.time, "sleep"):
                    check = verifier.run_probe(
                        "https://memoryendpoints.com",
                        "token",
                        "workspace",
                        "agent",
                        "project",
                        "run",
                        1,
                        0,
                        3,
                    )

        self.assertTrue(check["ok"])
        self.assertEqual(2, check["readbackAttemptsUsed"])
        self.assertEqual(3, check["readbackAttemptCount"])
        self.assertEqual({"exactSearchCount": 1, "reviewQueueMatchCount": 1, "auditMatchCount": 1}, check["durableReadback"])


if __name__ == "__main__":
    unittest.main()
