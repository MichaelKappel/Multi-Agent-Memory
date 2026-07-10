import json
import unittest

from scripts import verify_current_message_fanout as fanout


def inbox(*items, broadcast=0, targeted=0):
    return {
        "ok": True,
        "items": list(items),
        "deliveryCounts": {"broadcast": broadcast, "targeted": targeted},
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def message_item(summary, message_type, notification_id):
    return {
        "message": {"safeSummary": summary, "valuesRedacted": True},
        "notification": {"notificationId": notification_id, "status": "unread"},
        "delivery": {"messageType": message_type, "valuesRedacted": True},
    }


class CurrentMessageFanoutVerificationTests(unittest.TestCase):
    def test_broadcast_fanout_check_requires_all_agents_to_read_broadcast(self):
        agents = ["human-verifier-agent", "codex-agent", "swarm-observer-agent"]
        summary = "broadcast run 1"
        payloads = {
            "human-verifier-agent": inbox(message_item(summary, "broadcast", "note-human"), broadcast=1),
            "codex-agent": inbox(message_item(summary, "broadcast", "note-codex"), broadcast=1),
            "swarm-observer-agent": inbox(),
        }

        check = fanout.broadcast_fanout_check(payloads, summary, agents)

        self.assertFalse(check["ok"])
        self.assertEqual(["swarm-observer-agent"], check["missingAgents"])
        self.assertEqual(["human-verifier-agent", "codex-agent"], check["visibleAgents"])
        self.assertEqual(3, check["expectedRecipientCount"])
        self.assertEqual(2, check["visibleRecipientCount"])
        self.assertFalse(check["uniqueRecipientNotificationIds"])
        self.assertEqual(2, check["distinctNotificationIdCount"])
        self.assertEqual({"broadcast": 0, "targeted": 0}, check["deliveryCountsByAgent"]["swarm-observer-agent"])
        self.assertFalse(check["rawCredentialExposed"])
        self.assertFalse(check["rawPayloadExposed"])

    def test_broadcast_fanout_check_requires_per_recipient_notification_ids(self):
        agents = ["human-verifier-agent", "codex-agent", "swarm-observer-agent"]
        summary = "broadcast shared notification"
        payloads = {
            "human-verifier-agent": inbox(message_item(summary, "broadcast", "note-shared"), broadcast=1),
            "codex-agent": inbox(message_item(summary, "broadcast", "note-shared"), broadcast=1),
            "swarm-observer-agent": inbox(message_item(summary, "broadcast", "note-shared"), broadcast=1),
        }

        check = fanout.broadcast_fanout_check(payloads, summary, agents)

        self.assertFalse(check["ok"])
        self.assertFalse(check["uniqueRecipientNotificationIds"])
        self.assertEqual(1, check["distinctNotificationIdCount"])
        self.assertEqual(3, check["expectedNotificationIdCount"])
        self.assertEqual(["note-shared"], check["duplicateNotificationIds"])
        self.assertEqual([], check["missingAgents"])
        self.assertEqual(3, check["visibleRecipientCount"])

    def test_broadcast_fanout_check_accepts_per_recipient_notification_ids(self):
        agents = ["human-verifier-agent", "codex-agent", "swarm-observer-agent"]
        summary = "broadcast unique notifications"
        payloads = {
            "human-verifier-agent": inbox(message_item(summary, "broadcast", "note-human"), broadcast=1),
            "codex-agent": inbox(message_item(summary, "broadcast", "note-codex"), broadcast=1),
            "swarm-observer-agent": inbox(message_item(summary, "broadcast", "note-observer"), broadcast=1),
        }

        check = fanout.broadcast_fanout_check(payloads, summary, agents)

        self.assertTrue(check["ok"])
        self.assertTrue(check["uniqueRecipientNotificationIds"])
        self.assertEqual(3, check["distinctNotificationIdCount"])
        self.assertEqual(
            {
                "human-verifier-agent": "note-human",
                "codex-agent": "note-codex",
                "swarm-observer-agent": "note-observer",
            },
            check["primaryNotificationIdsByAgent"],
        )

    def test_broadcast_fanout_check_rejects_wrong_message_type(self):
        agents = ["human-verifier-agent", "codex-agent"]
        summary = "broadcast run 2"
        payloads = {
            "human-verifier-agent": inbox(message_item(summary, "broadcast", "note-human"), broadcast=1),
            "codex-agent": inbox(message_item(summary, "targeted", "note-codex"), targeted=1),
        }

        check = fanout.broadcast_fanout_check(payloads, summary, agents)

        self.assertFalse(check["ok"])
        self.assertEqual(["codex-agent"], check["wrongTypeAgents"])
        self.assertEqual([], check["missingAgents"])

    def test_targeted_delivery_check_distinguishes_targeted_from_broadcast(self):
        agents = ["human-verifier-agent", "codex-agent", "swarm-observer-agent"]
        summary = "targeted run 1"
        payloads = {
            "human-verifier-agent": inbox(),
            "codex-agent": inbox(message_item(summary, "targeted", "note-codex"), targeted=1),
            "swarm-observer-agent": inbox(),
        }

        check = fanout.targeted_delivery_check(payloads, summary, "codex-agent", agents)

        self.assertTrue(check["ok"])
        self.assertTrue(check["visibleToTarget"])
        self.assertEqual(["codex-agent"], check["visibleAgents"])
        self.assertEqual([], check["unexpectedAgents"])
        self.assertEqual({"codex-agent": ["note-codex"]}, check["notificationIdsByAgent"])

    def test_targeted_delivery_check_rejects_non_target_visibility(self):
        agents = ["human-verifier-agent", "codex-agent", "swarm-observer-agent"]
        summary = "targeted run 2"
        payloads = {
            "human-verifier-agent": inbox(message_item(summary, "targeted", "note-human"), targeted=1),
            "codex-agent": inbox(message_item(summary, "targeted", "note-codex"), targeted=1),
            "swarm-observer-agent": inbox(),
        }

        check = fanout.targeted_delivery_check(payloads, summary, "codex-agent", agents)

        self.assertFalse(check["ok"])
        self.assertEqual(["human-verifier-agent"], check["unexpectedAgents"])
        self.assertTrue(check["visibleToTarget"])

    def test_acknowledgement_isolation_keeps_broadcast_visible_to_other_agents(self):
        agents = ["human-verifier-agent", "codex-agent", "swarm-observer-agent"]
        summary = "broadcast ack run"
        before = inbox(message_item(summary, "broadcast", "note-codex"), broadcast=1)
        after = {
            "human-verifier-agent": inbox(message_item(summary, "broadcast", "note-human"), broadcast=1),
            "codex-agent": inbox(),
            "swarm-observer-agent": inbox(message_item(summary, "broadcast", "note-observer"), broadcast=1),
        }

        check = fanout.acknowledgement_isolation_check(before, after, summary, "codex-agent", agents)

        self.assertTrue(check["ok"])
        self.assertEqual("note-codex", check["ackNotificationId"])
        self.assertNotIn("codex-agent", check["visibleAfterAckAgents"])
        self.assertEqual(["human-verifier-agent", "swarm-observer-agent"], check["expectedRemainingAgents"])

    def test_build_report_is_secret_safe_and_sets_overall_status(self):
        agents = ["human-verifier-agent", "codex-agent", "swarm-observer-agent"]
        registration = {"ok": True, "items": [], "valuesRedacted": True}
        broadcast = {
            "ok": True,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        targeted_codex = {
            "ok": True,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        targeted_human = {
            "ok": True,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        redaction = {
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }

        report = fanout.build_report(
            "https://memoryendpoints.com",
            "abc123",
            agents,
            registration,
            broadcast,
            targeted_codex,
            targeted_human,
            redaction,
            workspace_id="ws-private-value",
            token="token-fixture",
        )
        text = json.dumps(report, sort_keys=True)

        self.assertTrue(report["ok"])
        self.assertTrue(report["messageTypesVerified"]["broadcast"])
        self.assertIn("sha256:", report["workspaceIdHash"])
        self.assertNotIn("ws-private-value", text)
        self.assertNotIn("token-fixture", text)
        self.assertFalse(report["rawCredentialValuesStored"])
        self.assertFalse(report["rawWorkspaceIdStored"])

    def test_response_redaction_check_flags_secret_echoes(self):
        payloads = [
            {
                "ok": True,
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
                "nested": {"apiKeySecret": "token-fixture"},
            }
        ]

        check = fanout.response_redaction_check(payloads, token="token-fixture")

        self.assertFalse(check["rawPayloadExposed"])
        self.assertTrue(check["rawCredentialExposed"])
        self.assertTrue(check["rawCredentialEchoed"])
        self.assertTrue(check["apiKeySecretFieldEchoed"])

    def test_read_current_messages_polls_until_expected_summary_is_visible(self):
        calls = []
        original_request_json = fanout.request_json

        def fake_request_json(*_args, **_kwargs):
            calls.append(_kwargs.get("query"))
            if len(calls) == 1:
                return 200, inbox(), {}
            return 200, inbox(message_item("broadcast summary", "broadcast", "note-agent"), broadcast=1), {}

        try:
            fanout.request_json = fake_request_json
            payloads, all_payloads = fanout.read_current_messages(
                "https://memoryendpoints.com",
                "token",
                "workspace-id",
                ["agent-a"],
                "msg-a",
                expected_summary="broadcast summary",
                expected_agents=["agent-a"],
                attempts=2,
                delay_seconds=0,
            )
        finally:
            fanout.request_json = original_request_json

        self.assertEqual(2, len(calls))
        self.assertEqual(1, len(all_payloads))
        self.assertEqual("broadcast summary", payloads["agent-a"]["items"][0]["message"]["safeSummary"])

    def test_read_current_messages_filters_by_agent_notification_id(self):
        calls = []
        original_request_json = fanout.request_json

        def fake_request_json(*_args, **_kwargs):
            calls.append(_kwargs.get("query"))
            return 200, inbox(message_item("broadcast summary", "broadcast", "note-agent"), broadcast=1), {}

        try:
            fanout.request_json = fake_request_json
            fanout.read_current_messages(
                "https://memoryendpoints.com",
                "token",
                "workspace-id",
                ["agent-a"],
                "msg-a",
                notification_ids_by_agent={"agent-a": "note-agent"},
                expected_summary="broadcast summary",
                expected_agents=["agent-a"],
                attempts=1,
                delay_seconds=0,
            )
        finally:
            fanout.request_json = original_request_json

        self.assertIn("notification_id=note-agent", calls[0])
        self.assertIn("message_id=msg-a", calls[0])

    def test_notification_ids_by_agent_from_submit_reads_broadcast_notifications(self):
        payload = {
            "notifications": [
                {"targetAgentId": "human-verifier-agent", "notificationId": "note-human"},
                {"targetAgentId": "codex-agent", "notificationId": "note-codex"},
            ]
        }

        self.assertEqual(
            {
                "human-verifier-agent": "note-human",
                "codex-agent": "note-codex",
            },
            fanout.notification_ids_by_agent_from_submit(payload),
        )


if __name__ == "__main__":
    unittest.main()
