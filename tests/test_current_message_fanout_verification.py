import json
import unittest

from scripts import verify_current_message_fanout as fanout


def inbox(*items, broadcast=0, targeted=0):
    return {
        "ok": True,
        "items": list(items),
        "readStatus": 200,
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
        self.assertEqual(200, check["readDiagnosticsByAgent"]["swarm-observer-agent"]["readStatus"])
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

    def test_read_diagnostics_record_failed_current_message_reads(self):
        agents = ["agent-a"]
        payloads = {
            "agent-a": {
                "ok": False,
                "readStatus": 0,
                "error": {"code": "current_message_read_failed", "status": 0},
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            }
        }

        diagnostics = fanout.read_diagnostics_by_agent(payloads, agents)

        self.assertEqual(0, diagnostics["agent-a"]["readStatus"])
        self.assertFalse(diagnostics["agent-a"]["ok"])
        self.assertEqual("current_message_read_failed", diagnostics["agent-a"]["errorCode"])
        self.assertEqual(0, diagnostics["agent-a"]["itemCount"])

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
        self.assertTrue(report["workspaceSetup"]["ok"])
        self.assertIn("runtimeLimits", report)
        self.assertIn("sha256:", report["workspaceIdHash"])
        self.assertNotIn("ws-private-value", text)
        self.assertNotIn("token-fixture", text)
        self.assertFalse(report["rawCredentialValuesStored"])
        self.assertFalse(report["rawWorkspaceIdStored"])

    def test_workspace_setup_check_records_safe_diagnostics_for_failed_setup(self):
        check = fanout.workspace_setup_check(
            "new_workspace",
            201,
            {"ok": True, "apiKeySecret": "must-not-appear"},
            401,
            {"ok": False, "error": {"code": "unauthorized"}, "valuesRedacted": True},
            workspace_id="workspace-private",
            workspace_key="token-private",
        )
        text = json.dumps(check, sort_keys=True)

        self.assertFalse(check["ok"])
        self.assertEqual("new_workspace", check["mode"])
        self.assertEqual(201, check["setupStatus"])
        self.assertEqual(401, check["readyStatus"])
        self.assertTrue(check["workspaceIdPresent"])
        self.assertTrue(check["workspaceKeyPresent"])
        self.assertTrue(check["oneTimeKeyReturned"])
        self.assertNotIn("workspace-private", text)
        self.assertNotIn("token-private", text)
        self.assertNotIn("must-not-appear", text)

    def test_workspace_setup_check_accepts_secret_workspace_readiness_without_setup_payload(self):
        check = fanout.workspace_setup_check(
            "secret_workspace",
            None,
            {},
            200,
            {
                "ok": True,
                "workspace": {"hierarchy": {"companyId": "company-redacted"}},
                "valuesRedacted": True,
            },
            workspace_id="workspace-private",
            workspace_key="token-private",
        )

        self.assertTrue(check["ok"])
        self.assertTrue(check["setupOk"])
        self.assertTrue(check["readyOk"])
        self.assertTrue(check["hierarchyReady"])
        self.assertFalse(check["oneTimeKeyReturned"])

    def test_configure_runtime_limits_clamps_to_safe_minimums(self):
        class Args(object):
            request_timeout = 0
            read_attempts = 0
            write_attempts = 0
            ack_read_attempts = 0
            workspace_ready_attempts = 0
            read_delay = -1
            write_delay = -1
            ack_delay = -1
            max_runtime_seconds = -1

        original = fanout.runtime_limits_summary()
        try:
            fanout.configure_runtime_limits(Args())
            limits = fanout.runtime_limits_summary()
        finally:
            class Restore(object):
                request_timeout = original["requestTimeoutSeconds"]
                read_attempts = original["readAttempts"]
                write_attempts = original["writeAttempts"]
                ack_read_attempts = original["ackReadAttempts"]
                workspace_ready_attempts = original["workspaceReadyAttempts"]
                read_delay = original["readDelaySeconds"]
                write_delay = original["writeDelaySeconds"]
                ack_delay = original["ackDelaySeconds"]
                max_runtime_seconds = original["maxRuntimeSeconds"]

            fanout.configure_runtime_limits(Restore())

        self.assertEqual(1, limits["requestTimeoutSeconds"])
        self.assertEqual(1, limits["readAttempts"])
        self.assertEqual(1, limits["writeAttempts"])
        self.assertEqual(1, limits["ackReadAttempts"])
        self.assertEqual(1, limits["workspaceReadyAttempts"])
        self.assertEqual(0.0, limits["readDelaySeconds"])
        self.assertEqual(0.0, limits["writeDelaySeconds"])
        self.assertEqual(0.0, limits["ackDelaySeconds"])
        self.assertEqual(0, limits["maxRuntimeSeconds"])

    def test_request_json_returns_safe_payload_after_deadline(self):
        original_deadline = fanout.RUNTIME_DEADLINE
        try:
            fanout.RUNTIME_DEADLINE = 1
            status, payload, headers = fanout.request_json(
                "https://memoryendpoints.com",
                "/api/matm/current-message",
            )
        finally:
            fanout.RUNTIME_DEADLINE = original_deadline

        self.assertEqual(0, status)
        self.assertEqual({}, headers)
        self.assertFalse(payload["ok"])
        self.assertEqual("verification_deadline_exceeded", payload["error"]["code"])
        self.assertTrue(payload["valuesRedacted"])
        self.assertFalse(payload["rawCredentialExposed"])

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
