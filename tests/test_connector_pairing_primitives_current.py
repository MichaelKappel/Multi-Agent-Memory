"""Current pure-policy coverage for connector pairing primitives.

These checks complement the storage/API matrix with deterministic tests for
the shared cryptographic and validation boundaries.
"""

from __future__ import annotations

import datetime
import pickle
import unittest
from unittest import mock

from memoryendpoints import connector_pairing as pairing


PEPPER = b"synthetic-connector-pepper-0123456789"
DIGEST = "sha256-v1:" + ("a" * 64)
IDEMPOTENCY = "connector-primitive-retry-0001"


class ConnectorPairingPrimitivesCurrentTests(unittest.TestCase):
    def test_remaining_policy_helpers_reject_malformed_and_cross_context_inputs(self):
        valid_state = pairing.generate_state()
        valid_code = pairing.derive_authorization_code(
            PEPPER, "code-primitive-2", DIGEST, DIGEST
        )
        valid_proof = pairing.derive_pairing_request_proof(
            PEPPER, "request-primitive-2", DIGEST, DIGEST
        )
        state_verifier = pairing.pairing_state_verifier(valid_state, PEPPER, DIGEST)
        code_verifier = pairing.authorization_code_verifier(valid_code, PEPPER, DIGEST)

        self.assertEqual(
            pairing.REGISTERED_CUSTOM_REDIRECT_URI,
            pairing.validate_redirect_uri(pairing.REGISTERED_CUSTOM_REDIRECT_URI),
        )
        self.assertEqual(
            pairing.REGISTERED_CUSTOM_REDIRECT_URI,
            pairing.build_wake_up_url(pairing.REGISTERED_CUSTOM_REDIRECT_URI),
        )
        self.assertEqual("code-primitive-2", pairing.parse_authorization_code(valid_code))
        self.assertEqual("request-primitive-2", pairing.parse_pairing_request_proof(valid_proof))

        with self.assertRaises(pairing.PairingPolicyError):
            pairing._validate_unpadded_b64url_256("A" * 42, "invalid_pkce")
        with mock.patch.object(
            pairing.base64, "urlsafe_b64decode", side_effect=ValueError("bad base64")
        ):
            with self.assertRaises(pairing.PairingPolicyError):
                pairing._validate_unpadded_b64url_256("A" * 43, "invalid_pkce")
        for function, args in (
            (pairing._validate_public_id, ("bad",)),
            (pairing.validate_service_root, ("https://memoryendpoints.com:bad",)),
            (pairing.validate_redirect_uri, ("http://127.0.0.1:bad/memoryendpoints/callback",)),
            (pairing.validate_redirect_uri, (pairing.REGISTERED_CUSTOM_REDIRECT_URI, ("other",))),
            (pairing.normalize_company_agent_name, (None,)),
            (pairing.normalize_company_agent_name, ("a",)),
            (pairing.normalize_company_agent_name, ("ümlaut",)),
            (pairing.normalize_connector_agent_name, (None,)),
            (pairing.validate_requested_scopes, (None,)),
            (pairing.validate_state, (None,)),
            (pairing.validate_authorization_code, ("bad",)),
            (pairing.validate_pairing_request_proof, ("bad",)),
            (pairing.validate_public_request_ref, ("bad",)),
            (pairing.build_authorization_url, ("bad",)),
        ):
            with self.subTest(function=function.__name__, args=args):
                with self.assertRaises(pairing.PairingPolicyError):
                    function(*args)

        for function, args in (
            (pairing.derive_authorization_code, (PEPPER, "bad", DIGEST, DIGEST)),
            (pairing.derive_authorization_code, (PEPPER, "code-primitive-2", "bad", DIGEST)),
            (pairing.derive_pairing_request_proof, (PEPPER, "bad", DIGEST, DIGEST)),
            (pairing._connector_secret_value, ("credential-primitive-2", b"short")),
            (pairing.connector_secret_verifier, ("secret", PEPPER, "bad")),
            (pairing.derive_pending_connector_secret, (PEPPER, "bad", DIGEST, DIGEST)),
            (pairing.idempotency_digest, ("short", DIGEST, PEPPER)),
            (pairing.idempotency_digest, (IDEMPOTENCY, "bad", PEPPER)),
        ):
            with self.subTest(function=function.__name__, args=args):
                with self.assertRaises(pairing.PairingPolicyError):
                    function(*args)

        self.assertFalse(pairing.verify_authorization_code_binding(valid_code, "bad", PEPPER, DIGEST))
        self.assertTrue(
            pairing.verify_authorization_code_binding(
                valid_code, code_verifier, PEPPER, DIGEST
            )
        )
        self.assertFalse(pairing.verify_pairing_state(valid_state, state_verifier, PEPPER, "bad"))
        with self.assertRaises(pairing.PairingPolicyError):
            pairing._hmac_message("pairing_state", "\ud800")
        with self.assertRaises(pairing.PairingPolicyError):
            pairing._scope_bound_verifier("value", PEPPER, "pairing_state", "bad")

        with self.assertRaises(pairing.PairingPolicyError):
            pairing._canonical_json_value(float("nan"))
        with self.assertRaises(pairing.PairingPolicyError):
            pairing._canonical_json_value(object())
        with self.assertRaises(pairing.PairingPolicyError):
            pairing.exact_request_digest("PATCH", "/api/test", {})
        with self.assertRaises(pairing.PairingPolicyError):
            pairing.exact_request_digest("GET", "/api/test", "x" * (pairing.MAX_CANONICAL_REQUEST_BYTES + 1))
        with self.assertRaises(pairing.PairingPolicyError):
            pairing.classify_one_use_replay(
                DIGEST, pairing.idempotency_digest(IDEMPOTENCY, DIGEST, PEPPER),
                stored_request_digest=DIGEST, consumed=False
            )
        with self.assertRaises(pairing.PairingPolicyError):
            pairing.classify_one_use_replay(
                DIGEST, pairing.idempotency_digest(IDEMPOTENCY, DIGEST, PEPPER),
                stored_request_digest="bad", stored_idempotency_verifier="bad", consumed=True
            )
        with self.assertRaises(pairing.PairingPolicyError):
            pairing.expires_at(datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc), 1)
        with self.assertRaises(pairing.PairingPolicyError):
            pairing.is_expired(valid_state, datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc))

    def test_issuer_redirect_identity_and_scope_boundaries(self):
        self.assertEqual(pairing.ISSUER, pairing.validate_service_root("https://memoryendpoints.com/"))
        self.assertEqual(
            "http://127.0.0.1:53682/memoryendpoints/callback",
            pairing.validate_redirect_uri("http://127.0.0.1:53682/memoryendpoints/callback"),
        )
        self.assertEqual(pairing.CLIENT_ID, pairing.validate_client_id(pairing.CLIENT_ID))
        self.assertEqual("alpha-agent", pairing.normalize_company_agent_name("  Alpha-Agent "))
        self.assertEqual(pairing.CANONICAL_AGENT_ID, pairing.normalize_connector_agent_name(pairing.CANONICAL_AGENT_ID))
        self.assertEqual(pairing.V1_REQUESTED_SCOPES, pairing.validate_requested_scopes(list(pairing.V1_REQUESTED_SCOPES)))
        self.assertEqual(pairing.V1_REQUESTED_SCOPES, pairing.validate_persisted_connector_scope(list(pairing.V1_REQUESTED_SCOPES), pairing.connector_scope_digest()))
        self.assertEqual(len(pairing.connector_scope_impacts()), len(pairing.V1_REQUESTED_SCOPES))

        invalid = (
            (pairing.validate_service_root, ("https://memoryendpoints.com:443",), "invalid_service_root"),
            (pairing.validate_service_root, ("https://evil.example",), "invalid_service_root"),
            (pairing.validate_redirect_uri, ("https://127.0.0.1/callback",), "invalid_redirect_uri"),
            (pairing.validate_redirect_uri, ("http://127.0.0.1:53682/wrong",), "invalid_redirect_uri"),
            (pairing.validate_client_id, ("wrong-client",), "invalid_client"),
            (pairing.normalize_company_agent_name, ("ümlaut",), "invalid_agent_identity"),
            (pairing.normalize_connector_agent_name, ("other-agent",), "invalid_agent_identity"),
            (pairing.validate_requested_scopes, (list(pairing.V1_REQUESTED_SCOPES) + ["admin"],), "connector_scopes_invalid"),
            (pairing.validate_persisted_connector_scope, (list(pairing.V1_REQUESTED_SCOPES), DIGEST), "connector_scopes_invalid"),
        )
        for function, args, code in invalid:
            with self.subTest(function=function.__name__, code=code):
                with self.assertRaises(pairing.PairingPolicyError) as error:
                    function(*args)
                self.assertEqual(code, error.exception.code)

    def test_pkce_hmac_derivation_and_secret_projection_are_exact(self):
        verifier = "v" * pairing.PKCE_VERIFIER_MIN_LENGTH
        challenge = pairing.pkce_s256_challenge(verifier)
        self.assertTrue(pairing.validate_pkce_s256(verifier, challenge))
        with self.assertRaises(pairing.PairingPolicyError):
            pairing.validate_pkce_s256("w" * len(verifier), challenge)

        code = pairing.derive_authorization_code(PEPPER, "code-primitive-1", DIGEST, DIGEST)
        proof = pairing.derive_pairing_request_proof(PEPPER, "request-primitive-1", DIGEST, DIGEST)
        secret = pairing.generate_connector_secret(PEPPER, DIGEST, "credential-primitive-1")
        pending = pairing.derive_pending_connector_secret(PEPPER, "credential-primitive-1", DIGEST, DIGEST)
        for value, validator in (
            (code, pairing.validate_authorization_code),
            (proof, pairing.validate_pairing_request_proof),
        ):
            self.assertEqual(value, validator(value))
        self.assertNotEqual(secret.reveal(), pending.reveal())
        self.assertTrue(pairing.verify_connector_secret(secret.reveal(), secret.persistable_state()["credentialVerifier"], PEPPER, DIGEST))
        self.assertFalse(pairing.verify_connector_secret(secret.reveal(), "bad", PEPPER, DIGEST))
        self.assertEqual("[REDACTED]", str(secret))
        self.assertIn("secret=[REDACTED]", repr(secret))
        self.assertEqual(pending.public_id, secret.public_id)
        with self.assertRaises(TypeError):
            pickle.dumps(secret)

    def test_connector_validation_and_context_bound_verifiers_cover_rejection_edges(self):
        self.assertEqual(PEPPER, pairing._validate_pepper(bytearray(PEPPER)))
        for candidate in (b"short", b"x" * (pairing.MAX_PEPPER_BYTES + 1), "not-bytes"):
            with self.subTest(candidate=type(candidate).__name__):
                with self.assertRaises(pairing.PairingPolicyError):
                    pairing._validate_pepper(candidate)
        state = pairing.generate_state()
        self.assertEqual(state, pairing.validate_state(state))
        self.assertEqual(state, pairing.validate_state(state))
        with self.assertRaises(pairing.PairingPolicyError):
            pairing.validate_state("short")
        with self.assertRaises(pairing.PairingPolicyError):
            pairing.build_wake_up_url("https://evil.example/callback")

        pairing_request = pairing.derive_pairing_request_proof(
            PEPPER, "request-primitive-1", DIGEST, DIGEST
        )
        verifier = pairing.pairing_request_proof_verifier(
            pairing_request, PEPPER, DIGEST
        )
        self.assertTrue(
            pairing.verify_pairing_request_proof(
                pairing_request, verifier, PEPPER, DIGEST
            )
        )
        self.assertFalse(
            pairing.verify_pairing_request_proof(
                "bad", verifier, PEPPER, DIGEST
            )
        )
        state_verifier = pairing.pairing_state_verifier(state, PEPPER, DIGEST)
        self.assertTrue(pairing.verify_pairing_state(state, state_verifier, PEPPER, DIGEST))
        self.assertFalse(pairing.verify_pairing_state(state, "bad", PEPPER, DIGEST))
        with self.assertRaises(pairing.PairingPolicyError):
            pairing._hmac_message("unknown", "value")
        with self.assertRaises(pairing.PairingPolicyError):
            pairing._hmac_message("pairing_state", "value\x00with-null")
        self.assertFalse(
            pairing.verify_contextual_hmac(
                "value", "bad", PEPPER, "pairing_state"
            )
        )
        self.assertTrue(
            pairing.verify_contextual_hmac(
                "value",
                pairing.contextual_hmac_verifier("value", PEPPER, "pairing_state"),
                PEPPER,
                "pairing_state",
            )
        )

        nested = None
        for _ in range(14):
            nested = [nested]
        with self.assertRaises(pairing.PairingPolicyError):
            pairing._canonical_json_value(nested)
        with self.assertRaises(pairing.PairingPolicyError):
            pairing._canonical_json_value({1: "invalid-key"})

    def test_replay_digest_and_time_state_machines_cover_each_outcome(self):
        idempotency_verifier = pairing.idempotency_digest(IDEMPOTENCY, DIGEST, PEPPER)
        self.assertTrue(pairing.validate_idempotency_key(IDEMPOTENCY))
        self.assertEqual(
            pairing.ReplayDecision.FIRST_USE,
            pairing.classify_one_use_replay(DIGEST, idempotency_verifier),
        )
        self.assertEqual(
            pairing.ReplayDecision.EXACT_RETRY,
            pairing.classify_one_use_replay(DIGEST, idempotency_verifier, DIGEST, idempotency_verifier, consumed=True),
        )
        self.assertEqual(
            pairing.ReplayDecision.REPLAY_REJECTED,
            pairing.classify_one_use_replay(DIGEST, idempotency_verifier, DIGEST, "hmac-sha256-v1:" + ("b" * 64), consumed=True),
        )
        self.assertEqual(
            pairing.ReplayDecision.EXPIRED,
            pairing.classify_one_use_replay(DIGEST, idempotency_verifier, expired=True),
        )
        with self.assertRaises(pairing.PairingPolicyError):
            pairing.classify_one_use_replay(DIGEST, idempotency_verifier, "bad", idempotency_verifier, consumed=True)
        now = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        expiry = pairing.expires_at(now, pairing.PAIRING_REQUEST_TTL_SECONDS)
        self.assertFalse(pairing.is_expired(expiry, now))
        self.assertTrue(pairing.is_expired(expiry, expiry))
        with self.assertRaises(pairing.PairingPolicyError):
            pairing.expires_at(now, 1)
        with self.assertRaises(pairing.PairingPolicyError):
            pairing.is_expired(expiry, datetime.datetime(2026, 1, 1))

    def test_public_error_and_receipt_envelopes_are_fixed_and_non_reflective(self):
        error = pairing.safe_error("rate_limited", retry_after_seconds=30)
        self.assertFalse(error["ok"])
        self.assertEqual(30, error["error"]["retryAfterSeconds"])
        self.assertTrue(error["error"]["retryable"])
        fallback = pairing.safe_error("attacker-controlled-code")
        self.assertEqual("service_error", fallback["error"]["code"])
        self.assertFalse(fallback["rawCredentialExposed"])
        for args in (
            ("service_error", 1),
            ("rate_limited", 0),
            ("rate_limited", 3601),
        ):
            with self.subTest(args=args):
                with self.assertRaises(pairing.PairingPolicyError):
                    pairing.safe_error(*args)
        receipt = pairing.safe_receipt(
            "rotate", "rotated", "receipt-1", idempotent_replay=True
        )
        self.assertTrue(receipt["ok"])
        self.assertTrue(receipt["receipt"]["idempotentReplay"])
        self.assertFalse(receipt["receipt"]["rawCredentialExposed"])
        for args in (
            ("unknown", "active", "receipt-1"),
            ("verify", "unknown", "receipt-1"),
            ("verify", "verified", "short"),
        ):
            with self.subTest(args=args):
                with self.assertRaises(pairing.PairingPolicyError):
                    pairing.safe_receipt(*args)

    def test_canonical_request_and_public_discovery_are_bounded(self):
        digest = pairing.exact_request_digest("post", "/api/test", {"b": 2, "a": [True, None]})
        self.assertRegex(digest, r"^sha256-v1:[a-f0-9]{64}$")
        public_ref = pairing.generate_public_request_ref()
        self.assertEqual(public_ref, pairing.validate_public_request_ref(public_ref))
        self.assertIn(public_ref, pairing.build_authorization_url(public_ref))
        document = pairing.build_discovery_document()
        self.assertEqual(pairing.SCHEMA, document["schema"])
        self.assertLessEqual(len(__import__("json").dumps(document).encode("utf-8")), pairing.MAX_DISCOVERY_RESPONSE_BYTES)
        for function, args in (
            (pairing.exact_request_digest, ("PATCH", "/api/test", {})),
            (pairing.exact_request_digest, ("GET", "//bad", {})),
            (pairing.exact_request_digest, ("GET", "/api/test?x=1", {})),
            (pairing.validate_idempotency_key, ("short",)),
            (pairing.validate_public_request_ref, ("pairref_bad",)),
        ):
            with self.subTest(function=function.__name__):
                with self.assertRaises(pairing.PairingPolicyError):
                    function(*args)


if __name__ == "__main__":
    unittest.main()
