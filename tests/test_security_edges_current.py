"""Current platform-independent edge coverage for secret handling."""

from __future__ import annotations

import unittest

from memoryendpoints import security


class SecurityEdgesCurrentTests(unittest.TestCase):
    def test_redaction_covers_assignment_dsn_private_key_and_unicode_paths(self):
        self.assertEqual(
            "password: [REDACTED_SECRET]",
            security.redact_text("password: synthetic-password-value"),
        )
        self.assertEqual(
            "mysql://[REDACTED_CREDENTIALS]@db.example",
            security.redact_text("mysql://user:password@db.example"),
        )
        self.assertEqual(
            "[REDACTED_SECRET]",
            security.redact_text("-----BEGIN PRIVATE KEY-----"),
        )
        self.assertEqual("abc", security.redact_text("a\u200bb\u200cc\u200d"))

    def test_sensitive_key_boundaries_and_nested_non_mapping_values(self):
        self.assertFalse(security._key_is_sensitive(""))
        self.assertTrue(security._key_is_sensitive("newSecret"))
        self.assertTrue(security._key_is_sensitive("private-key"))
        self.assertFalse(security._key_is_sensitive("displayName"))
        payload = security.redact_payload(
            {
                "nested": ["safe", 3, None],
                "tokenHash": "hidden",
                "constructor": "removed",
            }
        )
        self.assertEqual(["safe", 3, None], payload["nested"])
        self.assertEqual("[REDACTED_SECRET]", payload["tokenHash"])
        self.assertNotIn("constructor", payload)

    def test_firewall_accepts_clean_payload_and_scores_private_key(self):
        accepted = security.evaluate_memory_firewall({"body": "ordinary note"})
        self.assertEqual("accepted", accepted["decision"])
        self.assertFalse(accepted["valuesRedacted"])

        private_key = security.evaluate_memory_firewall(
            {"body": "-----BEGIN PRIVATE KEY-----"}
        )
        self.assertEqual("review_required", private_key["decision"])
        self.assertIn("private_key", private_key["detectedThreats"])
        self.assertFalse(private_key["rawPrivatePayloadStored"])

    def test_firewall_covers_script_and_prototype_markers_and_scalar_text(self):
        self.assertEqual("17", security._all_text(17))
        script = security.evaluate_memory_firewall({"body": "javascript:alert(1)"})
        self.assertEqual("review_required", script["decision"])
        self.assertIn("script_marker", script["detectedThreats"])
        polluted = security.evaluate_memory_firewall({"constructor": {"prototype": {}}})
        self.assertEqual("review_required", polluted["decision"])
        self.assertIn("prototype_pollution_marker", polluted["detectedThreats"])


if __name__ == "__main__":
    unittest.main()
