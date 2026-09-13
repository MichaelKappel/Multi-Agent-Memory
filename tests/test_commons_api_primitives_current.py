import unittest
from unittest.mock import Mock, patch

from memoryendpoints import commons, commons_api as api


class CommonsApiPrimitivesCurrentTests(unittest.TestCase):
    def test_route_classification_revision_request_ids_and_headers_are_closed(self):
        self.assertTrue(
            api._commons_request_requires_auth(
                "/api/matm/commons/enrollments/current", "GET"
            )
        )
        self.assertTrue(
            api._commons_request_requires_auth(
                "/api/matm/commons/enrollment-requests/commonsenrollment-" + "a" * 24,
                "GET",
            )
        )
        self.assertFalse(api._commons_request_requires_auth("/api/matm/commons/agents", "GET"))
        self.assertTrue(
            api._commons_request_requires_auth(
                "/api/matm/commons/rooms/room-1/join", "POST"
            )
        )
        self.assertTrue(
            api._commons_request_requires_auth(
                "/api/matm/commons/messages/message-1/withdrawal", "POST"
            )
        )
        self.assertFalse(api._commons_request_requires_auth("/api/matm/commons/policy", "PUT"))

        self.assertEqual(0, api._exact_revision(0, allow_zero=True))
        self.assertEqual(7, api._exact_revision(7, maximum=7))
        with self.assertRaises(commons.CommonsContractError):
            api._exact_revision(True)
        with self.assertRaises(commons.CommonsContractError):
            api._exact_revision(0)
        with self.assertRaises(commons.CommonsContractError):
            api._exact_revision(8, maximum=7)

        pattern = api._COMMONS_MESSAGE_ID
        valid_id = "commonsmessage-" + "a" * 24
        self.assertEqual(valid_id, api._exact_optional_id(valid_id, pattern, "messageId"))
        self.assertIsNone(api._exact_optional_id(None, pattern, "messageId"))
        with self.assertRaises(commons.CommonsContractError):
            api._exact_optional_id("wrong", pattern, "messageId")

        key = "k" * 64
        first = api._request_id("/api/matm/commons/me", "GET", key)
        self.assertEqual(first, api._request_id("/api/matm/commons/me", "GET", key))
        self.assertNotEqual(first, api._request_id("/api/matm/commons/me", "GET", "z" * 64))
        self.assertTrue(api._request_id("/api/matm/commons/me", "GET").startswith("commonsreq-"))
        headers = dict(api._headers(first, [("X-Test", "yes")]))
        self.assertEqual(first, headers["X-Request-Id"])
        self.assertEqual("yes", headers["X-Test"])
        self.assertEqual("DENY", headers["X-Frame-Options"])

    def test_availability_and_capability_projection_cover_blockers_and_policy_fallbacks(self):
        with patch.object(api, "configured_store_backend", return_value="sqlite"), patch.object(
            api, "credential_system_available", return_value=True
        ):
            backend, blockers, store, repository = api._availability(
                {"mode": "disabled"}, lambda: Mock()
            )
        self.assertEqual("sqlite", backend)
        self.assertEqual([], blockers)
        self.assertIsNone(store)
        self.assertIsNone(repository)

        with patch.object(api, "configured_store_backend", return_value="sqlite"), patch.object(
            api, "credential_system_available", return_value=True
        ):
            backend, blockers, store, repository = api._availability(
                {"mode": "production"}, lambda: Mock()
            )
        self.assertEqual("sqlite", backend)
        self.assertEqual(["commons_mysql_required"], blockers)
        self.assertIsNone(store)
        self.assertIsNone(repository)

        with patch.object(api, "configured_store_backend", return_value="memory"), patch.object(
            api, "credential_system_available", return_value=False
        ):
            backend, blockers, store, repository = api._availability(
                {"mode": "local_test"}, lambda: Mock()
            )
        self.assertEqual("memory", backend)
        self.assertEqual(
            ["commons_credential_system_unavailable", "commons_test_backend_invalid"],
            blockers,
        )
        self.assertIsNone(store)
        self.assertIsNone(repository)

        settings = {
            "mode": "local_test",
            "workspaceId": "workspace-1",
            "projectId": "project-1",
            "requestByteLimit": 99,
            "messageCharacterLimit": 77,
            "humanApprovalRequired": True,
        }
        capabilities = api._capabilities(settings, "sqlite", ["blocked"], Mock())
        self.assertFalse(capabilities["available"])
        self.assertEqual(["blocked"], capabilities["blockers"])
        self.assertEqual("workspace-1", capabilities["scope"]["workspaceId"])
        self.assertEqual(99, capabilities["limits"]["requestBytes"])
        self.assertFalse(capabilities["auth"]["autonomousEnrollmentCurrentlyAllowed"])
        self.assertTrue(capabilities["valuesRedacted"])

        repository = Mock()
        repository.policy.return_value = {
            "humanApprovalRequired": False,
        }
        available = api._capabilities(settings, "sqlite", [], repository)
        self.assertTrue(available["available"])
        self.assertEqual(
            {"humanApprovalRequired": False}, available["enrollmentPolicy"]
        )
        self.assertTrue(available["auth"]["autonomousEnrollmentCurrentlyAllowed"])
        repository.policy.side_effect = RuntimeError("policy unavailable")
        unavailable_policy = api._capabilities(settings, "sqlite", [], repository)
        self.assertFalse(unavailable_policy["available"])
        self.assertIn("commons_policy_unavailable", unavailable_policy["blockers"])

    def test_authorization_and_agent_helpers_preserve_scheme_and_failure_contracts(self):
        store = Mock()
        repository = Mock()
        repository.workspace_id = "workspace-1"
        repository.assert_active_agent = Mock()
        bearer = {"credentialType": "agent_token", "agentId": "agent-1"}
        session = {"credentialType": "browser_session", "humanAccountId": "human-1"}
        store.authenticate.return_value = bearer
        repository.authenticate_browser_session.return_value = session
        repository.authenticate_agent_credential.return_value = bearer

        self.assertEqual((None, None), api._authorization({}, store, repository))
        self.assertEqual(
            ("bearer", bearer),
            api._authorization(
                {"HTTP_AUTHORIZATION": "Bearer token"}, store, repository
            ),
        )
        store.authenticate.assert_called_with("token", "workspace-1")
        self.assertEqual(
            ("bearer", bearer),
            api._authorization(
                {"HTTP_AUTHORIZATION": "Bearer token"},
                store,
                repository,
                allow_revoked_agent=True,
            ),
        )
        repository.authenticate_agent_credential.assert_called_with(
            "token", allow_revoked=True
        )
        self.assertEqual(
            ("commons_session", session),
            api._authorization(
                {"HTTP_AUTHORIZATION": "CommonsSession session"}, store, repository
            ),
        )
        self.assertEqual((None, None), api._authorization({"HTTP_AUTHORIZATION": "Basic token"}, store, repository))
        self.assertEqual((None, None), api._authorization({"HTTP_AUTHORIZATION": "Bearer  token"}, store, repository))

        enrollment = {"requestId": "commonsenrollment-" + "a" * 24}
        repository.authenticate_enrollment_candidate.return_value = enrollment
        self.assertEqual(
            enrollment,
            api._enrollment_authorization(
                {"HTTP_AUTHORIZATION": "CommonsEnrollment candidate"}, repository
            ),
        )
        self.assertIsNone(api._enrollment_authorization({}, repository))
        self.assertIsNone(
            api._enrollment_authorization(
                {"HTTP_AUTHORIZATION": "Bearer candidate"}, repository
            )
        )

        repository.reset_mock()
        self.assertEqual(bearer, api._require_agent({"HTTP_AUTHORIZATION": "Bearer token"}, store, repository))
        repository.assert_active_agent.assert_called_once_with(bearer)
        self.assertIsNone(api._optional_agent({}, store, repository))
        with self.assertRaisesRegex(commons.CommonsContractError, "auth_required"):
            api._require_agent({}, store, repository)
        store.authenticate.return_value = None
        with self.assertRaisesRegex(commons.CommonsContractError, "auth_invalid"):
            api._optional_agent({"HTTP_AUTHORIZATION": "Bearer bad"}, store, repository)

    def test_receipts_and_rate_limit_helpers_are_deterministic_and_retryable(self):
        key = "i" * 64
        receipt = api._receipt("publish", "message", "message-1", "agent-1", key)
        self.assertEqual(receipt, api._receipt("publish", "message", "message-1", "agent-1", key))
        self.assertTrue(receipt["receiptId"].startswith("commonsreceipt-"))
        self.assertEqual("accepted", receipt["status"])
        self.assertFalse(receipt["idempotencyKeyExposed"])

        store = Mock()
        store.consume_connector_rate_limit.return_value = {"allowed": True}
        self.assertIsNone(api._rate(store, "bucket", "partition", 3))
        store.consume_connector_rate_limit.return_value = {
            "allowed": False,
            "retryAfterSeconds": 9,
        }
        with self.assertRaisesRegex(commons.CommonsContractError, "rate_limit_exceeded") as raised:
            api._rate(store, "bucket", "partition", 3)
        self.assertEqual(9, raised.exception.retry_after)

        store.consume_commons_layered_rate_limit.return_value = {"allowed": True}
        self.assertIsNone(api._layered_rate(store, "source", "s", 1, 60, "project", "p", 2, 60, 4))
        store.consume_commons_layered_rate_limit.return_value = {
            "allowed": False,
            "retryAfterSeconds": 0,
        }
        with self.assertRaises(commons.CommonsContractError) as raised:
            api._layered_rate(store, "source", "s", 1, 60, "project", "p", 2, 60, 4)
        self.assertEqual(1, raised.exception.retry_after)


if __name__ == "__main__":
    unittest.main()
