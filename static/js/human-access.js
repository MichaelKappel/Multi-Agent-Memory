(function (globalScope, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (globalScope) globalScope.MemoryEndpointsHumanAccess = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var ROUTES = Object.freeze({
    masterProof: Object.freeze({method: "POST", path: "/api/matm/human/company-master-proofs"}),
    accountCreate: Object.freeze({method: "POST", path: "/api/matm/human/accounts"}),
    sessionInspect: Object.freeze({method: "GET", path: "/api/matm/human/session"}),
    sessionLogin: Object.freeze({method: "POST", path: "/api/matm/human/session"}),
    sessionReauth: Object.freeze({method: "POST", path: "/api/matm/human/session/reauth"}),
    sessionLogout: Object.freeze({method: "POST", path: "/api/matm/human/session/logout"}),
    memberships: Object.freeze({method: "GET", path: "/api/matm/human/company-memberships"}),
    membershipLink: Object.freeze({method: "POST", path: "/api/matm/human/company-memberships/link"}),
    membershipSelect: Object.freeze({method: "POST", path: "/api/matm/human/session/company"}),
    roster: Object.freeze({method: "GET", path: "/api/matm/human/companies/{companyId}/agent-tokens"}),
    agentMasterSetting: Object.freeze({method: "GET", path: "/api/matm/human/companies/{companyId}/top-level-agent-master-credential-setting"}),
    agentMasterSettingUpdate: Object.freeze({method: "PATCH", path: "/api/matm/human/companies/{companyId}/top-level-agent-master-credential-setting"}),
    replacementPrepare: Object.freeze({method: "POST", path: "/api/matm/human/companies/{companyId}/agent-tokens/{credentialId}/replacements"}),
    replacementConfirm: Object.freeze({method: "POST", path: "/api/matm/human/companies/{companyId}/agent-tokens/{credentialId}/replacements/{replacementId}/confirm"}),
    replacementCancel: Object.freeze({method: "POST", path: "/api/matm/human/companies/{companyId}/agent-tokens/{credentialId}/replacements/{replacementId}/cancel"}),
    replacementStatus: Object.freeze({method: "GET", path: "/api/matm/human/companies/{companyId}/agent-tokens/{credentialId}/replacements/{replacementId}"})
  });

  var SELECTORS = Object.freeze({
    status: "[data-human-access-status]",
    locked: "[data-human-access-locked]",
    accountStep: "[data-human-access-account-step]",
    protected: "[data-human-access-protected]",
    demoLabel: "[data-human-access-demo-label]",
    masterProofForm: "[data-human-access-master-proof-form]",
    accountForm: "[data-human-access-account-form]",
    loginForm: "[data-human-access-login-form]",
    logout: "[data-human-access-logout]",
    membershipForm: "[data-human-access-membership-form]",
    membershipList: "[data-human-access-membership-list]",
    linkCompany: "[data-human-access-link-company]",
    linkDialog: "[data-human-access-link-dialog]",
    linkProofForm: "[data-human-access-link-proof-form]",
    linkCancel: "[data-human-access-link-cancel]",
    rosterList: "[data-human-access-roster-list]",
    rosterEmpty: "[data-human-access-roster-empty]",
    rosterRefresh: "[data-human-access-roster-refresh]",
    agentMasterSettingForm: "[data-human-access-agent-master-setting-form]",
    agentMasterSetting: "[data-human-access-agent-master-setting]",
    agentMasterSettingStatus: "[data-human-access-agent-master-setting-status]",
    reauthDialog: "[data-human-access-reauth-dialog]",
    reauthForm: "[data-human-access-reauth-form]",
    reauthCancel: "[data-human-access-reauth-cancel]",
    replacementDialog: "[data-human-access-replacement-dialog]",
    replacementSummary: "[data-human-access-replacement-summary]",
    replacementStatus: "[data-human-access-replacement-status]",
    successorToken: "[data-human-access-successor-token]",
    successorShow: "[data-human-access-successor-show]",
    successorCopy: "[data-human-access-successor-copy]",
    successorSaved: "[data-human-access-successor-saved]",
    successorClear: "[data-human-access-successor-clear]",
    possessionForm: "[data-human-access-possession-form]",
    possessionToken: "[data-human-access-possession-token]",
    replacementRetry: "[data-human-access-replacement-retry]",
    replacementCancel: "[data-human-access-replacement-cancel]"
  });

  var SESSION_STATES = Object.freeze({
    LOCKED: "locked",
    PROVING_MASTER: "proving_master",
    PROOF_READY: "proof_ready",
    CREATING_ACCOUNT: "creating_account",
    SIGNING_IN: "signing_in",
    REVALIDATING: "revalidating",
    CHOOSING_COMPANY: "choosing_company",
    SWITCHING_COMPANY: "switching_company",
    LOADING: "loading",
    READY: "ready",
    EMPTY: "empty",
    VALIDATION_ERROR: "validation_error",
    PERMISSION_ERROR: "permission_error",
    EXPIRED: "expired",
    RECOVERY_REQUIRED: "recovery_required"
  });

  var REPLACEMENT_STATES = Object.freeze({
    IDLE: "idle",
    REAUTHENTICATING: "reauthenticating",
    PREPARING: "preparing",
    REVEALED_UNSAVED: "revealed_unsaved",
    SAVED_CLEARED: "saved_cleared",
    CONFIRMING: "confirming",
    CONFIRMED: "confirmed",
    CANCELING: "canceling",
    CANCELED: "canceled",
    EXPIRED: "expired",
    OUTCOME_UNKNOWN: "outcome_unknown"
  });

  function HumanAccessError(code, status) {
    this.name = "HumanAccessError";
    this.code = String(code || "request_failed");
    this.status = Number(status || 0);
    this.message = this.code;
  }
  HumanAccessError.prototype = Object.create(Error.prototype);

  function safeSegment(value) {
    var text = String(value || "");
    if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/.test(text)) throw new HumanAccessError("invalid_route_parameter", 0);
    return encodeURIComponent(text);
  }

  function createRouteAdapter(overrides) {
    var routeMap = Object.assign({}, ROUTES, overrides || {});
    return Object.freeze({
      resolve: function (name, params) {
        var spec = routeMap[name];
        if (!spec || !spec.path || !spec.method) throw new HumanAccessError("unknown_operation", 0);
        var path = String(spec.path).replace(/\{([A-Za-z]+)\}/g, function (_, key) {
          return safeSegment((params || {})[key]);
        });
        if (path.indexOf("/api/matm/human/") !== 0 && path !== "/api/matm/human/session") {
          throw new HumanAccessError("unsafe_route", 0);
        }
        return {method: String(spec.method).toUpperCase(), path: path};
      },
      routes: Object.freeze(routeMap)
    });
  }

  function responseContainers(payload) {
    return [payload, payload && payload.data, payload && payload.result, payload && payload.session].filter(Boolean);
  }

  function takeSecret(payload, names) {
    var containers = responseContainers(payload);
    for (var i = 0; i < containers.length; i += 1) {
      for (var j = 0; j < names.length; j += 1) {
        var key = names[j];
        if (Object.prototype.hasOwnProperty.call(containers[i], key)) {
          var value = String(containers[i][key] || "");
          try { delete containers[i][key]; } catch (_) { containers[i][key] = ""; }
          return value;
        }
      }
    }
    return "";
  }

  function firstValue(payload, names, fallback) {
    var containers = responseContainers(payload);
    for (var i = 0; i < containers.length; i += 1) {
      for (var j = 0; j < names.length; j += 1) {
        if (containers[i][names[j]] !== undefined && containers[i][names[j]] !== null) return containers[i][names[j]];
      }
    }
    return fallback;
  }

  function normalizeAccount(payload) {
    var source = payload && payload.account || {};
    return {
      accountId: String(source.humanAccountId || ""),
      username: String(source.username || ""),
      displayName: String(source.displayName || source.username || "")
    };
  }

  function normalizeMemberships(payload) {
    var items = payload && payload.memberships;
    var singular = payload && payload.membership;
    if (!Array.isArray(items)) items = [];
    items = items.slice();
    if (singular && !items.some(function (item) { return String(item.authorityId || "") === String(singular.authorityId || ""); })) items.unshift(singular);
    return items.map(function (item) {
      var permissions = Array.isArray(item.permissions) ? item.permissions.map(String) : [];
      return {
        authorityId: String(item.authorityId || ""),
        companyId: String(item.companyId || ""),
        companyLabel: String(item.companyLabel || "Company"),
        role: String(item.role || "owner"),
        permissions: permissions,
        mockData: item.mockData === true
      };
    }).filter(function (item) { return item.authorityId && item.companyId; });
  }

  function normalizeRoster(payload) {
    var items = payload && payload.items;
    if (!Array.isArray(items)) return [];
    return items.map(function (item) {
      var grant = item.grant || {};
      return {
        credentialId: String(item.credentialId || ""),
        agentIdentityId: String(item.agentIdentityId || ""),
        requestedName: String(item.requestedName || ""),
        displayName: String(item.displayName || item.requestedName || ""),
        status: String(item.status || "active"),
        scopeType: String(grant.scopeType || ""),
        scopeId: String(grant.scopeId || ""),
        createdAt: String(item.createdAt || ""),
        expiresAt: String(item.expiresAt || ""),
        lastUsedAt: String(item.lastUsedAt || ""),
        grant: {
          scopeType: String(grant.scopeType || ""),
          scopeId: String(grant.scopeId || ""),
          accessRule: String(grant.accessRule || ""),
          immutable: grant.immutable === true
        },
        oneTimeSecretRetrievable: item.oneTimeSecretRetrievable === false,
        mockData: item.mockData === true
      };
    }).filter(function (item) {
      return item.credentialId && item.agentIdentityId && item.requestedName && item.displayName && item.scopeType && item.scopeId &&
        item.grant.accessRule && item.grant.immutable && item.oneTimeSecretRetrievable;
    });
  }

  function selectedCompany(payload) {
    var humanSession = payload && payload.humanSession || {};
    return String(payload && payload.selectedCompanyId || humanSession.selectedCompanyId || "");
  }

  function normalizeReplacement(payload) {
    var item = payload && payload.replacement || {};
    return {
      replacementId: String(item.replacementId || ""),
      credentialId: String(item.credentialId || ""),
      successorCredentialId: String(item.successorCredentialId || ""),
      status: String(item.status || ""),
      expiresAt: String(item.expiresAt || ""),
      predecessorRemainsActive: item.predecessorRemainsActive !== false,
      predecessorRevoked: item.predecessorRevoked === true,
      successorCredentialAlreadyDelivered: payload && payload.successorCredentialAlreadyDelivered === true
    };
  }

  function safeMessage(error) {
    var code = String(error && error.code || "request_failed");
    if (/session|csrf|authentication/.test(code) || Number(error && error.status) === 401) return "Your session is no longer available. Sign in again.";
    if (/permission|forbidden|required/.test(code) || Number(error && error.status) === 403) return "Your selected company membership does not allow that action.";
    if (/expired/.test(code) || Number(error && error.status) === 410) return "This one-time step expired. The existing credential remains active.";
    if (/invalid|validation|mismatch/.test(code) || Number(error && error.status) === 422) return "Check the entered values and try again.";
    if (/lost|network|unknown/.test(code) || Number(error && error.status) === 0) return "The outcome is unknown. Revalidate before retrying.";
    return "The request could not be completed safely.";
  }

  function createTransport(fetchImpl) {
    if (typeof fetchImpl !== "function") throw new TypeError("fetchImpl is required");
    return Object.freeze({
      request: async function (path, options) {
        var response;
        try { response = await fetchImpl(path, options); }
        catch (_) { throw new HumanAccessError("lost_response", 0); }
        var payload = {};
        try { payload = await response.json(); } catch (_) { payload = {}; }
        if (!response.ok) {
          var code = firstValue(payload, ["code"], "request_failed");
          var problem = payload.error || {};
          throw new HumanAccessError(problem.code || code, response.status);
        }
        return payload;
      }
    });
  }

  function createSessionAuthority() {
    var csrf = "";
    return Object.freeze({
      establish: function (session) { csrf = String(session && session.csrfToken || ""); },
      csrfToken: function () { return csrf; },
      clear: function () { csrf = ""; },
      inspect: function () { return {csrfAvailable: Boolean(csrf)}; }
    });
  }

  function clone(value) { return JSON.parse(JSON.stringify(value)); }

  function createDemoTransport(options) {
    var initialPlans = clone(Object.assign({}, options && options.plans || {}));
    var plans = clone(initialPlans);
    var calls = [];
    var signedIn = false;
    var selected = "";
    var pending = null;
    var csrfVersion = 0;
    var currentCsrf = "";
    var agentMasterEnabled = true;
    var initialMemberships = [{
      authorityId: "mock-authority-owner",
      companyId: "mock-company-memoryendpoints",
      companyLabel: "MemoryEndpoints Demo Company (Mock)",
      role: "owner",
      permissions: ["credential_admin"],
      mockData: true
    }];
    var initialRoster = [{
      credentialId: "mock-credential-frontend-agent",
      agentIdentityId: "mock-agent-identity-frontend",
      requestedName: "memoryendpoints-frontend-agent",
      displayName: "MemoryEndpoints Frontend Agent (Mock)",
      status: "active",
      grant: {scopeType: "workspace", scopeId: "mock-workspace-product-tour", accessRule: "scope_and_descendants", immutable: true},
      createdAt: "Demo sequence 01",
      lastUsedAt: "Demo sequence 04",
      oneTimeSecretRetrievable: false,
      mockData: true
    }];
    var memberships = clone(initialMemberships);
    var roster = clone(initialRoster);

    function sessionEnvelope(label) {
      csrfVersion += 1;
      currentCsrf = "DEMO CSRF PLACEHOLDER " + label + " " + csrfVersion;
      return {
        ok: true,
        csrfToken: currentCsrf,
        account: {humanAccountId: "mock-account-owner", username: "demo-owner", displayName: "Demo Owner (Mock)"},
        memberships: clone(memberships),
        humanSession: {humanAccountSessionId: "mock-session", selectedCompanyId: selected || null, expiresAt: "Demo session"},
        selectedCompanyId: selected || null,
        mockData: true
      };
    }

    function planned(operation) {
      var plan = plans[operation];
      if (Array.isArray(plan)) plan = plan.shift();
      if (!plan) return null;
      if (plan.lostResponse) throw new HumanAccessError("lost_response", 0);
      if (plan.error) throw new HumanAccessError(plan.error.code, plan.error.status);
      return clone(plan.payload || plan);
    }

    return Object.freeze({
      request: async function (path, requestOptions) {
        var operation = String(requestOptions.operation || "");
        var body = requestOptions.body ? JSON.parse(requestOptions.body) : {};
        var requestCsrf = requestOptions.headers && requestOptions.headers["X-CSRF-Token"] || "";
        var csrfRequired = ["sessionReauth", "sessionLogout", "memberships", "membershipLink", "membershipSelect", "roster", "agentMasterSetting", "agentMasterSettingUpdate", "replacementPrepare", "replacementConfirm", "replacementCancel", "replacementStatus"].indexOf(operation) >= 0;
        var csrfAccepted = !csrfRequired || Boolean(currentCsrf && requestCsrf === currentCsrf);
        calls.push({
          operation: operation,
          method: requestOptions.method,
          path: path,
          bodyKeys: Object.keys(body).sort(),
          csrfPresent: Boolean(requestCsrf),
          csrfAccepted: csrfAccepted,
          idempotencyKey: String(requestOptions.headers && requestOptions.headers["Idempotency-Key"] || "")
        });
        if (!csrfAccepted) throw new HumanAccessError("csrf_invalid", 403);
        var override = planned(operation);
        if (override) return override;
        if (operation === "masterProof") return {ok: true, companyMasterProofSecret: "DEMO PROOF PLACEHOLDER — NOT A CREDENTIAL", expiresInSeconds: 300, mockData: true};
        if (operation === "accountCreate" || operation === "sessionLogin") {
          signedIn = true;
          selected = "";
          var envelope = sessionEnvelope(operation);
          envelope.account.username = body.username || "demo-owner";
          if (operation === "accountCreate") envelope.membership = clone(memberships[0]);
          return envelope;
        }
        if (operation === "sessionInspect") {
          if (!signedIn) throw new HumanAccessError("human_session_required", 401);
          return sessionEnvelope("inspect");
        }
        if (operation === "memberships") return {ok: true, items: clone(memberships), selectedCompanyId: selected, mockData: true};
        if (operation === "membershipSelect") {
          var membership = memberships.filter(function (item) { return item.authorityId === String(body.authorityId || ""); })[0];
          if (!membership) throw new HumanAccessError("human_company_not_found", 404);
          selected = membership.companyId;
          return sessionEnvelope("company-select");
        }
        if (operation === "membershipLink") {
          var linked = {authorityId: "mock-authority-linked", companyId: "mock-company-linked", companyLabel: "Linked Demo Company (Mock)", role: "owner", permissions: ["agent_inventory_read", "credential_admin"], mockData: true};
          if (!memberships.some(function (item) { return item.authorityId === linked.authorityId; })) memberships.push(linked);
          return {ok: true, membership: clone(linked), memberships: clone(memberships), selectedCompanyId: selected || null, mockData: true};
        }
        if (operation === "roster") return {ok: true, items: clone(roster), mockData: true};
        if (operation === "agentMasterSetting") return {ok: true, enabled: agentMasterEnabled, databaseColumn: "top_level_agent_master_credential_enabled", mockData: true};
        if (operation === "agentMasterSettingUpdate") { agentMasterEnabled = body.enabled === true; return {ok: true, enabled: agentMasterEnabled, databaseColumn: "top_level_agent_master_credential_enabled", mockData: true}; }
        if (operation === "sessionReauth") return sessionEnvelope("reauth");
        if (operation === "replacementPrepare") {
          pending = {replacementId: "mock-replacement-pending", credentialId: path.split("/").slice(-2, -1)[0], status: "prepared", predecessorRemainsActive: true};
          return {ok: true, replacement: clone(pending), successorTokenSecret: "DEMO SUCCESSOR — NOT A CREDENTIAL", mockData: true};
        }
        if (operation === "replacementConfirm") { pending = Object.assign({}, pending || {}, {status: "confirmed", predecessorRemainsActive: false, predecessorRevoked: true}); return {ok: true, replacement: clone(pending), mockData: true}; }
        if (operation === "replacementCancel") { pending = Object.assign({}, pending || {}, {status: "canceled", predecessorRemainsActive: true, predecessorRevoked: false}); return {ok: true, replacement: clone(pending), mockData: true}; }
        if (operation === "replacementStatus") return {ok: true, replacement: clone(pending || {}), mockData: true};
        if (operation === "sessionLogout") { signedIn = false; selected = ""; pending = null; currentCsrf = ""; return {ok: true, mockData: true}; }
        throw new HumanAccessError("unknown_demo_operation", 400);
      },
      setPlan: function (operation, plan) { plans[operation] = plan; },
      reset: function () {
        plans = clone(initialPlans);
        memberships = clone(initialMemberships);
        roster = clone(initialRoster);
        signedIn = false;
        selected = "";
        pending = null;
        currentCsrf = "";
        agentMasterEnabled = true;
        csrfVersion = 0;
        calls.length = 0;
      },
      inspect: function () {
        return {
          mockData: true,
          networkRequestCount: 0,
          signedIn: signedIn,
          selectedCompany: Boolean(selected),
          pendingReplacement: Boolean(pending),
          membershipCount: memberships.length,
          calls: clone(calls)
        };
      }
    });
  }

  function required(root, selector) {
    var element = root.querySelector(selector);
    if (!element) throw new Error("Missing human access element: " + selector);
    return element;
  }

  function optional(root, selector) { return root.querySelector(selector) || null; }

  function clearNode(node) {
    if (typeof node.replaceChildren === "function") node.replaceChildren();
    else while (node.firstChild) node.removeChild(node.firstChild);
  }

  function clearControl(control) {
    if (!control) return;
    control.value = "";
    if (control.type === "text" && control.hasAttribute && control.hasAttribute("data-human-access-secret-control")) control.type = "password";
    if (control.checked !== undefined) control.checked = false;
    if (control.removeAttribute) control.removeAttribute("aria-invalid");
  }

  function create(options) {
    options = options || {};
    var root = options.root;
    if (!root) throw new TypeError("root is required");
    var documentRef = options.documentRef || root.ownerDocument;
    var windowRef = options.windowRef || (typeof window !== "undefined" ? window : null);
    var fetchImpl = options.fetchImpl || (windowRef && typeof windowRef.fetch === "function" ? windowRef.fetch.bind(windowRef) : null);
    var transport = options.transport || createTransport(fetchImpl);
    var sessionAuthority = options.sessionAuthority || createSessionAuthority();
    if (!sessionAuthority || typeof sessionAuthority.establish !== "function" || typeof sessionAuthority.csrfToken !== "function" || typeof sessionAuthority.clear !== "function") {
      throw new TypeError("sessionAuthority must implement establish, csrfToken, and clear");
    }
    var routes = createRouteAdapter(options.routes);
    var clipboard = options.clipboard || (windowRef && windowRef.navigator && windowRef.navigator.clipboard);
    var demoMode = options.demoMode === true;
    var preauthOnly = options.preauthOnly === true;
    var navigate = options.navigate || function (path) {
      if (windowRef && windowRef.location && typeof windowRef.location.assign === "function") windowRef.location.assign(path);
    };
    var operationCounter = 0;
    var epoch = 0;
    var mounted = false;
    var masterProofSecret = "";
    var successorTokenSecret = "";
    var dialogOpener = null;
    var pendingCredentialId = "";
    var replacementId = "";
    var prepareIdempotencyKey = "";
    var confirmIdempotencyKey = "";
    var cancelIdempotencyKey = "";
    var confirmAttempted = false;
    var prepareRequestBody = null;
    var reauthPurpose = "";

    var state = {
      sessionState: SESSION_STATES.LOCKED,
      replacementState: REPLACEMENT_STATES.IDLE,
      account: null,
      selectedCompanyId: "",
      workspaceId: "",
      projectId: "",
      agentId: "",
      memberships: [],
      roster: [],
      agentMasterEnabled: null,
      inventory: [],
      results: [],
      recoveryOperation: ""
    };

    var elements = {
      status: required(root, SELECTORS.status),
      locked: required(root, SELECTORS.locked),
      accountStep: required(root, SELECTORS.accountStep),
      protected: preauthOnly ? optional(root, SELECTORS.protected) : required(root, SELECTORS.protected),
      demoLabel: preauthOnly ? optional(root, SELECTORS.demoLabel) : required(root, SELECTORS.demoLabel),
      masterProofForm: required(root, SELECTORS.masterProofForm),
      accountForm: required(root, SELECTORS.accountForm),
      loginForm: required(root, SELECTORS.loginForm),
      logout: preauthOnly ? null : required(root, SELECTORS.logout),
      membershipForm: preauthOnly ? null : required(root, SELECTORS.membershipForm),
      membershipList: preauthOnly ? null : required(root, SELECTORS.membershipList),
      linkCompany: preauthOnly ? null : required(root, SELECTORS.linkCompany),
      linkDialog: preauthOnly ? null : required(root, SELECTORS.linkDialog),
      linkProofForm: preauthOnly ? null : required(root, SELECTORS.linkProofForm),
      linkCancel: preauthOnly ? null : required(root, SELECTORS.linkCancel),
      rosterList: preauthOnly ? null : required(root, SELECTORS.rosterList),
      rosterEmpty: preauthOnly ? null : required(root, SELECTORS.rosterEmpty),
      rosterRefresh: preauthOnly ? null : required(root, SELECTORS.rosterRefresh),
      agentMasterSettingForm: preauthOnly ? null : required(root, SELECTORS.agentMasterSettingForm),
      agentMasterSetting: preauthOnly ? null : required(root, SELECTORS.agentMasterSetting),
      agentMasterSettingStatus: preauthOnly ? null : required(root, SELECTORS.agentMasterSettingStatus),
      reauthDialog: preauthOnly ? null : required(root, SELECTORS.reauthDialog),
      reauthForm: preauthOnly ? null : required(root, SELECTORS.reauthForm),
      reauthCancel: preauthOnly ? null : required(root, SELECTORS.reauthCancel),
      replacementDialog: preauthOnly ? null : required(root, SELECTORS.replacementDialog),
      replacementSummary: preauthOnly ? null : required(root, SELECTORS.replacementSummary),
      replacementStatus: preauthOnly ? null : required(root, SELECTORS.replacementStatus),
      successorToken: preauthOnly ? null : required(root, SELECTORS.successorToken),
      successorShow: preauthOnly ? null : required(root, SELECTORS.successorShow),
      successorCopy: preauthOnly ? null : required(root, SELECTORS.successorCopy),
      successorSaved: preauthOnly ? null : required(root, SELECTORS.successorSaved),
      successorClear: preauthOnly ? null : required(root, SELECTORS.successorClear),
      possessionForm: preauthOnly ? null : required(root, SELECTORS.possessionForm),
      possessionToken: preauthOnly ? null : required(root, SELECTORS.possessionToken),
      replacementRetry: preauthOnly ? null : required(root, SELECTORS.replacementRetry),
      replacementCancel: preauthOnly ? null : required(root, SELECTORS.replacementCancel)
    };

    function formControl(form, name) { return form && form.elements ? form.elements[name] : null; }
    function setStatus(message, tone) { elements.status.textContent = String(message || ""); elements.status.dataset.tone = String(tone || ""); }
    function setSessionState(value) { state.sessionState = value; root.dataset.humanAccessState = value; }
    function setReplacementState(value) { state.replacementState = value; root.dataset.humanAccessReplacementState = value; }

    function createIdempotencyKey(label) {
      operationCounter += 1;
      return "human-access-" + label + "-" + operationCounter;
    }

    function openDialog(dialog, opener) {
      dialogOpener = opener || documentRef.activeElement || null;
      if (typeof dialog.showModal === "function") { if (!dialog.open) dialog.showModal(); }
      else { dialog.hidden = false; dialog.setAttribute("open", ""); dialog.setAttribute("aria-modal", "true"); }
    }

    function closeDialog(dialog) {
      if (typeof dialog.close === "function" && dialog.open) dialog.close();
      else { dialog.hidden = true; dialog.removeAttribute("open"); dialog.removeAttribute("aria-modal"); }
      var target = dialogOpener;
      dialogOpener = null;
      if (target && target.isConnected !== false && typeof target.focus === "function") target.focus();
      else if (typeof elements.status.focus === "function") elements.status.focus();
    }

    function clearReplacementSecrets(options) {
      var preserveAcknowledgement = Boolean(options && options.preserveAcknowledgement);
      successorTokenSecret = "";
      if (elements.successorToken) clearControl(elements.successorToken);
      if (elements.possessionToken) clearControl(elements.possessionToken);
      if (elements.successorSaved && !preserveAcknowledgement) clearControl(elements.successorSaved);
    }

    function renderMemberships() {
      clearNode(elements.membershipList);
      var placeholder = documentRef.createElement("option");
      placeholder.value = "";
      placeholder.textContent = state.memberships.length ? "Select a company" : "No linked companies";
      elements.membershipList.appendChild(placeholder);
      state.memberships.forEach(function (item) {
        var option = documentRef.createElement("option");
        option.value = item.authorityId;
        option.textContent = item.companyLabel + " — " + item.role + (item.mockData ? " — Mock data" : "");
        elements.membershipList.appendChild(option);
      });
      var selectedMembership = state.memberships.filter(function (item) { return item.companyId === state.selectedCompanyId; })[0];
      elements.membershipList.value = selectedMembership ? selectedMembership.authorityId : "";
    }

    function appendText(parent, tag, value, className) {
      var element = documentRef.createElement(tag);
      if (className) element.className = className;
      element.textContent = String(value || "");
      parent.appendChild(element);
      return element;
    }

    function canReplace() {
      var selected = state.memberships.filter(function (item) { return item.companyId === state.selectedCompanyId; })[0];
      return Boolean(selected && selected.permissions.indexOf("credential_admin") >= 0);
    }

    function renderRoster() {
      clearNode(elements.rosterList);
      elements.rosterEmpty.hidden = state.roster.length !== 0;
      state.roster.forEach(function (item) {
        var card = documentRef.createElement("article");
        card.className = "human-access-roster-card";
        appendText(card, "p", item.mockData ? "Mock data" : "Agent credential", "human-access-eyebrow");
        appendText(card, "h3", item.displayName, "human-access-card-title");
        appendText(card, "p", item.requestedName, "human-access-agent-name");
        appendText(card, "p", item.scopeType + (item.scopeId ? " · " + item.scopeId : ""), "human-access-scope");
        appendText(card, "p", "Status: " + item.status, "human-access-status-line");
        appendText(card, "p", "Agent identity: " + item.agentIdentityId, "human-access-agent-identity");
        appendText(card, "p", "Credential ID: " + item.credentialId, "human-access-credential-id");
        var replace = documentRef.createElement("button");
        replace.type = "button";
        replace.className = "button human-access-replace";
        replace.textContent = "Replace & reveal new token once";
        replace.disabled = !canReplace();
        replace.addEventListener("click", function () { beginReplacement(item.credentialId, replace); });
        card.appendChild(replace);
        elements.rosterList.appendChild(card);
      });
    }

    function renderAgentMasterSetting() {
      if (!elements.agentMasterSetting) return;
      elements.agentMasterSetting.checked = state.agentMasterEnabled === true;
      elements.agentMasterSetting.disabled = state.agentMasterEnabled === null;
      elements.agentMasterSettingStatus.textContent = state.agentMasterEnabled === null
        ? "Setting unavailable."
        : (state.agentMasterEnabled ? "Top-level agent recovery is enabled." : "Top-level agent recovery is disabled.");
    }

    function hideProtected() {
      elements.locked.hidden = false;
      if (elements.protected) {
        elements.protected.hidden = true;
        elements.protected.setAttribute("aria-hidden", "true");
      }
    }

    function showProtected() {
      elements.locked.hidden = true;
      if (!elements.protected) return;
      elements.protected.hidden = false;
      elements.protected.removeAttribute("aria-hidden");
    }

    function scrubProtectedState(reason) {
      epoch += 1;
      masterProofSecret = "";
      sessionAuthority.clear();
      clearReplacementSecrets();
      pendingCredentialId = "";
      replacementId = "";
      prepareIdempotencyKey = "";
      confirmIdempotencyKey = "";
      cancelIdempotencyKey = "";
      confirmAttempted = false;
      prepareRequestBody = null;
      reauthPurpose = "";
      state.account = null;
      state.selectedCompanyId = "";
      state.workspaceId = "";
      state.projectId = "";
      state.agentId = "";
      state.memberships = [];
      state.roster = [];
      state.agentMasterEnabled = null;
      state.inventory = [];
      state.results = [];
      state.recoveryOperation = "";
      clearControl(formControl(elements.masterProofForm, "companyMasterTokenSecret"));
      clearControl(formControl(elements.accountForm, "password"));
      clearControl(formControl(elements.accountForm, "passwordConfirmation"));
      clearControl(formControl(elements.loginForm, "password"));
      clearControl(formControl(elements.reauthForm, "password"));
      clearControl(formControl(elements.linkProofForm, "companyMasterTokenSecret"));
      if (elements.membershipList) clearNode(elements.membershipList);
      if (elements.rosterList) clearNode(elements.rosterList);
      if (elements.rosterEmpty) elements.rosterEmpty.hidden = true;
      if (elements.agentMasterSetting) {
        elements.agentMasterSetting.checked = false;
        elements.agentMasterSetting.disabled = true;
      }
      if (elements.agentMasterSettingStatus) elements.agentMasterSettingStatus.textContent = "";
      elements.accountStep.hidden = true;
      if (elements.reauthDialog && (elements.reauthDialog.open || elements.reauthDialog.hasAttribute("open"))) closeDialog(elements.reauthDialog);
      if (elements.linkDialog && (elements.linkDialog.open || elements.linkDialog.hasAttribute("open"))) closeDialog(elements.linkDialog);
      if (elements.replacementDialog && (elements.replacementDialog.open || elements.replacementDialog.hasAttribute("open"))) closeDialog(elements.replacementDialog);
      hideProtected();
      setReplacementState(REPLACEMENT_STATES.IDLE);
      setSessionState(SESSION_STATES.LOCKED);
      if (reason) setStatus(reason, "neutral");
    }

    async function requestOperation(name, params, body, requestOptions) {
      var spec = routes.resolve(name, params);
      var config = requestOptions || {};
      var headers = {Accept: "application/json"};
      if (body !== undefined) headers["Content-Type"] = "application/json";
      if (config.csrf) {
        var csrf = config.csrfOverride || sessionAuthority.csrfToken();
        if (!csrf) throw new HumanAccessError("csrf_required", 403);
        headers["X-CSRF-Token"] = csrf;
      }
      if (config.idempotencyKey) headers["Idempotency-Key"] = config.idempotencyKey;
      return transport.request(spec.path, {
        method: spec.method,
        headers: headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        operation: name
      });
    }

    function applyError(error, replacementOperation) {
      var code = String(error && error.code || "request_failed");
      if (/session|csrf|authentication/.test(code) || Number(error && error.status) === 401) {
        scrubProtectedState("Your session is no longer available. Sign in again.");
        return;
      }
      if (/expired/.test(code) || Number(error && error.status) === 410) {
        setSessionState(SESSION_STATES.EXPIRED);
        if (replacementOperation) {
          clearTerminalReplacement(REPLACEMENT_STATES.EXPIRED, "Replacement expired. The existing credential remains active.", true);
          refreshRoster();
        }
      } else if (/permission|forbidden|required/.test(code) || Number(error && error.status) === 403) {
        setSessionState(SESSION_STATES.PERMISSION_ERROR);
      } else if (/invalid|validation|mismatch/.test(code) || Number(error && error.status) === 422) {
        setSessionState(SESSION_STATES.VALIDATION_ERROR);
      } else if (Number(error && error.status) === 0 || /outcome_unknown/.test(code)) {
        state.recoveryOperation = replacementOperation || "session";
        setSessionState(SESSION_STATES.RECOVERY_REQUIRED);
        if (replacementOperation) setReplacementState(REPLACEMENT_STATES.OUTCOME_UNKNOWN);
      }
      setStatus(safeMessage(error), "error");
    }

    async function refreshRoster() {
      if (!state.selectedCompanyId || !sessionAuthority.csrfToken()) return;
      var actionEpoch = epoch;
      setSessionState(SESSION_STATES.LOADING);
      try {
        var payload = await requestOperation("roster", {companyId: state.selectedCompanyId}, undefined, {csrf: true});
        if (actionEpoch !== epoch) return;
        state.roster = normalizeRoster(payload);
        state.inventory = state.roster.slice();
        renderRoster();
        setSessionState(state.roster.length ? SESSION_STATES.READY : SESSION_STATES.EMPTY);
        setStatus(state.roster.length ? "Agent credential inventory loaded." : "No agent credentials exist for this company.", "success");
      } catch (error) { if (actionEpoch === epoch) applyError(error, ""); }
    }

    async function refreshAgentMasterSetting() {
      if (!state.selectedCompanyId || !sessionAuthority.csrfToken()) return;
      var actionEpoch = epoch;
      try {
        var payload = await requestOperation("agentMasterSetting", {companyId: state.selectedCompanyId}, undefined, {csrf: true});
        if (actionEpoch !== epoch) return;
        state.agentMasterEnabled = payload.enabled === true;
        renderAgentMasterSetting();
      } catch (error) { if (actionEpoch === epoch) applyError(error, ""); }
    }

    async function saveAgentMasterSetting() {
      if (!state.selectedCompanyId || !sessionAuthority.csrfToken()) return;
      var actionEpoch = epoch;
      var enabled = elements.agentMasterSetting.checked === true;
      elements.agentMasterSetting.disabled = true;
      elements.agentMasterSettingStatus.textContent = "Saving...";
      try {
        var payload = await requestOperation("agentMasterSettingUpdate", {companyId: state.selectedCompanyId}, {enabled: enabled}, {csrf: true});
        if (actionEpoch !== epoch) return;
        state.agentMasterEnabled = payload.enabled === true;
        renderAgentMasterSetting();
        setStatus("Top-level agent recovery setting saved.", "success");
      } catch (error) {
        if (actionEpoch === epoch) {
          renderAgentMasterSetting();
          applyError(error, "");
        }
      }
    }

    async function unlockFromSession(payload, actionEpoch, unlockOptions) {
      var config = unlockOptions || {};
      var nextCsrf = takeSecret(payload, ["csrfToken"]);
      if (!nextCsrf) throw new HumanAccessError("csrf_required", 403);
      if (actionEpoch !== epoch) return;
      state.account = normalizeAccount(payload);
      if (!state.account.accountId) throw new HumanAccessError("human_session_invalid", 422);
      state.memberships = normalizeMemberships(payload);
      state.selectedCompanyId = selectedCompany(payload);
      sessionAuthority.establish({
        csrfToken: nextCsrf,
        account: state.account,
        memberships: state.memberships,
        selectedCompanyId: state.selectedCompanyId,
        demoMode: demoMode
      });
      if (preauthOnly) {
        masterProofSecret = "";
        setSessionState(SESSION_STATES.READY);
        setStatus("Authentication succeeded. Loading the protected human console…", "success");
        navigate("/human");
        return;
      }
      showProtected();
      renderMemberships();
      if (!state.memberships.length) {
        state.roster = [];
        renderRoster();
        setSessionState(SESSION_STATES.EMPTY);
        setStatus("No linked companies are available.", "neutral");
        return;
      }
      if (!state.selectedCompanyId) {
        setSessionState(SESSION_STATES.CHOOSING_COMPANY);
        setStatus("Choose a linked company to continue.", "neutral");
        return;
      }
      if (config.skipRoster) {
        setSessionState(SESSION_STATES.READY);
        setStatus("Human session authority rotated successfully.", "success");
        return;
      }
      await refreshAgentMasterSetting();
      if (actionEpoch !== epoch) return;
      await refreshRoster();
    }

    async function submitMasterProof() {
      var input = formControl(elements.masterProofForm, "companyMasterTokenSecret");
      var rawMaster = String(input && input.value || "");
      clearControl(input);
      if (!rawMaster) { setSessionState(SESSION_STATES.VALIDATION_ERROR); setStatus("Enter a company master credential to prove ownership.", "error"); return; }
      var actionEpoch = epoch;
      setSessionState(SESSION_STATES.PROVING_MASTER);
      try {
        var pendingRequest = requestOperation("masterProof", {}, {companyMasterTokenSecret: rawMaster}, {});
        rawMaster = "";
        var payload = await pendingRequest;
        if (actionEpoch !== epoch) return;
        masterProofSecret = takeSecret(payload, ["companyMasterProofSecret"]);
        if (!masterProofSecret) throw new HumanAccessError("company_master_proof_missing", 422);
        elements.accountStep.hidden = false;
        setSessionState(SESSION_STATES.PROOF_READY);
        setStatus("Ownership proof accepted. Create the first human owner account.", "success");
      } catch (error) { if (actionEpoch === epoch) applyError(error, ""); }
    }

    async function createAccount() {
      var username = String(formControl(elements.accountForm, "username").value || "").trim();
      var displayName = String(formControl(elements.accountForm, "displayName").value || "").trim();
      var passwordInput = formControl(elements.accountForm, "password");
      var confirmationInput = formControl(elements.accountForm, "passwordConfirmation");
      var password = String(passwordInput.value || "");
      var confirmation = String(confirmationInput.value || "");
      clearControl(passwordInput);
      clearControl(confirmationInput);
      var proof = masterProofSecret;
      masterProofSecret = "";
      if (!username || !password || password !== confirmation || !proof) { password = ""; confirmation = ""; proof = ""; setSessionState(SESSION_STATES.VALIDATION_ERROR); setStatus("Complete ownership proof and enter matching account passwords.", "error"); return; }
      var actionEpoch = epoch;
      setSessionState(SESSION_STATES.CREATING_ACCOUNT);
      try {
        var pendingRequest = requestOperation("accountCreate", {}, {username: username, displayName: displayName, password: password, companyMasterProofSecret: proof}, {});
        password = ""; confirmation = ""; proof = "";
        var payload = await pendingRequest;
        if (actionEpoch !== epoch) return;
        await unlockFromSession(payload, actionEpoch);
      } catch (error) { if (actionEpoch === epoch) applyError(error, ""); }
    }

    async function login() {
      var username = String(formControl(elements.loginForm, "username").value || "").trim();
      var passwordInput = formControl(elements.loginForm, "password");
      var password = String(passwordInput.value || "");
      clearControl(passwordInput);
      if (!username || !password) { password = ""; setSessionState(SESSION_STATES.VALIDATION_ERROR); setStatus("Enter your username and password.", "error"); return; }
      var actionEpoch = epoch;
      setSessionState(SESSION_STATES.SIGNING_IN);
      try {
        var pendingRequest = requestOperation("sessionLogin", {}, {username: username, password: password}, {});
        password = "";
        var payload = await pendingRequest;
        if (actionEpoch !== epoch) return;
        await unlockFromSession(payload, actionEpoch);
      } catch (error) { if (actionEpoch === epoch) applyError(error, ""); }
    }

    async function revalidateHumanSession() {
      scrubProtectedState("Revalidating your human session…");
      var actionEpoch = epoch;
      setSessionState(SESSION_STATES.REVALIDATING);
      try {
        var payload = await requestOperation("sessionInspect", {}, undefined, {});
        if (actionEpoch !== epoch) return;
        await unlockFromSession(payload, actionEpoch);
      } catch (error) { if (actionEpoch === epoch) applyError(error, ""); }
    }

    async function selectMembership() {
      var authorityId = String(elements.membershipList.value || "");
      if (!authorityId) { setSessionState(SESSION_STATES.VALIDATION_ERROR); setStatus("Choose a company.", "error"); return; }
      var requestCsrf = sessionAuthority.csrfToken();
      scrubProtectedState("Switching companies…");
      var actionEpoch = epoch;
      setSessionState(SESSION_STATES.SWITCHING_COMPANY);
      try {
        var payload = await requestOperation("membershipSelect", {}, {authorityId: authorityId}, {csrf: true, csrfOverride: requestCsrf});
        requestCsrf = "";
        if (actionEpoch !== epoch) return;
        await unlockFromSession(payload, actionEpoch);
      } catch (error) { requestCsrf = ""; if (actionEpoch === epoch) applyError(error, ""); }
    }

    function beginReplacement(credentialId, opener) {
      if (!credentialId || !state.selectedCompanyId) return;
      pendingCredentialId = String(credentialId);
      reauthPurpose = "replacement";
      setReplacementState(REPLACEMENT_STATES.REAUTHENTICATING);
      setStatus("Re-enter your password before preparing a successor credential.", "neutral");
      openDialog(elements.reauthDialog, opener);
    }

    function beginLinkCompany(opener) {
      reauthPurpose = "link_company";
      setSessionState(SESSION_STATES.LOADING);
      setStatus("Re-enter your password before linking another company.", "neutral");
      openDialog(elements.reauthDialog, opener);
    }

    function cancelReauthentication(event) {
      if (event && typeof event.preventDefault === "function") event.preventDefault();
      var purpose = reauthPurpose;
      reauthPurpose = "";
      clearControl(formControl(elements.reauthForm, "password"));
      if (purpose === "replacement") {
        pendingCredentialId = "";
        setReplacementState(REPLACEMENT_STATES.IDLE);
      }
      setSessionState(state.selectedCompanyId ? SESSION_STATES.READY : SESSION_STATES.CHOOSING_COMPANY);
      closeDialog(elements.reauthDialog);
    }

    function cancelLinkCompanyDialog(event) {
      if (event && typeof event.preventDefault === "function") event.preventDefault();
      masterProofSecret = "";
      reauthPurpose = "";
      clearControl(formControl(elements.linkProofForm, "companyMasterTokenSecret"));
      setSessionState(state.selectedCompanyId ? SESSION_STATES.READY : SESSION_STATES.CHOOSING_COMPANY);
      closeDialog(elements.linkDialog);
    }

    async function submitReauthentication() {
      var passwordInput = formControl(elements.reauthForm, "password");
      var password = String(passwordInput.value || "");
      clearControl(passwordInput);
      if (!password) { setStatus("Enter your password to continue.", "error"); return; }
      var actionEpoch = epoch;
      try {
        var pendingRequest = requestOperation("sessionReauth", {}, {password: password}, {csrf: true});
        password = "";
        var payload = await pendingRequest;
        if (actionEpoch !== epoch) return;
        await unlockFromSession(payload, actionEpoch, {skipRoster: true});
        closeDialog(elements.reauthDialog);
        if (reauthPurpose === "link_company") {
          openDialog(elements.linkDialog, dialogOpener);
          setStatus("Enter the additional company master credential. It is used only for this proof request.", "neutral");
        } else {
          await prepareReplacement();
        }
      } catch (error) { password = ""; if (actionEpoch === epoch) applyError(error, reauthPurpose === "replacement" ? "replacement" : ""); }
    }

    async function submitLinkCompanyProof() {
      var input = formControl(elements.linkProofForm, "companyMasterTokenSecret");
      var rawMaster = String(input && input.value || "");
      clearControl(input);
      if (!rawMaster) { setSessionState(SESSION_STATES.VALIDATION_ERROR); setStatus("Enter the company master credential to link.", "error"); return; }
      var actionEpoch = epoch;
      try {
        var proofRequest = requestOperation("masterProof", {}, {companyMasterTokenSecret: rawMaster}, {});
        rawMaster = "";
        var proofPayload = await proofRequest;
        if (actionEpoch !== epoch) return;
        masterProofSecret = takeSecret(proofPayload, ["companyMasterProofSecret"]);
        if (!masterProofSecret) throw new HumanAccessError("company_master_proof_missing", 422);
        var proof = masterProofSecret;
        masterProofSecret = "";
        var linkRequest = requestOperation("membershipLink", {}, {companyMasterProofSecret: proof}, {csrf: true});
        proof = "";
        var linkPayload = await linkRequest;
        if (actionEpoch !== epoch) return;
        state.memberships = normalizeMemberships(linkPayload);
        renderMemberships();
        reauthPurpose = "";
        closeDialog(elements.linkDialog);
        setSessionState(state.selectedCompanyId ? SESSION_STATES.READY : SESSION_STATES.CHOOSING_COMPANY);
        setStatus("Company linked. Select it explicitly when you are ready to switch.", "success");
      } catch (error) {
        rawMaster = "";
        masterProofSecret = "";
        if (actionEpoch === epoch) applyError(error, "");
      }
    }

    async function prepareReplacement() {
      var actionEpoch = epoch;
      var credentialId = pendingCredentialId;
      setReplacementState(REPLACEMENT_STATES.PREPARING);
      prepareIdempotencyKey = createIdempotencyKey("replacement-prepare");
      confirmIdempotencyKey = "";
      cancelIdempotencyKey = "";
      confirmAttempted = false;
      prepareRequestBody = {};
      try {
        var payload = await requestOperation("replacementPrepare", {companyId: state.selectedCompanyId, credentialId: credentialId}, prepareRequestBody, {csrf: true, idempotencyKey: prepareIdempotencyKey});
        if (actionEpoch !== epoch) return;
        var replacement = normalizeReplacement(payload);
        replacementId = replacement.replacementId;
        successorTokenSecret = takeSecret(payload, ["successorTokenSecret"]);
        if (!replacementId) throw new HumanAccessError("replacement_metadata_missing", 422);
        if (replacement.successorCredentialAlreadyDelivered || !successorTokenSecret) {
          clearReplacementSecrets();
          state.recoveryOperation = "prepare";
          setSessionState(SESSION_STATES.RECOVERY_REQUIRED);
          setReplacementState(REPLACEMENT_STATES.OUTCOME_UNKNOWN);
          setStatus("The successor was already delivered or its reveal outcome is unknown. Check status before continuing.", "error");
          return;
        }
        elements.successorToken.type = "password";
        elements.successorToken.value = successorTokenSecret;
        elements.replacementSummary.textContent = "A pending successor is ready. The existing credential stays active until possession is confirmed.";
        elements.replacementStatus.textContent = "Copy and save this successor now. It will not be shown again.";
        setReplacementState(REPLACEMENT_STATES.REVEALED_UNSAVED);
        openDialog(elements.replacementDialog, dialogOpener);
      } catch (error) { if (actionEpoch === epoch) { clearReplacementSecrets(); applyError(error, "prepare"); } }
    }

    async function copySuccessor() {
      if (!successorTokenSecret || !clipboard || typeof clipboard.writeText !== "function") { setStatus("Copy is unavailable. Save the displayed successor manually.", "error"); return; }
      try { await clipboard.writeText(successorTokenSecret); setStatus("Successor copied. Confirm that you saved it.", "success"); }
      catch (_) { setStatus("Copy failed. Save the displayed successor manually.", "error"); }
    }

    function markSuccessorSaved() {
      if (!elements.successorSaved.checked) return;
      clearReplacementSecrets({preserveAcknowledgement: true});
      setReplacementState(REPLACEMENT_STATES.SAVED_CLEARED);
      elements.replacementStatus.textContent = "Reveal cleared. Paste the saved successor below to prove possession.";
      if (typeof elements.possessionToken.focus === "function") elements.possessionToken.focus();
    }

    function clearSuccessorReveal() {
      clearReplacementSecrets({preserveAcknowledgement: Boolean(elements.successorSaved.checked)});
      setReplacementState(REPLACEMENT_STATES.SAVED_CLEARED);
      elements.replacementStatus.textContent = "Reveal cleared. Paste your saved successor to confirm, or cancel to keep the existing credential.";
    }

    function clearTerminalReplacement(nextState, message, close) {
      clearReplacementSecrets();
      pendingCredentialId = "";
      replacementId = "";
      prepareIdempotencyKey = "";
      confirmIdempotencyKey = "";
      cancelIdempotencyKey = "";
      confirmAttempted = false;
      prepareRequestBody = null;
      reauthPurpose = "";
      state.recoveryOperation = "";
      state.roster = [];
      state.inventory = [];
      renderRoster();
      setReplacementState(nextState);
      if (elements.replacementStatus) elements.replacementStatus.textContent = message;
      setStatus(message, nextState === REPLACEMENT_STATES.CONFIRMED || nextState === REPLACEMENT_STATES.CANCELED ? "success" : "neutral");
      if (close && elements.replacementDialog && (elements.replacementDialog.open || elements.replacementDialog.hasAttribute("open"))) closeDialog(elements.replacementDialog);
    }

    async function finishReplacement(nextState, message) {
      clearTerminalReplacement(nextState, message, true);
      await refreshRoster();
    }

    async function confirmReplacement() {
      var input = elements.possessionToken;
      var proof = String(input.value || "");
      clearControl(input);
      if (!proof) { setStatus("Paste the saved successor to prove possession.", "error"); return; }
      var actionEpoch = epoch;
      setReplacementState(REPLACEMENT_STATES.CONFIRMING);
      if (!confirmIdempotencyKey) confirmIdempotencyKey = createIdempotencyKey("replacement-confirm");
      var body = {successorTokenProof: proof};
      confirmAttempted = true;
      try {
        var pendingRequest = requestOperation("replacementConfirm", {companyId: state.selectedCompanyId, credentialId: pendingCredentialId, replacementId: replacementId}, body, {csrf: true, idempotencyKey: confirmIdempotencyKey});
        proof = "";
        var payload = await pendingRequest;
        if (actionEpoch !== epoch) return;
        var replacement = normalizeReplacement(payload);
        if (replacement.status !== "confirmed") throw new HumanAccessError("replacement_confirmation_missing", 409);
        await finishReplacement(REPLACEMENT_STATES.CONFIRMED, "Successor confirmed. The predecessor is now revoked.");
      } catch (error) { proof = ""; if (actionEpoch === epoch) applyError(error, "confirm"); }
    }

    async function cancelReplacement(reuseKey) {
      clearReplacementSecrets();
      if (!replacementId) { setReplacementState(REPLACEMENT_STATES.CANCELED); closeDialog(elements.replacementDialog); return; }
      var actionEpoch = epoch;
      setReplacementState(REPLACEMENT_STATES.CANCELING);
      if (!reuseKey || !cancelIdempotencyKey) cancelIdempotencyKey = createIdempotencyKey("replacement-cancel");
      try {
        var payload = await requestOperation("replacementCancel", {companyId: state.selectedCompanyId, credentialId: pendingCredentialId, replacementId: replacementId}, {}, {csrf: true, idempotencyKey: cancelIdempotencyKey});
        if (actionEpoch !== epoch) return;
        var replacement = normalizeReplacement(payload);
        if (replacement.status !== "canceled" && replacement.status !== "expired") throw new HumanAccessError("replacement_cancel_missing", 409);
        await finishReplacement(replacement.status === "expired" ? REPLACEMENT_STATES.EXPIRED : REPLACEMENT_STATES.CANCELED, replacement.status === "expired" ? "Replacement expired. The existing credential remains active." : "Replacement canceled. The existing credential remains active.");
      } catch (error) { if (actionEpoch === epoch) applyError(error, "cancel"); }
    }

    async function recoverReplacementOutcome() {
      var actionEpoch = epoch;
      var recovery = state.recoveryOperation;
      setStatus("Checking the replacement status before taking another action…", "neutral");
      try {
        if (recovery === "prepare" && !replacementId) {
          var replayPayload = await requestOperation("replacementPrepare", {companyId: state.selectedCompanyId, credentialId: pendingCredentialId}, prepareRequestBody || {}, {csrf: true, idempotencyKey: prepareIdempotencyKey});
          if (actionEpoch !== epoch) return;
          var replayReplacement = normalizeReplacement(replayPayload);
          replacementId = replayReplacement.replacementId;
          var accidentallyReturnedSecret = takeSecret(replayPayload, ["successorTokenSecret"]);
          accidentallyReturnedSecret = "";
          clearReplacementSecrets();
          if (!replacementId) throw new HumanAccessError("replacement_outcome_unknown", 409);
        }
        if (!replacementId) throw new HumanAccessError("replacement_outcome_unknown", 409);
        var statusPayload = await requestOperation("replacementStatus", {companyId: state.selectedCompanyId, credentialId: pendingCredentialId, replacementId: replacementId}, undefined, {csrf: true});
        if (actionEpoch !== epoch) return;
        var replacement = normalizeReplacement(statusPayload);
        if (replacement.status === "confirmed") {
          await finishReplacement(REPLACEMENT_STATES.CONFIRMED, "Replacement was already confirmed. Protected state was refreshed.");
          return;
        }
        if (replacement.status === "canceled" || replacement.status === "expired") {
          await finishReplacement(replacement.status === "expired" ? REPLACEMENT_STATES.EXPIRED : REPLACEMENT_STATES.CANCELED, "The pending successor is no longer active. The predecessor remains active.");
          return;
        }
        if (replacement.status !== "prepared") throw new HumanAccessError("replacement_outcome_unknown", 409);
        if (recovery === "prepare") {
          await cancelReplacement(false);
          setStatus("The unrevealed successor was canceled. Reauthenticate before starting a fresh replacement.", "success");
          return;
        }
        if (recovery === "cancel") {
          await cancelReplacement(true);
          return;
        }
        state.recoveryOperation = "";
        setReplacementState(REPLACEMENT_STATES.SAVED_CLEARED);
        elements.replacementStatus.textContent = "The successor is still pending. Paste the saved successor again to confirm possession.";
        if (!elements.replacementDialog.open) openDialog(elements.replacementDialog, dialogOpener);
        if (typeof elements.possessionToken.focus === "function") elements.possessionToken.focus();
      } catch (error) { if (actionEpoch === epoch) applyError(error, recovery || "status"); }
    }

    async function logout() {
      var requestCsrf = sessionAuthority.csrfToken();
      scrubProtectedState("Signed out. Protected information was cleared.");
      try { await requestOperation("sessionLogout", {}, {}, {csrf: true, csrfOverride: requestCsrf}); } catch (_) { /* locked locally regardless */ }
      requestCsrf = "";
    }

    function getSnapshot() {
      return {
        sessionState: state.sessionState,
        replacementState: state.replacementState,
        authenticated: Boolean(state.account && sessionAuthority.csrfToken()),
        accountPresent: Boolean(state.account),
        accountIdPresent: Boolean(state.account && state.account.accountId),
        selectedCompanyPresent: Boolean(state.selectedCompanyId),
        membershipCount: state.memberships.length,
        rosterCount: state.roster.length,
        agentMasterEnabled: state.agentMasterEnabled,
        replacementPending: Boolean(replacementId),
        successorAvailable: Boolean(successorTokenSecret),
        recoveryOperation: state.recoveryOperation,
        demoMode: demoMode
      };
    }

    function onPageHide() { scrubProtectedState("Page hidden. Protected information was cleared."); }
    function onPageShow(event) { if (event && event.persisted) revalidateHumanSession(); }

    function mount() {
      if (mounted) return getSnapshot();
      mounted = true;
      if (elements.demoLabel) {
        elements.demoLabel.hidden = !demoMode;
        if (demoMode) elements.demoLabel.textContent = "Demo - clearly labeled, session-only mock data using the real human-access interface.";
      }
      elements.masterProofForm.addEventListener("submit", function (event) { event.preventDefault(); submitMasterProof(); });
      elements.accountForm.addEventListener("submit", function (event) { event.preventDefault(); createAccount(); });
      elements.loginForm.addEventListener("submit", function (event) { event.preventDefault(); login(); });
      if (!preauthOnly) {
        elements.membershipForm.addEventListener("submit", function (event) { event.preventDefault(); selectMembership(); });
        elements.logout.addEventListener("click", logout);
        elements.linkCompany.addEventListener("click", function () { beginLinkCompany(elements.linkCompany); });
        elements.linkProofForm.addEventListener("submit", function (event) { event.preventDefault(); submitLinkCompanyProof(); });
        elements.linkCancel.addEventListener("click", cancelLinkCompanyDialog);
        elements.linkDialog.addEventListener("cancel", cancelLinkCompanyDialog);
        elements.rosterRefresh.addEventListener("click", refreshRoster);
        elements.agentMasterSettingForm.addEventListener("submit", function (event) { event.preventDefault(); saveAgentMasterSetting(); });
        elements.reauthForm.addEventListener("submit", function (event) { event.preventDefault(); submitReauthentication(); });
        elements.reauthCancel.addEventListener("click", cancelReauthentication);
        elements.reauthDialog.addEventListener("cancel", cancelReauthentication);
        elements.successorShow.addEventListener("click", function () { elements.successorToken.type = elements.successorToken.type === "password" ? "text" : "password"; });
        elements.successorCopy.addEventListener("click", copySuccessor);
        elements.successorSaved.addEventListener("change", markSuccessorSaved);
        elements.successorClear.addEventListener("click", clearSuccessorReveal);
        elements.possessionForm.addEventListener("submit", function (event) { event.preventDefault(); confirmReplacement(); });
        elements.replacementRetry.addEventListener("click", recoverReplacementOutcome);
        elements.replacementCancel.addEventListener("click", function () { cancelReplacement(false); });
        elements.replacementDialog.addEventListener("cancel", function (event) { event.preventDefault(); cancelReplacement(false); });
      }
      if (windowRef && typeof windowRef.addEventListener === "function") {
        windowRef.addEventListener("pagehide", onPageHide);
        windowRef.addEventListener("pageshow", onPageShow);
      }
      scrubProtectedState("Sign in or prove a company master credential to continue.");
      return getSnapshot();
    }

    function destroy() {
      scrubProtectedState("Human access interface closed.");
      if (windowRef && typeof windowRef.removeEventListener === "function") {
        windowRef.removeEventListener("pagehide", onPageHide);
        windowRef.removeEventListener("pageshow", onPageShow);
      }
      mounted = false;
    }

    return Object.freeze({
      mount: mount,
      scrubProtectedState: scrubProtectedState,
      revalidateHumanSession: revalidateHumanSession,
      getSnapshot: getSnapshot,
      refreshRoster: refreshRoster,
      refreshAgentMasterSetting: refreshAgentMasterSetting,
      saveAgentMasterSetting: saveAgentMasterSetting,
      beginReplacement: beginReplacement,
      beginLinkCompany: beginLinkCompany,
      confirmReplacement: confirmReplacement,
      cancelReplacement: cancelReplacement,
      recoverReplacementOutcome: recoverReplacementOutcome,
      logout: logout,
      destroy: destroy
    });
  }

  function createPreauth(options) {
    return create(Object.assign({}, options || {}, {preauthOnly: true, demoMode: false}));
  }

  return Object.freeze({
    ROUTES: ROUTES,
    SELECTORS: SELECTORS,
    SESSION_STATES: SESSION_STATES,
    REPLACEMENT_STATES: REPLACEMENT_STATES,
    HumanAccessError: HumanAccessError,
    createRouteAdapter: createRouteAdapter,
    createTransport: createTransport,
    createSessionAuthority: createSessionAuthority,
    createDemoTransport: createDemoTransport,
    createPreauth: createPreauth,
    create: create
  });
});
