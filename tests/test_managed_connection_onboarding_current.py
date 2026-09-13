"""Current deterministic coverage for the installer-managed onboarding adapter."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memoryendpoints import managed_connection as managed
from tests.test_managed_connection_recovery import (
    AGENT_ID,
    AGENT_TOKEN,
    INVITE_SECRET,
    PROFILE_ID,
    _Response,
    _protect,
    _unprotect,
)


class ManagedConnectionOnboardingCurrentTests(unittest.TestCase):
    def _protector(self):
        return managed.SecretProtector(
            "test-protection-v1",
            _protect,
            _unprotect,
            workload_identity_id="workload-test-001",
        )

    def _call(self, root, opener, **overrides):
        target = Path(root) / "credentials" / "agent.json"
        pending = Path(root) / "credentials" / ".agent.pending.json"
        values = {
            "agent_id": AGENT_ID,
            "profile_id": PROFILE_ID,
            "project_root": root,
            "base_url": "https://10.1.10.209:8088",
            "invite_file": None,
            "environ": {managed.DEFAULT_INVITE_ENVIRONMENT: INVITE_SECRET},
            "open_url": opener,
            "credential_paths": (target, pending),
            "protector": self._protector(),
            "profile_binding": "a" * 64,
            "ca_content": b"test-ca",
            "expected_company_id": "company-test-boundary",
            "expected_workspace_id": "workspace-test-boundary",
            "expected_project_id": "project-test-boundary",
        }
        values.update(overrides)
        return managed.onboard_agent(**values), target, pending

    def test_onboarding_persists_verifies_and_reuses_existing_credential(self):
        candidate_id = AGENT_TOKEN.split(".", 2)[1]

        def opener(request, **_kwargs):
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
                            "companyId": "company-test-boundary",
                            "workspaceId": "workspace-test-boundary",
                            "projectId": "project-test-boundary",
                            "credentialId": candidate_id,
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
                        "companyId": "company-test-boundary",
                        "workspaceId": "workspace-test-boundary",
                        "projectId": "project-test-boundary",
                    },
                },
            )

        with tempfile.TemporaryDirectory() as root, patch.object(
            managed, "_new_agent_token_secret", return_value=AGENT_TOKEN
        ), patch.object(
            managed, "_new_idempotency_key", return_value="i" * 43
        ), patch.object(managed.ssl, "create_default_context", return_value=object()):
            result, target, pending = self._call(root, opener)
            self.assertEqual("onboarded", result["status"])
            self.assertFalse(result["credentialValuesPrinted"])
            self.assertTrue(target.exists())
            self.assertFalse(pending.exists())
            existing, _, _ = self._call(root, opener)
            self.assertEqual("verified_existing", existing["status"])

    def test_http_outcomes_preserve_pending_state_and_map_to_safe_actions(self):
        outcomes = (
            (429, "enrollment_temporarily_unavailable", True),
            (404, "managed_server_contract_incompatible", False),
            (409, "enrollment_binding_conflict", False),
            (400, "enrollment_authority_required", False),
        )
        for status, code, retryable in outcomes:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as root, patch.object(
                managed, "_new_agent_token_secret", return_value=AGENT_TOKEN
            ), patch.object(
                managed, "_new_idempotency_key", return_value="i" * 43
            ), patch.object(managed.ssl, "create_default_context", return_value=object()):
                def opener(_request, status=status, **_kwargs):
                    return _Response(status, {"ok": False, "error": {"code": "server_error"}})

                with self.assertRaises(managed.OnboardingError) as raised:
                    self._call(root, opener)
                self.assertEqual(code, raised.exception.code)
                self.assertEqual(retryable, raised.exception.retryable)
                self.assertTrue((Path(root) / "credentials" / ".agent.pending.json").exists())

    def test_invalid_response_and_profile_binding_fail_closed_before_persistence(self):
        with tempfile.TemporaryDirectory() as root, patch.object(
            managed, "_new_agent_token_secret", return_value=AGENT_TOKEN
        ), patch.object(
            managed, "_new_idempotency_key", return_value="i" * 43
        ), patch.object(managed.ssl, "create_default_context", return_value=object()):
            with self.assertRaises(managed.OnboardingError) as raised:
                self._call(root, lambda _request, **_kwargs: _Response(201, {"ok": True}))
            self.assertEqual("enrollment_response_invalid", raised.exception.code)
            self.assertTrue((Path(root) / "credentials" / ".agent.pending.json").exists())

            with self.assertRaises(managed.OnboardingError) as raised:
                self._call(root + "-other", lambda *_args, **_kwargs: _Response(200, {}), profile_binding="bad")
            self.assertEqual("managed_profile_invalid", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
