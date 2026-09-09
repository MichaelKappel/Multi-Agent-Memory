"""Black-box contract checks for unattended managed-service adapters.

Consuming products can reuse the fixture shape here with their real service
vault, signed-profile registry, durable state, and recovery implementation.
Passing these reference checks does not certify a product-specific adapter.
"""

import base64
import hashlib
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memoryendpoints import managed_connection as managed


BASE_URL = "https://10.1.10.209:8088"
PROFILE_ID = "unattended-profile-001"
AGENT_ID = "unattended-service-agent"
COMPANY_ID = "company-conformance"
WORKSPACE_ID = "workspace-conformance"
PROJECT_ID = "project-conformance"
DEVICE_ID = "device-conformance-001"
SERVICE_INSTANCE_ID = "service-instance-conformance-001"
WORKLOAD_IDENTITY_ID = "service-account-conformance-001"
VERIFIER_ID = "fleet-profile-signer-v1"
RECOVERY_ID = "fleet-recovery-authority-v1"
PROTECTION_ID = "service-vault-conformance-v1"
INVITE_SECRET = "me_invite_v1.invite-" + ("a" * 20) + "." + ("b" * 43)
AGENT_TOKEN = "me_agent_v1.agenttoken-" + ("c" * 20) + "." + ("d" * 43)
IDEMPOTENCY_KEY = "e" * 43


def _protect(secret, profile_id, agent_id, profile_binding):
    material = "\0".join((profile_id, agent_id, profile_binding, secret))
    return base64.b64encode(material.encode("utf-8")).decode("ascii")


def _unprotect(protected, profile_id, agent_id, profile_binding):
    material = base64.b64decode(protected).decode("utf-8")
    prefix = "\0".join((profile_id, agent_id, profile_binding, ""))
    if not material.startswith(prefix):
        raise managed.OnboardingError(
            "credential_unavailable",
            "The service vault rejected the workload binding.",
            "quarantine_identity",
        )
    return material[len(prefix) :]


class _Response:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        return False

    def read(self, _size=-1):
        return json.dumps(self._payload).encode("utf-8")


class ManagedServiceConformanceMixin:
    """Reusable assertions for one prompt-free unattended-service adapter."""

    def service_context(self):
        return managed.ManagedServiceContext(
            client_kind="conformance-service",
            service_instance_id=SERVICE_INSTANCE_ID,
            workload_identity_id=WORKLOAD_IDENTITY_ID,
            project_id=PROJECT_ID,
            profile_verifier_id=VERIFIER_ID,
            recovery_authority_id=RECOVERY_ID,
            max_attempts=3,
            base_retry_seconds=1,
            max_retry_seconds=4,
            attempt_lease_seconds=5,
        )

    def protector(self):
        return managed.SecretProtector(
            PROTECTION_ID,
            _protect,
            _unprotect,
            workload_identity_id=WORKLOAD_IDENTITY_ID,
        )

    def verifier(self):
        return managed.SignedProfileVerifier(
            VERIFIER_ID,
            lambda verifier_id, payload, context: (
                verifier_id == VERIFIER_ID
                and payload["runtimeClass"]
                == managed.MANAGED_RUNTIME_CLASS_UNATTENDED_SERVICE
                and context.runtime_class
                == managed.MANAGED_RUNTIME_CLASS_UNATTENDED_SERVICE
            ),
            lambda verifier_id, context: 1,
        )

    def profile_document(self, ca_content, **overrides):
        document = {
            "schemaVersion": managed.MANAGED_PROFILE_SCHEMA,
            "profileId": PROFILE_ID,
            "profilePurpose": managed.MANAGED_PROFILE_PURPOSE,
            "runtimeClass": managed.MANAGED_RUNTIME_CLASS_UNATTENDED_SERVICE,
            "clientKind": "conformance-service",
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
        document.update(overrides)
        return document

    def install(self, root, **profile_overrides):
        ca_content = b"test-only-conformance-ca"
        profile_path = Path(root) / "managed" / managed.MANAGED_PROFILE_FILE
        document = self.profile_document(ca_content, **profile_overrides)
        verifier = self.verifier()
        managed.provision_managed_connection(
            document,
            ca_content,
            INVITE_SECRET,
            profile_path,
            protector=self.protector(),
            profile_verifier=lambda verifier_id, payload: verifier.verify(
                payload, self.service_context()
            ),
        )
        return profile_path, document

    def adapters(self, root, profile_path, document, recovery=None):
        context = self.service_context()
        verifier = self.verifier()
        state = managed.FileDurableStateCAS(Path(root) / "state" / "controller.json")
        authority = managed.ManagedRecoveryAuthority(
            RECOVERY_ID,
            recovery
            or (lambda request: {
                "schemaVersion": managed.MANAGED_RECOVERY_DIRECTIVE_SCHEMA,
                "action": "quarantine_replace",
                "authorityId": RECOVERY_ID,
                "contextDigest": request["contextDigest"],
                "stateRevision": request["stateRevision"],
                "operationDigest": request["operationDigest"],
                "failureCode": request["failureCode"],
                "requestDigest": request["requestDigest"],
                "reasonCode": "managed_instance_replacement_required",
                "retryAfterSeconds": None,
                "valuesRedacted": True,
            }),
        )
        managed.initialize_managed_controller_state(
            context,
            profile_document=document,
            verifier=verifier,
            state_cas=state,
            recovery_authority=authority,
        )
        return {
            "context": context,
            "locator": managed.ManagedProfileLocator(lambda actual: profile_path),
            "protector": self.protector(),
            "verifier": verifier,
            "state_cas": state,
            "recovery_authority": authority,
        }


class ManagedServiceConformanceTests(
    ManagedServiceConformanceMixin, unittest.TestCase
):
    def setUp(self):
        self.token_patch = patch.object(
            managed, "_new_agent_token_secret", return_value=AGENT_TOKEN
        )
        self.key_patch = patch.object(
            managed, "_new_idempotency_key", return_value=IDEMPOTENCY_KEY
        )
        self.tls_patch = patch.object(
            managed.ssl, "create_default_context", return_value=object()
        )
        self.token_patch.start()
        self.key_patch.start()
        self.tls_patch.start()
        self.addCleanup(self.token_patch.stop)
        self.addCleanup(self.key_patch.stop)
        self.addCleanup(self.tls_patch.stop)

    @staticmethod
    def success_transport(request, timeout, context):
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

    def test_service_entrypoint_has_no_human_or_ambient_input_parameters(self):
        parameters = set(
            inspect.signature(managed.reconcile_managed_connection).parameters
        )
        for forbidden in (
            "profile_path",
            "credential",
            "token",
            "invite",
            "ca_bundle",
            "environ",
            "username",
            "machine_name",
        ):
            self.assertNotIn(forbidden, parameters)

    def test_unattended_profile_cannot_use_per_user_connector(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile_path, _document = self.install(temporary)
            calls = []
            with self.assertRaises(managed.OnboardingError) as raised:
                managed.connect_managed_agent(
                    profile_path=profile_path,
                    protector=self.protector(),
                    profile_verifier=lambda verifier_id, payload: True,
                    open_url=lambda *args, **kwargs: calls.append(args),
                )
            self.assertEqual(
                "managed_service_controller_required", raised.exception.code
            )
            self.assertEqual([], calls)

    def test_unattended_profile_rejects_missing_project_or_weak_local_trust(self):
        cases = (
            {"projectId": None},
            {"protectionId": managed.WINDOWS_USER_PROTECTION_ID},
            {"profileVerifierId": "protected-state-binding"},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as temporary:
                ca_content = b"test-only-conformance-ca"
                profile_path = Path(temporary) / "managed" / managed.MANAGED_PROFILE_FILE
                with self.assertRaises(managed.OnboardingError) as raised:
                    managed.provision_managed_connection(
                        self.profile_document(ca_content, **overrides),
                        ca_content,
                        INVITE_SECRET,
                        profile_path,
                        protector=self.protector(),
                        profile_verifier=lambda verifier_id, payload: True,
                    )
                self.assertEqual("managed_service_profile_invalid", raised.exception.code)

    def test_reconciliation_requires_the_durable_state_adapter_type(self):
        class DuckState:
            def read(self, _key):
                return 0, None

            def compare_exchange(self, _key, _revision, _state):
                return 1

        with tempfile.TemporaryDirectory() as temporary:
            profile_path, document = self.install(temporary)
            adapters = self.adapters(temporary, profile_path, document)
            adapters["state_cas"] = DuckState()
            with self.assertRaises(ValueError):
                managed.reconcile_managed_connection(
                    **adapters, transport=self.success_transport, clock=lambda: 100
                )

    def test_signed_profile_generation_may_advance_above_external_floor(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile_path, document = self.install(temporary, profileGeneration=2)
            adapters = self.adapters(temporary, profile_path, document)
            result = managed.reconcile_managed_connection(
                **adapters, transport=self.success_transport, clock=lambda: 100
            )
            self.assertTrue(result["ok"])
            self.assertEqual("active", result["phase"])

    def test_reconstructed_file_state_resumes_without_human_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile_path, document = self.install(temporary)
            adapters = self.adapters(temporary, profile_path, document)

            first = managed.reconcile_managed_connection(
                **adapters,
                transport=lambda *args, **kwargs: _Response(503, {"ok": False}),
                clock=lambda: 100,
            )
            self.assertEqual("retry_wait", first["phase"])

            adapters["state_cas"] = managed.FileDurableStateCAS(
                Path(temporary) / "state" / "controller.json"
            )
            resumed = managed.reconcile_managed_connection(
                **adapters,
                transport=self.success_transport,
                clock=lambda: first["nextAttemptAtEpoch"],
            )
            self.assertTrue(resumed["ok"])
            self.assertEqual("active", resumed["phase"])
            self.assertFalse(resumed["humanInputRequired"])

    def test_unavailable_recovery_authority_fails_closed_to_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile_path, document = self.install(temporary)
            adapters = self.adapters(
                temporary,
                profile_path,
                document,
                recovery=lambda request: (_ for _ in ()).throw(
                    RuntimeError("test recovery outage")
                ),
            )
            result = managed.reconcile_managed_connection(
                **adapters,
                transport=lambda *args, **kwargs: _Response(403, {"ok": False}),
                clock=lambda: 100,
            )
            self.assertFalse(result["ok"])
            self.assertEqual("quarantined", result["phase"])
            self.assertEqual("quarantine_replace", result["action"])
            self.assertEqual("fleet_controller", result["actionAuthority"])
            self.assertFalse(result["humanInputRequired"])


if __name__ == "__main__":
    unittest.main()
