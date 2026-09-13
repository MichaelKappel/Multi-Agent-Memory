"""Current, hermetic boundary coverage for the managed connector controller."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from memoryendpoints import managed_connection as managed
from tests.test_managed_connection_recovery import (
    AGENT_ID,
    AGENT_TOKEN,
    BASE_URL,
    COMPANY_ID,
    IDEMPOTENCY_KEY,
    INVITE_SECRET,
    PROFILE_ID,
    PROJECT_ID,
    PROTECTION_ID,
    SERVICE_INSTANCE_ID,
    VERIFIER_ID,
    WORKLOAD_IDENTITY_ID,
    WORKSPACE_ID,
    _protect,
    _unprotect,
)


class _Response:
    def __init__(self, status=200, payload=None, raw=None):
        self.status = status
        self._payload = payload
        self._raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size=-1):
        if self._raw is not None:
            return self._raw
        return json.dumps(self._payload).encode("utf-8")

    def close(self):
        return None


class ManagedConnectionPrimitivesCurrentTests(unittest.TestCase):
    def _protector(self):
        return managed.SecretProtector(
            PROTECTION_ID,
            _protect,
            _unprotect,
            workload_identity_id=WORKLOAD_IDENTITY_ID,
        )

    def _profile(self, ca_content=b"test-only-ca", **overrides):
        payload = {
            "schemaVersion": managed.MANAGED_PROFILE_SCHEMA,
            "profileId": PROFILE_ID,
            "profilePurpose": managed.MANAGED_PROFILE_PURPOSE,
            "clientKind": "concresca-service",
            "runtimeClass": managed.MANAGED_RUNTIME_CLASS_UNATTENDED_SERVICE,
            "enrollmentKind": managed.MANAGED_ENROLLMENT_KIND,
            "commonsFallback": managed.MANAGED_FALLBACK_POLICY,
            "identityFallback": managed.MANAGED_FALLBACK_POLICY,
            "baseUrl": BASE_URL,
            "agentId": AGENT_ID,
            "companyId": COMPANY_ID,
            "workspaceId": WORKSPACE_ID,
            "projectId": PROJECT_ID,
            "deviceId": "managed-device-001",
            "serviceInstanceId": SERVICE_INSTANCE_ID,
            "workloadIdentityId": WORKLOAD_IDENTITY_ID,
            "policyRevision": 1,
            "profileGeneration": 1,
            "trustMode": managed.MANAGED_TRUST_MODE,
            "caSha256": hashlib.sha256(ca_content).hexdigest(),
            "protectionId": PROTECTION_ID,
            "profileVerifierId": VERIFIER_ID,
        }
        payload.update(overrides)
        return payload

    def test_identity_origin_context_and_protector_validation_matrix(self):
        self.assertEqual("agent-name", managed._validate_agent_id(" Agent-Name "))
        self.assertEqual("profile-001", managed._validate_profile_id("PROFILE-001"))
        self.assertEqual("https://example.test", managed._validate_base_url("https://example.test/"))
        self.assertEqual("http://127.0.0.1:8080", managed._validate_base_url("http://127.0.0.1:8080/"))
        credential_path, pending_path = managed._credential_paths("/tmp", "a")
        self.assertEqual("a.json", credential_path.name)
        self.assertEqual(".a.pending.json", pending_path.name)
        self.assertEqual(".local-secrets", credential_path.parent.parent.name)

        invalid = (
            (managed._validate_agent_id, (None,)),
            (managed._validate_agent_id, ("ab",)),
            (managed._validate_agent_id, ("bad name",)),
            (managed._validate_profile_id, (None,)),
            (managed._validate_profile_id, ("short",)),
            (managed._validate_base_url, ("http://example.test",)),
            (managed._validate_base_url, ("https://example.test/path",)),
            (managed._validate_base_url, ("https://user:pass@example.test",)),
            (managed._validate_base_url, ("https://example.test?secret=1",)),
            (managed._validate_base_url, ("https://example.test:bad",)),
            (managed._validate_bound_id, ("bad/id", "workspace")),
            (managed._validate_controller_key, ("short",)),
        )
        for function, args in invalid:
            with self.subTest(function=function.__name__, args=args):
                with self.assertRaises((managed.OnboardingError, ValueError)):
                    function(*args)
        self.assertIsNone(managed._validate_bound_id(None, "project", allow_none=True))

        with self.assertRaises(managed.OnboardingError):
            managed._secret_protector(self._protector(), protect_secret=lambda value: value)
        with self.assertRaises(managed.OnboardingError):
            managed._secret_protector(object())

    def test_controller_state_and_public_result_phase_matrices_are_closed(self):
        digest = "a" * 64
        base = {
            "schemaVersion": managed.MANAGED_CONTROLLER_STATE_SCHEMA,
            "profileId": PROFILE_ID,
            "serviceInstanceId": SERVICE_INSTANCE_ID,
            "profileGeneration": 1,
            "policyRevision": 1,
            "activeProfileDigest": digest,
            "activeTrustSha256": "b" * 64,
            "maxAttempts": 3,
            "quarantined": False,
        }
        states = (
            dict(base, phase="pending", attemptCount=0, attemptLeaseExpiresAtEpoch=None, nextAttemptAtEpoch=None, lastFailureCode=None, operationDigest=None),
            dict(base, phase="connecting", attemptCount=1, attemptLeaseExpiresAtEpoch=100, nextAttemptAtEpoch=None, lastFailureCode=None, operationDigest=digest),
            dict(base, phase="retry_wait", attemptCount=1, attemptLeaseExpiresAtEpoch=None, nextAttemptAtEpoch=100, lastFailureCode="transport_unavailable", operationDigest=digest),
            dict(base, phase="active", attemptCount=0, attemptLeaseExpiresAtEpoch=None, nextAttemptAtEpoch=None, lastFailureCode=None, operationDigest=digest),
            dict(base, phase="quarantined", attemptCount=1, attemptLeaseExpiresAtEpoch=None, nextAttemptAtEpoch=None, lastFailureCode="profile_invalid", operationDigest=digest, quarantined=True),
            dict(base, phase="halted", attemptCount=1, attemptLeaseExpiresAtEpoch=None, nextAttemptAtEpoch=None, lastFailureCode="halted", operationDigest=digest),
        )
        for state in states:
            with self.subTest(phase=state["phase"]):
                self.assertEqual(state, managed._validate_controller_state(state))
        with self.assertRaises(managed.OnboardingError):
            managed._validate_controller_state(dict(states[1], attemptCount=0))
        with self.assertRaises(managed.OnboardingError):
            managed._validate_controller_state(dict(states[0], quarantined=True))

        success = managed._public_result("verified_existing", AGENT_ID)
        self.assertEqual(success, managed.parse_managed_connection_result(success))
        failure = managed._public_error_result(
            managed.OnboardingError(
                "transport_unavailable",
                "safe",
                "retry_with_bounded_backoff",
                retryable=True,
                retry_after_seconds=2,
            )
        )
        self.assertEqual(failure, managed.parse_managed_connection_result(failure))
        for mutation in (
            {"valuesRedacted": False},
            {"controllerAction": "none", "retryable": True},
            {"error": ""},
        ):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                managed.parse_managed_connection_result(dict(failure, **mutation))

    def test_profile_and_credential_validation_reject_binding_drift(self):
        ca = b"test-only-ca"
        verifier = lambda _identifier, _payload: True
        profile = managed._validate_managed_profile_payload(
            self._profile(ca), profile_verifier=verifier
        )
        self.assertEqual(AGENT_ID, profile["agentId"])
        self.assertRegex(profile["profileBinding"], r"^[a-f0-9]{64}$")
        protector = self._protector()
        credential = managed._credential_document(
            BASE_URL,
            COMPANY_ID,
            WORKSPACE_ID,
            PROJECT_ID,
            AGENT_ID,
            AGENT_TOKEN,
            PROFILE_ID,
            profile["profileBinding"],
            protector=protector,
        )
        validated = managed._validated_credential_document(
            credential, BASE_URL, AGENT_ID, PROFILE_ID, profile["profileBinding"], protector
        )
        self.assertEqual(AGENT_TOKEN, validated["agentTokenSecret"])

        profile_mutations = (
            {"profilePurpose": "other"},
            {"runtimeClass": managed.MANAGED_RUNTIME_CLASS_UNATTENDED_SERVICE, "projectId": None},
            {"commonsFallback": "allowed"},
            {"policyRevision": 0},
            {"trustMode": "system"},
            {"caSha256": "bad"},
            {"profileVerifierId": "protected-state-binding"},
        )
        for mutation in profile_mutations:
            with self.subTest(mutation=mutation), self.assertRaises(managed.OnboardingError):
                managed._validate_managed_profile_payload(
                    dict(self._profile(ca), **mutation), profile_verifier=verifier
                )
        for mutation in (
            {"baseUrl": "https://other.test"},
            {"profileBinding": "c" * 64},
            {"agentId": "other-agent"},
            {"credentialProtection": "other-protection"},
            {"protectedAgentToken": _protect("not-a-governed-token", PROFILE_ID, AGENT_ID, profile["profileBinding"])},
        ):
            with self.subTest(mutation=mutation), self.assertRaises(managed.OnboardingError):
                managed._validated_credential_document(
                    dict(credential, **mutation), BASE_URL, AGENT_ID, PROFILE_ID, profile["profileBinding"], protector
                )

    def test_invitation_sources_and_transport_response_boundaries_are_typed(self):
        valid_url = BASE_URL + "/api/matm/access/invites/redeem#invite=" + INVITE_SECRET
        valid_json = json.dumps({"agentId": AGENT_ID, "baseUrl": BASE_URL, "inviteSecret": INVITE_SECRET})
        self.assertEqual(INVITE_SECRET, managed._extract_invite_secret(INVITE_SECRET, BASE_URL, AGENT_ID))
        self.assertEqual(INVITE_SECRET, managed._extract_invite_secret(valid_url, BASE_URL, AGENT_ID))
        self.assertEqual(INVITE_SECRET, managed._extract_invite_secret(valid_json, BASE_URL, AGENT_ID))
        invalid = (
            "",
            "[]",
            "{bad",
            json.dumps({"agentId": "other-agent", "inviteSecret": INVITE_SECRET}),
            json.dumps({"baseUrl": "https://other.test", "inviteSecret": INVITE_SECRET}),
            json.dumps({"inviteSecret": 7}),
            BASE_URL + "#wrong=" + INVITE_SECRET,
            BASE_URL + "#invite=" + "bad",
        )
        for value in invalid:
            with self.subTest(value=value[:32]), self.assertRaises(managed.OnboardingError):
                managed._extract_invite_secret(value, BASE_URL, AGENT_ID)

        with self.assertRaises(managed.OnboardingError):
            managed._read_invite_source(None, "MISSING_INVITE", {}, BASE_URL, AGENT_ID)
        with self.assertRaises(managed.OnboardingError):
            managed._read_invite_source("invite.json", "INVITE", {"INVITE": INVITE_SECRET}, BASE_URL, AGENT_ID)

        with patch.object(managed.ssl, "create_default_context", return_value="default") as create_context:
            self.assertEqual("default", managed._ssl_context(BASE_URL))
            self.assertIsNone(managed._ssl_context("http://localhost"))
            create_context.assert_called_once_with()
        with self.assertRaises(managed.OnboardingError):
            managed._ssl_context(BASE_URL, ca_bundle="bundle.pem", ca_content=b"ca")
        with self.assertRaises(managed.OnboardingError):
            managed._ssl_context(BASE_URL, ca_content=b"")

        self.assertEqual({"ok": True}, managed._read_json_response(_Response(payload={"ok": True})))
        for raw in (b"[]", b"not-json", b"\xff"):
            with self.subTest(raw=raw), self.assertRaises(managed._OutcomeUnknown):
                managed._read_json_response(_Response(raw=raw))

        def opener(request, **kwargs):
            self.assertEqual("GET", request.method)
            self.assertEqual("Bearer " + AGENT_TOKEN, request.get_header("Authorization"))
            self.assertEqual(30, kwargs["timeout"])
            return _Response(payload={"ok": True})

        status, payload = managed._request_json(BASE_URL, managed.ME_ROUTE, "GET", None, AGENT_TOKEN, None, opener)
        self.assertEqual((200, {"ok": True}), (status, payload))
        with self.assertRaises(managed._OutcomeUnknown):
            managed._request_json(BASE_URL, managed.ME_ROUTE, "GET", None, None, None, lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("down")))
        error = HTTPError(BASE_URL + managed.ME_ROUTE, 503, "unavailable", {}, _Response(raw=b"bad"))
        self.assertEqual((503, {}), managed._request_json(BASE_URL, managed.ME_ROUTE, "GET", None, None, None, lambda *_args, **_kwargs: (_ for _ in ()).throw(error)))

    def test_controller_adapter_objects_and_public_error_defaults_are_closed(self):
        default_error = managed.OnboardingError("not safe", action="not-an-action")
        self.assertEqual("agent_onboarding_failed", default_error.code)
        self.assertEqual("halt_managed_connection_controller", default_error.action)
        self.assertEqual("recovery_required", default_error.state)
        retry = managed.OnboardingError("transport_unavailable", retryable=True, retry_after_seconds=0)
        self.assertEqual(30, retry.retry_after_seconds)
        self.assertEqual("retry_wait", retry.state)
        quarantined = managed.OnboardingError("profile_invalid", action="quarantine_identity")
        self.assertEqual("quarantined", quarantined.state)

        valid = self._protector()
        for args in (
            (None, valid.protect, valid.unprotect),
            ("bad/id", valid.protect, valid.unprotect),
            (PROTECTION_ID, None, valid.unprotect),
            (PROTECTION_ID, valid.protect, None),
            (PROTECTION_ID, valid.protect, valid.unprotect, "bad/id"),
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                managed.SecretProtector(*args)

        context = managed.ManagedServiceContext(
            client_kind="concresca-service",
            service_instance_id=SERVICE_INSTANCE_ID,
            workload_identity_id=WORKLOAD_IDENTITY_ID,
            project_id=PROJECT_ID,
            profile_verifier_id=VERIFIER_ID,
            recovery_authority_id="concresca-recovery-authority-v1",
        )
        self.assertEqual(context, managed.ManagedProfileLocator(lambda value: value).locate(context))
        with self.assertRaises(ValueError):
            managed.ManagedProfileLocator(None)
        for overrides in (
            {"runtime_class": "other"},
            {"max_attempts": 0},
            {"max_retry_seconds": 1},
            {"attempt_lease_seconds": 1},
            {"profile_verifier_id": "protected-state-binding"},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                values = dict(
                    client_kind=context.client_kind,
                    service_instance_id=context.service_instance_id,
                    workload_identity_id=context.workload_identity_id,
                    project_id=context.project_id,
                    profile_verifier_id=context.profile_verifier_id,
                    recovery_authority_id=context.recovery_authority_id,
                )
                values.update(overrides)
                managed.ManagedServiceContext(**values)

        verifier = managed.SignedProfileVerifier(
            VERIFIER_ID,
            lambda verifier_id, payload, actual: verifier_id == VERIFIER_ID and payload["ok"] and actual == context,
            lambda _verifier_id, _actual: 3,
        )
        self.assertTrue(verifier.verify({"ok": True}, context))
        self.assertEqual(3, verifier.minimum_generation(context))
        with self.assertRaises(ValueError):
            managed.SignedProfileVerifier("protected-state-binding", lambda *_args: True, lambda *_args: 1)
        with self.assertRaises(ValueError):
            managed.SignedProfileVerifier(VERIFIER_ID, None, lambda *_args: 1)
        with self.assertRaises(managed.OnboardingError):
            managed.SignedProfileVerifier(VERIFIER_ID, lambda *_args: True, lambda *_args: 0).minimum_generation(context)

        records = {"key": (2, {"phase": "active"})}
        cas = managed.DurableStateCAS(
            "durable-state-v1",
            lambda key: records[key],
            lambda key, revision, state: (key, revision, state),
        )
        self.assertEqual(records["key"], cas.read("key"))
        self.assertEqual(("key", 2, {"phase": "active"}), cas.compare_exchange("key", 2, records["key"][1]))
        with self.assertRaises(ValueError):
            managed.DurableStateCAS("bad/id", lambda _key: None, lambda *_args: None)
        recovery = managed.ManagedRecoveryAuthority("recovery-authority-v1", lambda request: request)
        self.assertEqual({"request": "value"}, recovery.reconcile({"request": "value"}))
        with self.assertRaises(ValueError):
            managed.ManagedRecoveryAuthority("bad/id", lambda _request: None)

    def test_file_state_and_private_local_artifact_boundaries_are_durable(self):
        digest = "a" * 64
        state = {
            "schemaVersion": managed.MANAGED_CONTROLLER_STATE_SCHEMA,
            "profileId": PROFILE_ID,
            "serviceInstanceId": SERVICE_INSTANCE_ID,
            "profileGeneration": 1,
            "policyRevision": 1,
            "activeProfileDigest": digest,
            "activeTrustSha256": "b" * 64,
            "phase": "pending",
            "attemptCount": 0,
            "maxAttempts": 3,
            "attemptLeaseExpiresAtEpoch": None,
            "nextAttemptAtEpoch": None,
            "lastFailureCode": None,
            "operationDigest": None,
            "quarantined": False,
        }
        key = "c" * 64
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "state.json"
            cas = managed.FileDurableStateCAS(path)
            self.assertEqual((0, None), cas.read(key))
            self.assertEqual(1, cas.compare_exchange(key, 0, state))
            self.assertEqual((1, state), cas.read(key))
            with self.assertRaises(managed.OnboardingError) as conflict:
                cas.compare_exchange(key, 0, state)
            self.assertEqual("managed_controller_state_conflict", conflict.exception.code)
            with self.assertRaises(ValueError):
                cas.compare_exchange(key, -1, state)

            managed._private_write(path, {"ok": True})
            self.assertEqual({"ok": True}, managed._read_private_json(path))
            binary = Path(root) / "support.bin"
            managed._private_write_bytes(binary, b"support")
            self.assertEqual(b"support", binary.read_bytes())
            pending = Path(root) / "pending.json"
            managed._private_write(pending, {"pending": True})
            promoted = Path(root) / "promoted.json"
            managed._promote_pending(pending, promoted)
            self.assertEqual({"pending": True}, managed._read_private_json(promoted))
            managed._private_write(promoted, {"existing": True})
            with self.assertRaises(managed.OnboardingError):
                managed._promote_pending(Path(root) / "missing.json", promoted)

            managed._private_write(path, ["not", "an", "object"])
            with self.assertRaises(managed.OnboardingError):
                managed._read_private_json(path)
            path.write_bytes(b"not-json")
            with self.assertRaises(managed.OnboardingError):
                managed._read_private_json(path)
            with patch.object(managed.os, "chmod", side_effect=OSError("test-only")):
                managed._private_write(path, {"chmod": "ignored"})
                managed._private_write_bytes(binary, b"chmod-ignored")

    def test_invitation_file_environment_and_profile_resolution_matrix(self):
        valid = json.dumps({"agentId": AGENT_ID, "baseUrl": BASE_URL, "inviteSecret": INVITE_SECRET})
        with tempfile.TemporaryDirectory() as root:
            invite = Path(root) / "invite.json"
            invite.write_text(valid, encoding="utf-8")
            self.assertEqual(
                INVITE_SECRET,
                managed._read_invite_source(str(invite), "INVITE", {}, BASE_URL, AGENT_ID),
            )
            self.assertEqual(
                INVITE_SECRET,
                managed._read_invite_source(None, "INVITE", {"INVITE": valid}, BASE_URL, AGENT_ID),
            )
            with self.assertRaises(managed.OnboardingError):
                managed._read_invite_source(str(invite), "INVITE", {"INVITE": valid}, BASE_URL, AGENT_ID)
            with self.assertRaises(managed.OnboardingError):
                managed._read_invite_source(str(Path(root) / "missing"), "INVITE", {}, BASE_URL, AGENT_ID)
            invite.write_bytes(b"\xff")
            with self.assertRaises(managed.OnboardingError):
                managed._read_invite_source(str(invite), "INVITE", {}, BASE_URL, AGENT_ID)
            invite.write_bytes(b"x" * (managed.MAX_LOCAL_JSON_BYTES + 1))
            with self.assertRaises(managed.OnboardingError):
                managed._read_invite_source(str(invite), "INVITE", {}, BASE_URL, AGENT_ID)

            first = Path(root) / "first.json"
            second = Path(root) / "second.json"
            first.write_text("{}", encoding="utf-8")
            with self.assertRaises(managed.OnboardingError) as missing:
                managed._resolve_managed_profile(candidates=(Path(root) / "none.json",))
            self.assertEqual("managed_profile_missing", missing.exception.code)
            self.assertEqual(first.resolve(), managed._resolve_managed_profile(candidates=(first,)))
            second.write_text("{}", encoding="utf-8")
            with self.assertRaises(managed.OnboardingError) as conflict:
                managed._resolve_managed_profile(candidates=(first, second))
            self.assertEqual("managed_profile_conflict", conflict.exception.code)


if __name__ == "__main__":
    unittest.main()
