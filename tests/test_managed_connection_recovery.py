import base64
import hashlib
import inspect
import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from memoryendpoints import managed_connection as managed


BASE_URL = "https://10.1.10.209:8088"
PROFILE_ID = "concresca-profile-001"
AGENT_ID = "concresca-service-agent"
COMPANY_ID = "company-test-boundary"
WORKSPACE_ID = "workspace-test-boundary"
PROJECT_ID = "project-test-boundary"
DEVICE_ID = "concresca-device-001"
SERVICE_INSTANCE_ID = "concresca-service-instance-001"
WORKLOAD_IDENTITY_ID = "concresca-service-account-001"
VERIFIER_ID = "concresca-fleet-signer-v1"
AUTHORITY_ID = "concresca-recovery-authority-v1"
PROTECTION_ID = "concresca-service-vault-v1"
INVITE_SECRET = "me_invite_v1.invite-" + ("a" * 20) + "." + ("b" * 43)
AGENT_TOKEN = "me_agent_v1.agenttoken-" + ("c" * 20) + "." + ("d" * 43)
IDEMPOTENCY_KEY = "e" * 43


def _protect(secret, profile_id, agent_id, profile_binding):
    return base64.b64encode(
        (profile_id + "\0" + agent_id + "\0" + profile_binding + "\0" + secret).encode(
            "utf-8"
        )
    ).decode("ascii")


def _unprotect(protected, profile_id, agent_id, profile_binding):
    decoded = base64.b64decode(protected).decode("utf-8")
    prefix = profile_id + "\0" + agent_id + "\0" + profile_binding + "\0"
    if not decoded.startswith(prefix):
        raise managed.OnboardingError(
            "credential_unavailable",
            "Protected state is not bound to this workload.",
            "quarantine_identity",
        )
    return decoded[len(prefix) :]


class _Response:
    def __init__(self, status, payload):
        self.status = status
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        return False

    def read(self, _size=-1):
        return json.dumps(self.payload).encode("utf-8")


class _MemoryCAS(managed.DurableStateCAS):
    def __init__(self):
        self.durability_id = "test-durable-state-v1"
        self.revision = 0
        self.state = None

    def read(self, _key):
        return self.revision, None if self.state is None else dict(self.state)

    def compare_exchange(self, _key, expected_revision, next_state):
        if expected_revision != self.revision:
            raise managed.OnboardingError(
                "managed_controller_state_conflict",
                "State changed concurrently.",
                "retry_with_bounded_backoff",
                retryable=True,
                retry_after_seconds=1,
            )
        self.revision += 1
        self.state = dict(next_state)
        return self.revision


class _Crash(BaseException):
    pass


def _file_cas_worker(path, key, state, ready, start, results):
    try:
        cas = managed.FileDurableStateCAS(path)
        ready.put(True)
        start.wait(10)
        revision = cas.compare_exchange(key, 0, state)
        results.put(("success", revision))
    except managed.OnboardingError as exc:
        results.put(("error", exc.code))
    except Exception:
        results.put(("error", "unexpected"))


class ManagedConnectionRecoveryTests(unittest.TestCase):
    def setUp(self):
        token = patch.object(managed, "_new_agent_token_secret", return_value=AGENT_TOKEN)
        key = patch.object(managed, "_new_idempotency_key", return_value=IDEMPOTENCY_KEY)
        tls = patch.object(managed.ssl, "create_default_context", return_value=object())
        token.start()
        key.start()
        tls.start()
        self.addCleanup(token.stop)
        self.addCleanup(key.stop)
        self.addCleanup(tls.stop)

    def _context(self, **overrides):
        values = {
            "client_kind": "concresca-service",
            "service_instance_id": SERVICE_INSTANCE_ID,
            "workload_identity_id": WORKLOAD_IDENTITY_ID,
            "project_id": PROJECT_ID,
            "profile_verifier_id": VERIFIER_ID,
            "recovery_authority_id": AUTHORITY_ID,
            "max_attempts": 3,
            "base_retry_seconds": 5,
            "max_retry_seconds": 30,
            "attempt_lease_seconds": 5,
        }
        values.update(overrides)
        return managed.ManagedServiceContext(**values)

    def _protector(self):
        return managed.SecretProtector(
            PROTECTION_ID,
            _protect,
            _unprotect,
            workload_identity_id=WORKLOAD_IDENTITY_ID,
        )

    def _profile(self, ca_content, **overrides):
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
            "deviceId": DEVICE_ID,
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

    def _install(self, root):
        ca_content = b"test-only-concresca-ca"
        profile_path = Path(root) / "managed" / managed.MANAGED_PROFILE_FILE
        verifier = managed.SignedProfileVerifier(
            VERIFIER_ID,
            lambda verifier_id, payload, context: True,
            lambda verifier_id, context: 1,
        )
        managed.provision_managed_connection(
            self._profile(ca_content),
            ca_content,
            INVITE_SECRET,
            profile_path,
            protector=self._protector(),
            profile_verifier=lambda verifier_id, payload: verifier.verify(
                payload, self._context()
            ),
        )
        return profile_path

    def _adapters(self, profile_path, state_cas=None, recovery=None):
        context = self._context()
        locator = managed.ManagedProfileLocator(lambda actual: profile_path)
        verifier = managed.SignedProfileVerifier(
            VERIFIER_ID,
            lambda verifier_id, payload, actual: (
                verifier_id == VERIFIER_ID
                and actual == context
                and payload["profileId"] == PROFILE_ID
            ),
            lambda verifier_id, actual: 1,
        )
        if recovery is None:
            recovery = lambda request: {
                "schemaVersion": managed.MANAGED_RECOVERY_DIRECTIVE_SCHEMA,
                "action": "quarantine_replace",
                "authorityId": AUTHORITY_ID,
                "contextDigest": request["contextDigest"],
                "stateRevision": request["stateRevision"],
                "operationDigest": request["operationDigest"],
                "failureCode": request["failureCode"],
                "requestDigest": request["requestDigest"],
                "reasonCode": "managed_identity_replacement_required",
                "retryAfterSeconds": None,
                "valuesRedacted": True,
            }
        state_cas = state_cas or _MemoryCAS()
        recovery_authority = managed.ManagedRecoveryAuthority(
            AUTHORITY_ID, recovery
        )
        managed.initialize_managed_controller_state(
            context,
            profile_document=json.loads(profile_path.read_text(encoding="utf-8")),
            verifier=verifier,
            state_cas=state_cas,
            recovery_authority=recovery_authority,
        )
        return {
            "context": context,
            "locator": locator,
            "protector": self._protector(),
            "verifier": verifier,
            "state_cas": state_cas,
            "recovery_authority": recovery_authority,
        }

    @staticmethod
    def _success_transport(request, timeout, context):
        if request.full_url.endswith(managed.REDEEM_ROUTE):
            return _Response(
                201,
                {
                    "ok": True,
                    "candidateCredentialAccepted": True,
                    "credentialReturnedOnce": False,
                    "idempotencySupported": True,
                    "replaySafe": True,
                    "rawCredentialExposed": False,
                    "principal": {
                        "credentialType": "agent_token",
                        "agentId": AGENT_ID,
                        "companyId": COMPANY_ID,
                        "workspaceId": WORKSPACE_ID,
                        "projectId": PROJECT_ID,
                        "credentialId": "agenttoken-" + ("c" * 20),
                    },
                    "onboarding": {
                        "agentId": AGENT_ID,
                        "workspaceId": WORKSPACE_ID,
                        "projectId": PROJECT_ID,
                    },
                },
            )
        return _Response(
            200,
            {
                "ok": True,
                "principal": {
                    "credentialType": "agent_token",
                    "agentId": AGENT_ID,
                    "companyId": COMPANY_ID,
                    "workspaceId": WORKSPACE_ID,
                    "projectId": PROJECT_ID,
                },
            },
        )

    def test_reconcile_connects_without_human_input_and_commits_active_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile_path = self._install(temporary)
            adapters = self._adapters(profile_path)
            result = managed.reconcile_managed_connection(
                **adapters, transport=self._success_transport, clock=lambda: 100
            )
            self.assertEqual("active", result["phase"])
            self.assertEqual("none", result["action"])
            self.assertFalse(result["humanInputRequired"])
            self.assertTrue(result["valuesRedacted"])
            self.assertEqual("active", adapters["state_cas"].state["phase"])
            self.assertEqual(0, adapters["state_cas"].state["attemptCount"])

    def test_no_human_entrypoint_has_no_path_secret_ca_or_environment_arguments(self):
        parameters = set(
            inspect.signature(managed.reconcile_managed_connection).parameters
        )
        self.assertEqual(
            {
                "context",
                "locator",
                "protector",
                "verifier",
                "state_cas",
                "recovery_authority",
                "transport",
                "clock",
            },
            parameters,
        )
        for forbidden in (
            "profile_path",
            "credential",
            "token",
            "invite",
            "ca_bundle",
            "environ",
            "project_root",
        ):
            self.assertNotIn(forbidden, parameters)
        with tempfile.TemporaryDirectory() as temporary:
            profile_path = self._install(temporary)
            adapters = self._adapters(profile_path)
            with patch.object(
                managed,
                "_managed_profile_candidates",
                side_effect=AssertionError("ambient discovery used"),
            ):
                result = managed.reconcile_managed_connection(
                    **adapters,
                    transport=self._success_transport,
                    clock=lambda: 100,
                )
            self.assertEqual("active", result["phase"])

    def test_wrong_service_binding_fails_closed_before_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile_path = self._install(temporary)
            adapters = self._adapters(profile_path)
            adapters["context"] = self._context(
                service_instance_id="different-service-instance"
            )
            calls = []
            result = managed.reconcile_managed_connection(
                **adapters,
                transport=lambda *args, **kwargs: calls.append(args),
                clock=lambda: 100,
            )
            self.assertEqual("quarantined", result["phase"])
            self.assertEqual("quarantine_replace", result["action"])
            self.assertEqual([], calls)

    def test_transient_failure_uses_durable_bounded_backoff_without_sleep(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile_path = self._install(temporary)
            state = _MemoryCAS()
            adapters = self._adapters(profile_path, state_cas=state)
            calls = []

            def unavailable(request, timeout, context):
                calls.append(request.full_url)
                raise URLError("test outage")

            first = managed.reconcile_managed_connection(
                **adapters, transport=unavailable, clock=lambda: 100
            )
            self.assertEqual("retry_wait", first["phase"])
            self.assertEqual(30, first["retryAfterSeconds"])
            self.assertEqual(130, first["nextAttemptAtEpoch"])
            before_due = managed.reconcile_managed_connection(
                **adapters, transport=unavailable, clock=lambda: 102
            )
            self.assertEqual(28, before_due["retryAfterSeconds"])
            self.assertEqual(1, len(calls))
            second = managed.reconcile_managed_connection(
                **adapters, transport=unavailable, clock=lambda: 130
            )
            self.assertEqual(30, second["retryAfterSeconds"])
            self.assertEqual(2, len(calls))

    def test_retry_exhaustion_requires_machine_recovery_and_never_loops(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile_path = self._install(temporary)
            state = _MemoryCAS()
            recovery_requests = []

            def recovery(request):
                recovery_requests.append(request)
                return {
                    "schemaVersion": managed.MANAGED_RECOVERY_DIRECTIVE_SCHEMA,
                    "action": "quarantine_replace",
                    "authorityId": AUTHORITY_ID,
                    "contextDigest": request["contextDigest"],
                    "stateRevision": request["stateRevision"],
                    "operationDigest": request["operationDigest"],
                    "failureCode": request["failureCode"],
                    "requestDigest": request["requestDigest"],
                    "reasonCode": "retry_budget_exhausted",
                    "retryAfterSeconds": None,
                    "valuesRedacted": True,
                }

            adapters = self._adapters(
                profile_path,
                state_cas=state,
                recovery=recovery,
            )
            calls = []

            def unavailable(request, timeout, context):
                calls.append(request.full_url)
                raise URLError("test outage")

            first = managed.reconcile_managed_connection(
                **adapters, transport=unavailable, clock=lambda: 100
            )
            second = managed.reconcile_managed_connection(
                **adapters,
                transport=unavailable,
                clock=lambda: first["nextAttemptAtEpoch"],
            )
            terminal = managed.reconcile_managed_connection(
                **adapters,
                transport=unavailable,
                clock=lambda: second["nextAttemptAtEpoch"],
            )
            replay = managed.reconcile_managed_connection(
                **adapters, transport=unavailable, clock=lambda: 1000
            )
            self.assertEqual(3, len(calls))
            self.assertEqual(1, len(recovery_requests))
            self.assertEqual("quarantined", terminal["phase"])
            self.assertEqual("quarantine_replace", terminal["action"])
            self.assertTrue(terminal["terminal"])
            self.assertEqual(terminal, replay)

    def test_profile_generation_drift_is_reconciled_before_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile_path = self._install(temporary)
            state = _MemoryCAS()
            adapters = self._adapters(profile_path, state_cas=state)
            active = managed.reconcile_managed_connection(
                **adapters, transport=self._success_transport, clock=lambda: 100
            )
            self.assertEqual("active", active["phase"])

            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["profileGeneration"] = 2
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            adapters["verifier"] = managed.SignedProfileVerifier(
                VERIFIER_ID,
                lambda verifier_id, payload, actual: True,
                lambda verifier_id, actual: 2,
            )
            calls = []
            result = managed.reconcile_managed_connection(
                **adapters,
                transport=lambda *args, **kwargs: calls.append(args),
                clock=lambda: 101,
            )
            self.assertEqual([], calls)
            self.assertEqual("quarantined", result["phase"])
            self.assertEqual("quarantine_replace", result["action"])

    def test_profile_drift_recovery_delay_is_durable_and_honored(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile_path = self._install(temporary)
            state = _MemoryCAS()
            recovery_calls = []

            def recovery(request):
                recovery_calls.append(request)
                return {
                    "schemaVersion": managed.MANAGED_RECOVERY_DIRECTIVE_SCHEMA,
                    "action": "retry_after",
                    "authorityId": AUTHORITY_ID,
                    "contextDigest": request["contextDigest"],
                    "stateRevision": request["stateRevision"],
                    "operationDigest": request["operationDigest"],
                    "failureCode": request["failureCode"],
                    "requestDigest": request["requestDigest"],
                    "reasonCode": "profile_rollout_pending",
                    "retryAfterSeconds": 600,
                    "valuesRedacted": True,
                }

            adapters = self._adapters(
                profile_path, state_cas=state, recovery=recovery
            )
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["profileGeneration"] = 2
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            adapters["verifier"] = managed.SignedProfileVerifier(
                VERIFIER_ID,
                lambda verifier_id, payload, actual: True,
                lambda verifier_id, actual: 2,
            )
            first = managed.reconcile_managed_connection(
                **adapters, transport=lambda *args: self.fail("network used"),
                clock=lambda: 100,
            )
            before_due = managed.reconcile_managed_connection(
                **adapters, transport=lambda *args: self.fail("network used"),
                clock=lambda: 101,
            )
            at_due = managed.reconcile_managed_connection(
                **adapters, transport=lambda *args: self.fail("network used"),
                clock=lambda: 700,
            )
            self.assertEqual(700, first["nextAttemptAtEpoch"], first)
            self.assertEqual(599, before_due["retryAfterSeconds"])
            self.assertEqual(1300, at_due["nextAttemptAtEpoch"])
            self.assertEqual(2, len(recovery_calls))
            self.assertEqual(2, state.state["attemptCount"])

    def test_workload_vault_loss_fails_closed_before_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile_path = self._install(temporary)
            adapters = self._adapters(profile_path)
            adapters["protector"] = managed.SecretProtector(
                PROTECTION_ID,
                _protect,
                lambda *args: (_ for _ in ()).throw(OSError("vault unavailable")),
                workload_identity_id=WORKLOAD_IDENTITY_ID,
            )
            calls = []
            result = managed.reconcile_managed_connection(
                **adapters,
                transport=lambda *args, **kwargs: calls.append(args),
                clock=lambda: 100,
            )
            self.assertEqual([], calls)
            self.assertEqual("quarantined", result["phase"])
            self.assertEqual("quarantine_replace", result["action"])
            self.assertFalse(result["humanInputRequired"])

    def test_crash_after_durable_intent_replays_same_enrollment_material(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile_path = self._install(temporary)
            state = _MemoryCAS()
            adapters = self._adapters(profile_path, state_cas=state)
            first_headers = []

            def crash(request, timeout, context):
                first_headers.append(dict(request.header_items()))
                raise _Crash()

            with self.assertRaises(_Crash):
                managed.reconcile_managed_connection(
                    **adapters, transport=crash, clock=lambda: 100
                )
            self.assertEqual("connecting", state.state["phase"])
            second_headers = []

            def succeed(request, timeout, context):
                second_headers.append(dict(request.header_items()))
                return self._success_transport(request, timeout, context)

            result = managed.reconcile_managed_connection(
                **adapters, transport=succeed, clock=lambda: 105
            )
            self.assertEqual("active", result["phase"])
            self.assertEqual(
                first_headers[0]["Idempotency-key"],
                second_headers[0]["Idempotency-key"],
            )

    def test_repeated_process_crashes_exhaust_the_durable_attempt_lease(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile_path = self._install(temporary)
            state = _MemoryCAS()
            adapters = self._adapters(profile_path, state_cas=state)
            calls = []

            def crash(request, timeout, context):
                calls.append(dict(request.header_items()))
                raise _Crash()

            for now in (100, 105, 110):
                with self.assertRaises(_Crash):
                    managed.reconcile_managed_connection(
                        **adapters, transport=crash, clock=lambda now=now: now
                    )
            terminal = managed.reconcile_managed_connection(
                **adapters, transport=crash, clock=lambda: 115
            )
            replay = managed.reconcile_managed_connection(
                **adapters, transport=crash, clock=lambda: 1000
            )
            self.assertEqual(3, len(calls))
            self.assertEqual("quarantined", terminal["phase"])
            self.assertEqual("quarantine_replace", terminal["action"])
            self.assertEqual(3, terminal["attemptCount"])
            self.assertEqual(terminal, replay)

    def test_missing_controller_state_never_becomes_first_boot_at_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile_path = self._install(temporary)
            adapters = self._adapters(profile_path)
            adapters["state_cas"] = _MemoryCAS()
            calls = []
            result = managed.reconcile_managed_connection(
                **adapters,
                transport=lambda *args, **kwargs: calls.append(args),
                clock=lambda: 100,
            )
            self.assertEqual([], calls)
            self.assertEqual("managed_controller_state_missing", result["code"])
            self.assertEqual("quarantined", result["phase"])

    def test_external_generation_floor_rejects_rollback_after_state_loss(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile_path = self._install(temporary)
            adapters = self._adapters(profile_path)
            adapters["state_cas"] = _MemoryCAS()
            adapters["verifier"] = managed.SignedProfileVerifier(
                VERIFIER_ID,
                lambda verifier_id, payload, actual: True,
                lambda verifier_id, actual: 2,
            )
            calls = []
            result = managed.reconcile_managed_connection(
                **adapters,
                transport=lambda *args, **kwargs: calls.append(args),
                clock=lambda: 100,
            )
            self.assertEqual([], calls)
            self.assertEqual("managed_service_binding_mismatch", result["code"])
            self.assertEqual("quarantined", result["phase"])

    def test_context_digest_binds_retry_policy_and_recovery_authority(self):
        base = self._context()
        retry_changed = self._context(max_attempts=4)
        authority_changed = self._context(
            recovery_authority_id="concresca-recovery-authority-v2"
        )
        self.assertNotEqual(
            managed._service_context_digest(base),
            managed._service_context_digest(retry_changed),
        )
        self.assertNotEqual(
            managed._service_context_digest(base),
            managed._service_context_digest(authority_changed),
        )

    def test_incoherent_controller_state_fails_closed_before_network(self):
        corruptions = (
            {"phase": "connecting", "attemptCount": 0},
            {"phase": "active", "attemptCount": 4},
            {"phase": "retry_wait", "nextAttemptAtEpoch": None},
        )
        for changes in corruptions:
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as temporary:
                profile_path = self._install(temporary)
                state = _MemoryCAS()
                adapters = self._adapters(profile_path, state_cas=state)
                state.state.update(changes)
                calls = []
                result = managed.reconcile_managed_connection(
                    **adapters,
                    transport=lambda *args, **kwargs: calls.append(args),
                    clock=lambda: 100,
                )
                self.assertEqual([], calls)
                self.assertEqual("managed_controller_state_invalid", result["code"])
                self.assertEqual("quarantined", result["phase"])

    def test_nonretryable_failure_uses_bound_recovery_directive(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile_path = self._install(temporary)
            requests = []

            def recovery(request):
                requests.append(request)
                return {
                    "schemaVersion": managed.MANAGED_RECOVERY_DIRECTIVE_SCHEMA,
                    "action": "halt",
                    "authorityId": AUTHORITY_ID,
                    "contextDigest": request["contextDigest"],
                    "stateRevision": request["stateRevision"],
                    "operationDigest": request["operationDigest"],
                    "failureCode": request["failureCode"],
                    "requestDigest": request["requestDigest"],
                    "reasonCode": "credential_revoked_terminal",
                    "retryAfterSeconds": None,
                    "valuesRedacted": True,
                }

            adapters = self._adapters(profile_path, recovery=recovery)
            result = managed.reconcile_managed_connection(
                **adapters,
                transport=lambda request, timeout, context: _Response(
                    401, {"ok": False}
                ),
                clock=lambda: 100,
            )
            self.assertEqual("halted", result["phase"])
            self.assertEqual("halt", result["action"])
            self.assertEqual("independent_recovery_authority", result["actionAuthority"])
            self.assertEqual(1, len(requests))
            self.assertEqual(managed.MANAGED_RECOVERY_REQUEST_SCHEMA, requests[0]["schemaVersion"])
            self.assertNotIn(COMPANY_ID, json.dumps(requests[0]))

    def test_invalid_or_unavailable_recovery_authority_quarantines_for_replacement(self):
        for recovery in (
            lambda request: {"action": "retry_after"},
            lambda request: (_ for _ in ()).throw(OSError("private path")),
        ):
            with self.subTest(recovery=recovery), tempfile.TemporaryDirectory() as temporary:
                profile_path = self._install(temporary)
                adapters = self._adapters(profile_path, recovery=recovery)
                result = managed.reconcile_managed_connection(
                    **adapters,
                    transport=lambda request, timeout, context: _Response(
                        401, {"ok": False}
                    ),
                    clock=lambda: 100,
                )
                self.assertEqual("quarantined", result["phase"])
                self.assertEqual("quarantine_replace", result["action"])
                self.assertEqual("managed_recovery_authority_unavailable", result["code"])
                self.assertNotIn("path", json.dumps(result).lower())

    def test_file_state_cas_is_closed_durable_and_rejects_stale_revision(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state" / "controller.json"
            cas = managed.FileDurableStateCAS(path)
            key = "f" * 64
            state = {
                "schemaVersion": managed.MANAGED_CONTROLLER_STATE_SCHEMA,
                "profileId": PROFILE_ID,
                "serviceInstanceId": SERVICE_INSTANCE_ID,
                "profileGeneration": 1,
                "policyRevision": 1,
                "activeProfileDigest": "a" * 64,
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
            self.assertEqual((0, None), cas.read(key))
            self.assertEqual(1, cas.compare_exchange(key, 0, state))
            self.assertEqual((1, state), cas.read(key))
            with self.assertRaises(managed.OnboardingError) as conflict:
                cas.compare_exchange(key, 0, state)
            self.assertEqual("managed_controller_state_conflict", conflict.exception.code)

    def test_file_state_cas_serializes_competing_processes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state" / "controller.json"
            key = "f" * 64
            state = managed._initial_controller_state(
                self._profile(b"test-only-concresca-ca"),
                "a" * 64,
                self._context(),
            )
            process_context = multiprocessing.get_context("spawn")
            ready = process_context.Queue()
            start = process_context.Event()
            results = process_context.Queue()
            workers = [
                process_context.Process(
                    target=_file_cas_worker,
                    args=(path, key, state, ready, start, results),
                )
                for _ in range(2)
            ]
            for worker in workers:
                worker.start()
            self.assertTrue(ready.get(timeout=10))
            self.assertTrue(ready.get(timeout=10))
            start.set()
            outcomes = [results.get(timeout=10), results.get(timeout=10)]
            for worker in workers:
                worker.join(timeout=10)
                self.assertFalse(worker.is_alive())
            self.assertEqual(1, sum(outcome[0] == "success" for outcome in outcomes))
            self.assertEqual(1, sum(outcome[0] == "error" for outcome in outcomes))
            error_code = next(outcome[1] for outcome in outcomes if outcome[0] == "error")
            self.assertIn(
                error_code,
                {"managed_connection_busy", "managed_controller_state_conflict"},
            )
            revision, persisted = managed.FileDurableStateCAS(path).read(key)
            self.assertEqual(1, revision)
            self.assertEqual(state, persisted)

    def test_file_state_cas_rechecks_link_substitution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "state" / "controller.json"
            outside = root / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            cas = managed.FileDurableStateCAS(path)
            path.parent.mkdir(parents=True)
            try:
                path.symlink_to(outside)
            except OSError as exc:
                self.skipTest("file symlinks unavailable: %s" % type(exc).__name__)
            with self.assertRaises(managed.OnboardingError) as raised:
                cas.read("f" * 64)
            self.assertEqual("managed_profile_invalid", raised.exception.code)

    def test_result_parser_rejects_extensions_and_incoherent_human_fallback(self):
        result = managed._reconciliation_result(
            ok=True,
            phase="active",
            code="managed_connection_active",
            action="none",
            action_authority="none",
            retryable=False,
            terminal=False,
            attempt_count=0,
            max_attempts=3,
            operation_digest="a" * 64,
        )
        self.assertEqual(result, managed.parse_managed_reconciliation_result(result))
        with self.assertRaises(ValueError):
            managed.parse_managed_reconciliation_result(dict(result, humanInputRequired=True))
        with self.assertRaises(ValueError):
            managed.parse_managed_reconciliation_result(dict(result, extra=True))
        for invalid in (
            dict(
                result,
                ok=False,
                phase="halted",
                code="managed_connection_terminal",
                action="quarantine_replace",
                actionAuthority="fleet_controller",
                terminal=True,
            ),
            dict(
                result,
                ok=False,
                phase="quarantined",
                code="managed_connection_terminal",
                action="halt",
                actionAuthority="independent_recovery_authority",
                terminal=True,
            ),
            dict(result, attemptCount=4, maxAttempts=3),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    managed.parse_managed_reconciliation_result(invalid)


if __name__ == "__main__":
    unittest.main()
