import dataclasses
import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

from memoryendpoints.connector_authorize_ui import (
    ApprovalResultDisplay,
    CompanyOption,
    ConnectorAuthorizationRenderError,
    ConnectorAuthorizationView,
    PairingRequestDisplay,
    TransportAuthority,
    VIEW_STATES,
    WorkspaceOption,
    demo_authorization_view,
    production_authorization_view,
    render_connector_authorization,
)
from tests.test_connector_pairing_api import REDIRECT_URI, REQUESTED_SCOPES, SCOPE_DIGEST


PUBLIC_REQUEST_REF = "pairref_" + ("A" * 43)
WORKSPACE_REF = "workref_" + ("B" * 43)
COMPANY_REF = "companyref_" + ("C" * 43)
SCOPE_IMPACT_LABELS = (
    "Verify this exact connector, workspace, and agent binding.",
    "Register the exact LocalEndpoint agent during activation.",
    "Submit public-safe memory as this exact connector agent.",
    "Search memory readable by this exact connector grant.",
)
REQUIRED_VIEW_STATES = (
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


class _MarkupAudit(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = []
        self.label_fors = []
        self.inputs = []
        self.buttons = []
        self.links = []
        self.configs = []
        self._config = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"])
        if tag == "label" and values.get("for"):
            self.label_fors.append(values["for"])
        if tag in ("input", "select", "textarea"):
            self.inputs.append(values)
        if tag == "button":
            self.buttons.append(values)
        if tag == "a":
            self.links.append(values)
        if tag == "script" and "data-connector-authorization-config" in values:
            self._config = []

    def handle_data(self, data):
        if self._config is not None:
            self._config.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._config is not None:
            self.configs.append("".join(self._config))
            self._config = None


def _fields(cls):
    return tuple(item.name for item in dataclasses.fields(cls))


def _request(**overrides):
    desired = {
        "public_request_ref": PUBLIC_REQUEST_REF,
        "client_name": "LocalEndpoint Connect",
        "agent_display_name": "LocalEndpoint Agent",
        "status_label": "Pending approval",
        "expires_at_label": "Expires in 10 minutes",
        "scope_digest": SCOPE_DIGEST,
    }
    desired.update(overrides)
    if "public_request_ref" in _fields(PairingRequestDisplay):
        return PairingRequestDisplay(**desired)
    legacy = {
        "request_reference": desired["public_request_ref"],
        "client_name": desired["client_name"],
        "agent_id": "localendpoint-agent",
        "agent_display_name": desired["agent_display_name"],
        "expires_at_label": desired["expires_at_label"],
    }
    return PairingRequestDisplay(**legacy)


def _workspace(ref=WORKSPACE_REF, label="Main Workspace"):
    if "workspace_ref" in _fields(WorkspaceOption):
        return WorkspaceOption(workspace_ref=ref, label=label)
    return WorkspaceOption(workspace_id=ref, label=label)


def _company(ref=COMPANY_REF, label="Example Company"):
    if "company_ref" in _fields(CompanyOption):
        return CompanyOption(company_ref=ref, label=label)
    return CompanyOption(authority_id=ref, company_id="legacy-company-id", label=label)


def _result(**overrides):
    desired = {
        "workspace_label": "Main Workspace",
        "agent_display_name": "LocalEndpoint Agent",
        "wake_up_url": REDIRECT_URI,
        "scope_digest": SCOPE_DIGEST,
    }
    desired.update(overrides)
    if "wake_up_url" in _fields(ApprovalResultDisplay):
        return ApprovalResultDisplay(**desired)
    return ApprovalResultDisplay(WORKSPACE_REF, desired["workspace_label"], "localendpoint-agent")


def _runtime_state(state):
    if state in VIEW_STATES:
        return state
    return {"approved": "success", "canceled": "cancelled", "replay": "success"}.get(
        state, state
    )


def _production_view(state="pending", **overrides):
    runtime_state = _runtime_state(state)
    values = {
        "authenticated": True,
        "state": runtime_state,
        "request": _request(),
        "company_label": "Example Company",
        "workspaces": (_workspace(),),
        "result": _result() if state in ("approved", "replay") else None,
        "error_code": "service_error" if state == "error" else "",
    }
    values.update(overrides)
    return production_authorization_view(**values)


def _audit(body):
    parser = _MarkupAudit()
    parser.feed(body)
    return parser


class ConnectorAuthorizationUiTests(unittest.TestCase):
    def test_renderer_models_contain_only_public_refs_and_display_metadata(self):
        self.assertEqual(
            (
                "public_request_ref",
                "client_name",
                "agent_display_name",
                "status_label",
                "expires_at_label",
                "scope_digest",
            ),
            _fields(PairingRequestDisplay),
        )
        self.assertEqual(("workspace_ref", "label"), _fields(WorkspaceOption))
        self.assertEqual(("company_ref", "label"), _fields(CompanyOption))
        self.assertEqual(
            ("workspace_label", "agent_display_name", "wake_up_url", "scope_digest"),
            _fields(ApprovalResultDisplay),
        )
        for cls in (PairingRequestDisplay, WorkspaceOption, CompanyOption, ApprovalResultDisplay):
            joined = " ".join(_fields(cls)).lower()
            for forbidden in ("request_id", "workspace_id", "company_id", "agent_id"):
                self.assertNotIn(forbidden, joined)

    def test_signed_out_production_is_a_neutral_fail_closed_shell(self):
        canaries = (
            "request-internal-canary",
            "Company Canary",
            "workspace-internal-canary",
            "agent-internal-canary",
        )
        view = production_authorization_view(
            authenticated=False,
            request=_request(agent_display_name=canaries[3]),
            company_label=canaries[1],
            workspaces=(_workspace(canaries[2], "Workspace Canary"),),
        )
        body = render_connector_authorization(view)
        self.assertIn("data-human-preauth-shell", body)
        self.assertIn('data-connector-authenticated="false"', body)
        self.assertIn('name="username"', body)
        self.assertIn('name="password"', body)
        self.assertIn('name="companyMasterTokenSecret"', body)
        self.assertNotIn("data-connector-approval-form", body)
        self.assertNotIn('name="workspaceRef"', body)
        self.assertNotIn('name="canonicalAgentApproved"', body)
        for canary in canaries:
            self.assertNotIn(canary, body)

        parser = _audit(body)
        self.assertEqual(1, len(parser.configs))
        config = json.loads(parser.configs[0])
        self.assertFalse(config["authenticated"])
        self.assertNotIn("publicRequestRef", config)
        self.assertEqual("same_origin_human_session", config["transport"]["kind"])

    def test_signed_out_shell_has_no_submit_path_that_can_leak_raw_inputs(self):
        body = render_connector_authorization(production_authorization_view(authenticated=False))
        self.assertNotRegex(body, r"(?i)<form\b")
        self.assertNotRegex(body, r"(?i)\saction\s*=")
        self.assertNotRegex(body, r"(?i)https?://")
        parser = _audit(body)
        self.assertTrue(parser.buttons)
        self.assertTrue(all(button.get("type") == "button" for button in parser.buttons))

    def test_signed_out_proof_and_account_creation_actions_share_only_allowed_inputs(self):
        body = render_connector_authorization(production_authorization_view(authenticated=False))
        self.assertIn("data-connector-master-proof", body)
        self.assertIn("data-connector-account-create", body)
        self.assertIn('data-client-method="connectorAuthorization.beginEnrollment"', body)
        self.assertIn('data-client-method="connectorAuthorization.completeEnrollment"', body)
        self.assertNotRegex(body, r"(?i)<form\b")
        self.assertNotRegex(body, r"(?i)\saction\s*=")

        parser = _audit(body)
        self.assertEqual(
            {"username", "password", "passwordConfirmation", "companyMasterTokenSecret"},
            {field.get("name") for field in parser.inputs if field.get("name")},
        )
        config = json.loads(parser.configs[0])
        self.assertEqual(
            "connectorAuthorization.completeEnrollment",
            config["clientMethods"]["completeEnrollment"],
        )

    def test_authenticated_pending_uses_opaque_refs_exact_consent_and_fixed_scope_labels(self):
        body = render_connector_authorization(_production_view())
        self.assertIn("data-connector-authorize-renderer", body)
        self.assertIn("data-connector-approval-form", body)
        self.assertIn('data-client-method="connectorAuthorization.approve"', body)
        self.assertIn('data-client-method="connectorAuthorization.cancel"', body)
        self.assertIn('name="workspaceMode"', body)
        self.assertIn('name="workspaceRef"', body)
        self.assertIn('name="workspaceLabel"', body)
        self.assertIn('name="canonicalAgentApproved"', body)
        self.assertIn('name="scopeImpactApproved"', body)
        self.assertIn("Pending approval", body)
        self.assertIn(SCOPE_DIGEST, body)
        for label in SCOPE_IMPACT_LABELS:
            self.assertIn(label, body)
        for forbidden in (
            'name="workspaceId"',
            'name="companyId"',
            'name="agentId"',
            'name="approvedAgentId"',
            "localendpoint-agent",
            *REQUESTED_SCOPES,
        ):
            self.assertNotIn(forbidden, body)
        parser = _audit(body)
        config = json.loads(parser.configs[0])
        self.assertEqual(PUBLIC_REQUEST_REF, config.get("publicRequestRef"))
        self.assertNotIn("requestId", config)
        self.assertNotIn("workspaceId", config)
        self.assertNotIn("companyId", config)
        self.assertNotIn("agentId", config)

    def test_authenticated_markup_has_unique_ids_and_bound_labels(self):
        for view in (_production_view(), production_authorization_view(authenticated=False)):
            with self.subTest(authenticated=view.authenticated):
                parser = _audit(render_connector_authorization(view))
                self.assertEqual(len(parser.ids), len(set(parser.ids)))
                for target in parser.label_fors:
                    self.assertIn(target, parser.ids)
                for field in parser.inputs:
                    if field.get("name") and field.get("type") not in ("radio", "hidden"):
                        self.assertTrue(field.get("id"))

    def test_renderer_exposes_scoped_responsive_stylesheet_hooks(self):
        pending = render_connector_authorization(_production_view())
        signed_out = render_connector_authorization(
            production_authorization_view(authenticated=False)
        )
        for marker in (
            "connector-authorize-shell",
            "connector-authorize-header",
            "connector-pending-layout",
            "connector-detail-grid",
            "connector-fieldset",
            "connector-choice",
            "connector-scope-impact",
            "connector-actions",
        ):
            self.assertIn(marker, pending)
        self.assertIn("connector-auth-grid", signed_out)
        self.assertIn("connector-panel", signed_out)
        self.assertIn("connector-form-stack", signed_out)

        stylesheet = (
            Path(__file__).resolve().parents[1]
            / "static"
            / "css"
            / "connector-authorize.css"
        ).read_text(encoding="utf-8")
        self.assertIn(".connector-authorize", stylesheet)
        self.assertIn("min-height: 44px", stylesheet)
        self.assertIn("overflow-wrap: anywhere", stylesheet)
        self.assertIn("@media (max-width: 720px)", stylesheet)
        self.assertIn("@media (max-width: 360px)", stylesheet)
        self.assertIn("@media (prefers-reduced-motion: reduce)", stylesheet)
        self.assertNotIn("@import", stylesheet)
        self.assertNotRegex(stylesheet, r"(?i)url\s*\(")

    def test_display_values_are_escaped_and_config_is_script_safe(self):
        view = _production_view(
            request=_request(
                client_name='Client <script>alert(1)</script> & "quoted"',
            ),
            company_label="Company </script><script>bad()</script>",
            workspaces=(_workspace(label="Workspace <Alpha> & Beta"),),
        )
        body = render_connector_authorization(view)
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertNotIn("</script><script>bad()", body)
        parser = _audit(body)
        self.assertEqual(1, len(parser.configs))
        config = json.loads(parser.configs[0])
        self.assertEqual(PUBLIC_REQUEST_REF, config.get("publicRequestRef"))

    def test_view_states_are_exact_and_every_demo_state_reuses_the_renderer(self):
        self.assertEqual(REQUIRED_VIEW_STATES, tuple(VIEW_STATES))
        for state in REQUIRED_VIEW_STATES:
            with self.subTest(state=state):
                body = render_connector_authorization(demo_authorization_view(state))
                self.assertIn("data-connector-authorize-renderer", body)
                self.assertIn("Mock data:", body)
                self.assertIn('data-client-method="connectorAuthorization.resetDemo"', body)
                self.assertNotIn("/api/", body)
                self.assertNotRegex(body, r"(?i)https?://")
                self.assertNotIn("me_connector_v1.", body)
                self.assertNotIn("me_pairproof_v1.", body)
                self.assertNotIn("me_paircode_v1.", body)
                self.assertNotIn("localendpoint-agent", body)
                for scope in REQUESTED_SCOPES:
                    self.assertNotIn(scope, body)
                parser = _audit(body)
                config = json.loads(parser.configs[0])
                self.assertEqual("mock_browser_session", config["transport"]["kind"])
                self.assertFalse(config["transport"]["protectedNetworkAllowed"])
                self.assertEqual("browser_session", config["transport"]["sessionScope"])
                self.assertTrue(config["transport"]["resettable"])
                self.assertTrue(config["transport"]["labelledMock"])

    def test_demo_pending_uses_production_controls_and_fixed_impact_copy(self):
        production = render_connector_authorization(_production_view())
        demo = render_connector_authorization(demo_authorization_view("pending"))
        for marker in (
            "data-connector-approval-form",
            'data-client-method="connectorAuthorization.approve"',
            'data-client-method="connectorAuthorization.cancel"',
            'name="workspaceMode"',
            'name="workspaceRef"',
            'name="workspaceLabel"',
            'name="canonicalAgentApproved"',
            'name="scopeImpactApproved"',
            "data-validation-summary",
            'data-error-for="workspace"',
        ) + SCOPE_IMPACT_LABELS:
            self.assertIn(marker, production)
            self.assertIn(marker, demo)

    def test_demo_states_have_accessible_fixed_messages(self):
        expected = {
            "company_selection": "Choose the company to approve for",
            "reauth_required": "Confirm your password",
            "approved": "Connection approved",
            "error": "Approval could not be completed",
            "expired": "This connection request expired",
            "canceled": "Connection request canceled",
            "replay": "Approval already completed",
            "permission_denied": "Approval permission required",
        }
        for state, heading in expected.items():
            with self.subTest(state=state):
                body = render_connector_authorization(demo_authorization_view(state))
                self.assertIn(heading, body)
                self.assertIn('data-connector-state="%s"' % state.replace("_", "-"), body)

    def test_approved_result_has_explicit_safe_return_and_never_auto_navigates(self):
        body = render_connector_authorization(_production_view("approved"))
        self.assertIn("data-connector-return-action", body)
        self.assertIn('href="%s"' % REDIRECT_URI, body)
        self.assertNotIn(REDIRECT_URI + "?", body)
        self.assertNotIn(REDIRECT_URI + "#", body)
        self.assertRegex(body, r'rel="[^"]*\bnoopener\b[^"]*"')
        self.assertRegex(body, r'rel="[^"]*\bnoreferrer\b[^"]*"')
        self.assertIn('referrerpolicy="no-referrer"', body)
        self.assertNotRegex(body, r"(?i)<meta[^>]+http-equiv=[\"']?refresh")
        self.assertNotIn("location.assign", body)
        self.assertNotIn("location.replace", body)
        self.assertIn("No credential or private workspace payload", body)
        for forbidden in (WORKSPACE_REF, "localendpoint-agent", *REQUESTED_SCOPES):
            self.assertNotIn(forbidden, body)

    def test_permission_denial_does_not_require_or_render_tenant_metadata(self):
        body = render_connector_authorization(
            production_authorization_view(
                authenticated=True,
                state="permission_denied",
            )
        )
        self.assertIn("Approval permission required", body)
        self.assertNotIn("data-connector-approval-form", body)
        self.assertNotIn("Selected company", body)

    def test_neutral_terminal_states_are_scrubbed_before_render_and_config(self):
        for state in ("error", "expired", "canceled", "permission_denied"):
            with self.subTest(state=state):
                view = demo_authorization_view(state)
                self.assertIsNone(view.request)
                self.assertIsNone(view.result)
                self.assertEqual("", view.company_label)
                self.assertEqual((), view.companies)
                self.assertEqual((), view.workspaces)

                body = render_connector_authorization(view)
                self.assertIn("data-connector-authorize-renderer", body)
                self.assertIn("Mock data:", body)
                self.assertNotIn("pairref_", body)
                self.assertNotIn("companyref_", body)
                self.assertNotIn("workref_", body)
                config = json.loads(_audit(body).configs[0])
                self.assertNotIn("publicRequestRef", config)
                self.assertNotIn("scopeDigest", config)

        with self.assertRaisesRegex(
            ConnectorAuthorizationRenderError, "terminal_state_not_scrubbed"
        ):
            render_connector_authorization(
                production_authorization_view(
                    authenticated=True,
                    state="expired",
                    request=_request(),
                )
            )

    def test_pending_validation_error_is_fixed_and_not_reflected(self):
        body = render_connector_authorization(
            demo_authorization_view("pending", field_error_code="workspace_required")
        )
        self.assertIn("Choose an existing workspace or create a new one.", body)
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "field_error_code_invalid"):
            render_connector_authorization(
                demo_authorization_view("pending", field_error_code="<script>bad()</script>")
            )

    def test_authority_and_state_are_closed_enums(self):
        unsafe_authority = TransportAuthority(
            kind="fetch_anywhere",
            protected_network_allowed=True,
            session_scope="local_storage",
            resettable=False,
            labelled_mock=False,
        )
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "authority_invalid"):
            render_connector_authorization(
                ConnectorAuthorizationView(authority=unsafe_authority, authenticated=False)
            )
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "view_state_invalid"):
            render_connector_authorization(
                production_authorization_view(authenticated=False, state="unknown")
            )

    def test_authenticated_views_reject_invalid_or_duplicate_opaque_refs(self):
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "request_required"):
            render_connector_authorization(production_authorization_view(authenticated=True))
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "public_request_ref_invalid"):
            render_connector_authorization(
                _production_view(request=_request(public_request_ref="short"))
            )
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "workspace_duplicate"):
            render_connector_authorization(
                _production_view(workspaces=(_workspace(), _workspace(label="Two")))
            )
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "workspace_ref_invalid"):
            render_connector_authorization(
                _production_view(workspaces=(_workspace("workspace-internal-id"),))
            )
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "company_duplicate"):
            render_connector_authorization(
                production_authorization_view(
                    authenticated=True,
                    state="company_selection",
                    companies=(_company(), _company(label="Company Two")),
                )
            )
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "company_ref_invalid"):
            render_connector_authorization(
                production_authorization_view(
                    authenticated=True,
                    state="company_selection",
                    companies=(_company("company-internal-id"),),
                )
            )
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "scope_digest_invalid"):
            render_connector_authorization(
                _production_view(request=_request(scope_digest="sha256-v1:" + ("0" * 64)))
            )
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "agent_display_name_invalid"):
            render_connector_authorization(
                _production_view(request=_request(agent_display_name="Renamed Connector Agent"))
            )
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "wake_up_url_invalid"):
            render_connector_authorization(
                _production_view(
                    "approved", result=_result(wake_up_url=REDIRECT_URI + "?code=forbidden")
                )
            )
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "error_code_invalid"):
            render_connector_authorization(_production_view(error_code="raw_backend_message"))


if __name__ == "__main__":
    unittest.main()
