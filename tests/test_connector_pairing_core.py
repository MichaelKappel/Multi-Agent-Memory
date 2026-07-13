import datetime
import hashlib
import json
import pickle
import re
import secrets
import unittest
from urllib.parse import urlsplit

from memoryendpoints.connector_pairing import (
    AUTHORIZATION_CODE_CLAIM_PATH,
    AUTHORIZATION_CODE_TTL_SECONDS,
    AUTHORIZE_PATH,
    CANONICAL_AGENT_ID,
    CLIENT_ID,
    ISSUER,
    MAX_DISCOVERY_RESPONSE_BYTES,
    MAX_JSON_REQUEST_BYTES,
    PAIRING_REQUEST_TTL_SECONDS,
    PENDING_ACTIVATION_TTL_SECONDS,
    PUBLIC_REQUEST_REF_PATTERN,
    RATE_LIMIT_POLICIES,
    REGISTERED_CUSTOM_REDIRECT_URI,
    SCHEMA,
    V1_REQUESTED_SCOPES,
    PairingPolicyError,
    authorization_code_verifier,
    build_authorization_url,
    build_discovery_document,
    build_wake_up_url,
    connector_scope_digest,
    connector_scope_impacts,
    derive_authorization_code,
    derive_pairing_request_proof,
    derive_pending_connector_secret,
    exact_request_digest,
    expires_at,
    generate_connector_credential_id,
    generate_connector_secret,
    generate_public_request_ref,
    generate_state,
    is_expired,
    normalize_connector_agent_name,
    pairing_request_proof_verifier,
    pairing_state_verifier,
    parse_authorization_code,
    parse_pairing_request_proof,
    pkce_s256_challenge,
    validate_authorization_code,
    validate_client_id,
    validate_pairing_request_proof,
    validate_persisted_connector_scope,
    validate_pkce_s256,
    validate_public_request_ref,
    validate_redirect_uri,
    validate_requested_scopes,
    validate_service_root,
    validate_state,
    verify_authorization_code_binding,
    verify_connector_secret,
    verify_pairing_request_proof,
    verify_pairing_state,
)


PEPPER = b"connector-pairing-test-pepper-v1--not-production-material"
OTHER_PEPPER = b"connector-pairing-test-pepper-v1--different-test-material"


def _digest(label):
    return "sha256-v1:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


class ConnectorPairingTransportPolicyTests(unittest.TestCase):
    def test_service_root_is_exact_https_issuer(self):
        self.assertEqual(ISSUER, validate_service_root(ISSUER))
        self.assertEqual(ISSUER, validate_service_root(ISSUER + "/"))
        for value in (
            "http://memoryendpoints.com",
            "https://MEMORYENDPOINTS.com",
            "https://memoryendpoints.com:443",
            "https://user@memoryendpoints.com",
            "https://memoryendpoints.com/path",
            "https://memoryendpoints.com/?query=1",
            "https://memoryendpoints.com/#fragment",
        ):
            with self.subTest(value=value), self.assertRaisesRegex(
                PairingPolicyError, "invalid_service_root"
            ):
                validate_service_root(value)

    def test_redirect_validation_and_parameter_free_wakeup(self):
        callbacks = (
            REGISTERED_CUSTOM_REDIRECT_URI,
            "http://127.0.0.1:49152/memoryendpoints/callback",
        )
        for callback in callbacks:
            self.assertEqual(callback, validate_redirect_uri(callback))
            self.assertEqual(callback, build_wake_up_url(callback))
            parsed = urlsplit(build_wake_up_url(callback))
            self.assertEqual("", parsed.query)
            self.assertEqual("", parsed.fragment)
        for value in (
            REGISTERED_CUSTOM_REDIRECT_URI + "?code=forbidden",
            "http://localhost:49152/memoryendpoints/callback",
            "http://127.0.0.1:49152/other",
            "http://127.0.0.1:49152/memoryendpoints/callback#state",
        ):
            with self.subTest(value=value), self.assertRaises(PairingPolicyError):
                build_wake_up_url(value)

    def test_authorization_url_contains_only_public_non_authorizing_ref(self):
        public_ref = generate_public_request_ref()
        self.assertRegex(public_ref, "^" + PUBLIC_REQUEST_REF_PATTERN + "$")
        self.assertEqual(public_ref, validate_public_request_ref(public_ref))
        authorization_url = build_authorization_url(public_ref)
        parsed = urlsplit(authorization_url)
        self.assertEqual(ISSUER, "%s://%s" % (parsed.scheme, parsed.netloc))
        self.assertEqual(AUTHORIZE_PATH + "/" + public_ref, parsed.path)
        self.assertEqual("", parsed.query)
        self.assertEqual("", parsed.fragment)
        for invalid in ("", "pairref_short", public_ref + "?proof=bad", "pairproof_" + public_ref):
            with self.subTest(invalid=invalid), self.assertRaises(PairingPolicyError):
                validate_public_request_ref(invalid)


class ConnectorScopeAndIdentityTests(unittest.TestCase):
    def test_v1_agent_identity_is_byte_for_byte_exact(self):
        self.assertEqual(CANONICAL_AGENT_ID, normalize_connector_agent_name(CANONICAL_AGENT_ID))
        for value in (
            " LocalEndpoint-Agent ",
            "LocalEndpoint-Agent",
            "another-agent",
            "localendpoint_agent",
            "localendpoint agent",
        ):
            with self.subTest(value=value), self.assertRaisesRegex(
                PairingPolicyError, "invalid_agent_identity"
            ):
                normalize_connector_agent_name(value)

    def test_v1_scope_order_is_exact_and_digest_is_versioned(self):
        self.assertEqual(V1_REQUESTED_SCOPES, validate_requested_scopes(list(V1_REQUESTED_SCOPES)))
        expected = "sha256-v1:" + hashlib.sha256(
            json.dumps(
                {"schemaVersion": SCHEMA, "scopes": list(V1_REQUESTED_SCOPES)},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(expected, connector_scope_digest(V1_REQUESTED_SCOPES))
        self.assertRegex(expected, r"^sha256-v1:[a-f0-9]{64}$")
        self.assertEqual(list(V1_REQUESTED_SCOPES), [item["scope"] for item in connector_scope_impacts()])
        invalid = (
            list(reversed(V1_REQUESTED_SCOPES)),
            list(V1_REQUESTED_SCOPES[:-1]),
            list(V1_REQUESTED_SCOPES) + ["company:admin"],
            set(V1_REQUESTED_SCOPES),
            None,
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaisesRegex(
                PairingPolicyError, "connector_scopes_invalid"
            ):
                validate_requested_scopes(value)

    def test_persisted_scope_binding_is_independently_canonical(self):
        digest = connector_scope_digest()
        self.assertEqual(
            V1_REQUESTED_SCOPES,
            validate_persisted_connector_scope(list(V1_REQUESTED_SCOPES), digest),
        )
        for scopes, candidate_digest in (
            (list(V1_REQUESTED_SCOPES) + ["company:admin"], digest),
            (list(V1_REQUESTED_SCOPES), "sha256-v1:" + ("0" * 64)),
            (list(reversed(V1_REQUESTED_SCOPES)), digest),
            (list(V1_REQUESTED_SCOPES), None),
        ):
            with self.subTest(scopes=scopes, digest=candidate_digest), self.assertRaisesRegex(
                PairingPolicyError, "connector_scopes_invalid"
            ):
                validate_persisted_connector_scope(scopes, candidate_digest)


class ConnectorBodyCredentialTests(unittest.TestCase):
    def setUp(self):
        self.scope_digest = connector_scope_digest()
        self.request_digest = _digest("create-request")
        self.approval_digest = _digest("approve-request")
        self.exchange_digest = _digest("exchange-request")

    def test_pairing_proof_is_deterministic_body_only_and_scope_bound(self):
        request_id = "pairingrequest_12345678"
        proof = derive_pairing_request_proof(
            PEPPER, request_id, self.request_digest, self.scope_digest
        )
        self.assertEqual(request_id, parse_pairing_request_proof(proof))
        self.assertEqual(proof, validate_pairing_request_proof(proof))
        verifier = pairing_request_proof_verifier(proof, PEPPER, self.scope_digest)
        self.assertTrue(verify_pairing_request_proof(proof, verifier, PEPPER, self.scope_digest))
        self.assertFalse(verify_pairing_request_proof(proof, verifier, OTHER_PEPPER, self.scope_digest))
        changed_scope = "sha256-v1:" + ("0" * 64)
        self.assertFalse(verify_pairing_request_proof(proof, verifier, PEPPER, changed_scope))
        self.assertNotIn(proof, build_authorization_url(generate_public_request_ref()))

    def test_state_is_verified_without_raw_persistence(self):
        state = generate_state()
        self.assertEqual(state, validate_state(state))
        verifier = pairing_state_verifier(state, PEPPER, self.scope_digest)
        self.assertNotIn(state, verifier)
        self.assertTrue(verify_pairing_state(state, verifier, PEPPER, self.scope_digest))
        self.assertFalse(verify_pairing_state(generate_state(), verifier, PEPPER, self.scope_digest))

    def test_authorization_code_is_prefixed_deterministic_and_scope_bound(self):
        code_id = "paircode_12345678"
        code = derive_authorization_code(
            PEPPER, code_id, self.approval_digest, self.scope_digest
        )
        retry = derive_authorization_code(
            PEPPER, code_id, self.approval_digest, self.scope_digest
        )
        self.assertTrue(secrets.compare_digest(code, retry))
        self.assertEqual(code_id, parse_authorization_code(code))
        self.assertEqual(code, validate_authorization_code(code))
        verifier = authorization_code_verifier(code, PEPPER, self.scope_digest)
        self.assertTrue(verify_authorization_code_binding(code, verifier, PEPPER, self.scope_digest))
        self.assertFalse(verify_authorization_code_binding(code, verifier, OTHER_PEPPER, self.scope_digest))
        self.assertNotIn(code, build_wake_up_url(REGISTERED_CUSTOM_REDIRECT_URI))

    def test_pending_connector_secret_exact_retry_and_scope_binding(self):
        credential_id = generate_connector_credential_id()
        first = derive_pending_connector_secret(
            PEPPER, credential_id, self.exchange_digest, self.scope_digest
        )
        retry = derive_pending_connector_secret(
            PEPPER, credential_id, self.exchange_digest, self.scope_digest
        )
        raw = first.reveal()
        self.assertTrue(secrets.compare_digest(raw, retry.reveal()))
        self.assertTrue(
            verify_connector_secret(
                raw,
                first.persistable_state()["credentialVerifier"],
                PEPPER,
                self.scope_digest,
            )
        )
        self.assertNotIn(raw, json.dumps(first.persistable_state(), sort_keys=True))
        self.assertNotIn(raw, repr(first))
        with self.assertRaises(TypeError):
            pickle.dumps(first)

        fresh = generate_connector_secret(PEPPER, self.scope_digest)
        fresh_raw = fresh.reveal()
        self.assertTrue(
            verify_connector_secret(
                fresh_raw,
                fresh.persistable_state()["credentialVerifier"],
                PEPPER,
                self.scope_digest,
            )
        )

    def test_pkce_s256_is_required(self):
        verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        challenge = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
        self.assertEqual(challenge, pkce_s256_challenge(verifier))
        self.assertTrue(validate_pkce_s256(verifier, challenge))
        with self.assertRaisesRegex(PairingPolicyError, "invalid_pkce"):
            validate_pkce_s256("x" * 43, challenge)


class ConnectorDiscoveryAndExpiryTests(unittest.TestCase):
    def test_discovery_publishes_claim_not_callback_credentials(self):
        document = build_discovery_document()
        encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.assertLessEqual(len(encoded), MAX_DISCOVERY_RESPONSE_BYTES)
        self.assertEqual(SCHEMA, document["schemaVersion"])
        self.assertEqual(ISSUER + AUTHORIZATION_CODE_CLAIM_PATH, document["endpoints"]["authorizationCodeClaim"])
        self.assertEqual([], document["authorizationCode"]["callbackFields"])
        self.assertFalse(document["authorizationCode"]["callbackParametersAllowed"])
        self.assertEqual("body_only", document["authorizationCode"]["claimDelivery"])
        self.assertFalse(document["transport"]["credentialsInUrlsAllowed"])
        self.assertEqual(MAX_JSON_REQUEST_BYTES, document["transport"]["maximumJsonRequestBytes"])
        self.assertEqual(list(V1_REQUESTED_SCOPES), document["requestedScopes"])
        self.assertEqual(connector_scope_digest(), document["scopeDigest"])
        self.assertEqual(10, RATE_LIMIT_POLICIES["authorizationCodeClaim"]["limit"])
        self.assertEqual(600, RATE_LIMIT_POLICIES["authorizationCodeClaim"]["windowSeconds"])
        expected_allowed_operation_limits = {
            "selfRegistration": {
                "limit": 5,
                "windowSeconds": 600,
                "partition": "connector_credential",
            },
            "publicSafeSubmit": {
                "limit": 60,
                "windowSeconds": 60,
                "partition": "connector_credential",
            },
            "search": {
                "limit": 120,
                "windowSeconds": 60,
                "partition": "connector_credential",
            },
        }
        for bucket, policy in expected_allowed_operation_limits.items():
            self.assertEqual(policy, RATE_LIMIT_POLICIES[bucket])
            self.assertEqual(policy, document["rateLimits"][bucket])
        for endpoint in document["endpoints"].values():
            parsed = urlsplit(endpoint)
            self.assertEqual("memoryendpoints.com", parsed.netloc)
            self.assertEqual("", parsed.query)
            self.assertEqual("", parsed.fragment)
        lowered = encoded.lower()
        for forbidden in (b"workspaceid", b"companyid", b"connectorcredentialsecret"):
            self.assertNotIn(forbidden, lowered)

    def test_fixed_ttls_and_aware_expiry(self):
        now = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        for ttl in (
            PAIRING_REQUEST_TTL_SECONDS,
            AUTHORIZATION_CODE_TTL_SECONDS,
            PENDING_ACTIVATION_TTL_SECONDS,
        ):
            expiry = expires_at(now, ttl)
            self.assertFalse(is_expired(expiry, now))
            self.assertTrue(is_expired(expiry, expiry))
        with self.assertRaises(PairingPolicyError):
            expires_at(now, 1)

    def test_fixed_client_id(self):
        self.assertEqual(CLIENT_ID, validate_client_id(CLIENT_ID))
        for value in ("LocalEndpoint-Connect", "localendpoint", "", None):
            with self.subTest(value=value), self.assertRaises(PairingPolicyError):
                validate_client_id(value)


if __name__ == "__main__":
    unittest.main()
