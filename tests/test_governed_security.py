import unittest
import json

from memoryendpoints.app import _cors_headers
from memoryendpoints.http import one_time_secret_response
from memoryendpoints.security import evaluate_memory_firewall, governed_bearer_token, redact_payload, redact_text


class GovernedCredentialRedactionTests(unittest.TestCase):
    def test_strict_bearer_parser_accepts_only_versioned_governed_tokens(self):
        master = "me_master_v1.master-record." + ("a" * 43)
        agent = "me_agent_v1.agent-record." + ("b" * 43)
        connector = "me_connector_v1.connector-record." + ("c" * 43)
        self.assertEqual(master, governed_bearer_token("Bearer " + master))
        self.assertEqual(agent, governed_bearer_token("bearer " + agent))
        self.assertEqual(connector, governed_bearer_token("Bearer " + connector))
        for rejected in (
            master,
            "Basic " + master,
            "Bearer me_live_legacyworkspacekey",
            "Bearer me_invite_v1.invite-record." + ("c" * 43),
            "Bearer " + master + " trailing",
            "Bearer " + master + ",other",
        ):
            with self.subTest(rejected=rejected.split(" ", 1)[0]):
                self.assertEqual("", governed_bearer_token(rejected))

    def test_cors_does_not_reflect_unapproved_request_headers(self):
        headers = dict(
            _cors_headers(
                {
                    "HTTP_ORIGIN": "https://agent.example",
                    "HTTP_ACCESS_CONTROL_REQUEST_HEADERS": "Authorization, X-Exfiltrate, Idempotency-Key",
                }
            )
        )
        self.assertEqual("Authorization, Idempotency-Key", headers["Access-Control-Allow-Headers"])
        self.assertNotIn("X-Exfiltrate", headers["Access-Control-Allow-Headers"])

    def test_one_time_secret_response_is_non_cacheable_and_truthful(self):
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        body = b"".join(
            one_time_secret_response(
                start_response,
                {"ok": True, "agentToken": "delivered-only-in-this-test", "rawCredentialExposed": False},
            )
        )
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual("201 Created", captured["status"])
        self.assertIn("no-store", captured["headers"]["Cache-Control"])
        self.assertEqual("no-cache", captured["headers"]["Pragma"])
        self.assertEqual("no-referrer", captured["headers"]["Referrer-Policy"])
        self.assertTrue(payload["credentialDeliveredToAuthorizedRecipient"])
        self.assertFalse(payload["rawCredentialPersisted"])
        self.assertNotIn("rawCredentialExposed", payload)

    def test_governed_credentials_and_invite_fragments_are_redacted_from_text(self):
        fixtures = (
            "me_master_v1.master-record.private-master-secret-value",
            "me_agent_v1.agent-record.private-agent-secret-value",
            "me_invite_v1.invite-record.private-invite-secret-value",
            "me_human_v1.human-record.private-human-secret-value",
            "me_closure_v1.intent-record.private-closure-secret-value",
            "me_hsession_v1.session-record.private-session-secret-value",
            "me_connector_v1.connector-record.private-connector-secret-value",
            "me_paircode_v1.code-record.private-authorization-code-value",
            "https://memoryendpoints.com/agent-setup#invite=privateinvitefragmentvalue",
            "https://memoryendpoints.com/agent-invite#secret=privateinvitefragmentvalue",
            "https://memoryendpoints.com/agent-invite#code=privateinvitefragmentvalue",
        )
        for fixture in fixtures:
            with self.subTest(fixture=fixture.split(".", 1)[0]):
                self.assertNotIn("private", redact_text(fixture).lower())

    def test_secret_key_normalization_covers_common_separator_and_case_variants(self):
        sentinel = "must-not-survive"
        payload = {
            "safeAgentTokenId": "agent-token-id-public",
            "companyMasterTokenSecret": sentinel,
            "company_master_token": sentinel,
            "agent.token": sentinel,
            "agent_token": sentinel,
            "invite-secret": sentinel,
            "invite_secret": sentinel,
            "inviteCode": sentinel,
            "redemption_code": sentinel,
            "Authorization": sentinel,
            "tokenHash": sentinel,
            "secret_hash": sentinel,
            "credentialVerifier": sentinel,
            "humanOwnerRecoverySecret": sentinel,
            "closureIntentSecret": sentinel,
            "csrfToken": sentinel,
        }
        redacted = redact_payload(payload)
        self.assertEqual("agent-token-id-public", redacted["safeAgentTokenId"])
        self.assertNotIn(sentinel, str(redacted))

    def test_memory_firewall_never_returns_raw_governed_credential(self):
        token = "me_agent_v1.agent-record.private-agent-secret-value"
        result = evaluate_memory_firewall({"summary": "credential=" + token})
        self.assertNotIn(token, str(result))
        self.assertFalse(result["rawPrivatePayloadStored"])


if __name__ == "__main__":
    unittest.main()
