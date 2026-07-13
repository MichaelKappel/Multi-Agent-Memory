(function (globalScope, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (globalScope) globalScope.MemoryEndpointsConnectorAuthorize = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var CLIENT_SCHEMA = "memoryendpoints.connector_authorization_client.v1";
  var PAIRING_SCHEMA = "memoryendpoints.connector_pairing.v1";
  var MAX_RESPONSE_BYTES = 65536;
  var PUBLIC_REF_PATTERN = /^pairref_[A-Za-z0-9_-]{43}$/;
  var COMPANY_REF_PATTERN = /^companyref_[A-Za-z0-9_-]{43}$/;
  var WORKSPACE_REF_PATTERN = /^workref_[A-Za-z0-9_-]{43}$/;
  var REGISTERED_CUSTOM_WAKE = "localendpoint-connect://memoryendpoints/callback";
  var REQUESTED_SCOPES = Object.freeze([
    "connector:self:readback",
    "agent:self:register",
    "memory:public-safe:submit",
    "memory:search:read"
  ]);
  var SCOPE_DIGEST = "sha256-v1:1358698c6ddba1a74a688d3718a739f78e4ef50d0773b22c96e025b38aa86594";
  var SCOPE_IMPACT_LABELS = Object.freeze({
    "connector:self:readback": "Verify this exact connector, workspace, and agent binding.",
    "agent:self:register": "Register the exact LocalEndpoint agent during activation.",
    "memory:public-safe:submit": "Submit public-safe memory as this exact connector agent.",
    "memory:search:read": "Search memory readable by this exact connector grant."
  });

  var ROUTES = Object.freeze({
    masterProof: Object.freeze({method: "POST", path: "/api/matm/human/company-master-proofs"}),
    accountCreate: Object.freeze({method: "POST", path: "/api/matm/human/accounts"}),
    sessionInspect: Object.freeze({method: "GET", path: "/api/matm/human/session"}),
    sessionLogin: Object.freeze({method: "POST", path: "/api/matm/human/session"}),
    sessionReauth: Object.freeze({method: "POST", path: "/api/matm/human/session/reauth"}),
    membershipSelect: Object.freeze({method: "POST", path: "/api/matm/human/connector-pairings/{publicRequestRef}/company-selection"}),
    approve: Object.freeze({method: "POST", path: "/api/matm/human/connector-pairings/{publicRequestRef}/approve"}),
    cancel: Object.freeze({method: "POST", path: "/api/matm/human/connector-pairings/{publicRequestRef}/cancel"})
  });

  var STATES = Object.freeze({
    SIGNED_OUT: "signed_out",
    LOCKED: "signed_out",
    REVALIDATING: "revalidating",
    PENDING: "pending",
    READY: "pending",
    PROVING_MASTER: "proving_master",
    PROOF_READY: "proof_ready",
    CREATING_ACCOUNT: "creating_account",
    SIGNING_IN: "signing_in",
    COMPANY_SELECTION: "company_selection",
    SWITCHING_COMPANY: "switching_company",
    REAUTH_REQUIRED: "reauth_required",
    REAUTHENTICATING: "reauthenticating",
    VALIDATION_ERROR: "validation_error",
    APPROVING: "approving",
    APPROVED: "approved",
    CANCELLING: "cancelling",
    CANCELED: "canceled",
    EXPIRED: "expired",
    REPLAY: "replay",
    PERMISSION_DENIED: "permission_denied",
    ERROR: "error",
    SCRUBBED: "scrubbed"
  });

  var SAFE_MESSAGES = Object.freeze({
    signed_out: "Sign in to review this connection request.",
    revalidating: "Revalidating your account session…",
    pending: "Review the four exact capabilities and workspace before approving.",
    proving_master: "Verifying company ownership…",
    proof_ready: "Company ownership verified. Create the owner account to continue.",
    creating_account: "Creating the owner account…",
    signing_in: "Signing in…",
    company_selection: "Choose a company explicitly before continuing.",
    switching_company: "Switching the selected company…",
    reauth_required: "Confirm your password before approving this connection.",
    reauthenticating: "Confirming your password…",
    validation_error: "Check the highlighted values and try again.",
    approving: "Approving the reviewed connection…",
    approved: "Connection approved. Open LocalEndpoint when you are ready.",
    cancelling: "Cancelling this connection request…",
    canceled: "Connection request canceled. Nothing was activated.",
    expired: "This connection request expired. Start a new request from LocalEndpoint Connect.",
    replay: "This approval was already completed.",
    permission_denied: "Your selected company membership cannot approve this connection.",
    error: "The request could not be completed safely.",
    scrubbed: "Protected page state was cleared."
  });

  function ConnectorAuthorizationError(code, status) {
    this.name = "ConnectorAuthorizationError";
    this.code = String(code || "request_failed");
    this.status = Number(status || 0);
    this.message = this.code;
  }
  ConnectorAuthorizationError.prototype = Object.create(Error.prototype);

  function clone(value) { return JSON.parse(JSON.stringify(value)); }
  function own(object, key) { return Boolean(object) && Object.prototype.hasOwnProperty.call(object, key); }
  function exactArray(left, right) {
    if (!Array.isArray(left) || left.length !== right.length) return false;
    for (var index = 0; index < right.length; index += 1) if (left[index] !== right[index]) return false;
    return true;
  }

  function validatePublicRef(value) {
    var text = String(value || "");
    if (!PUBLIC_REF_PATTERN.test(text)) throw new ConnectorAuthorizationError("public_request_ref_invalid", 0);
    return text;
  }

  function routeFor(operation, params) {
    var route = ROUTES[operation];
    if (!route) throw new ConnectorAuthorizationError("operation_not_supported", 0);
    var path = route.path;
    if (path.indexOf("{publicRequestRef}") >= 0) {
      path = path.replace("{publicRequestRef}", validatePublicRef(params && params.publicRequestRef));
    }
    if (path.indexOf("/api/matm/human/") !== 0) throw new ConnectorAuthorizationError("unsafe_route", 0);
    return {method: route.method, path: path};
  }

  function extractErrorCode(payload) {
    var error = payload && payload.error;
    return String(error && error.code || payload && payload.code || "request_failed");
  }

  function responseCsrf(payload) {
    var containers = [payload, payload && payload.data, payload && payload.result, payload && payload.humanSession];
    for (var index = 0; index < containers.length; index += 1) {
      var item = containers[index];
      if (item && typeof item.csrfToken === "string" && item.csrfToken) return item.csrfToken;
    }
    return "";
  }

  function takeSecret(payload, key) {
    var containers = [payload, payload && payload.data, payload && payload.result];
    for (var index = 0; index < containers.length; index += 1) {
      var item = containers[index];
      if (item && own(item, key)) {
        var secret = String(item[key] || "");
        try { delete item[key]; } catch (_) { item[key] = ""; }
        return secret;
      }
    }
    return "";
  }

  function createSessionAuthority() {
    var csrfToken = "";
    var accountAvailable = false;
    return Object.freeze({
      establish: function (payload) {
        csrfToken = responseCsrf(payload);
        accountAvailable = Boolean(payload && (payload.account || payload.username || payload.humanSession));
      },
      csrf: function () { return csrfToken; },
      clear: function () { csrfToken = ""; accountAvailable = false; },
      inspect: function () { return {csrfAvailable: Boolean(csrfToken), accountAvailable: accountAvailable}; }
    });
  }

  function defaultIdempotencyKey() {
    var cryptoRef = typeof globalThis !== "undefined" ? globalThis.crypto : null;
    if (!cryptoRef || typeof cryptoRef.getRandomValues !== "function") throw new ConnectorAuthorizationError("secure_random_unavailable", 0);
    var bytes = new Uint8Array(24);
    cryptoRef.getRandomValues(bytes);
    var text = "";
    for (var index = 0; index < bytes.length; index += 1) text += bytes[index].toString(16).padStart(2, "0");
    return "connector-ui-" + text;
  }

  function createProductionTransport(fetchImpl, options) {
    if (typeof fetchImpl !== "function") throw new TypeError("fetchImpl is required");
    var randomKey = options && options.randomKey || defaultIdempotencyKey;
    return Object.freeze({
      mode: "production",
      request: async function (operation, params) {
        params = params || {};
        var route = routeFor(operation, params);
        var headers = {"Accept": "application/json"};
        var request = {
          method: route.method,
          credentials: "same-origin",
          cache: "no-store",
          redirect: "error",
          referrerPolicy: "no-referrer",
          keepalive: false,
          headers: headers
        };
        if (route.method !== "GET") {
          headers["Content-Type"] = "application/json";
          headers["Idempotency-Key"] = String(params.idempotencyKey || randomKey());
          if (params.csrfToken) headers["X-CSRF-Token"] = String(params.csrfToken);
          request.body = JSON.stringify(params.body || {});
        }
        var response;
        try { response = await fetchImpl(route.path, request); }
        catch (_) { throw new ConnectorAuthorizationError("transport_unavailable", 0); }
        var contentType = String(response.headers && response.headers.get && response.headers.get("content-type") || "").toLowerCase();
        if (contentType.indexOf("application/json") !== 0) throw new ConnectorAuthorizationError("invalid_response", response.status);
        var raw = "";
        try { raw = await response.text(); } catch (_) { throw new ConnectorAuthorizationError("invalid_response", response.status); }
        if (raw.length > MAX_RESPONSE_BYTES) throw new ConnectorAuthorizationError("response_too_large", response.status);
        var payload;
        try { payload = raw ? JSON.parse(raw) : {}; } catch (_) { throw new ConnectorAuthorizationError("invalid_response", response.status); }
        if (!response.ok) throw new ConnectorAuthorizationError(extractErrorCode(payload), response.status);
        return payload;
      },
      scrub: function () {},
      inspect: function () { return {mode: "production", protectedNetworkAllowed: true}; }
    });
  }

  function createDemoTransport(options) {
    options = options || {};
    var plans = Object.assign({}, options.plans || {});
    var calls = [];
    var signedIn = options.signedIn !== false;
    var companySelected = options.companySelected !== false;
    var recentlyReauthenticated = options.recentlyReauthenticated === true;
    var canceled = false;
    var sequence = 0;
    var mockCompanyRef = "companyref_" + "C".repeat(43);
    var mockWorkspaceRef = "workref_" + "B".repeat(43);

    function planned(operation) {
      var plan = plans[operation];
      if (Array.isArray(plan)) plan = plan.shift();
      if (!plan) return null;
      if (plan.error) throw new ConnectorAuthorizationError(plan.error.code, plan.error.status);
      if (plan.lostResponse) throw new ConnectorAuthorizationError("transport_unavailable", 0);
      return clone(plan.payload || plan);
    }

    function record(operation, params) {
      calls.push({
        operation: operation,
        bodyKeys: Object.keys(params && params.body || {}).sort(),
        csrfPresent: Boolean(params && params.csrfToken),
        idempotencyPresent: Boolean(params && params.idempotencyKey)
      });
    }

    return Object.freeze({
      mode: "demo",
      request: async function (operation, params) {
        params = params || {};
        routeFor(operation, params);
        record(operation, params);
        var override = planned(operation);
        if (override) return override;
        var body = params.body || {};
        if (operation === "masterProof") return {ok: true, companyMasterProofSecret: "MOCK PROOF - NOT A CREDENTIAL", mockData: true};
        if (operation === "accountCreate" || operation === "sessionLogin") {
          signedIn = true;
          return {ok: true, account: {username: String(body.username || "mock-owner")}, csrfToken: "MOCK CSRF - NOT A CREDENTIAL", mockData: true};
        }
        if (operation === "sessionInspect") {
          if (!signedIn) throw new ConnectorAuthorizationError("human_session_required", 401);
          return {
            ok: true,
            account: {username: "mock-owner"},
            humanSession: {
              selectedCompanyRef: companySelected ? mockCompanyRef : "",
              passwordReauthenticatedAt: recentlyReauthenticated ? "Mock sequence 4" : null
            },
            csrfToken: "MOCK CSRF - NOT A CREDENTIAL",
            mockData: true
          };
        }
        if (operation === "membershipSelect") {
          if (body.schemaVersion !== PAIRING_SCHEMA || !COMPANY_REF_PATTERN.test(String(body.companyRef || ""))) throw new ConnectorAuthorizationError("company_ref_invalid", 401);
          companySelected = true;
          recentlyReauthenticated = false;
          return {
            ok: true,
            schemaVersion: PAIRING_SCHEMA,
            status: "company_selected",
            sessionRotated: true,
            csrfToken: "MOCK CSRF ROTATED - NOT A CREDENTIAL",
            expiresAt: "Mock session expiry",
            tenantIdentifiersExposed: false,
            mockData: true
          };
        }
        if (operation === "sessionReauth") {
          recentlyReauthenticated = true;
          return {ok: true, account: {username: "mock-owner"}, humanSession: {passwordReauthenticatedAt: "Mock sequence 4"}, csrfToken: "MOCK CSRF REAUTH ROTATED - NOT A CREDENTIAL", mockData: true};
        }
        if (operation === "approve") {
          if (!recentlyReauthenticated) throw new ConnectorAuthorizationError("recent_reauthentication_required", 403);
          canceled = false;
          sequence += 1;
          return {
            ok: true,
            schemaVersion: PAIRING_SCHEMA,
            status: "approved_awaiting_connector_claim",
            approvedScopes: REQUESTED_SCOPES.slice(),
            scopeDigest: SCOPE_DIGEST,
            wakeUpUrl: "http://127.0.0.1:53682/memoryendpoints/callback",
            mockData: true,
            sequence: sequence
          };
        }
        if (operation === "cancel") {
          canceled = true;
          return {ok: true, status: "canceled", safeNoOpOnRetry: true, mockData: true};
        }
        throw new ConnectorAuthorizationError("operation_not_supported", 400);
      },
      setPlan: function (operation, plan) { plans[operation] = plan; },
      scrub: function () { recentlyReauthenticated = false; },
      reset: function () {
        calls.length = 0;
        signedIn = options.signedIn !== false;
        companySelected = options.companySelected !== false;
        recentlyReauthenticated = options.recentlyReauthenticated === true;
        canceled = false;
        sequence = 0;
      },
      inspect: function () {
        return {
          mode: "demo",
          mockData: true,
          protectedNetworkAllowed: false,
          networkRequestCount: 0,
          callCount: calls.length,
          calls: clone(calls),
          signedIn: signedIn,
          companySelected: companySelected,
          recentlyReauthenticated: recentlyReauthenticated,
          canceled: canceled
        };
      }
    });
  }

  function cleanText(value, maximum) {
    var text = String(value || "").trim();
    if (!text || text.length > maximum || /[\u0000-\u001f\u007f]/.test(text)) return "";
    return text;
  }

  function canonicalUsername(value) {
    var text = String(value || "").replace(/^[ \t\r\n\f\v]+|[ \t\r\n\f\v]+$/g, "").toLowerCase();
    return text.length >= 3 && text.length <= 64 && /^[a-z0-9]+(?:[._-][a-z0-9]+)*$/.test(text) ? text : "";
  }

  function validPassword(value, username) {
    if (typeof value !== "string" || value.length < 15 || value.indexOf("\u0000") >= 0) return false;
    var byteLength;
    try { byteLength = new TextEncoder().encode(value).length; } catch (_) { return false; }
    if (byteLength > 1024) return false;
    var folded = value.toLowerCase();
    if (["correcthorsebatterystaple", "letmeinletmeinletmein", "passwordpasswordpassword", "qwertyuiopqwertyuiop", "thisisaverybadpassword"].indexOf(folded) >= 0) return false;
    return !username || folded !== String(username).toLowerCase();
  }

  function validateCompanySelection(values) {
    values = values || {};
    var value = String(values.companyRef || "");
    if (!COMPANY_REF_PATTERN.test(value)) throw new ConnectorAuthorizationError("company_ref_invalid", 401);
    return {schemaVersion: PAIRING_SCHEMA, companyRef: value};
  }

  function validateApproval(values) {
    values = values || {};
    if (values.canonicalAgentApproved !== true) throw new ConnectorAuthorizationError("canonical_agent_approval_required", 422);
    if (values.scopeImpactApproved !== true) throw new ConnectorAuthorizationError("scope_impact_approval_required", 422);
    if (own(values, "approvedScopes") && !exactArray(values.approvedScopes, REQUESTED_SCOPES)) throw new ConnectorAuthorizationError("approved_scopes_invalid", 422);
    var mode = String(values.workspaceMode || "").toLowerCase();
    var selection;
    if (mode === "existing") {
      var workspaceRef = String(values.workspaceRef || "");
      if (!WORKSPACE_REF_PATTERN.test(workspaceRef)) throw new ConnectorAuthorizationError("workspace_ref_invalid", 401);
      selection = {mode: "existing", workspaceRef: workspaceRef};
    } else if (mode === "new") {
      var workspaceLabel = cleanText(values.workspaceLabel, 80);
      var projectLabel = cleanText(values.projectLabel || "LocalEndpoint Pairing", 120);
      if (workspaceLabel.length < 3) throw new ConnectorAuthorizationError("workspace_name_invalid", 422);
      if (projectLabel.length < 3) throw new ConnectorAuthorizationError("project_name_invalid", 422);
      selection = {mode: "new", workspaceLabel: workspaceLabel, projectLabel: projectLabel};
    } else {
      throw new ConnectorAuthorizationError("workspace_required", 422);
    }
    return {
      schemaVersion: PAIRING_SCHEMA,
      canonicalAgentApproved: true,
      approvedScopes: REQUESTED_SCOPES.slice(),
      workspaceSelection: selection
    };
  }

  function safeWakeUpUrl(value) {
    if (typeof value !== "string" || !value || value.length > 2048 || value !== value.trim()) throw new ConnectorAuthorizationError("wake_up_url_invalid", 0);
    if (value === REGISTERED_CUSTOM_WAKE) return value;
    var match = /^http:\/\/127\.0\.0\.1:([0-9]{1,5})\/memoryendpoints\/callback$/.exec(value);
    if (!match) throw new ConnectorAuthorizationError("wake_up_url_invalid", 0);
    var port = Number(match[1]);
    if (port < 1024 || port > 65535 || String(port) !== match[1]) throw new ConnectorAuthorizationError("wake_up_url_invalid", 0);
    return value;
  }

  function validateConfig(config) {
    if (!config || typeof config !== "object" || Array.isArray(config)) throw new ConnectorAuthorizationError("client_config_invalid", 0);
    var allowed = {schema: true, authenticated: true, viewState: true, publicRequestRef: true, scopeDigest: true, clientMethods: true, transport: true};
    Object.keys(config).forEach(function (key) {
      if (!allowed[key]) throw new ConnectorAuthorizationError("config_field_invalid", 0);
    });
    if (own(config, "schema") && config.schema !== "memoryendpoints.connector_authorization_ui.v1") throw new ConnectorAuthorizationError("client_config_invalid", 0);
    if (typeof config.authenticated !== "boolean") throw new ConnectorAuthorizationError("client_config_invalid", 0);
    if (!config.transport || ["same_origin_human_session", "mock_browser_session"].indexOf(config.transport.kind) < 0) throw new ConnectorAuthorizationError("client_authority_invalid", 0);
    var transportKeys = {kind: true, protectedNetworkAllowed: true, sessionScope: true, resettable: true, labelledMock: true};
    Object.keys(config.transport).forEach(function (key) {
      if (!transportKeys[key]) throw new ConnectorAuthorizationError("config_field_invalid", 0);
    });
    if (config.transport.kind === "mock_browser_session" && config.transport.protectedNetworkAllowed !== false) throw new ConnectorAuthorizationError("demo_network_authority_invalid", 0);
    if (config.transport.kind === "same_origin_human_session" && config.transport.protectedNetworkAllowed !== true) throw new ConnectorAuthorizationError("client_authority_invalid", 0);
    if (own(config.transport, "sessionScope")) {
      var expectedScope = config.transport.kind === "mock_browser_session" ? "browser_session" : "server_account_session";
      if (config.transport.sessionScope !== expectedScope) throw new ConnectorAuthorizationError("client_authority_invalid", 0);
    }
    if (own(config.transport, "resettable") && config.transport.resettable !== (config.transport.kind === "mock_browser_session")) throw new ConnectorAuthorizationError("client_authority_invalid", 0);
    if (own(config.transport, "labelledMock") && config.transport.labelledMock !== (config.transport.kind === "mock_browser_session")) throw new ConnectorAuthorizationError("client_authority_invalid", 0);
    if (own(config, "clientMethods")) {
      var expectedMethods = {
        login: "connectorAuthorization.login",
        beginEnrollment: "connectorAuthorization.beginEnrollment",
        completeEnrollment: "connectorAuthorization.completeEnrollment",
        selectCompany: "connectorAuthorization.selectCompany",
        reauthenticate: "connectorAuthorization.reauthenticate",
        approve: "connectorAuthorization.approve",
        cancel: "connectorAuthorization.cancel",
        retry: "connectorAuthorization.retry",
        returnToDesktop: "connectorAuthorization.returnToDesktop",
        resetDemo: "connectorAuthorization.resetDemo"
      };
      if (!config.clientMethods || typeof config.clientMethods !== "object" || Array.isArray(config.clientMethods)) throw new ConnectorAuthorizationError("client_config_invalid", 0);
      var suppliedMethods = Object.keys(config.clientMethods);
      if (suppliedMethods.length !== Object.keys(expectedMethods).length) throw new ConnectorAuthorizationError("client_config_invalid", 0);
      suppliedMethods.forEach(function (key) {
        if (!own(expectedMethods, key) || config.clientMethods[key] !== expectedMethods[key]) throw new ConnectorAuthorizationError("client_config_invalid", 0);
      });
    }
    var neutralTerminal = ["error", "expired", "canceled", "permission_denied"].indexOf(String(config.viewState || "")) >= 0;
    if (config.authenticated && !neutralTerminal) {
      validatePublicRef(config.publicRequestRef);
      if (config.scopeDigest !== SCOPE_DIGEST) throw new ConnectorAuthorizationError("scope_digest_invalid", 0);
    } else if (config.authenticated && neutralTerminal) {
      if (own(config, "publicRequestRef") || own(config, "scopeDigest")) throw new ConnectorAuthorizationError("config_field_invalid", 0);
    } else if (own(config, "publicRequestRef") || own(config, "scopeDigest")) {
      throw new ConnectorAuthorizationError("config_field_invalid", 0);
    }
    if (own(config, "viewState") && [
      "signed_out", "company_selection", "reauth_required", "pending", "approved", "error", "expired", "canceled", "replay", "permission_denied"
    ].indexOf(String(config.viewState)) < 0) throw new ConnectorAuthorizationError("view_state_invalid", 0);
    return config;
  }

  function safeStateForError(error) {
    var code = String(error && error.code || "request_failed");
    var status = Number(error && error.status || 0);
    if (code === "company_ref_invalid" || code === "company_ref_expired") return STATES.COMPANY_SELECTION;
    if (code === "workspace_ref_invalid" || code === "workspace_ref_expired") return STATES.VALIDATION_ERROR;
    if (/reauth/.test(code)) return STATES.REAUTH_REQUIRED;
    if (/session|login|csrf/.test(code)) return STATES.SIGNED_OUT;
    if (/permission|authority/.test(code) || status === 403) return STATES.PERMISSION_DENIED;
    if (/already.*approved|replay|redeemed/.test(code)) return STATES.REPLAY;
    if (/cancel/.test(code)) return STATES.CANCELED;
    if (/expired/.test(code) || status === 410) return STATES.EXPIRED;
    if (status === 401) return STATES.SIGNED_OUT;
    if (/invalid|mismatch|required/.test(code) && status === 422) return STATES.VALIDATION_ERROR;
    return STATES.ERROR;
  }

  function clearControl(item) {
    if (!item) return;
    if ("value" in item) item.value = "";
    if ("checked" in item && (item.type === "checkbox" || item.type === "radio")) item.checked = false;
    if (item.removeAttribute) item.removeAttribute("aria-invalid");
  }
  function control(container, name) { return container && container.querySelector ? container.querySelector('[name="' + name + '"]') : null; }
  function controlValue(container, name) { var item = control(container, name); return item ? String(item.value || "") : ""; }
  function checkedValue(container, name) {
    if (!container || !container.querySelectorAll) return "";
    var items = container.querySelectorAll('[name="' + name + '"]');
    for (var index = 0; index < items.length; index += 1) if (items[index].checked) return String(items[index].value || "");
    return "";
  }

  function create(options) {
    options = options || {};
    var root = options.root;
    if (!root || typeof root.querySelector !== "function") throw new TypeError("root is required");
    var windowRef = options.windowRef || (typeof window !== "undefined" ? window : null);
    var config = clone(validateConfig(options.config || {}));
    var demoMode = config.transport.kind === "mock_browser_session" || options.demoMode === true;
    var randomKey = options.randomKey || defaultIdempotencyKey;
    var transport = options.transport || (demoMode ? createDemoTransport({
      companySelected: config.viewState !== "company_selection",
      recentlyReauthenticated: config.viewState === "pending"
    }) : createProductionTransport(options.fetchImpl || (windowRef && windowRef.fetch && windowRef.fetch.bind(windowRef))));
    var sessionAuthority = options.sessionAuthority || createSessionAuthority();
    var navigate = options.navigate || function (target) { if (windowRef && windowRef.location) windowRef.location.assign(target); };
    var reload = options.reload || function () { if (windowRef && windowRef.location) windowRef.location.reload(); };
    var demoStateNavigate = options.demoStateNavigate || function (next) {
      if (windowRef && windowRef.location) windowRef.location.assign("/tour/connect/authorize/" + next);
    };
    var statusElement = root.querySelector("[data-connector-status]");
    var configElement = root.querySelector("[data-connector-authorization-config]");
    var approvalForm = root.querySelector("[data-connector-approval-form]");
    var returnAction = root.querySelector("[data-connector-return-action]");
    var mounted = false;
    var state = config.authenticated ? STATES.REVALIDATING : STATES.SIGNED_OUT;
    var proofSecret = "";
    var publicRef = config.authenticated ? config.publicRequestRef : "";
    var wakeTarget = "";
    var lastApproval = false;
    var operationKeys = {};
    var activeOperation = 0;
    var listeners = [];

    function setState(next, message) {
      state = next;
      if (root.dataset) root.dataset.connectorClientState = next;
      if (statusElement) statusElement.textContent = message || SAFE_MESSAGES[next] || SAFE_MESSAGES.error;
    }
    function beginOperation(next) { activeOperation += 1; setState(next); return activeOperation; }
    function current(epoch) { return epoch === activeOperation && state !== STATES.SCRUBBED; }
    function csrfForMutation() {
      var value = sessionAuthority.csrf();
      if (!value) throw new ConnectorAuthorizationError("csrf_required", 403);
      return value;
    }
    function idempotencyFor(operation) {
      if (!operationKeys[operation]) operationKeys[operation] = randomKey();
      return operationKeys[operation];
    }
    function operationCompleted(operation) { delete operationKeys[operation]; }

    function showFieldError(code) {
      var messages = {
        workspace_required: "Choose an existing workspace or create a new one.",
        workspace_name_invalid: "Use 3 to 80 visible characters for the new workspace name.",
        project_name_invalid: "Use 3 to 120 visible characters for the project name.",
        canonical_agent_approval_required: "Confirm the fixed LocalEndpoint Agent identity.",
        scope_impact_approval_required: "Confirm the four listed capability impacts.",
        company_selection_required: "Choose one linked company.",
        login_input_invalid: "Enter a valid username and password.",
        account_input_invalid: "Use a valid username and a matching password of at least 15 characters.",
        reauthentication_input_invalid: "Enter your current password."
      };
      var field = /workspace|project|canonical|scope/.test(code) ? "workspace" : /company/.test(code) ? "companyRef" : /reauth/.test(code) ? "password" : "";
      var target = field ? root.querySelector('[data-error-for="' + field + '"]') : null;
      if (target) target.textContent = messages[code] || SAFE_MESSAGES.validation_error;
      var summary = root.querySelector("[data-validation-summary]");
      if (summary) target ? target.textContent = messages[code] || SAFE_MESSAGES.validation_error : null;
      if (summary) summary.textContent = messages[code] || SAFE_MESSAGES.validation_error;
    }

    function clearEphemeralControls() {
      if (!root.querySelectorAll) return;
      var items = root.querySelectorAll("input,select,textarea");
      for (var index = 0; index < items.length; index += 1) clearControl(items[index]);
    }

    function handleFailure(error) {
      proofSecret = "";
      var code = String(error && error.code || "request_failed");
      var next = safeStateForError(error);
      var referenceRefresh = /^company_ref_/.test(code) || /^workspace_ref_/.test(code);
      var terminal = [STATES.SIGNED_OUT, STATES.PERMISSION_DENIED, STATES.EXPIRED, STATES.CANCELED, STATES.REPLAY].indexOf(next) >= 0;
      var unrecoverableError = next === STATES.ERROR && code !== "transport_unavailable";
      if (referenceRefresh || terminal || unrecoverableError) {
        var routeState = /^company_ref_/.test(code) ? STATES.COMPANY_SELECTION : /^workspace_ref_/.test(code) ? STATES.PENDING : next;
        scrubProtectedState();
        setState(routeState);
        if (demoMode) demoStateNavigate(routeState); else reload();
        return {ok: false, state: routeState, code: code};
      }
      if (next === STATES.VALIDATION_ERROR || next === STATES.COMPANY_SELECTION) showFieldError(code);
      setState(next);
      return {ok: false, state: next, code: code};
    }

    function stateAfterSession(payload) {
      var session = payload && payload.humanSession || {};
      if (own(session, "selectedCompanyRef") && !session.selectedCompanyRef) return STATES.COMPANY_SELECTION;
      var selectedKey = Object.keys(session).find(function (key) { return /^selected(?:authority|company)id$/i.test(key); });
      if (selectedKey && !session[selectedKey]) return STATES.COMPANY_SELECTION;
      if (own(session, "passwordReauthenticatedAt")) return session.passwordReauthenticatedAt ? STATES.PENDING : STATES.REAUTH_REQUIRED;
      var configured = String(config.viewState || "");
      if (["company_selection", "reauth_required", "pending"].indexOf(configured) >= 0) return configured;
      return STATES.REAUTH_REQUIRED;
    }

    async function revalidateSession() {
      var epoch = beginOperation(STATES.REVALIDATING);
      try {
        var payload = await transport.request("sessionInspect", {});
        if (!current(epoch)) return {ok: false, stale: true};
        sessionAuthority.establish(payload);
        if (!sessionAuthority.csrf()) throw new ConnectorAuthorizationError("csrf_required", 403);
        setState(stateAfterSession(payload));
        return {ok: true, state: state};
      } catch (error) {
        if (!current(epoch)) return {ok: false, stale: true};
        return handleFailure(error);
      }
    }

    async function login(values) {
      var container = root.querySelector("[data-connector-login]");
      var passwordControl = control(container, "password");
      var username = canonicalUsername(values && values.username !== undefined ? values.username : controlValue(container, "username"));
      var password = String(values && values.password !== undefined ? values.password : passwordControl && passwordControl.value || "");
      clearControl(passwordControl);
      if (!username || !validPassword(password)) { password = ""; return handleFailure(new ConnectorAuthorizationError("login_input_invalid", 422)); }
      var epoch = beginOperation(STATES.SIGNING_IN);
      try {
        var payload = await transport.request("sessionLogin", {idempotencyKey: idempotencyFor("sessionLogin"), body: {username: username, password: password}});
        password = "";
        if (!current(epoch)) return {ok: false, stale: true};
        operationCompleted("sessionLogin");
        sessionAuthority.establish(payload);
        if (!demoMode) {
          scrubProtectedState();
          reload();
        } else {
          var loginSession = await revalidateSession();
          if (!loginSession.ok) return loginSession;
          var loginNext = loginSession.state;
          scrubProtectedState();
          setState(loginNext);
          demoStateNavigate(loginNext);
        }
        return {ok: true};
      } catch (error) {
        password = "";
        if (!current(epoch)) return {ok: false, stale: true};
        return handleFailure(error);
      }
    }

    async function beginEnrollment(values) {
      var container = root.querySelector("[data-connector-master-proof]");
      var masterControl = control(container, "companyMasterTokenSecret");
      var master = String(values && values.companyMasterTokenSecret !== undefined ? values.companyMasterTokenSecret : masterControl && masterControl.value || "");
      clearControl(masterControl);
      if (master.length < 20 || master.length > 1024) { master = ""; return handleFailure(new ConnectorAuthorizationError("company_master_input_invalid", 422)); }
      var epoch = beginOperation(STATES.PROVING_MASTER);
      try {
        var payload = await transport.request("masterProof", {idempotencyKey: idempotencyFor("masterProof"), body: {companyMasterTokenSecret: master}});
        master = "";
        if (!current(epoch)) return {ok: false, stale: true};
        operationCompleted("masterProof");
        proofSecret = takeSecret(payload, "companyMasterProofSecret");
        if (!proofSecret) throw new ConnectorAuthorizationError("company_master_proof_invalid", 401);
        setState(STATES.PROOF_READY);
        return {ok: true, proofReady: true};
      } catch (error) {
        master = "";
        if (!current(epoch)) return {ok: false, stale: true};
        return handleFailure(error);
      }
    }

    async function completeEnrollment(values) {
      values = values || {};
      var usernameControl = root.querySelector('[data-connector-account-create] [name="username"]');
      var passwordControl = root.querySelector('[data-connector-account-create] [name="password"]');
      var confirmationControl = root.querySelector('[data-connector-account-create] [name="passwordConfirmation"]');
      var username = canonicalUsername(values.username !== undefined ? values.username : usernameControl && usernameControl.value || "");
      var password = String(values.password !== undefined ? values.password : passwordControl && passwordControl.value || "");
      var confirmation = String(values.passwordConfirmation !== undefined ? values.passwordConfirmation : confirmationControl && confirmationControl.value || "");
      clearControl(passwordControl); clearControl(confirmationControl);
      if (!proofSecret || !username || !validPassword(password, username) || password !== confirmation) {
        password = ""; confirmation = "";
        return handleFailure(new ConnectorAuthorizationError("account_input_invalid", 422));
      }
      var oneTimeProof = proofSecret;
      proofSecret = "";
      var epoch = beginOperation(STATES.CREATING_ACCOUNT);
      try {
        var payload = await transport.request("accountCreate", {idempotencyKey: idempotencyFor("accountCreate"), body: {username: username, password: password, companyMasterProofSecret: oneTimeProof}});
        password = ""; confirmation = ""; oneTimeProof = "";
        if (!current(epoch)) return {ok: false, stale: true};
        operationCompleted("accountCreate");
        sessionAuthority.establish(payload);
        if (!demoMode) {
          scrubProtectedState();
          reload();
        } else {
          var accountSession = await revalidateSession();
          if (!accountSession.ok) return accountSession;
          var accountNext = accountSession.state;
          scrubProtectedState();
          setState(accountNext);
          demoStateNavigate(accountNext);
        }
        return {ok: true};
      } catch (error) {
        password = ""; confirmation = ""; oneTimeProof = "";
        if (!current(epoch)) return {ok: false, stale: true};
        return handleFailure(error);
      }
    }

    async function selectCompany(values) {
      var container = root.querySelector("[data-connector-company-selection]");
      var body;
      try { body = validateCompanySelection({companyRef: values && values.companyRef !== undefined ? values.companyRef : controlValue(container, "companyRef")}); }
      catch (error) { return handleFailure(error); }
      var epoch = beginOperation(STATES.SWITCHING_COMPANY);
      try {
        var payload = await transport.request("membershipSelect", {publicRequestRef: publicRef, idempotencyKey: idempotencyFor("membershipSelect"), csrfToken: csrfForMutation(), body: body});
        if (!current(epoch)) return {ok: false, stale: true};
        operationCompleted("membershipSelect");
        if (payload.schemaVersion !== PAIRING_SCHEMA || payload.status !== "company_selected" || payload.sessionRotated !== true || payload.tenantIdentifiersExposed !== false || !payload.expiresAt || !responseCsrf(payload)) throw new ConnectorAuthorizationError("invalid_response", 0);
        sessionAuthority.establish(payload);
        scrubProtectedState();
        setState(STATES.REAUTH_REQUIRED);
        if (demoMode) demoStateNavigate("reauth_required"); else reload();
        return {ok: true};
      } catch (error) {
        if (!current(epoch)) return {ok: false, stale: true};
        return handleFailure(error);
      }
    }

    async function reauthenticate(values) {
      var container = root.querySelector("[data-connector-reauthentication]") || root.querySelector("[data-connector-reauth]");
      var passwordControl = control(container, "password");
      var password = String(values && values.password !== undefined ? values.password : passwordControl && passwordControl.value || "");
      clearControl(passwordControl);
      if (!validPassword(password)) { password = ""; return handleFailure(new ConnectorAuthorizationError("reauthentication_input_invalid", 422)); }
      var epoch = beginOperation(STATES.REAUTHENTICATING);
      try {
        var payload = await transport.request("sessionReauth", {idempotencyKey: idempotencyFor("sessionReauth"), csrfToken: csrfForMutation(), body: {password: password}});
        password = "";
        if (!current(epoch)) return {ok: false, stale: true};
        operationCompleted("sessionReauth");
        sessionAuthority.establish(payload);
        if (!sessionAuthority.csrf()) throw new ConnectorAuthorizationError("csrf_required", 403);
        scrubProtectedState();
        setState(STATES.PENDING);
        if (demoMode) demoStateNavigate("pending"); else reload();
        return {ok: true};
      } catch (error) {
        password = "";
        if (!current(epoch)) return {ok: false, stale: true};
        return handleFailure(error);
      }
    }

    function approvalValues(values) {
      if (values) return values;
      return {
        workspaceMode: checkedValue(approvalForm, "workspaceMode"),
        workspaceRef: controlValue(approvalForm, "workspaceRef"),
        workspaceLabel: controlValue(approvalForm, "workspaceLabel"),
        projectLabel: controlValue(approvalForm, "projectLabel"),
        canonicalAgentApproved: Boolean(control(approvalForm, "canonicalAgentApproved") && control(approvalForm, "canonicalAgentApproved").checked),
        scopeImpactApproved: Boolean(control(approvalForm, "scopeImpactApproved") && control(approvalForm, "scopeImpactApproved").checked)
      };
    }

    function consumeApproval(payload) {
      if (!payload || payload.schemaVersion !== PAIRING_SCHEMA || payload.status !== "approved_awaiting_connector_claim") throw new ConnectorAuthorizationError("invalid_response", 0);
      if (!exactArray(payload.approvedScopes, REQUESTED_SCOPES) || payload.scopeDigest !== SCOPE_DIGEST) throw new ConnectorAuthorizationError("scope_digest_invalid", 0);
      var target = takeSecret(payload, "wakeUpUrl");
      return safeWakeUpUrl(target);
    }

    async function approve(values) {
      var body;
      try { body = validateApproval(approvalValues(values)); }
      catch (error) { return handleFailure(error); }
      var epoch = beginOperation(STATES.APPROVING);
      try {
        var payload = await transport.request("approve", {publicRequestRef: publicRef, idempotencyKey: idempotencyFor("approve"), csrfToken: csrfForMutation(), body: body});
        if (!current(epoch)) return {ok: false, stale: true};
        wakeTarget = consumeApproval(payload);
        operationCompleted("approve");
        lastApproval = true;
        scrubProtectedState();
        setState(STATES.APPROVED);
        if (demoMode) demoStateNavigate("approved"); else reload();
        return {ok: true, awaitingConnectorClaim: true, rendererTransition: true};
      } catch (error) {
        if (!current(epoch)) return {ok: false, stale: true};
        return handleFailure(error);
      }
    }

    function returnToDesktop() {
      if (!lastApproval || !wakeTarget) return {ok: false, code: "wake_up_url_unavailable"};
      var target = safeWakeUpUrl(wakeTarget);
      if (demoMode) return {ok: true, mockNavigationPrevented: true};
      navigate(target);
      return {ok: true};
    }

    async function cancel() {
      var epoch = beginOperation(STATES.CANCELLING);
      try {
        await transport.request("cancel", {publicRequestRef: publicRef, idempotencyKey: idempotencyFor("cancel"), csrfToken: csrfForMutation(), body: {schemaVersion: PAIRING_SCHEMA, reason: "human_cancelled"}});
        if (!current(epoch)) return {ok: false, stale: true};
        operationCompleted("cancel");
        scrubProtectedState();
        setState(STATES.CANCELED);
        if (demoMode) demoStateNavigate("canceled"); else reload();
        return {ok: true, canceled: true};
      } catch (error) {
        if (!current(epoch)) return {ok: false, stale: true};
        return handleFailure(error);
      }
    }

    async function retry() {
      if (demoMode) return revalidateSession();
      var result = await revalidateSession();
      if (result.ok) reload();
      return result;
    }

    function resetDemo() {
      if (!demoMode || typeof transport.reset !== "function") return {ok: false};
      var next = STATES.SIGNED_OUT;
      transport.reset();
      scrubProtectedState();
      setState(next);
      demoStateNavigate(next);
      return {ok: true};
    }

    function scrubProtectedState() {
      activeOperation += 1;
      proofSecret = ""; publicRef = ""; wakeTarget = ""; lastApproval = false; operationKeys = {};
      sessionAuthority.clear();
      if (transport && typeof transport.scrub === "function") transport.scrub();
      clearEphemeralControls();
      if (returnAction && returnAction.removeAttribute) returnAction.removeAttribute("href");
      returnAction = null;
      delete config.publicRequestRef;
      delete config.scopeDigest;
      delete config.viewState;
      if (configElement) configElement.textContent = "";
      setState(STATES.SCRUBBED);
      if (typeof root.replaceChildren === "function") root.replaceChildren();
    }

    function invoke(method) {
      if (method === "connectorAuthorization.login") return login();
      if (method === "connectorAuthorization.beginEnrollment") return beginEnrollment();
      if (method === "connectorAuthorization.completeEnrollment") return completeEnrollment();
      if (method === "connectorAuthorization.selectCompany") return selectCompany();
      if (method === "connectorAuthorization.reauthenticate") return reauthenticate();
      if (method === "connectorAuthorization.approve") return approve();
      if (method === "connectorAuthorization.returnToDesktop") return returnToDesktop();
      if (method === "connectorAuthorization.cancel") return cancel();
      if (method === "connectorAuthorization.retry") return retry();
      if (method === "connectorAuthorization.resetDemo") return resetDemo();
      return null;
    }

    function clickHandler(event) {
      var node = event.target;
      while (node && node !== root && !(node.getAttribute && node.getAttribute("data-client-method"))) node = node.parentNode;
      var method = node && node.getAttribute && node.getAttribute("data-client-method");
      if (method) { event.preventDefault(); invoke(method); }
    }
    function keyHandler(event) {
      if (event.key !== "Enter") return;
      var node = event.target;
      while (node && node !== root && !(node.getAttribute && node.getAttribute("data-enter-action"))) node = node.parentNode;
      var method = node && node.getAttribute && node.getAttribute("data-enter-action");
      if (method) { event.preventDefault(); invoke(method); }
    }
    function pageHideHandler() { scrubProtectedState(); }
    function pageShowHandler(event) {
      if (!event.persisted) return;
      sessionAuthority.clear();
      if (demoMode) {
        if (typeof transport.reset === "function") transport.reset();
        setState(config.authenticated ? STATES.REVALIDATING : STATES.SIGNED_OUT);
        if (config.authenticated) revalidateSession().then(function (result) { if (result.ok) reload(); });
      } else {
        revalidateSession().then(function (result) { if (result.ok) reload(); });
      }
    }
    function listen(target, name, handler) {
      if (!target || typeof target.addEventListener !== "function") return;
      target.addEventListener(name, handler);
      listeners.push([target, name, handler]);
    }

    function terminalViewState() {
      var map = {approved: STATES.APPROVED, error: STATES.ERROR, expired: STATES.EXPIRED, canceled: STATES.CANCELED, replay: STATES.REPLAY, permission_denied: STATES.PERMISSION_DENIED};
      return map[String(config.viewState || "")] || "";
    }

    function hydrateTerminalWake(terminal) {
      if (terminal !== STATES.APPROVED && terminal !== STATES.REPLAY) return true;
      var value = returnAction && returnAction.getAttribute ? returnAction.getAttribute("href") : "";
      try { wakeTarget = safeWakeUpUrl(value); }
      catch (_) {
        wakeTarget = "";
        lastApproval = false;
        if (returnAction && returnAction.removeAttribute) returnAction.removeAttribute("href");
        setState(STATES.ERROR);
        return false;
      }
      lastApproval = true;
      return true;
    }

    function mount() {
      if (mounted) return controller;
      mounted = true;
      listen(root, "click", clickHandler);
      listen(root, "keydown", keyHandler);
      listen(windowRef, "pagehide", pageHideHandler);
      listen(windowRef, "pageshow", pageShowHandler);
      var terminal = terminalViewState();
      setState(config.authenticated ? terminal || STATES.REVALIDATING : STATES.SIGNED_OUT);
      if (terminal && !hydrateTerminalWake(terminal)) return controller;
      if (config.authenticated && !terminal) revalidateSession();
      return controller;
    }

    function destroy() {
      scrubProtectedState();
      for (var index = 0; index < listeners.length; index += 1) listeners[index][0].removeEventListener(listeners[index][1], listeners[index][2]);
      listeners.length = 0;
      mounted = false;
    }

    function getSnapshot() {
      return {
        schema: CLIENT_SCHEMA,
        state: state,
        demoMode: demoMode,
        csrfAvailable: sessionAuthority.inspect().csrfAvailable,
        proofReady: Boolean(proofSecret),
        approvalAwaitingClaim: lastApproval,
        wakeUpAvailable: Boolean(wakeTarget),
        protectedIdentifiersRetained: Boolean(publicRef || wakeTarget || own(config, "publicRequestRef"))
      };
    }

    var controller = Object.freeze({
      mount: mount,
      destroy: destroy,
      login: login,
      beginEnrollment: beginEnrollment,
      completeEnrollment: completeEnrollment,
      selectCompany: selectCompany,
      reauthenticate: reauthenticate,
      approve: approve,
      returnToDesktop: returnToDesktop,
      cancel: cancel,
      retry: retry,
      resetDemo: resetDemo,
      revalidateSession: revalidateSession,
      scrubProtectedState: scrubProtectedState,
      getSnapshot: getSnapshot
    });
    return controller;
  }

  function readConfig(root) {
    var script = root.querySelector("[data-connector-authorization-config]");
    if (!script) throw new ConnectorAuthorizationError("client_config_missing", 0);
    var config;
    try { config = JSON.parse(script.textContent || "{}"); } catch (_) { throw new ConnectorAuthorizationError("client_config_invalid", 0); }
    return validateConfig(config);
  }

  function bootstrap(documentRef, windowRef) {
    if (!documentRef || typeof documentRef.querySelectorAll !== "function") return [];
    var roots = documentRef.querySelectorAll("[data-connector-authorize]");
    var controllers = [];
    for (var index = 0; index < roots.length; index += 1) {
      try {
        var config = readConfig(roots[index]);
        var controller = create({root: roots[index], windowRef: windowRef, config: config});
        controller.mount();
        controllers.push(controller);
      } catch (_) {
        var status = roots[index].querySelector("[data-connector-status]");
        if (status) status.textContent = SAFE_MESSAGES.error;
      }
    }
    if (controllers.length === 1 && windowRef) windowRef.connectorAuthorization = controllers[0];
    return controllers;
  }

  if (typeof document !== "undefined" && typeof window !== "undefined") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { bootstrap(document, window); }, {once: true});
    else bootstrap(document, window);
  }

  return Object.freeze({
    SCHEMA: CLIENT_SCHEMA,
    PAIRING_SCHEMA: PAIRING_SCHEMA,
    MAX_RESPONSE_BYTES: MAX_RESPONSE_BYTES,
    REQUESTED_SCOPES: REQUESTED_SCOPES,
    SCOPE_IMPACT_LABELS: SCOPE_IMPACT_LABELS,
    SCOPE_DIGEST: SCOPE_DIGEST,
    ROUTES: ROUTES,
    STATES: STATES,
    SAFE_MESSAGES: SAFE_MESSAGES,
    ConnectorAuthorizationError: ConnectorAuthorizationError,
    createSessionAuthority: createSessionAuthority,
    createProductionTransport: createProductionTransport,
    createDemoTransport: createDemoTransport,
    validateConfig: validateConfig,
    validateCompanySelection: validateCompanySelection,
    validateApproval: validateApproval,
    safeWakeUpUrl: safeWakeUpUrl,
    create: create,
    readConfig: readConfig,
    bootstrap: bootstrap
  });
});
