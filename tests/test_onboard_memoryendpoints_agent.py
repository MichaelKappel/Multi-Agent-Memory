import base64
import contextlib
import hashlib
import io
import json
import os
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from memoryendpoints import managed_connection as onboarding


BASE_URL = "https://10.1.10.209:8088"
AGENT_ID = "onboarding-helper-agent"
PROFILE_ID = "lan-profile-001"
WORKSPACE_ID = "workspace-private-test-boundary"
COMPANY_ID = "company-private-test-boundary"
PROJECT_ID = "project-private-test-boundary"
DEVICE_ID = "device-private-test-boundary"
SERVICE_INSTANCE_ID = "service-instance-private-test-boundary"
WORKLOAD_IDENTITY_ID = "workload-identity-private-test-boundary"
INVITE_SECRET = "me_invite_v1.invite-" + ("a" * 20) + "." + ("b" * 43)
AGENT_TOKEN = "me_agent_v1.agenttoken-" + ("c" * 20) + "." + ("d" * 43)
IDEMPOTENCY_KEY = "e" * 43
REAL_WINDOWS_PROTECT = onboarding._windows_protect_secret
REAL_WINDOWS_UNPROTECT = onboarding._windows_unprotect_secret


def _protect(secret, profile_id, agent_id, profile_binding):
    return base64.b64encode(
        (
            profile_id
            + "\0"
            + agent_id
            + "\0"
            + profile_binding
            + "\0"
            + secret
        ).encode("utf-8")
    ).decode("ascii")


def _unprotect(protected, profile_id, agent_id, profile_binding):
    raw = base64.b64decode(protected).decode("utf-8")
    prefix = profile_id + "\0" + agent_id + "\0" + profile_binding + "\0"
    if not raw.startswith(prefix):
        raise onboarding.OnboardingError(
            "credential_unavailable",
            "The managed secret does not match this profile binding.",
            "quarantine_identity",
        )
    return raw[len(prefix) :]


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


def _headers(request):
    return {key.lower(): value for key, value in request.header_items()}


def _redeemed_payload():
    return {
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
    }


def _me_payload():
    return {
        "ok": True,
        "principal": {
            "credentialType": "agent_token",
            "agentId": AGENT_ID,
            "companyId": COMPANY_ID,
            "workspaceId": WORKSPACE_ID,
            "projectId": PROJECT_ID,
            "credentialId": "credential-private-test-boundary",
        },
    }


class OnboardMemoryEndpointsAgentTests(unittest.TestCase):
    def setUp(self):
        protect = patch.object(
            onboarding, "_windows_protect_secret", side_effect=_protect
        )
        unprotect = patch.object(
            onboarding, "_windows_unprotect_secret", side_effect=_unprotect
        )
        protect.start()
        unprotect.start()
        self.addCleanup(protect.stop)
        self.addCleanup(unprotect.stop)
        token = patch.object(
            onboarding, "_new_agent_token_secret", return_value=AGENT_TOKEN
        )
        idempotency = patch.object(
            onboarding, "_new_idempotency_key", return_value=IDEMPOTENCY_KEY
        )
        token.start()
        idempotency.start()
        self.addCleanup(token.stop)
        self.addCleanup(idempotency.stop)

    def _invite_file(self, root):
        path = Path(root) / "invite.json"
        path.write_text(
            json.dumps(
                {
                    "baseUrl": BASE_URL,
                    "agentId": AGENT_ID,
                    "inviteSecret": INVITE_SECRET,
                }
            ),
            encoding="utf-8",
        )
        return path

    def _credential_paths(self, root):
        return onboarding._credential_paths(root, AGENT_ID)

    def _managed_profile_payload(self, ca_content, **overrides):
        payload = {
            "schemaVersion": onboarding.MANAGED_PROFILE_SCHEMA,
            "profileId": PROFILE_ID,
            "profilePurpose": onboarding.MANAGED_PROFILE_PURPOSE,
            "clientKind": "localendpoints-desktop",
            "runtimeClass": onboarding.MANAGED_RUNTIME_CLASS_PER_USER,
            "enrollmentKind": onboarding.MANAGED_ENROLLMENT_KIND,
            "commonsFallback": onboarding.MANAGED_FALLBACK_POLICY,
            "identityFallback": onboarding.MANAGED_FALLBACK_POLICY,
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
            "trustMode": onboarding.MANAGED_TRUST_MODE,
            "caSha256": hashlib.sha256(ca_content).hexdigest(),
            "protectionId": onboarding.WINDOWS_USER_PROTECTION_ID,
            "profileVerifierId": "protected-state-binding",
        }
        payload.update(overrides)
        return payload

    def _managed_install(self, root):
        managed = Path(root) / "managed"
        ca_content = b"test-only-managed-ca"
        profile = managed / onboarding.MANAGED_PROFILE_FILE
        profile_document = self._managed_profile_payload(ca_content)
        onboarding.provision_managed_connection(
            profile_document,
            ca_content,
            INVITE_SECRET,
            profile,
        )
        return profile

    def test_success_persists_before_introspection_and_redacts_public_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            target, pending = self._credential_paths(temporary)
            invite_file = self._invite_file(temporary)
            calls = []

            def open_url(request, timeout, context):
                self.assertEqual(30, timeout)
                self.assertIsInstance(context, ssl.SSLContext)
                calls.append(request.full_url)
                if request.full_url.endswith(onboarding.REDEEM_ROUTE):
                    self.assertTrue(pending.is_file())
                    marker = json.loads(pending.read_text(encoding="utf-8"))
                    self.assertEqual(onboarding.PENDING_SCHEMA, marker["schemaVersion"])
                    self.assertNotIn(INVITE_SECRET, pending.read_text(encoding="utf-8"))
                    self.assertEqual(
                        {
                            "schemaVersion": "memoryendpoints.agent_invite_redemption.v1",
                            "inviteSecret": INVITE_SECRET,
                            "candidateAgentTokenSecret": AGENT_TOKEN,
                        },
                        json.loads(request.data.decode("utf-8")),
                    )
                    self.assertNotIn("authorization", _headers(request))
                    self.assertEqual(
                        IDEMPOTENCY_KEY, _headers(request)["idempotency-key"]
                    )
                    return _Response(200, _redeemed_payload())
                self.assertTrue(target.is_file(), "credential must exist before /api/matm/me")
                self.assertFalse(pending.exists())
                self.assertEqual("Bearer " + AGENT_TOKEN, _headers(request)["authorization"])
                return _Response(200, _me_payload())

            result = onboarding.onboard_agent(
                AGENT_ID,
                PROFILE_ID,
                project_root=temporary,
                base_url=BASE_URL,
                invite_file=invite_file,
                environ={},
                open_url=open_url,
            )

            self.assertEqual(
                [BASE_URL + onboarding.REDEEM_ROUTE, BASE_URL + onboarding.ME_ROUTE],
                calls,
            )
            document = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(onboarding.AGENT_CREDENTIAL_SCHEMA, document["schemaVersion"])
            self.assertEqual("windows-dpapi-current-user", document["credentialProtection"])
            self.assertNotIn("agentTokenSecret", document)
            self.assertNotIn(AGENT_TOKEN, target.read_text(encoding="utf-8"))
            self.assertEqual(
                AGENT_TOKEN,
                _unprotect(
                    document["protectedAgentToken"],
                    PROFILE_ID,
                    AGENT_ID,
                    document["profileBinding"],
                ),
            )
            self.assertEqual("onboarded", result["status"])
            encoded = json.dumps(result)
            for forbidden in (
                INVITE_SECRET,
                AGENT_TOKEN,
                WORKSPACE_ID,
                "project-private-test-boundary",
                "credential-private-test-boundary",
                BASE_URL,
            ):
                self.assertNotIn(forbidden, encoded)
            self.assertEqual(AGENT_ID, result["agentId"])

    def test_existing_credential_reconciles_without_invitation_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            target, _pending = self._credential_paths(temporary)
            onboarding._private_write(
                target,
                onboarding._credential_document(
                    BASE_URL,
                    COMPANY_ID,
                    WORKSPACE_ID,
                    PROJECT_ID,
                    AGENT_ID,
                    AGENT_TOKEN,
                    PROFILE_ID,
                    onboarding._profile_binding(
                        PROFILE_ID,
                        BASE_URL,
                        AGENT_ID,
                        hashlib.sha256(b"system-trust").hexdigest(),
                    ),
                ),
            )
            calls = []

            def open_url(request, timeout, context):
                calls.append(request.full_url)
                return _Response(200, _me_payload())

            result = onboarding.onboard_agent(
                AGENT_ID,
                PROFILE_ID,
                project_root=temporary,
                base_url=BASE_URL,
                environ={},
                open_url=open_url,
            )

            self.assertEqual("verified_existing", result["status"])
            self.assertEqual([BASE_URL + onboarding.ME_ROUTE], calls)

    def test_introspection_failure_retains_final_and_rerun_reconciles(self):
        with tempfile.TemporaryDirectory() as temporary:
            target, pending = self._credential_paths(temporary)
            invite_file = self._invite_file(temporary)
            calls = 0

            def first_open_url(request, timeout, context):
                nonlocal calls
                calls += 1
                if request.full_url.endswith(onboarding.REDEEM_ROUTE):
                    return _Response(200, _redeemed_payload())
                self.assertTrue(target.is_file())
                raise URLError("introspection transport unavailable")

            with self.assertRaisesRegex(
                onboarding.OnboardingError, "remains protected"
            ):
                onboarding.onboard_agent(
                    AGENT_ID,
                    PROFILE_ID,
                    project_root=temporary,
                    base_url=BASE_URL,
                    invite_file=invite_file,
                    environ={},
                    open_url=first_open_url,
                )
            self.assertEqual(2, calls)
            self.assertTrue(target.is_file())
            self.assertFalse(pending.exists())

            result = onboarding.onboard_agent(
                AGENT_ID,
                PROFILE_ID,
                project_root=temporary,
                base_url=BASE_URL,
                environ={},
                open_url=lambda request, timeout, context: _Response(
                    200, _me_payload()
                ),
            )
            self.assertEqual("verified_existing", result["status"])

    def test_failed_final_promotion_retains_credential_pending_and_rerun_promotes(self):
        with tempfile.TemporaryDirectory() as temporary:
            target, pending = self._credential_paths(temporary)
            invite_file = self._invite_file(temporary)

            def first_open_url(request, timeout, context):
                self.assertTrue(request.full_url.endswith(onboarding.REDEEM_ROUTE))
                return _Response(200, _redeemed_payload())

            with patch.object(
                onboarding,
                "_promote_pending",
                side_effect=OSError("test-only promotion failure"),
            ):
                with self.assertRaisesRegex(
                    onboarding.OnboardingError, "protected in pending state"
                ):
                    onboarding.onboard_agent(
                        AGENT_ID,
                        PROFILE_ID,
                        project_root=temporary,
                        base_url=BASE_URL,
                        invite_file=invite_file,
                        environ={},
                        open_url=first_open_url,
                    )

            self.assertFalse(target.exists())
            self.assertTrue(pending.is_file())
            pending_document = json.loads(pending.read_text(encoding="utf-8"))
            self.assertEqual(onboarding.AGENT_CREDENTIAL_SCHEMA, pending_document["schemaVersion"])
            self.assertNotIn("agentTokenSecret", pending_document)
            self.assertNotIn(AGENT_TOKEN, pending.read_text(encoding="utf-8"))

            calls = []

            def reconcile_open_url(request, timeout, context):
                calls.append(request.full_url)
                self.assertTrue(target.is_file())
                self.assertFalse(pending.exists())
                return _Response(200, _me_payload())

            result = onboarding.onboard_agent(
                AGENT_ID,
                PROFILE_ID,
                project_root=temporary,
                base_url=BASE_URL,
                environ={},
                open_url=reconcile_open_url,
            )
            self.assertEqual("reconciled_pending_credential", result["status"])
            self.assertEqual([BASE_URL + onboarding.ME_ROUTE], calls)

    def test_unknown_redemption_retains_protected_exact_retry_and_rerun_completes(self):
        with tempfile.TemporaryDirectory() as temporary:
            _target, pending = self._credential_paths(temporary)
            invite_file = self._invite_file(temporary)

            with self.assertRaisesRegex(onboarding.OnboardingError, "outcome is unknown"):
                onboarding.onboard_agent(
                    AGENT_ID,
                    PROFILE_ID,
                    project_root=temporary,
                    base_url=BASE_URL,
                    invite_file=invite_file,
                    environ={},
                    open_url=lambda request, timeout, context: (_ for _ in ()).throw(
                        URLError("response lost")
                    ),
                )
            marker = json.loads(pending.read_text(encoding="utf-8"))
            self.assertEqual("redemption_outcome_unknown", marker["state"])
            self.assertNotIn(INVITE_SECRET, pending.read_text(encoding="utf-8"))
            self.assertNotIn(AGENT_TOKEN, pending.read_text(encoding="utf-8"))
            self.assertNotIn(IDEMPOTENCY_KEY, pending.read_text(encoding="utf-8"))

            calls = []

            def retry_open_url(request, timeout, context):
                calls.append(request.full_url)
                if request.full_url.endswith(onboarding.REDEEM_ROUTE):
                    self.assertEqual(
                        IDEMPOTENCY_KEY, _headers(request)["idempotency-key"]
                    )
                    return _Response(201, _redeemed_payload())
                return _Response(200, _me_payload())

            result = onboarding.onboard_agent(
                AGENT_ID,
                PROFILE_ID,
                project_root=temporary,
                base_url=BASE_URL,
                invite_file=invite_file,
                environ={},
                open_url=retry_open_url,
            )
            self.assertEqual("onboarded", result["status"])
            self.assertEqual(2, len(calls))

    def test_remote_http_and_non_origin_urls_fail_before_source_or_network(self):
        calls = []
        for base_url in (
            "http://example.com",
            "https://example.com/path",
            "https://user@example.com",
            "https://example.com?query=1",
        ):
            with self.subTest(base_url=base_url):
                with self.assertRaises(onboarding.OnboardingError):
                    onboarding.onboard_agent(
                        AGENT_ID,
                        PROFILE_ID,
                        base_url=base_url,
                        invite_file="does-not-exist",
                        open_url=lambda request, **kwargs: calls.append(request),
                    )
        self.assertEqual([], calls)
        self.assertEqual(
            "http://127.0.0.1:8123",
            onboarding._validate_base_url("http://127.0.0.1:8123/"),
        )

    def test_configured_ca_bundle_is_loaded_and_used_for_both_requests(self):
        with tempfile.TemporaryDirectory() as temporary:
            invite_file = self._invite_file(temporary)
            ca_bundle = Path(temporary) / "lan-ca.pem"
            ca_bundle.write_text("test-only-ca", encoding="utf-8")
            sentinel = object()
            contexts = []

            def open_url(request, timeout, context):
                contexts.append(context)
                if request.full_url.endswith(onboarding.REDEEM_ROUTE):
                    return _Response(200, _redeemed_payload())
                return _Response(200, _me_payload())

            with patch.object(
                onboarding.ssl, "create_default_context", return_value=sentinel
            ) as create_context:
                onboarding.onboard_agent(
                    AGENT_ID,
                    PROFILE_ID,
                    project_root=temporary,
                    base_url=BASE_URL,
                    invite_file=invite_file,
                    ca_bundle=ca_bundle,
                    environ={},
                    open_url=open_url,
                )

            create_context.assert_called_once_with(cadata="test-only-ca")
            self.assertEqual([sentinel, sentinel], contexts)

    def test_cli_has_no_raw_invitation_secret_argument(self):
        option_strings = {
            option
            for action in onboarding._parser()._actions
            for option in action.option_strings
        }
        self.assertEqual({"-h", "--help", "--profile"}, option_strings)
        self.assertNotIn("--agent-id", option_strings)
        self.assertNotIn("--base-url", option_strings)
        self.assertNotIn("--ca-bundle", option_strings)
        self.assertNotIn("--invite-file", option_strings)
        self.assertNotIn("--invite-environment", option_strings)

    def test_managed_connect_is_cwd_independent_and_reuses_protected_credential(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as other:
            profile = self._managed_install(temporary)
            managed = profile.parent
            invitation_bytes = (
                managed / onboarding.MANAGED_INVITE_FILE
            ).read_text(encoding="utf-8")
            self.assertNotIn(INVITE_SECRET, invitation_bytes)
            calls = []

            def open_url(request, timeout, context):
                calls.append(request.full_url)
                if request.full_url.endswith(onboarding.REDEEM_ROUTE):
                    return _Response(200, _redeemed_payload())
                return _Response(200, _me_payload())

            original_cwd = Path.cwd()
            try:
                os.chdir(other)
                with patch.object(
                    onboarding.ssl, "create_default_context", return_value=object()
                ):
                    first = onboarding.connect_managed_agent(
                        profile_candidates=(profile,), open_url=open_url
                    )
                    second = onboarding.connect_managed_agent(
                        profile_candidates=(profile,), open_url=open_url
                    )
            finally:
                os.chdir(original_cwd)

            self.assertEqual("onboarded", first["status"])
            self.assertEqual("verified_existing", second["status"])
            self.assertEqual(
                [
                    BASE_URL + onboarding.REDEEM_ROUTE,
                    BASE_URL + onboarding.ME_ROUTE,
                    BASE_URL + onboarding.ME_ROUTE,
                ],
                calls,
            )
            self.assertFalse((managed / onboarding.MANAGED_INVITE_FILE).exists())
            credential = managed / onboarding.MANAGED_CREDENTIAL_FILE
            self.assertTrue(credential.is_file())
            persisted = credential.read_text(encoding="utf-8")
            self.assertNotIn(INVITE_SECRET, persisted)
            self.assertNotIn(AGENT_TOKEN, persisted)

    def test_missing_and_duplicate_profiles_fail_closed_without_network(self):
        calls = []
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing.json"
            with self.assertRaises(onboarding.OnboardingError) as absent:
                onboarding.connect_managed_agent(
                    profile_candidates=(missing,),
                    open_url=lambda request, **kwargs: calls.append(request),
                )
            self.assertEqual("managed_profile_missing", absent.exception.code)
            first = self._managed_install(Path(temporary) / "first")
            second = self._managed_install(Path(temporary) / "second")
            with self.assertRaises(onboarding.OnboardingError) as conflict:
                onboarding.connect_managed_agent(
                    profile_candidates=(first, second),
                    open_url=lambda request, **kwargs: calls.append(request),
                )
            self.assertEqual("managed_profile_conflict", conflict.exception.code)
        self.assertEqual([], calls)

    def test_main_zero_args_emits_stable_machine_action_when_profile_missing(self):
        stderr = io.StringIO()
        with patch.object(
            onboarding, "_managed_profile_candidates", return_value=()
        ), contextlib.redirect_stderr(stderr):
            result = onboarding.main([], environ={})
        self.assertEqual(1, result)
        payload = json.loads(stderr.getvalue())
        self.assertEqual("managed_profile_missing", payload["code"])
        self.assertEqual(
            "install_managed_connection_profile", payload["controllerAction"]
        )
        self.assertFalse(payload["retryable"])
        self.assertTrue(payload["valuesRedacted"])

    def test_default_discovery_uses_one_windows_known_folder_without_environment(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {}, clear=True
        ), patch.object(
            onboarding,
            "_windows_local_app_data",
            return_value=Path(temporary),
        ):
            candidates = onboarding._managed_profile_candidates()
        self.assertEqual(
            (
                Path(temporary)
                / "LocalEndpoints"
                / "MemoryEndpoints"
                / "connection.json",
            ),
            candidates,
        )

    def test_verification_distinguishes_outage_rejection_and_server_drift(self):
        cases = (
            (503, "credential_verification_deferred", "retry_with_bounded_backoff", True),
            (401, "credential_rejected", "reconcile_credential_with_recovery_authority", False),
            (404, "managed_server_contract_incompatible", "hold_for_compatible_server_release", False),
        )
        for status, code, action, retryable in cases:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temporary:
                target, _pending = self._credential_paths(temporary)
                binding = onboarding._profile_binding(
                    PROFILE_ID,
                    BASE_URL,
                    AGENT_ID,
                    hashlib.sha256(b"system-trust").hexdigest(),
                )
                onboarding._private_write(
                    target,
                    onboarding._credential_document(
                        BASE_URL,
                        COMPANY_ID,
                        WORKSPACE_ID,
                        PROJECT_ID,
                        AGENT_ID,
                        AGENT_TOKEN,
                        PROFILE_ID,
                        binding,
                    ),
                )
                with self.assertRaises(onboarding.OnboardingError) as caught:
                    onboarding.onboard_agent(
                        AGENT_ID,
                        PROFILE_ID,
                        project_root=temporary,
                        base_url=BASE_URL,
                        environ={},
                        open_url=lambda request, timeout, context, response_status=status: _Response(
                            response_status, {"ok": False}
                        ),
                    )
                self.assertEqual(code, caught.exception.code)
                self.assertEqual(action, caught.exception.action)
                self.assertEqual(retryable, caught.exception.retryable)

    def test_managed_profile_and_ca_replacement_cannot_open_bound_invitation(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile = self._managed_install(temporary)
            ca = profile.parent / onboarding.MANAGED_TRUST_FILE
            ca.write_bytes(b"replacement-test-ca")
            payload = json.loads(profile.read_text(encoding="utf-8"))
            payload["caSha256"] = hashlib.sha256(ca.read_bytes()).hexdigest()
            profile.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(onboarding.OnboardingError) as caught:
                onboarding.connect_managed_agent(profile_candidates=(profile,))
            self.assertEqual("managed_invitation_mismatch", caught.exception.code)
            self.assertEqual("quarantine_profile_conflict", caught.exception.action)

    def test_managed_unknown_outcome_reuses_exact_protected_material(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile = self._managed_install(temporary)
            managed = profile.parent
            with patch.object(
                onboarding.ssl, "create_default_context", return_value=object()
            ):
                with self.assertRaises(onboarding.OnboardingError) as unknown:
                    onboarding.connect_managed_agent(
                        profile_candidates=(profile,),
                        open_url=lambda request, timeout, context: (_ for _ in ()).throw(
                            URLError("lost response")
                        ),
                    )
                self.assertEqual("enrollment_outcome_unknown", unknown.exception.code)
                calls = []

                def retry(request, timeout, context):
                    calls.append((request.full_url, _headers(request)))
                    if request.full_url.endswith(onboarding.REDEEM_ROUTE):
                        return _Response(201, _redeemed_payload())
                    return _Response(200, _me_payload())

                result = onboarding.connect_managed_agent(
                    profile_candidates=(profile,), open_url=retry
                )

            self.assertEqual("onboarded", result["status"])
            self.assertEqual(2, len(calls))
            self.assertEqual(IDEMPOTENCY_KEY, calls[0][1]["idempotency-key"])
            self.assertFalse((managed / onboarding.MANAGED_INVITE_FILE).exists())

    def test_profile_is_closed_schema_and_ca_digest_is_enforced(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile = self._managed_install(temporary)
            payload = json.loads(profile.read_text(encoding="utf-8"))
            payload["caPath"] = r"C:\manual\override.pem"
            profile.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(onboarding.OnboardingError) as invalid:
                onboarding.connect_managed_agent(profile_candidates=(profile,))
            self.assertEqual("managed_profile_invalid", invalid.exception.code)

            payload.pop("caPath")
            profile.write_text(json.dumps(payload), encoding="utf-8")
            (profile.parent / onboarding.MANAGED_TRUST_FILE).write_bytes(b"changed")
            with self.assertRaises(onboarding.OnboardingError) as trust:
                onboarding.connect_managed_agent(profile_candidates=(profile,))
            self.assertEqual("managed_trust_mismatch", trust.exception.code)

    def test_managed_profile_binds_exact_tenant_project_and_forbids_commons_fallback(self):
        for field, value in (
            ("companyId", "wrong-company"),
            ("workspaceId", "wrong-workspace"),
            ("projectId", "wrong-project"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                profile = self._managed_install(temporary)
                calls = []

                def open_url(request, timeout, context):
                    calls.append(request.full_url)
                    payload = _redeemed_payload()
                    payload["principal"][field] = value
                    return _Response(201, payload)

                with patch.object(
                    onboarding.ssl, "create_default_context", return_value=object()
                ), self.assertRaises(onboarding.OnboardingError) as caught:
                    onboarding.connect_managed_agent(
                        profile_candidates=(profile,), open_url=open_url
                    )
                self.assertEqual("enrollment_binding_mismatch", caught.exception.code)
                self.assertEqual("quarantine_identity", caught.exception.action)
                self.assertEqual([BASE_URL + onboarding.REDEEM_ROUTE], calls)

        with tempfile.TemporaryDirectory() as temporary:
            profile = self._managed_install(temporary)
            payload = json.loads(profile.read_text(encoding="utf-8"))
            payload["commonsFallback"] = "allowed"
            profile.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(onboarding.OnboardingError) as caught:
                onboarding.connect_managed_agent(profile_candidates=(profile,))
            self.assertEqual("quarantine_profile_conflict", caught.exception.action)

    def test_final_pending_credential_promotes_without_an_invitation(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile_path = self._managed_install(temporary)
            profile = onboarding._load_managed_profile(profile_path)
            paths = onboarding._managed_state_paths(profile_path)
            onboarding._private_write(
                paths["pending"],
                onboarding._credential_document(
                    BASE_URL,
                    COMPANY_ID,
                    WORKSPACE_ID,
                    PROJECT_ID,
                    AGENT_ID,
                    AGENT_TOKEN,
                    PROFILE_ID,
                    profile["profileBinding"],
                ),
            )
            paths["invite"].unlink()
            calls = []
            with patch.object(
                onboarding.ssl, "create_default_context", return_value=object()
            ):
                result = onboarding.connect_managed_agent(
                    profile_candidates=(profile_path,),
                    open_url=lambda request, timeout, context: (
                        calls.append(request.full_url) or _Response(200, _me_payload())
                    ),
                )
            self.assertEqual("reconciled_pending_credential", result["status"])
            self.assertEqual([BASE_URL + onboarding.ME_ROUTE], calls)
            self.assertTrue(paths["credential"].is_file())

    def test_profile_verifier_and_custom_service_protector_are_first_class(self):
        with tempfile.TemporaryDirectory() as temporary:
            ca_content = b"test-only-service-ca"
            profile_path = Path(temporary) / "service" / onboarding.MANAGED_PROFILE_FILE
            profile_document = self._managed_profile_payload(
                ca_content,
                clientKind="concresca-service",
                runtimeClass=onboarding.MANAGED_RUNTIME_CLASS_UNATTENDED_SERVICE,
                protectionId="test-service-vault",
                profileVerifierId="test-signed-fleet-profile",
            )
            protector = onboarding.SecretProtector(
                "test-service-vault",
                _protect,
                _unprotect,
                workload_identity_id=WORKLOAD_IDENTITY_ID,
            )
            verifier_calls = []

            def verifier(verifier_id, payload):
                verifier_calls.append((verifier_id, payload["clientKind"]))
                return True

            result = onboarding.provision_managed_connection(
                profile_document,
                ca_content,
                INVITE_SECRET,
                profile_path,
                protector=protector,
                profile_verifier=verifier,
            )
            self.assertTrue(result["invitationProtected"])
            invitation = json.loads(
                (profile_path.parent / onboarding.MANAGED_INVITE_FILE).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual("test-service-vault", invitation["credentialProtection"])
            self.assertNotIn(INVITE_SECRET, json.dumps(invitation))
            self.assertEqual(
                [("test-signed-fleet-profile", "concresca-service")],
                verifier_calls,
            )
            replay = onboarding.provision_managed_connection(
                profile_document,
                ca_content,
                INVITE_SECRET,
                profile_path,
                protector=protector,
                profile_verifier=verifier,
            )
            self.assertTrue(replay["idempotentReplay"])

    def test_installer_rejects_a_vault_bound_to_another_workload(self):
        with tempfile.TemporaryDirectory() as temporary:
            ca_content = b"test-only-service-ca"
            profile_path = Path(temporary) / "service" / onboarding.MANAGED_PROFILE_FILE
            profile_document = self._managed_profile_payload(
                ca_content,
                clientKind="concresca-service",
                runtimeClass=onboarding.MANAGED_RUNTIME_CLASS_UNATTENDED_SERVICE,
                protectionId="test-service-vault",
                profileVerifierId="test-signed-fleet-profile",
            )
            wrong_protector = onboarding.SecretProtector(
                "test-service-vault",
                _protect,
                _unprotect,
                workload_identity_id="different-workload-identity",
            )
            with self.assertRaises(onboarding.OnboardingError) as raised:
                onboarding.provision_managed_connection(
                    profile_document,
                    ca_content,
                    INVITE_SECRET,
                    profile_path,
                    protector=wrong_protector,
                    profile_verifier=lambda verifier_id, payload: True,
                )
            self.assertEqual("credential_protection_invalid", raised.exception.code)
            self.assertFalse(profile_path.parent.exists())

    def test_installer_resumes_matching_partial_state_after_interruption(self):
        with tempfile.TemporaryDirectory() as temporary:
            ca_content = b"test-only-service-ca"
            profile_path = Path(temporary) / "service" / onboarding.MANAGED_PROFILE_FILE
            profile_document = self._managed_profile_payload(ca_content)
            original_write = onboarding._private_write

            def interrupt_before_profile(path, payload):
                if Path(path) == profile_path:
                    raise OSError("simulated interruption")
                return original_write(path, payload)

            with patch.object(
                onboarding, "_private_write", side_effect=interrupt_before_profile
            ), self.assertRaises(onboarding.OnboardingError) as interrupted:
                onboarding.provision_managed_connection(
                    profile_document,
                    ca_content,
                    INVITE_SECRET,
                    profile_path,
                )
            self.assertEqual(
                "managed_installation_incomplete", interrupted.exception.code
            )
            self.assertFalse(profile_path.exists())
            self.assertTrue(
                (profile_path.parent / onboarding.MANAGED_TRUST_FILE).is_file()
            )
            self.assertTrue(
                (profile_path.parent / onboarding.MANAGED_INVITE_FILE).is_file()
            )

            resumed = onboarding.provision_managed_connection(
                profile_document,
                ca_content,
                INVITE_SECRET,
                profile_path,
            )
            self.assertTrue(resumed["ok"])
            self.assertFalse(resumed["idempotentReplay"])
            replay = onboarding.provision_managed_connection(
                profile_document,
                ca_content,
                INVITE_SECRET,
                profile_path,
            )
            self.assertTrue(replay["idempotentReplay"])

    def test_controller_result_is_closed_typed_and_main_redacts_unexpected_errors(self):
        success = onboarding._public_result("verified_existing", AGENT_ID)
        self.assertIn("none", onboarding.CONTROLLER_ACTIONS)
        self.assertEqual(success, onboarding.parse_managed_connection_result(success))
        with self.assertRaises(ValueError):
            onboarding.parse_managed_connection_result(dict(success, extra=True))

        stderr = io.StringIO()
        with patch.object(
            onboarding, "connect_managed_agent", side_effect=OSError(r"C:\secret\path")
        ), contextlib.redirect_stderr(stderr):
            result = onboarding.main([])
        self.assertEqual(1, result)
        payload = json.loads(stderr.getvalue())
        self.assertEqual("managed_connection_internal_error", payload["code"])
        self.assertNotIn("secret", stderr.getvalue().lower())
        self.assertTrue(payload["terminal"])

        stderr = io.StringIO()
        injected = onboarding.OnboardingError(
            "credential_unavailable",
            r"vault failed at C:\private\credential.txt with me_agent_v1.secret",
            "quarantine_identity",
        )
        with patch.object(
            onboarding, "connect_managed_agent", side_effect=injected
        ), contextlib.redirect_stderr(stderr):
            result = onboarding.main([])
        self.assertEqual(1, result)
        payload = json.loads(stderr.getvalue())
        self.assertEqual("credential_unavailable", payload["code"])
        self.assertNotIn("private", stderr.getvalue().lower())
        self.assertNotIn("me_agent", stderr.getvalue().lower())
        self.assertTrue(payload["valuesRedacted"])

    def test_profile_strict_types_and_external_verifier_fail_before_network(self):
        ca_content = b"test-only-managed-ca"
        for override in (
            {"caSha256": 1},
            {"policyRevision": "1"},
            {"projectId": 1},
            {"profileVerifierId": "fleet-signed-v1"},
        ):
            with self.subTest(override=override), tempfile.TemporaryDirectory() as temporary:
                profile_path = Path(temporary) / "managed" / onboarding.MANAGED_PROFILE_FILE
                payload = self._managed_profile_payload(ca_content, **override)
                profile_path.parent.mkdir(parents=True)
                profile_path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(onboarding.OnboardingError):
                    onboarding.connect_managed_agent(
                        profile_candidates=(profile_path,),
                        open_url=lambda request, **kwargs: self.fail("network used"),
                    )

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI contract")
    def test_windows_dpapi_round_trip_is_ciphertext_only_and_context_bound(self):
        sample_value = "test-only-dpapi-value"
        binding = "f" * 64
        protected = REAL_WINDOWS_PROTECT(
            sample_value, PROFILE_ID, AGENT_ID, binding
        )
        self.assertNotIn(sample_value, protected)
        self.assertEqual(
            sample_value,
            REAL_WINDOWS_UNPROTECT(
                protected, PROFILE_ID, AGENT_ID, binding
            ),
        )
        with self.assertRaises(onboarding.OnboardingError) as mismatch:
            REAL_WINDOWS_UNPROTECT(
                protected, "different-profile", AGENT_ID, binding
            )
        self.assertEqual("credential_unavailable", mismatch.exception.code)


if __name__ == "__main__":
    unittest.main()
