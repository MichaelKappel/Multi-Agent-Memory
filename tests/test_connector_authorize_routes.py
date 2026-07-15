import io
import inspect
import json
import re
import unittest
from unittest import mock
from urllib.parse import urlsplit

from app import application
import memoryendpoints.app as app_module
from tests.test_connector_pairing_api import (
    REDIRECT_URI,
    REQUEST_BODY_LIMIT,
    REQUESTED_SCOPES,
    SITE_ORIGIN,
    SCOPE_DIGEST,
    ConnectorPairingApiContract,
    _header,
    call_raw,
)


SCOPE_IMPACT_LABELS = (
    "Verify this exact connector, workspace, and agent binding.",
    "Register the exact LocalEndpoint agent during activation.",
    "Submit public-safe memory as this exact connector agent.",
    "Search memory readable by this exact connector grant.",
)


def call_html(path, cookie="", query=""):
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "wsgi.input": io.BytesIO(b""),
        "CONTENT_LENGTH": "0",
    }
    if cookie:
        environ["HTTP_COOKIE"] = cookie
    raw = b"".join(application(environ, start_response))
    return captured["status"], captured["headers"], raw.decode("utf-8")


class ConnectorAuthorizeRouteContract(ConnectorPairingApiContract):
    # This suite reuses only the connector fixture/helpers; the API contract
    # itself runs independently in tests.test_connector_pairing_api.
    test_approval_wakeup_is_parameter_free_and_claim_retry_rederives_code = None
    test_auth_concealment_permissions_rate_limit_and_service_errors = None
    test_claim_binding_is_fail_closed_without_revealing_which_value_failed = None
    test_claim_expiry_cancellation_and_redeemed_states_are_typed_safe_no_ops = None
    test_claim_idempotency_conflicts_and_replay_are_stable = None
    test_claim_body_limit_precedes_schema_dispatch = None
    test_claim_requires_json_and_idempotency = None
    test_concurrent_claims_issue_exactly_one_code = None
    test_connector_disconnect_is_immediate_idempotent_no_op = None
    test_connector_public_safe_submit_rejects_private_raw_or_actor_supplied_payloads = None
    test_connector_request_body_limit_precedes_schema_dispatch = None
    test_connector_scope_threat_model_denies_every_unlisted_surface_before_validation = None
    test_connector_scopes_allow_only_self_confirmation_public_safe_submit_and_search = None
    test_credential_service_failure_is_redacted_and_retryable = None
    test_every_connector_mutation_enforces_exact_versioned_body_schema = None
    test_happy_path_is_crash_safe_and_exact_readback_proves_scope = None
    test_human_can_create_workspace_during_approval_without_leaking_identifiers_to_wakeup = None
    test_master_revocation_is_immediate_idempotent_no_op = None
    test_only_normalized_exact_canonical_agent_identity_is_accepted = None
    test_pending_claim_does_not_reserve_idempotency_key_and_approval_releases_code = None
    test_pkce_validation_and_code_replay_rules_are_stable = None
    test_public_discovery_is_same_origin_versioned_bounded_and_secret_free = None
    test_request_code_and_pending_grant_ttls_are_enforced = None
    test_request_validation_json_and_idempotency_are_safe_no_ops = None
    test_rotation_is_two_phase_and_old_credential_survives_until_activation = None
    test_secure_store_failure_can_cancel_and_abandoned_grant_expires = None
    test_workspace_ref_is_request_and_human_session_bound = None

    def assert_authorize_security_headers(self, headers):
        cache_control = _header(headers, "Cache-Control", "")
        self.assertIn("no-store", cache_control)
        self.assertIn("private", cache_control)
        self.assertEqual("no-referrer", _header(headers, "Referrer-Policy"))
        self.assertEqual("same-origin", _header(headers, "Cross-Origin-Opener-Policy"))
        self.assertEqual("same-origin", _header(headers, "Cross-Origin-Resource-Policy"))
        self.assertEqual("nosniff", _header(headers, "X-Content-Type-Options"))
        permissions = _header(headers, "Permissions-Policy", "")
        for directive in ("camera=()", "microphone=()", "geolocation=()", "payment=()", "usb=()"):
            self.assertIn(directive, permissions)
        csp = _header(headers, "Content-Security-Policy", "")
        for directive in (
            "default-src 'none'",
            "base-uri 'none'",
            "form-action 'self'",
            "frame-ancestors 'none'",
            "object-src 'none'",
        ):
            self.assertIn(directive, csp)
        self.assertRegex(csp, r"(?:^|;)\s*script-src\s+'self'(?:\s|;|$)")
        self.assertRegex(csp, r"(?:^|;)\s*style-src\s+'self'(?:\s|;|$)")
        self.assertRegex(csp, r"(?:^|;)\s*connect-src\s+'self'(?:\s|;|$)")
        vary = {
            item.strip().lower()
            for item in _header(headers, "Vary", "").split(",")
            if item.strip()
        }
        self.assertIn("cookie", vary)

    def assert_connector_stylesheet(self, body):
        self.assertRegex(
            body,
            r'<link rel="stylesheet" href="/static/css/connector-authorize\.css\?v=[^"]+">',
        )

    def _approve_for_route_render(self, request, key):
        from tests.test_connector_pairing_api import call_api

        approval = call_api(
            "/api/matm/human/connector-pairings/%s/approve"
            % request["publicRequestRef"],
            "POST",
            {
                "schemaVersion": "memoryendpoints.connector_pairing.v1",
                "canonicalAgentApproved": True,
                "approvedScopes": list(REQUESTED_SCOPES),
                "workspaceSelection": {
                    "mode": "existing",
                    "workspaceRef": self._existing_workspace_ref(request),
                },
            },
            extra_headers=self._human_mutation_headers(key),
        )
        self._assert_json(approval[0], approval[1], approval[3], 200)
        self.assertEqual("approved_awaiting_connector_claim", approval[2]["status"])
        self.assertEqual(REDIRECT_URI, approval[2]["wakeUpUrl"])
        return approval

    def assert_request_neutral_html(self, body, public_request_ref):
        for forbidden in (
            public_request_ref,
            self.company_id,
            self.workspace_id,
            self.project_id,
            "LocalEndpoint Test Company",
            "LocalEndpoint Workspace",
            "companyref_",
            "workref_",
            '"publicRequestRef"',
            '"scopeDigest"',
        ):
            self.assertNotIn(forbidden, body)

    def test_forbidden_bearer_precedes_malformed_or_oversized_human_mutation_body(self):
        request, _verifier, _state = self._start_request()
        public_ref = request["publicRequestRef"]
        mutation_paths = (
            (
                "/api/matm/human/connector-pairings/%s/approve" % public_ref,
                "approve_connector_pairing_request",
            ),
            (
                "/api/matm/human/connector-pairings/%s/cancel" % public_ref,
                "cancel_connector_pairing_request",
            ),
        )
        bodies = (
            b'{"schemaVersion":',
            b'{"oversized":"' + (b"x" * (REQUEST_BODY_LIMIT + 1)) + b'"}',
        )
        synthetic_bearer = "synthetic-forbidden-browser-bearer"
        store_type = type(self._new_store())

        with mock.patch.object(
            app_module,
            "_connector_operation_rate_limited",
            side_effect=AssertionError("rate limiting must follow human-owner auth"),
        ), mock.patch.object(
            store_type,
            "approve_connector_pairing_request",
            side_effect=AssertionError("approval storage must follow human-owner auth"),
        ), mock.patch.object(
            store_type,
            "cancel_connector_pairing_request",
            side_effect=AssertionError("cancellation storage must follow human-owner auth"),
        ):
            for path, mutation_name in mutation_paths:
                for raw in bodies:
                    with self.subTest(mutation=mutation_name, size=len(raw)):
                        response = call_raw(
                            path,
                            "POST",
                            raw,
                            token=synthetic_bearer,
                        )
                        self._assert_error(
                            response,
                            403,
                            "human_owner_required",
                            (synthetic_bearer, public_ref),
                        )

    def test_authorize_html_explicitly_varies_on_cookie(self):
        request, _verifier, _state = self._start_request()
        for path in (
            "/connect/authorize/" + request["publicRequestRef"],
            "/tour/connect/authorize/signed_out",
        ):
            with self.subTest(path=path):
                status, headers, _body = call_html(path)
                self.assertEqual("200 OK", status)
                self.assert_authorize_security_headers(headers)
                self.assert_connector_stylesheet(_body)

    def test_authorize_route_rejects_query_and_legacy_demo_aliases(self):
        for source in (
            inspect.getsource(app_module.route_connector_authorize),
            inspect.getsource(app_module.application),
        ):
            self.assertNotIn("opaque_handle", source)

        request, _verifier, _state = self._start_request()
        status, headers, body = call_html(
            "/connect/authorize/" + request["publicRequestRef"],
            query="code=must-never-enter-a-url",
        )
        self.assertEqual("422 Unprocessable Entity", status)
        self.assertIn("no-store", _header(headers, "Cache-Control", ""))
        self.assertEqual("no-referrer", _header(headers, "Referrer-Policy"))
        self.assertNotIn(request["publicRequestRef"], body)
        self.assertNotIn("must-never-enter-a-url", body)
        for alias in ("success", "cancelled"):
            with self.subTest(alias=alias):
                alias_status, _alias_headers, _alias_body = call_html(
                    "/tour/connect/authorize/" + alias
                )
                self.assertEqual("404 Not Found", alias_status)

    def test_signed_out_is_neutral_then_authenticated_session_can_review_exact_request(self):
        # Recover the exact authorization URL through an idempotent replay.
        body, verifier, state = self._request_body()
        key = "authorize-route-replay"
        first = self._start_request(verifier=verifier, state=state, key=key)[0]
        stored = json.loads(self.store_path.read_text(encoding="utf-8")) if self.backend == "file" else None
        if stored is not None:
            record = stored["connectorPairingRequests"][self._internal_request_id(first)]
            self.assertNotIn("requestSecret", record)
        from tests.test_connector_pairing_api import call_api

        replay = call_api(
            "/api/matm/connector-pairings/requests",
            "POST",
            body,
            extra_headers=self._idempotency_headers(key),
        )
        self.assertEqual(201, replay[0], replay[2])
        self.assertEqual(first, replay[2]["pairingRequest"])
        path = urlsplit(replay[2]["authorizationUrl"]).path
        public_request_ref = path.rsplit("/", 1)[-1]
        self.assertEqual(first["publicRequestRef"], public_request_ref)
        claim_material = self._claim_material[public_request_ref]

        status, headers, signed_out = call_html(path)
        self.assertEqual("200 OK", status)
        self.assert_authorize_security_headers(headers)
        self.assertIn("data-human-preauth-shell", signed_out)
        for forbidden in (
            self._internal_request_id(first),
            self.workspace_id,
            self.company_id,
            self.project_id,
            "localendpoint-agent",
            claim_material["pairingRequestProof"],
            claim_material["state"],
            *REQUESTED_SCOPES,
            "authorityId",
            "companyId",
            "workspaceId",
            "projectId",
            "requestId",
            "agentId",
            "requestReference",
        ):
            self.assertNotIn(forbidden, signed_out)

        cookie = "__Host-memoryendpoints-human=" + self.human_session_secret
        status, headers, authenticated = call_html(path, cookie)
        self.assertEqual("200 OK", status)
        self.assert_authorize_security_headers(headers)
        self.assertIn("data-connector-approval-form", authenticated)
        self.assertIn("LocalEndpoint Connect", authenticated)
        self.assertIn("LocalEndpoint Agent", authenticated)
        self.assertIn("Pending approval", authenticated)
        self.assertIn(public_request_ref, authenticated)
        self.assertIn(SCOPE_DIGEST, authenticated)
        self.assertRegex(
            authenticated,
            r'name="workspaceRef"[^>]*>[\s\S]*value="workref_[A-Za-z0-9_-]{43}"',
        )
        for label in SCOPE_IMPACT_LABELS:
            self.assertIn(label, authenticated)
        for forbidden in (
            self._internal_request_id(first),
            self.workspace_id,
            self.company_id,
            self.project_id,
            "localendpoint-agent",
            claim_material["pairingRequestProof"],
            claim_material["state"],
            "connectorCredentialSecret",
            'companyMasterTokenSecret":',
            *REQUESTED_SCOPES,
            "authorityId",
            "companyId",
            "workspaceId",
            "projectId",
            "requestId",
            "agentId",
            "requestReference",
            "callbackUrl",
        ):
            self.assertNotIn(forbidden, authenticated)
        self.assertIsNone(re.search(r'<meta[^>]+http-equiv=["\']?refresh', authenticated, re.I))

    def test_approved_page_requires_an_explicit_parameter_free_return_action(self):
        request, _verifier, _state = self._start_request()
        self._approve_for_route_render(request, "authorize-route-approved-render")
        path = "/connect/authorize/" + request["publicRequestRef"]
        cookie = "__Host-memoryendpoints-human=" + self.human_session_secret
        status, headers, body = call_html(path, cookie)
        self.assertEqual("200 OK", status)
        self.assert_authorize_security_headers(headers)
        self.assertIn("Approved", body)
        self.assertIn("data-connector-return-action", body)
        self.assertIn('href="%s"' % REDIRECT_URI, body)
        self.assertRegex(body, r'rel="[^"]*\bnoopener\b[^"]*"')
        self.assertRegex(body, r'rel="[^"]*\bnoreferrer\b[^"]*"')
        self.assertIn('referrerpolicy="no-referrer"', body)
        self.assertNotIn(REDIRECT_URI + "?", body)
        self.assertNotIn(REDIRECT_URI + "#", body)
        self.assertIsNone(re.search(r'<meta[^>]+http-equiv=["\']?refresh', body, re.I))
        self.assertNotIn("location.replace", body)
        self.assertNotIn("location.assign", body)
        self.assertNotIn("callbackUrl", body)

        store_type = type(self._new_store())
        original_context = store_type.connector_pairing_authorization_context

        def context_without_workspace_label(store, session_secret, public_request_ref):
            result = original_context(store, session_secret, public_request_ref)
            if not result.get("ok"):
                return result
            redacted = dict(result)
            context = dict(result.get("authorizationContext") or {})
            context.pop("workspaceLabel", None)
            redacted["authorizationContext"] = context
            return redacted

        with mock.patch.object(
            store_type,
            "connector_pairing_authorization_context",
            context_without_workspace_label,
        ):
            missing_status, missing_headers, missing_body = call_html(path, cookie)
        self.assertEqual("200 OK", missing_status)
        self.assert_authorize_security_headers(missing_headers)
        self.assertIn('data-connector-state="error"', missing_body)
        self.assertNotIn("data-connector-return-action", missing_body)
        self.assertNotIn(REDIRECT_URI, missing_body)

    def test_post_claim_get_never_republishes_the_wake_url(self):
        request, _verifier, _state = self._start_request()
        self._approve_for_route_render(request, "authorize-route-post-claim")
        claim = self._claim_response(request, "authorize-route-code-claim")
        self._assert_json(claim[0], claim[1], claim[3], 200)
        self.assertEqual("authorization_code_issued", claim[2]["status"])
        status, headers, body = call_html(
            "/connect/authorize/" + request["publicRequestRef"],
            "__Host-memoryendpoints-human=" + self.human_session_secret,
        )
        self.assertEqual("200 OK", status)
        self.assert_authorize_security_headers(headers)
        self.assertIn('data-connector-state="error"', body)
        self.assertNotIn("data-connector-return-action", body)
        self.assertNotIn(REDIRECT_URI, body)
        self.assert_request_neutral_html(body, request["publicRequestRef"])

    def test_company_selection_uses_only_short_lived_session_bound_company_refs(self):
        from tests.test_connector_pairing_api import call_api

        request, _verifier, _state = self._start_request()
        fresh = self._new_store().login_human_account(
            "localendpoint-owner", self.password
        )
        self.assertTrue(fresh["ok"], fresh)
        memberships = self._new_store().list_human_company_memberships(
            fresh["sessionSecret"]
        )
        self.assertTrue(memberships["ok"], memberships)
        status, headers, body = call_html(
            "/connect/authorize/" + request["publicRequestRef"],
            "__Host-memoryendpoints-human=" + fresh["sessionSecret"],
        )
        self.assertEqual("200 OK", status)
        self.assert_authorize_security_headers(headers)
        self.assertIn("data-connector-company-selection", body)
        self.assertIn('name="companyRef"', body)
        self.assertNotIn('name="authorityId"', body)
        self.assertNotIn('name="companyId"', body)
        match = re.search(r'value="(companyref_[A-Za-z0-9_-]{43})"', body)
        self.assertIsNotNone(match)
        company_ref = match.group(1)
        for item in memberships["items"]:
            self.assertNotIn(item["authorityId"], body)
            self.assertNotIn(item["companyId"], body)
        for forbidden in (
            self._internal_request_id(request),
            self.workspace_id,
            self.project_id,
            "localendpoint-agent",
            *REQUESTED_SCOPES,
        ):
            self.assertNotIn(forbidden, body)

        other = self._new_store().login_human_account(
            "localendpoint-owner", self.password
        )
        self.assertTrue(other["ok"], other)

        def selection_headers(session, key):
            return {
                "HTTP_COOKIE": "__Host-memoryendpoints-human="
                + session["sessionSecret"],
                "HTTP_X_CSRF_TOKEN": session["csrfToken"],
                "HTTP_ORIGIN": SITE_ORIGIN,
                "HTTP_SEC_FETCH_SITE": "same-origin",
                "HTTP_SEC_FETCH_MODE": "cors",
                "HTTP_SEC_FETCH_DEST": "empty",
                "HTTP_IDEMPOTENCY_KEY": key,
            }

        selection_path = (
            "/api/matm/human/connector-pairings/%s/company-selection"
            % request["publicRequestRef"]
        )
        selection_body = {
            "schemaVersion": "memoryendpoints.connector_pairing.v1",
            "companyRef": company_ref,
        }
        self._assert_error(
            call_api(
                selection_path,
                "POST",
                selection_body,
                extra_headers=selection_headers(
                    other, "cross-session-company-ref-selection"
                ),
            ),
            401,
            "company_ref_invalid",
            (company_ref, self.company_id),
        )
        self._assert_error(
            call_api(
                selection_path,
                "POST",
                dict(selection_body, authorityId=memberships["items"][0]["authorityId"]),
                extra_headers=selection_headers(
                    fresh, "company-selection-rejects-internal-id"
                ),
            ),
            422,
            "invalid_request",
            (memberships["items"][0]["authorityId"], company_ref),
        )
        selected = call_api(
            selection_path,
            "POST",
            selection_body,
            extra_headers=selection_headers(
                fresh, "own-session-company-ref-selection"
            ),
        )
        self._assert_json(selected[0], selected[1], selected[3], 200)
        self.assertTrue(selected[2]["sessionRotated"])
        self.assertNotIn("csrfRotated", selected[2])
        self.assertNotEqual(fresh["csrfToken"], selected[2]["csrfToken"])
        self.assertIn(
            "__Host-memoryendpoints-human=",
            _header(selected[1], "Set-Cookie", ""),
        )
        encoded = json.dumps(selected[2], sort_keys=True)
        self.assertNotIn(company_ref, encoded)

    def test_explicit_demo_states_use_mock_authority_and_no_protected_urls(self):
        states = (
            "signed_out",
            "company_selection",
            "reauth_required",
            "pending",
            "approved",
            "error",
            "expired",
            "canceled",
            "replay",
            "permission_denied",
        )
        for state in states:
            with self.subTest(state=state):
                status, headers, body = call_html("/tour/connect/authorize/" + state)
                self.assertEqual("200 OK", status)
                self.assertIn("Mock data:", body)
                self.assertIn('"kind":"mock_browser_session"', body)
                self.assertIn('"protectedNetworkAllowed":false', body)
                self.assertNotIn("/api/matm/", body)
                self.assertNotIn("me_connector_v1.", body)
                self.assertNotIn("me_pairproof_v1.", body)
                self.assertNotIn("me_paircode_v1.", body)
                self.assertNotIn("localendpoint-agent", body)
                for scope in REQUESTED_SCOPES:
                    self.assertNotIn(scope, body)
                self.assertIn("data-connector-authorize-renderer", body)
                self.assert_authorize_security_headers(headers)

    def test_same_session_csrf_rotation_invalidates_the_previous_value(self):
        rotated = self._new_store().rotate_human_account_session_csrf(self.human_session_secret)
        self.assertTrue(rotated["ok"], rotated)
        fresh = rotated["csrfToken"]
        self.assertNotEqual(self.human_csrf, fresh)
        verifier = self._new_store()
        self.assertFalse(
            verifier.authenticate_human_account_session(
                self.human_session_secret, self.human_csrf, require_csrf=True
            )
        )
        self.assertTrue(
            verifier.authenticate_human_account_session(
                self.human_session_secret, fresh, require_csrf=True
            )
        )

    def test_same_origin_session_inspection_delivers_fresh_in_memory_csrf(self):
        from tests.test_connector_pairing_api import call_api

        response = call_api(
            "/api/matm/human/session",
            extra_headers={
                "HTTP_COOKIE": "__Host-memoryendpoints-human=" + self.human_session_secret,
                "HTTP_SEC_FETCH_SITE": "same-origin",
                "HTTP_SEC_FETCH_MODE": "cors",
                "HTTP_SEC_FETCH_DEST": "empty",
            },
        )
        self.assertEqual(200, response[0], response[2])
        fresh = response[2]["csrfToken"]
        self.assertTrue(response[2]["csrfRotated"])
        self.assertNotEqual(self.human_csrf, fresh)
        verifier = self._new_store()
        self.assertFalse(
            verifier.authenticate_human_account_session(
                self.human_session_secret, self.human_csrf, require_csrf=True
            )
        )
        self.assertTrue(
            verifier.authenticate_human_account_session(
                self.human_session_secret, fresh, require_csrf=True
            )
        )

    def test_human_cancel_is_exactly_idempotent_before_any_grant_exists(self):
        from tests.test_connector_pairing_api import call_api

        request, _verifier, _state = self._start_request()
        path = "/api/matm/human/connector-pairings/%s/cancel" % request["publicRequestRef"]
        headers = self._human_mutation_headers("human-cancel-idempotency")
        body = {"schemaVersion": "memoryendpoints.connector_pairing.v1", "reason": "human_cancelled"}
        first = call_api(path, "POST", body, extra_headers=headers)
        self.assertEqual(200, first[0], first[2])
        self.assertEqual("canceled", first[2]["pairingRequest"]["status"])
        self._assert_receipt(first[2], "cancel", "canceled", False, SCOPE_DIGEST)
        retry = call_api(path, "POST", body, extra_headers=headers)
        self.assertEqual(200, retry[0], retry[2])
        self.assertTrue(retry[2]["idempotentReplay"])
        self.assertEqual(first[2]["receipt"]["receiptId"], retry[2]["receipt"]["receiptId"])
        self._assert_receipt(retry[2], "cancel", "canceled", True, SCOPE_DIGEST)
        self.assertEqual(0, self._agent_registration_count("localendpoint-agent"))
        html_status, html_headers, html_body = call_html(
            "/connect/authorize/" + request["publicRequestRef"],
            "__Host-memoryendpoints-human=" + self.human_session_secret,
        )
        self.assertEqual("200 OK", html_status)
        self.assert_authorize_security_headers(html_headers)
        self.assertIn('data-connector-state="canceled"', html_body)
        self.assertNotIn("data-connector-return-action", html_body)
        self.assert_request_neutral_html(html_body, request["publicRequestRef"])


class FileConnectorAuthorizeRouteTests(ConnectorAuthorizeRouteContract, unittest.TestCase):
    backend = "file"


class SQLiteConnectorAuthorizeRouteTests(ConnectorAuthorizeRouteContract, unittest.TestCase):
    backend = "sqlite"


if __name__ == "__main__":
    unittest.main()
