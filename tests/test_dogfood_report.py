import unittest
from urllib.parse import parse_qs

from scripts import dogfood_memoryendpoints


class FakeTransport(object):
    mode = "live_http"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def call(self, path, method="GET", body=None, headers=None, query=""):
        self.calls.append({"path": path, "query": query, "method": method})
        if self.responses:
            return self.responses.pop(0)
        return "200 OK", {"ok": True, "items": [], "valuesRedacted": True}


class DogfoodReportTests(unittest.TestCase):
    def test_canonical_url_helpers_parse_relative_and_absolute_urls(self):
        self.assertEqual(
            ("/api/matm/current-message", "agent_id=agent-b"),
            dogfood_memoryendpoints.canonical_path_query("/api/matm/current-message?agent_id=agent-b"),
        )
        self.assertEqual(
            ("/api/matm/meeting-messages", "room_id=room-1"),
            dogfood_memoryendpoints.canonical_path_query("https://memoryendpoints.com/api/matm/meeting-messages?room_id=room-1"),
        )

    def test_contract_verified_step_requires_http_and_readback_evidence(self):
        report = {"steps": []}
        dogfood_memoryendpoints.step(report, "read_current_message", "200 OK", {"items": []}, verified=False)

        self.assertFalse(report["steps"][0]["ok"])
        self.assertFalse(report["steps"][0]["contractVerified"])

    def test_readback_helpers_match_returned_ids(self):
        self.assertTrue(
            dogfood_memoryendpoints.contains_memory_event(
                {"items": [{"eventId": "mem-1"}]},
                "mem-1",
            )
        )
        self.assertTrue(
            dogfood_memoryendpoints.contains_meeting_message(
                {"items": [{"meetingMessageId": "meetmsg-1"}]},
                "meetmsg-1",
            )
        )
        self.assertTrue(
            dogfood_memoryendpoints.contains_current_message(
                {"items": [{"message": {"messageId": "msg-1"}, "notification": {"notificationId": "note-1"}}]},
                "msg-1",
                "note-1",
            )
        )

    def test_current_message_query_includes_exact_readback_filters(self):
        query = dogfood_memoryendpoints.current_message_query("ws-1", "agent-b", "msg-1", "note-1")
        parsed = parse_qs(query)

        self.assertEqual(["ws-1"], parsed["workspace_id"])
        self.assertEqual(["agent-b"], parsed["agent_id"])
        self.assertEqual(["msg-1"], parsed["message_id"])
        self.assertEqual(["note-1"], parsed["notification_id"])

    def test_read_current_message_until_polls_until_exact_notification_visible(self):
        transport = FakeTransport(
            [
                ("200 OK", {"ok": True, "items": [], "valuesRedacted": True}),
                (
                    "200 OK",
                    {
                        "ok": True,
                        "items": [
                            {
                                "message": {"messageId": "msg-1"},
                                "notification": {"notificationId": "note-1"},
                            }
                        ],
                        "valuesRedacted": True,
                    },
                ),
            ]
        )

        status, payload = dogfood_memoryendpoints.read_current_message_until(
            transport,
            {"HTTP_AUTHORIZATION": "Bearer hidden"},
            "ws-1",
            "agent-b",
            "msg-1",
            "note-1",
            expected_visible=True,
            attempts=3,
            delay_seconds=0,
        )

        self.assertEqual("200 OK", status)
        self.assertTrue(dogfood_memoryendpoints.contains_current_message(payload, "msg-1", "note-1"))
        self.assertEqual(2, len(transport.calls))
        self.assertEqual("/api/matm/current-message", transport.calls[0]["path"])
        self.assertEqual(["note-1"], parse_qs(transport.calls[0]["query"])["notification_id"])

    def test_combined_report_preserves_audit_readback_evidence(self):
        report = dogfood_memoryendpoints.combine_reports(
            [
                {
                    "mode": "local_wsgi",
                    "ok": True,
                    "coreDogfoodWorkflowVerified": True,
                    "latestDogfoodContractVerified": True,
                    "localDogfoodVerified": True,
                    "liveDogfoodVerified": False,
                    "liveCoreDogfoodVerified": False,
                    "rawCredentialValuesStored": False,
                    "rawPrivatePayloadsStored": False,
                    "requiredStepFailureCount": 0,
                    "optionalStepFailureCount": 0,
                    "auditLogCount": 3,
                    "auditTrailReadbackVerified": True,
                    "meetingMemoryPromotionVerified": True,
                    "meetingMemoryReadbackVerified": True,
                    "meetingMemorySourceReadbackVerified": True,
                }
            ]
        )

        self.assertTrue(report["ok"])
        self.assertTrue(report["localDogfoodVerified"])
        self.assertFalse(report["liveCoreDogfoodVerified"])
        self.assertTrue(report["latestDogfoodContractVerified"])
        self.assertTrue(report["localAuditTrailReadbackVerified"])
        self.assertEqual(3, report["auditLogCount"])
        self.assertTrue(report["auditTrailReadbackVerified"])
        self.assertTrue(report["meetingMemoryPromotionVerified"])
        self.assertTrue(report["meetingMemoryReadbackVerified"])
        self.assertTrue(report["meetingMemorySourceReadbackVerified"])
        self.assertFalse(report["rawCredentialValuesStored"])

    def test_combined_report_distinguishes_live_core_from_latest_contract(self):
        report = dogfood_memoryendpoints.combine_reports(
            [
                {
                    "mode": "live_http",
                    "ok": False,
                    "coreDogfoodWorkflowVerified": True,
                    "latestDogfoodContractVerified": False,
                    "localDogfoodVerified": False,
                    "liveDogfoodVerified": False,
                    "liveCoreDogfoodVerified": True,
                    "rawCredentialValuesStored": False,
                    "rawPrivatePayloadsStored": False,
                    "requiredStepFailureCount": 1,
                    "optionalStepFailureCount": 1,
                    "auditLogCount": 0,
                    "auditTrailReadbackVerified": False,
                }
            ]
        )

        self.assertFalse(report["ok"])
        self.assertFalse(report["liveDogfoodVerified"])
        self.assertTrue(report["liveCoreDogfoodVerified"])
        self.assertFalse(report["latestDogfoodContractVerified"])
        self.assertFalse(report["liveAuditTrailReadbackVerified"])
        self.assertEqual(0, report["auditLogCount"])


if __name__ == "__main__":
    unittest.main()
