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
        agents = ["human-verifier-agent", "MemoryEndpoints-Backend-Agent", "swarm-observer-agent"]
        summary = "broadcast run 1"
        payloads = {
            "human-verifier-agent": inbox(message_item(summary, "broadcast", "note-human"), broadcast=1),
            "MemoryEndpoints-Backend-Agent": inbox(message_item(summary, "broadcast", "note-backend"), broadcast=1),
            "swarm-observer-agent": inbox(),
        }

        check = fanout.broadcast_fanout_check(payloads, summary, agents)

        self.assertFalse(check["ok"])
        self.assertEqual(["swarm-observer-agent"], check["missingAgents"])
        self.assertEqual(["human-verifier-agent", "MemoryEndpoints-Backend-Agent"], check["visibleAgents"])
        self.assertEqual(3, check["expectedRecipientCount"])
        self.assertEqual(2, check["visibleRecipientCount"])
        self.assertFalse(check["uniqueRecipientNotificationIds"])
        self.assertEqual(2, check["distinctNotificationIdCount"])
        self.assertEqual({"broadcast": 0, "targeted": 0}, check["deliveryCountsByAgent"]["swarm-observer-agent"])
        self.assertFalse(check["rawCredentialExposed"])
        self.assertFalse(check["rawPayloadExposed"])

    def test_broadcast_fanout_check_requires_per_recipient_notification_ids(self):
        agents = ["human-verifier-agent", "MemoryEndpoints-Backend-Agent", "swarm-observer-agent"]
        summary = "broadcast shared notification"
        payloads = {
            "human-verifier-agent": inbox(message_item(summary, "broadcast", "note-shared"), broadcast=1),
            "MemoryEndpoints-Backend-Agent": inbox(message_item(summary, "broadcast", "note-shared"), broadcast=1),
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
        agents = ["human-verifier-agent", "MemoryEndpoints-Backend-Agent", "swarm-observer-agent"]
        summary = "broadcast unique notifications"
        payloads = {
            "human-verifier-agent": inbox(message_item(summary, "broadcast", "note-human"), broadcast=1),
            "MemoryEndpoints-Backend-Agent": inbox(message_item(summary, "broadcast", "note-backend"), broadcast=1),
            "swarm-observer-agent": inbox(message_item(summary, "broadcast", "note-observer"), broadcast=1),
        }

        check = fanout.broadcast_fanout_check(payloads, summary, agents)

        self.assertTrue(check["ok"])
        self.assertTrue(check["uniqueRecipientNotificationIds"])
        self.assertEqual(3, check["distinctNotificationIdCount"])
        self.assertEqual(
            {
                "human-verifier-agent": "note-human",
                "MemoryEndpoints-Backend-Agent": "note-backend",
                "swarm-observer-agent": "note-observer",
            },
            check["primaryNotificationIdsByAgent"],
        )

    def test_broadcast_fanout_check_rejects_wrong_message_type(self):
        agents = ["human-verifier-agent", "MemoryEndpoints-Backend-Agent"]
        summary = "broadcast run 2"
        payloads = {
            "human-verifier-agent": inbox(message_item(summary, "broadcast", "note-human"), broadcast=1),
            "MemoryEndpoints-Backend-Agent": inbox(message_item(summary, "targeted", "note-backend"), targeted=1),
        }

        check = fanout.broadcast_fanout_check(payloads, summary, agents)

        self.assertFalse(check["ok"])
        self.assertEqual(["MemoryEndpoints-Backend-Agent"], check["wrongTypeAgents"])
        self.assertEqual([], check["missingAgents"])

    def test_targeted_delivery_check_distinguishes_targeted_from_broadcast(self):
        agents = ["human-verifier-agent", "MemoryEndpoints-Backend-Agent", "swarm-observer-agent"]
        summary = "targeted run 1"
        payloads = {
            "human-verifier-agent": inbox(),
            "MemoryEndpoints-Backend-Agent": inbox(message_item(summary, "targeted", "note-backend"), targeted=1),
            "swarm-observer-agent": inbox(),
        }

        check = fanout.targeted_delivery_check(payloads, summary, "MemoryEndpoints-Backend-Agent", agents)

        self.assertTrue(check["ok"])
        self.assertTrue(check["visibleToTarget"])
        self.assertEqual(["MemoryEndpoints-Backend-Agent"], check["visibleAgents"])
        self.assertEqual([], check["unexpectedAgents"])
        self.assertEqual({"MemoryEndpoints-Backend-Agent": ["note-backend"]}, check["notificationIdsByAgent"])

    def test_targeted_delivery_check_rejects_non_target_visibility(self):
        agents = ["human-verifier-agent", "MemoryEndpoints-Backend-Agent", "swarm-observer-agent"]
        summary = "targeted run 2"
        payloads = {
            "human-verifier-agent": inbox(message_item(summary, "targeted", "note-human"), targeted=1),
            "MemoryEndpoints-Backend-Agent": inbox(message_item(summary, "targeted", "note-backend"), targeted=1),
            "swarm-observer-agent": inbox(),
        }

        check = fanout.targeted_delivery_check(payloads, summary, "MemoryEndpoints-Backend-Agent", agents)

        self.assertFalse(check["ok"])
        self.assertEqual(["human-verifier-agent"], check["unexpectedAgents"])
        self.assertTrue(check["visibleToTarget"])

    def test_acknowledgement_isolation_keeps_broadcast_visible_to_other_agents(self):
        agents = ["human-verifier-agent", "MemoryEndpoints-Backend-Agent", "swarm-observer-agent"]
        summary = "broadcast ack run"
        before = inbox(message_item(summary, "broadcast", "note-backend"), broadcast=1)
        after = {
            "human-verifier-agent": inbox(message_item(summary, "broadcast", "note-human"), broadcast=1),
            "MemoryEndpoints-Backend-Agent": inbox(),
            "swarm-observer-agent": inbox(message_item(summary, "broadcast", "note-observer"), broadcast=1),
        }

        check = fanout.acknowledgement_isolation_check(before, after, summary, "MemoryEndpoints-Backend-Agent", agents)

        self.assertTrue(check["ok"])
        self.assertEqual("note-backend", check["ackNotificationId"])
        self.assertNotIn("MemoryEndpoints-Backend-Agent", check["visibleAfterAckAgents"])
        self.assertEqual(["human-verifier-agent", "swarm-observer-agent"], check["expectedRemainingAgents"])

    def test_build_report_is_secret_safe_and_sets_overall_status(self):
        agents = ["human-verifier-agent", "MemoryEndpoints-Backend-Agent", "swarm-observer-agent"]
        registration = {"ok": True, "items": [], "valuesRedacted": True}
        broadcast = {
            "ok": True,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        targeted_backend = {
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
            targeted_backend,
            targeted_human,
            redaction,
            workspace_id="ws-private-value",
            token="token-fixture",
        )
        text = json.dumps(report, sort_keys=True)

        self.assertTrue(report["ok"])
        self.assertTrue(report["messageTypesVerified"]["broadcast"])
        self.assertTrue(report["messageTypesVerified"]["targetedToBackend"])
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

    def test_request_json_with_retries_retries_configured_transient_status(self):
        calls = []
        original_request_json = fanout.request_json

        def fake_request_json(*_args, **_kwargs):
            calls.append(_kwargs.get("body"))
            if len(calls) == 1:
                return 500, {"ok": False, "valuesRedacted": True}, {}
            return 202, {"ok": True, "valuesRedacted": True}, {"x-test": "ok"}

        try:
            fanout.request_json = fake_request_json
            status, payload, headers = fanout.request_json_with_retries(
                "https://memoryendpoints.com",
                "/api/matm/agent-messages",
                method="POST",
                body={"workspaceId": "workspace-id"},
                retry_statuses=(500,),
                attempts=2,
                delay_seconds=0,
            )
        finally:
            fanout.request_json = original_request_json

        self.assertEqual(2, len(calls))
        self.assertEqual(202, status)
        self.assertTrue(payload["ok"])
        self.assertEqual("ok", headers["x-test"])

    def test_request_json_converts_timeout_to_safe_failed_payload(self):
        original_urlopen = fanout.urlopen

        def fake_urlopen(*_args, **_kwargs):
            raise TimeoutError("simulated timeout")

        try:
            fanout.urlopen = fake_urlopen
            status, payload, headers = fanout.request_json(
                "https://memoryendpoints.com",
                "/api/matm/current-message",
            )
        finally:
            fanout.urlopen = original_urlopen

        self.assertEqual(0, status)
        self.assertEqual({}, headers)
        self.assertFalse(payload["ok"])
        self.assertEqual("request_failed", payload["error"]["code"])
        self.assertTrue(payload["valuesRedacted"])
        self.assertFalse(payload["rawCredentialExposed"])

    def test_request_json_with_retries_stops_on_non_retry_status(self):
        calls = []
        original_request_json = fanout.request_json

        def fake_request_json(*_args, **_kwargs):
            calls.append(_kwargs.get("path"))
            return 422, {"ok": False, "valuesRedacted": True}, {}

        try:
            fanout.request_json = fake_request_json
            status, payload, _headers = fanout.request_json_with_retries(
                "https://memoryendpoints.com",
                "/api/matm/agent-messages",
                retry_statuses=(500,),
                attempts=3,
                delay_seconds=0,
            )
        finally:
            fanout.request_json = original_request_json

        self.assertEqual(1, len(calls))
        self.assertEqual(422, status)
        self.assertFalse(payload["ok"])

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

    def test_read_current_messages_polls_until_excluded_agent_clears(self):
        calls = []
        original_request_json = fanout.request_json

        def fake_request_json(*_args, **_kwargs):
            query = _kwargs.get("query") or ""
            calls.append(query)
            if "agent_id=agent-a" in query:
                return 200, inbox(message_item("broadcast summary", "broadcast", "note-a"), broadcast=1), {}
            if len(calls) <= 2:
                return 200, inbox(message_item("broadcast summary", "broadcast", "note-b"), broadcast=1), {}
            return 200, inbox(), {}

        try:
            fanout.request_json = fake_request_json
            payloads, _all_payloads = fanout.read_current_messages(
                "https://memoryendpoints.com",
                "token",
                "workspace-id",
                ["agent-a", "agent-b"],
                "msg-a",
                expected_summary="broadcast summary",
                expected_agents=["agent-a"],
                excluded_agents=["agent-b"],
                attempts=2,
                delay_seconds=0,
            )
        finally:
            fanout.request_json = original_request_json

        self.assertEqual(4, len(calls))
        self.assertEqual("broadcast summary", payloads["agent-a"]["items"][0]["message"]["safeSummary"])
        self.assertEqual([], payloads["agent-b"]["items"])

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
                {"targetAgentId": "MemoryEndpoints-Backend-Agent", "notificationId": "note-backend"},
            ]
        }

        self.assertEqual(
            {
                "human-verifier-agent": "note-human",
                "MemoryEndpoints-Backend-Agent": "note-backend",
            },
            fanout.notification_ids_by_agent_from_submit(payload),
        )


if __name__ == "__main__":
    unittest.main()
