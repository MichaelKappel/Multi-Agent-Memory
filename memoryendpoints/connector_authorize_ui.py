"""Fail-closed HTML renderer for LocalEndpoint connector authorization.

The renderer accepts only tenant-neutral display metadata and short-lived,
request-bound opaque references. Production and Demo use the same models,
markup, selectors, and logical client methods; only their injected transport
authority differs.
"""

from __future__ import annotations

import dataclasses
import html
import json
import re
from typing import Optional, Tuple

from .connector_pairing import PairingPolicyError, build_wake_up_url


VIEW_STATES = (
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

SCOPE_DIGEST = (
    "sha256-v1:"
    "1358698c6ddba1a74a688d3718a739f78e4ef50d0773b22c96e025b38aa86594"
)
SCOPE_IMPACT_LABELS = (
    "Verify this exact connector, workspace, and agent binding.",
    "Register the exact LocalEndpoint agent during activation.",
    "Submit public-safe memory as this exact connector agent.",
    "Search memory readable by this exact connector grant.",
)
CANONICAL_AGENT_DISPLAY_NAME = "LocalEndpoint Agent"

_ERROR_MESSAGES = {
    "invalid_request": "This connection request is not valid.",
    "request_conflict": "This connection request conflicts with a newer action.",
    "service_error": "The connection service is temporarily unavailable.",
    "rate_limited": "Too many attempts were made. Wait before trying again.",
}
_PUBLIC_REQUEST_REF = re.compile(r"\Apairref_[A-Za-z0-9_-]{43}\Z")
_COMPANY_REF = re.compile(r"\Acompanyref_[A-Za-z0-9_-]{43}\Z")
_WORKSPACE_REF = re.compile(r"\Aworkref_[A-Za-z0-9_-]{43}\Z")
_NEUTRAL_TERMINAL_STATES = ("error", "expired", "canceled", "permission_denied")


class ConnectorAuthorizationRenderError(ValueError):
    """Raised when a route attempts to render unsafe or incoherent data."""


@dataclasses.dataclass(frozen=True)
class TransportAuthority:
    """Declarative boundary consumed by the shared browser client."""

    kind: str
    protected_network_allowed: bool
    session_scope: str
    resettable: bool
    labelled_mock: bool


PRODUCTION_AUTHORITY = TransportAuthority(
    kind="same_origin_human_session",
    protected_network_allowed=True,
    session_scope="server_account_session",
    resettable=False,
    labelled_mock=False,
)

DEMO_AUTHORITY = TransportAuthority(
    kind="mock_browser_session",
    protected_network_allowed=False,
    session_scope="browser_session",
    resettable=True,
    labelled_mock=True,
)


@dataclasses.dataclass(frozen=True)
class PairingRequestDisplay:
    public_request_ref: str
    client_name: str
    agent_display_name: str
    status_label: str
    expires_at_label: str
    scope_digest: str


@dataclasses.dataclass(frozen=True)
class WorkspaceOption:
    workspace_ref: str
    label: str


@dataclasses.dataclass(frozen=True)
class CompanyOption:
    company_ref: str
    label: str


@dataclasses.dataclass(frozen=True)
class ApprovalResultDisplay:
    workspace_label: str
    agent_display_name: str
    wake_up_url: str
    scope_digest: str


@dataclasses.dataclass(frozen=True)
class ConnectorAuthorizationView:
    """Complete immutable input for one connector authorization render."""

    authority: TransportAuthority
    authenticated: bool
    state: str = "pending"
    request: Optional[PairingRequestDisplay] = None
    company_label: str = ""
    companies: Tuple[CompanyOption, ...] = ()
    workspaces: Tuple[WorkspaceOption, ...] = ()
    result: Optional[ApprovalResultDisplay] = None
    error_code: str = ""
    field_error_code: str = ""


def production_authorization_view(
    *,
    authenticated: bool,
    state: Optional[str] = None,
    request: Optional[PairingRequestDisplay] = None,
    company_label: str = "",
    companies: Tuple[CompanyOption, ...] = (),
    workspaces: Tuple[WorkspaceOption, ...] = (),
    result: Optional[ApprovalResultDisplay] = None,
    error_code: str = "",
    field_error_code: str = "",
) -> ConnectorAuthorizationView:
    """Build a production view using the sole accepted live authority."""

    resolved_state = state if state is not None else ("pending" if authenticated else "signed_out")
    return ConnectorAuthorizationView(
        authority=PRODUCTION_AUTHORITY,
        authenticated=authenticated,
        state=resolved_state,
        request=request,
        company_label=company_label,
        companies=tuple(companies),
        workspaces=tuple(workspaces),
        result=result,
        error_code=error_code,
        field_error_code=field_error_code,
    )


def demo_authorization_view(state="pending", *, field_error_code=""):
    """Build one clearly labelled, secret-free, session-local Demo state."""

    request = PairingRequestDisplay(
        public_request_ref="pairref_" + ("M" * 43),
        client_name="Mock LocalEndpoint Connect",
        agent_display_name=CANONICAL_AGENT_DISPLAY_NAME,
        status_label="Mock pending approval",
        expires_at_label="Mock countdown: 10 minutes",
        scope_digest=SCOPE_DIGEST,
    )
    result = ApprovalResultDisplay(
        workspace_label="Mock Connector Architecture Lab",
        agent_display_name=CANONICAL_AGENT_DISPLAY_NAME,
        wake_up_url="localendpoint-connect://memoryendpoints/callback",
        scope_digest=SCOPE_DIGEST,
    )
    request_bound = state in (
        "company_selection",
        "reauth_required",
        "pending",
        "approved",
        "replay",
    )
    return ConnectorAuthorizationView(
        authority=DEMO_AUTHORITY,
        authenticated=state != "signed_out",
        state=state,
        request=request if request_bound else None,
        company_label="Mock Memory Architecture Company" if request_bound else "",
        companies=(
            (
                CompanyOption("companyref_" + ("M" * 43), "Mock Memory Architecture Company"),
                CompanyOption("companyref_" + ("N" * 43), "Mock Connector Security Company"),
            )
            if request_bound
            else ()
        ),
        workspaces=(
            (
                WorkspaceOption("workref_" + ("M" * 43), "Mock Connector Architecture Lab"),
                WorkspaceOption("workref_" + ("N" * 43), "Mock Security Review Workspace"),
            )
            if request_bound
            else ()
        ),
        result=result if state in ("approved", "replay") else None,
        error_code="service_error" if state == "error" else "",
        field_error_code=field_error_code,
    )


def render_connector_authorization(view):
    """Validate and render a connector authorization HTML fragment."""

    _validate_view(view)
    if not view.authenticated:
        return _render_signed_out(view)
    return _render_authenticated(view)


def _validate_view(view):
    if not isinstance(view, ConnectorAuthorizationView):
        raise ConnectorAuthorizationRenderError("view_invalid")
    if view.authority not in (PRODUCTION_AUTHORITY, DEMO_AUTHORITY):
        raise ConnectorAuthorizationRenderError("authority_invalid")
    if not isinstance(view.authenticated, bool):
        raise ConnectorAuthorizationRenderError("authentication_state_invalid")
    if view.state not in VIEW_STATES:
        raise ConnectorAuthorizationRenderError("view_state_invalid")
    if view.error_code and view.error_code not in _ERROR_MESSAGES:
        raise ConnectorAuthorizationRenderError("error_code_invalid")
    if view.field_error_code not in ("", "workspace_required", "workspace_name_invalid"):
        raise ConnectorAuthorizationRenderError("field_error_code_invalid")

    # A signed-out response is deliberately neutral even if its caller supplies
    # unsafe protected values. None of those values are inspected or serialized.
    if not view.authenticated:
        return

    if view.state in _NEUTRAL_TERMINAL_STATES and (
        view.request is not None
        or view.result is not None
        or view.company_label
        or view.companies
        or view.workspaces
    ):
        raise ConnectorAuthorizationRenderError("terminal_state_not_scrubbed")

    if view.request is None and view.state in ("pending", "approved", "replay"):
        raise ConnectorAuthorizationRenderError("request_required")
    if view.request is not None:
        _validate_request(view.request)
    if view.company_label:
        _validate_label(view.company_label, "company_label", 96)
    elif view.state == "pending":
        raise ConnectorAuthorizationRenderError("company_label_invalid")

    if len(view.companies) > 100:
        raise ConnectorAuthorizationRenderError("company_count_invalid")
    company_refs = set()
    for company in view.companies:
        if not isinstance(company, CompanyOption):
            raise ConnectorAuthorizationRenderError("company_invalid")
        if not _COMPANY_REF.fullmatch(company.company_ref or ""):
            raise ConnectorAuthorizationRenderError("company_ref_invalid")
        _validate_label(company.label, "company_label", 96)
        if company.company_ref in company_refs:
            raise ConnectorAuthorizationRenderError("company_duplicate")
        company_refs.add(company.company_ref)
    if view.state == "company_selection" and not view.companies:
        raise ConnectorAuthorizationRenderError("company_required")

    if len(view.workspaces) > 100:
        raise ConnectorAuthorizationRenderError("workspace_count_invalid")
    workspace_refs = set()
    for workspace in view.workspaces:
        if not isinstance(workspace, WorkspaceOption):
            raise ConnectorAuthorizationRenderError("workspace_invalid")
        if not _WORKSPACE_REF.fullmatch(workspace.workspace_ref or ""):
            raise ConnectorAuthorizationRenderError("workspace_ref_invalid")
        _validate_label(workspace.label, "workspace_label", 96)
        if workspace.workspace_ref in workspace_refs:
            raise ConnectorAuthorizationRenderError("workspace_duplicate")
        workspace_refs.add(workspace.workspace_ref)

    if view.state in ("approved", "replay"):
        if view.result is None:
            raise ConnectorAuthorizationRenderError("result_required")
        _validate_result(view.result)
    elif view.result is not None:
        raise ConnectorAuthorizationRenderError("result_state_invalid")

    if view.authority == DEMO_AUTHORITY:
        _validate_demo_data(view)


def _validate_request(request):
    if not isinstance(request, PairingRequestDisplay):
        raise ConnectorAuthorizationRenderError("request_invalid")
    if not _PUBLIC_REQUEST_REF.fullmatch(request.public_request_ref or ""):
        raise ConnectorAuthorizationRenderError("public_request_ref_invalid")
    _validate_label(request.client_name, "client_name", 80)
    if request.agent_display_name != CANONICAL_AGENT_DISPLAY_NAME:
        raise ConnectorAuthorizationRenderError("agent_display_name_invalid")
    _validate_label(request.status_label, "status_label", 80)
    _validate_label(request.expires_at_label, "expires_at_label", 96)
    if request.scope_digest != SCOPE_DIGEST:
        raise ConnectorAuthorizationRenderError("scope_digest_invalid")


def _validate_result(result):
    if not isinstance(result, ApprovalResultDisplay):
        raise ConnectorAuthorizationRenderError("result_invalid")
    _validate_label(result.workspace_label, "workspace_label", 96)
    if result.agent_display_name != CANONICAL_AGENT_DISPLAY_NAME:
        raise ConnectorAuthorizationRenderError("agent_display_name_invalid")
    if result.scope_digest != SCOPE_DIGEST:
        raise ConnectorAuthorizationRenderError("scope_digest_invalid")
    try:
        validated = build_wake_up_url(result.wake_up_url)
    except PairingPolicyError as exc:
        raise ConnectorAuthorizationRenderError("wake_up_url_invalid") from exc
    if validated != result.wake_up_url:
        raise ConnectorAuthorizationRenderError("wake_up_url_invalid")


def _validate_label(value, name, maximum):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise ConnectorAuthorizationRenderError(name + "_invalid")
    if value != value.strip() or any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ConnectorAuthorizationRenderError(name + "_invalid")


def _validate_demo_data(view):
    labels = [view.company_label]
    if view.request is not None:
        labels.extend((view.request.client_name, view.request.status_label, view.request.expires_at_label))
    labels.extend(item.label for item in view.companies)
    labels.extend(item.label for item in view.workspaces)
    if view.result is not None:
        labels.append(view.result.workspace_label)
    if any("mock" not in value.lower() for value in labels if value):
        raise ConnectorAuthorizationRenderError("demo_object_not_labelled_mock")


def _render_signed_out(view):
    config = _config_json(view.authority, authenticated=False, state="signed_out")
    demo_callout = ""
    if view.authority == DEMO_AUTHORITY:
        demo_callout = (
            '<aside class="demo-callout connector-demo-callout" aria-label="Mock signed-out authorization">'
            '<p><strong>Mock data:</strong> This uses browser-session-only mock authority for sign-in and enrollment. '
            'It makes no protected network request and persists nothing.</p>'
            '<button type="button" class="button secondary" '
            'data-client-method="connectorAuthorization.resetDemo">Reset mock sign-in</button></aside>'
        )
    return """<section class="connector-authorize connector-authorize-shell connector-authorize-preauth" data-connector-authorize data-connector-authorize-renderer data-human-preauth-shell data-connector-authenticated="false" aria-labelledby="connector-auth-title">
  %s
  <header class="connector-authorize-header">
    <p class="eyebrow">Secure connection approval</p>
    <h1 id="connector-auth-title">Sign in to continue</h1>
    <p>Authentication is required before connection details or approval controls are loaded.</p>
  </header>
  <div class="connector-auth-grid">
    <section class="connector-panel" aria-labelledby="connector-login-title">
      <h2 id="connector-login-title">Sign in</h2>
      <div role="form" class="connector-form-stack" data-connector-login data-enter-action="connectorAuthorization.login">
        <label for="connector-login-username">Username</label>
        <input id="connector-login-username" name="username" type="text" autocomplete="username" required maxlength="80" aria-describedby="connector-login-username-error">
        <p id="connector-login-username-error" class="field-error" data-error-for="username" aria-live="polite"></p>
        <label for="connector-login-password">Password</label>
        <input id="connector-login-password" name="password" type="password" autocomplete="current-password" required maxlength="1024" aria-describedby="connector-login-password-error">
        <p id="connector-login-password-error" class="field-error" data-error-for="password" aria-live="polite"></p>
        <button type="button" class="button primary" data-client-method="connectorAuthorization.login">Sign in</button>
      </div>
    </section>
    <section class="connector-panel" aria-labelledby="connector-enroll-title">
      <h2 id="connector-enroll-title">Create an owner account</h2>
      <p>Prove control with a company master token. The browser clears it immediately after the one-time proof request.</p>
      <div role="form" class="connector-form-stack" data-connector-master-proof data-enter-action="connectorAuthorization.beginEnrollment">
        <label for="connector-master-token">Company master token</label>
        <input id="connector-master-token" name="companyMasterTokenSecret" type="password" autocomplete="off" required maxlength="1024" aria-describedby="connector-master-token-help connector-master-token-error">
        <p id="connector-master-token-help" class="field-help">The token is never saved in page state, a URL, or account storage.</p>
        <p id="connector-master-token-error" class="field-error" data-error-for="companyMasterTokenSecret" aria-live="polite"></p>
        <button type="button" class="button secondary" data-client-method="connectorAuthorization.beginEnrollment">Verify master token</button>
        <div class="connector-account-step connector-form-stack" data-connector-account-create>
          <label for="connector-enroll-username">New username</label>
          <input id="connector-enroll-username" name="username" type="text" autocomplete="username" required maxlength="80" aria-describedby="connector-enroll-username-error">
          <p id="connector-enroll-username-error" class="field-error" data-error-for="enrollmentUsername" aria-live="polite"></p>
          <label for="connector-enroll-password">New password</label>
          <input id="connector-enroll-password" name="password" type="password" autocomplete="new-password" required maxlength="1024" aria-describedby="connector-enroll-password-error">
          <p id="connector-enroll-password-error" class="field-error" data-error-for="enrollmentPassword" aria-live="polite"></p>
          <label for="connector-enroll-password-confirmation">Confirm new password</label>
          <input id="connector-enroll-password-confirmation" name="passwordConfirmation" type="password" autocomplete="new-password" required maxlength="1024" aria-describedby="connector-enroll-password-confirmation-error">
          <p id="connector-enroll-password-confirmation-error" class="field-error" data-error-for="passwordConfirmation" aria-live="polite"></p>
          <button type="button" class="button primary" data-client-method="connectorAuthorization.completeEnrollment">Create owner account</button>
        </div>
      </div>
    </section>
  </div>
  <div class="status-region" role="status" aria-live="polite" aria-atomic="true" data-connector-status></div>
  <noscript><p role="alert">JavaScript is required for secure sign-in and connection approval.</p></noscript>
  <script type="application/json" data-connector-authorization-config>%s</script>
</section>""" % (demo_callout, config)


def _render_authenticated(view):
    request = view.request
    config = _config_json(
        view.authority,
        authenticated=True,
        state=view.state,
        public_request_ref=request.public_request_ref if request is not None else "",
        scope_digest=request.scope_digest if request is not None else "",
    )
    demo_callout = ""
    if view.authority == DEMO_AUTHORITY:
        demo_callout = """<aside class="demo-callout connector-demo-callout" aria-label="Mock connector authorization">
    <p><strong>Mock data:</strong> This is the production connector approval interface with browser-session-only mock authority. It makes no protected network request, performs no external navigation, and persists nothing.</p>
    <button type="button" class="button secondary" data-client-method="connectorAuthorization.resetDemo">Reset mock approval</button>
  </aside>"""
    return """<section class="connector-authorize connector-authorize-shell" data-connector-authorize data-connector-authorize-renderer data-connector-authenticated="true" data-connector-view-state="%s" aria-labelledby="connector-auth-title">
  %s
  <header class="connector-authorize-header">
    <p class="eyebrow">LocalEndpoint Connect</p>
    <h1 id="connector-auth-title">Approve one agent connection</h1>
    <p>Review the fixed LocalEndpoint agent and choose one workspace destination.</p>
  </header>
  <div class="status-region" role="status" aria-live="polite" aria-atomic="true" data-connector-status></div>
  %s
  <noscript><p role="alert">JavaScript is required to approve, cancel, or reset this connection safely.</p></noscript>
  <script type="application/json" data-connector-authorization-config>%s</script>
</section>""" % (_attr(view.state), demo_callout, _render_state_content(view), config)


def _render_state_content(view):
    if view.state == "company_selection":
        return _render_company_selection(view)
    if view.state == "reauth_required":
        return _render_reauthentication()
    if view.state == "pending":
        return _render_pending(view)
    if view.state == "approved":
        return _render_approved(view, replay=False)
    if view.state == "replay":
        return _render_approved(view, replay=True)
    if view.state == "error":
        return _state_panel(
            "error",
            "Approval could not be completed",
            _ERROR_MESSAGES[view.error_code or "service_error"],
            alert=True,
            retry=True,
        )
    if view.state == "expired":
        return _state_panel(
            "expired",
            "This connection request expired",
            "Return to LocalEndpoint Connect and begin a new request. Nothing was activated.",
            alert=True,
        )
    if view.state == "canceled":
        return _state_panel(
            "canceled",
            "Connection request canceled",
            "Nothing was activated. You may safely close this page.",
        )
    return _state_panel(
        "permission-denied",
        "Approval permission required",
        "Your selected company membership cannot approve connector credentials.",
        alert=True,
    )


def _render_company_selection(view):
    options = "".join(
        '<option value="%s">%s</option>' % (_attr(item.company_ref), _text(item.label))
        for item in view.companies
    )
    return """<div class="connector-authorization-state" data-connector-state="company-selection">
  <section aria-labelledby="connector-company-title">
    <h2 id="connector-company-title">Choose the company to approve for</h2>
    <p>Select explicitly. MemoryEndpoints never guesses or silently chooses the first membership.</p>
    <div role="form" class="connector-form-stack" data-connector-company-selection data-enter-action="connectorAuthorization.selectCompany">
      <label for="connector-company-select">Company</label>
      <select id="connector-company-select" name="companyRef" required aria-describedby="connector-company-error">%s</select>
      <p id="connector-company-error" class="field-error" data-error-for="companyRef" aria-live="polite"></p>
      <button type="button" class="button primary" data-client-method="connectorAuthorization.selectCompany">Use selected company</button>
    </div>
  </section>
</div>""" % options


def _render_reauthentication():
    return """<div class="connector-authorization-state" data-connector-state="reauth-required">
  <section aria-labelledby="connector-reauth-title">
    <h2 id="connector-reauth-title">Confirm your password</h2>
    <p>Recent password confirmation is required before issuing a connector credential.</p>
    <div role="form" class="connector-form-stack" data-connector-reauth data-enter-action="connectorAuthorization.reauthenticate">
      <label for="connector-reauth-password">Password</label>
      <input id="connector-reauth-password" name="password" type="password" autocomplete="current-password" required maxlength="1024" aria-describedby="connector-reauth-error">
      <p id="connector-reauth-error" class="field-error" data-error-for="password" aria-live="polite"></p>
      <button type="button" class="button primary" data-client-method="connectorAuthorization.reauthenticate">Confirm password</button>
    </div>
  </section>
</div>"""


def _render_pending(view):
    request = view.request
    options = "".join(
        '<option value="%s">%s</option>' % (_attr(item.workspace_ref), _text(item.label))
        for item in view.workspaces
    )
    if not options:
        options = '<option value="" disabled selected>No existing workspaces available</option>'
    workspace_error = ""
    if view.field_error_code == "workspace_required":
        workspace_error = "Choose an existing workspace or create a new one."
    elif view.field_error_code == "workspace_name_invalid":
        workspace_error = "Use 3 to 80 visible characters for the new workspace name."
    impacts = "".join("<li>%s</li>" % _text(label) for label in SCOPE_IMPACT_LABELS)
    return """<div class="connector-authorization-state connector-pending-layout" data-connector-state="pending">
  <section class="connector-request-summary" aria-labelledby="connector-request-title">
    <h2 id="connector-request-title">Connection request</h2>
    <dl class="connector-detail-grid">
      <div><dt>Desktop client</dt><dd>%s</dd></div>
      <div><dt>Agent</dt><dd>%s</dd></div>
      <div><dt>Status</dt><dd>%s</dd></div>
      <div><dt>Approval window</dt><dd>%s</dd></div>
      <div><dt>Selected company</dt><dd>%s</dd></div>
      <div><dt>Scope digest</dt><dd><code>%s</code></dd></div>
    </dl>
  </section>
  <div role="form" class="connector-approval-form" data-connector-approval-form data-enter-action="connectorAuthorization.approve">
    <div class="validation-summary" data-validation-summary tabindex="-1" aria-live="assertive"></div>
    <fieldset class="connector-fieldset connector-workspace-fieldset">
      <legend>Workspace destination</legend>
      <label class="connector-choice"><input type="radio" name="workspaceMode" value="existing" checked data-workspace-mode> <span>Use an existing workspace</span></label>
      <label for="connector-workspace-select">Workspace</label>
      <select id="connector-workspace-select" name="workspaceRef" required aria-describedby="connector-workspace-error" data-workspace-existing>%s</select>
      <label class="connector-choice"><input type="radio" name="workspaceMode" value="new" data-workspace-mode> <span>Create a new workspace</span></label>
      <label for="connector-workspace-label">New workspace name</label>
      <input id="connector-workspace-label" name="workspaceLabel" type="text" minlength="3" maxlength="80" pattern="[^\\s].*[^\\s]|[^\\s]{3,}" aria-describedby="connector-workspace-error" data-workspace-new>
      <p id="connector-workspace-error" class="field-error" data-error-for="workspace">%s</p>
    </fieldset>
    <fieldset class="connector-fieldset connector-impact-fieldset">
      <legend>Exact connector impact</legend>
      <p>The immutable connector identity is <strong>%s</strong>.</p>
      <ol class="connector-scope-impact">%s</ol>
      <label class="connector-choice connector-consent" for="connector-agent-consent"><input id="connector-agent-consent" name="canonicalAgentApproved" type="checkbox" value="true" required> <span>I approve this fixed LocalEndpoint Agent identity.</span></label>
      <label class="connector-choice connector-consent" for="connector-scope-consent"><input id="connector-scope-consent" name="scopeImpactApproved" type="checkbox" value="true" required> <span>I approve all four listed capabilities without widening them.</span></label>
    </fieldset>
    <div class="button-row connector-actions">
      <button type="button" class="button primary" data-client-method="connectorAuthorization.approve">Approve connection</button>
      <button type="button" class="button secondary" data-client-method="connectorAuthorization.cancel">Cancel request</button>
    </div>
  </div>
</div>""" % (
        _text(request.client_name),
        _text(request.agent_display_name),
        _text(request.status_label),
        _text(request.expires_at_label),
        _text(view.company_label),
        _text(request.scope_digest),
        options,
        _text(workspace_error),
        _text(request.agent_display_name),
        impacts,
    )


def _render_approved(view, *, replay):
    result = view.result
    title = "Approval already completed" if replay else "Connection approved"
    state = "replay" if replay else "approved"
    return """<section class="connector-authorization-state" data-connector-state="%s" aria-labelledby="connector-success-title">
  <h2 id="connector-success-title">%s</h2>
  <p>LocalEndpoint Connect may now claim its short-lived authorization code through the body-only desktop flow.</p>
  <dl class="connector-detail-grid">
    <div><dt>Workspace</dt><dd>%s</dd></div>
    <div><dt>Agent</dt><dd>%s</dd></div>
    <div><dt>Scope digest</dt><dd><code>%s</code></dd></div>
    <div><dt>Grant state</dt><dd>Approved, awaiting connector claim</dd></div>
  </dl>
  <p>No credential or private workspace payload is shown on this page.</p>
  <a class="button primary" href="%s" data-connector-return-action data-client-method="connectorAuthorization.returnToDesktop" rel="noopener noreferrer" referrerpolicy="no-referrer">Open LocalEndpoint</a>
</section>""" % (
        state,
        _text(title),
        _text(result.workspace_label),
        _text(result.agent_display_name),
        _text(result.scope_digest),
        _attr(result.wake_up_url),
    )


def _state_panel(state, title, message, *, alert=False, retry=False):
    role = ' role="alert"' if alert else ""
    retry_button = ""
    if retry:
        retry_button = '<button type="button" class="button secondary" data-client-method="connectorAuthorization.retry">Try again</button>'
    return """<section class="connector-authorization-state" data-connector-state="%s" aria-labelledby="connector-state-title"%s>
  <h2 id="connector-state-title">%s</h2>
  <p>%s</p>
  %s
</section>""" % (_attr(state), role, _text(title), _text(message), retry_button)


def _config_json(
    authority,
    *,
    authenticated,
    state,
    public_request_ref="",
    scope_digest="",
):
    payload = {
        "schema": "memoryendpoints.connector_authorization_ui.v1",
        "authenticated": authenticated,
        "viewState": state,
        "transport": {
            "kind": authority.kind,
            "protectedNetworkAllowed": authority.protected_network_allowed,
            "sessionScope": authority.session_scope,
            "resettable": authority.resettable,
            "labelledMock": authority.labelled_mock,
        },
        "clientMethods": {
            "login": "connectorAuthorization.login",
            "beginEnrollment": "connectorAuthorization.beginEnrollment",
            "completeEnrollment": "connectorAuthorization.completeEnrollment",
            "selectCompany": "connectorAuthorization.selectCompany",
            "reauthenticate": "connectorAuthorization.reauthenticate",
            "approve": "connectorAuthorization.approve",
            "cancel": "connectorAuthorization.cancel",
            "retry": "connectorAuthorization.retry",
            "returnToDesktop": "connectorAuthorization.returnToDesktop",
            "resetDemo": "connectorAuthorization.resetDemo",
        },
    }
    if authenticated and public_request_ref:
        payload["publicRequestRef"] = public_request_ref
    if authenticated and scope_digest:
        payload["scopeDigest"] = scope_digest
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return encoded.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def _text(value):
    return html.escape(str(value), quote=False)


def _attr(value):
    return html.escape(str(value), quote=True)


__all__ = [
    "ApprovalResultDisplay",
    "CANONICAL_AGENT_DISPLAY_NAME",
    "CompanyOption",
    "ConnectorAuthorizationRenderError",
    "ConnectorAuthorizationView",
    "DEMO_AUTHORITY",
    "PRODUCTION_AUTHORITY",
    "PairingRequestDisplay",
    "SCOPE_DIGEST",
    "SCOPE_IMPACT_LABELS",
    "TransportAuthority",
    "VIEW_STATES",
    "WorkspaceOption",
    "demo_authorization_view",
    "production_authorization_view",
    "render_connector_authorization",
]
