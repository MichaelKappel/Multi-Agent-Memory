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
        self.assertEqual({"broadcast": 0, "targeted": 0}, check["deliveryCountsByAgent"]["swarm-observer-agent"])
        self.assertFalse(check["rawCredentialExposed"])
        self.assertFalse(check["rawPayloadExposed"])

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


if __name__ == "__main__":
    unittest.main()
