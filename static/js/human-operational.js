(function (globalScope, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (globalScope) globalScope.MemoryEndpointsHumanOperational = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function frozenList(values) {
    return Object.freeze(values.slice());
  }

  function operation(method, path, options) {
    var config = options || {};
    return Object.freeze({
      method: method,
      path: path,
      queryKeys: frozenList(config.queryKeys || []),
      bodyKeys: frozenList(config.bodyKeys || []),
      requiredBodyKeys: frozenList(config.requiredBodyKeys || []),
      mutation: config.mutation === true,
      transition: config.transition === true,
      terminal: config.terminal === true,
      requiresCompany: config.requiresCompany === true,
      requiresResource: config.requiresResource === true,
      permission: config.permission || ""
    });
  }

  var PERMISSIONS = Object.freeze({
    workspaceRead: "canReadOperationalWorkspace",
    memorySearch: "canSearchOperationalMemory",
    memorySubmit: "canSubmitOperationalMemory",
    knowledgeRead: "canReadOperationalKnowledge",
    externalLinksRead: "canReadOperationalExternalLinks",
    internetSearch: "canSearchOperationalInternet"
  });

  var OPERATION_MAP = Object.freeze({
    sessionInspect: operation("GET", "/api/matm/human/session", {transition: true}),
    sessionLogout: operation("POST", "/api/matm/human/session/logout", {mutation: true, terminal: true}),
    companySelect: operation("POST", "/api/matm/human/session/company", {
      bodyKeys: ["authorityId"], requiredBodyKeys: ["authorityId"], mutation: true, transition: true
    }),
    contextCatalog: operation("GET", "/api/matm/human/operational/context-catalog", {requiresCompany: true}),
    resourceContextSelect: operation("POST", "/api/matm/human/session/resource-context", {
      bodyKeys: ["workspaceId", "projectId"], requiredBodyKeys: ["workspaceId"],
      mutation: true, transition: true, requiresCompany: true
    }),
    workspaceRead: operation("GET", "/api/matm/human/operational/workspace", {
      requiresResource: true, permission: PERMISSIONS.workspaceRead
    }),
    memorySearch: operation("GET", "/api/matm/human/operational/search", {
      queryKeys: ["q", "scope", "memory_type", "review_status", "promotion_state", "source_prefix", "tag", "event_id", "limit", "cursor"],
      requiresResource: true, permission: PERMISSIONS.memorySearch
    }),
    memorySubmit: operation("POST", "/api/matm/human/operational/memory-events/submit", {
      bodyKeys: ["scope", "title", "summary", "tags", "memoryType", "source"],
      requiredBodyKeys: ["scope", "title", "summary", "memoryType"],
      mutation: true, requiresResource: true, permission: PERMISSIONS.memorySubmit
    }),
    knowledgeTree: operation("GET", "/api/matm/human/operational/knowledge-tree", {
      queryKeys: ["scope", "category", "knowledge_status", "authority_level"],
      requiresResource: true, permission: PERMISSIONS.knowledgeRead
    }),
    knowledgeDocuments: operation("GET", "/api/matm/human/operational/knowledge-documents", {
      queryKeys: ["q", "scope", "category", "knowledge_status", "authority_level", "include_text", "limit", "document_id", "route_or_path", "cursor"],
      requiresResource: true, permission: PERMISSIONS.knowledgeRead
    }),
    externalLinks: operation("GET", "/api/matm/human/operational/external-links", {
      queryKeys: ["document_id", "limit", "cursor"],
      requiresResource: true, permission: PERMISSIONS.externalLinksRead
    }),
    internetSearch: operation("GET", "/api/matm/human/operational/internet-search", {
      queryKeys: ["q", "scope", "category", "knowledge_status", "authority_level", "limit", "cursor"],
      requiresResource: true, permission: PERMISSIONS.internetSearch
    })
  });

  var ROUTES = Object.freeze(Object.keys(OPERATION_MAP).reduce(function (result, name) {
    result[name] = Object.freeze({method: OPERATION_MAP[name].method, path: OPERATION_MAP[name].path});
    return result;
  }, {}));

  var SELECTORS = Object.freeze({
    root: "[data-human-operational]",
    status: "[data-human-operational-status]",
    account: "[data-human-operational-account]",
    companyForm: "[data-human-operational-company-form]",
    authoritySelect: "[data-human-operational-authority-select]",
    workspaceForm: "[data-human-operational-workspace-form]",
    workspaceSelect: "[data-human-operational-workspace-select]",
    projectForm: "[data-human-operational-project-form]",
    projectSelect: "[data-human-operational-project-select]",
    context: "[data-human-operational-context]",
    protected: "[data-human-operational-protected]",
    logout: "[data-human-operational-logout]",
    retry: "[data-human-operational-retry]",
    demoLabel: "[data-human-operational-demo-label]",
    demoReset: "[data-human-operational-demo-reset]",
    privateOutput: "[data-human-operational-private-output]"
  });

  var PHASES = Object.freeze({
    LOCKED: "locked",
    REVALIDATING: "revalidating",
    CHOOSING_COMPANY: "choosing_company",
    CHOOSING_RESOURCE: "choosing_resource",
    READY: "ready",
    EMPTY: "empty",
    SWITCHING_COMPANY: "switching_company",
    SWITCHING_RESOURCE: "switching_resource",
    SIGNING_OUT: "signing_out",
    CONTEXT_EXPIRED: "context_expired",
    SESSION_EXPIRED: "session_expired",
    DESTROYED: "destroyed"
  });

  var OUTCOMES = Object.freeze({
    IDLE: "idle",
    SUCCESS: "success",
    EMPTY: "empty",
    VALIDATION_ERROR: "validation_error",
    PERMISSION_DENIED: "permission_denied",
    STALE: "stale",
    LOST_RESPONSE: "lost_response",
    ERROR: "error"
  });

  var ALLOWED_RETURN_PATHS = frozenList(["/human", "/console", "/knowledge"]);
  var SAFE_HEADER_NAMES = frozenList(["Accept", "Content-Type", "X-CSRF-Token", "Idempotency-Key"]);
  var idempotencyCounter = 0;

  function OperationalError(code, status, options) {
    var config = options || {};
    this.name = "HumanOperationalError";
    this.code = String(code || "request_failed");
    this.status = Number(status || 0);
    this.message = this.code;
    this.safeNoOp = true;
    this.valuesRedacted = true;
    this.rawCredentialExposed = false;
    this.rawPayloadExposed = false;
    this.recoverable = config.recoverable === true;
    this.idempotencyKey = config.idempotencyKey || "";
  }
  OperationalError.prototype = Object.create(Error.prototype);
  OperationalError.prototype.constructor = OperationalError;

  function fail(code, status, options) {
    throw new OperationalError(code, status, options);
  }

  function plainObject(value) {
    if (!value || Object.prototype.toString.call(value) !== "[object Object]") return false;
    var prototype = Object.getPrototypeOf(value);
    return prototype === Object.prototype || prototype === null;
  }

  function safeString(value, allowEmpty) {
    if (typeof value !== "string") fail("invalid_value", 0);
    if (!allowEmpty && !value.trim()) fail("value_required", 0);
    if (value.length > 4096) fail("value_too_long", 0);
    return value;
  }

  function safeCode(value, fallback) {
    var text = String(value || fallback || "request_failed");
    return /^[a-z][a-z0-9_]{1,79}$/.test(text) ? text : String(fallback || "request_failed");
  }

  function safeCsrfToken(value) {
    if (typeof value !== "string" || !/^[\x21-\x7E]{1,4096}$/.test(value)) fail("csrf_required", 403);
    return value;
  }

  function copy(value) {
    if (value === undefined) return undefined;
    return JSON.parse(JSON.stringify(value));
  }

  function createIdempotencyKey(operationName) {
    idempotencyCounter += 1;
    return "human-ui-" + String(operationName || "mutation").replace(/[^a-z0-9_-]/gi, "-").toLowerCase()
      + "-" + Date.now().toString(36) + "-" + idempotencyCounter.toString(36)
      + "-" + Math.random().toString(36).slice(2, 10);
  }

  function normalizeIdempotencyKey(value) {
    if (typeof value !== "string" || !/^[A-Za-z0-9._:-]{1,200}$/.test(value)) {
      fail("invalid_idempotency_key", 0);
    }
    return value;
  }

  function normalizeReturnPath(value, surface) {
    var requested = String(value || "");
    if (ALLOWED_RETURN_PATHS.indexOf(requested) !== -1) return requested;
    return surface === "knowledge" ? "/knowledge" : (surface === "console" ? "/console" : "/human");
  }

  function validateKeys(value, allowed, required, kind) {
    var data = value === undefined ? {} : value;
    if (!plainObject(data)) fail("invalid_" + kind, 0);
    Object.keys(data).forEach(function (key) {
      if (allowed.indexOf(key) === -1) fail("unknown_" + kind + "_field", 0);
    });
    required.forEach(function (key) {
      if (!Object.prototype.hasOwnProperty.call(data, key)) fail(kind + "_field_required", 0);
      if (typeof data[key] === "string" && !data[key].trim()) fail(kind + "_field_required", 0);
    });
    return data;
  }

  function validateBody(name, spec, body) {
    if (spec.method === "GET") {
      if (body !== undefined && body !== null) fail("body_not_allowed", 0);
      return undefined;
    }
    var data = validateKeys(body, spec.bodyKeys, spec.requiredBodyKeys, "body");
    if (name === "companySelect") safeString(data.authorityId, false);
    if (name === "resourceContextSelect") {
      safeString(data.workspaceId, false);
      if (Object.prototype.hasOwnProperty.call(data, "projectId")) safeString(data.projectId, true);
    }
    if (name === "memorySubmit") {
      if (["company", "workspace", "project"].indexOf(data.scope) === -1) fail("unsupported_scope", 0);
      safeString(data.title, false);
      safeString(data.summary, false);
      safeString(data.memoryType, false);
      if (data.source !== undefined) safeString(data.source, true);
      if (data.tags !== undefined && (!Array.isArray(data.tags) || data.tags.some(function (tag) { return typeof tag !== "string" || tag.length > 160; }))) {
        fail("invalid_tags", 0);
      }
    }
    return copy(data);
  }

  function buildQuery(spec, query) {
    var data = validateKeys(query, spec.queryKeys, [], "query");
    var parts = [];
    Object.keys(data).sort().forEach(function (key) {
      var value = data[key];
      if (value === undefined || value === null || value === "") return;
      if (["string", "number", "boolean"].indexOf(typeof value) === -1) fail("invalid_query_value", 0);
      parts.push(encodeURIComponent(key) + "=" + encodeURIComponent(String(value)));
    });
    return parts.length ? "?" + parts.join("&") : "";
  }

  function createRouteAdapter() {
    return Object.freeze({
      resolve: function (name, input) {
        var spec = OPERATION_MAP[name];
        if (!spec) fail("unknown_operation", 0);
        var data = input === undefined ? {} : input;
        if (!plainObject(data)) fail("invalid_operation_input", 0);
        Object.keys(data).forEach(function (key) {
          if (["query", "body"].indexOf(key) === -1) fail("unknown_operation_input", 0);
        });
        var body = validateBody(name, spec, data.body);
        var path = spec.path + buildQuery(spec, data.query);
        if (path.charAt(0) !== "/" || path.charAt(1) === "/" || path.indexOf("://") !== -1 || path.indexOf("\\") !== -1 || path.indexOf("#") !== -1) {
          fail("unsafe_route", 0);
        }
        return Object.freeze({name: name, spec: spec, method: spec.method, path: path, body: body});
      }
    });
  }

  function createTransport(fetchImpl) {
    if (typeof fetchImpl !== "function") throw new TypeError("fetchImpl is required");
    return Object.freeze({
      request: async function (path, options) {
        var config = options || {};
        if (typeof path !== "string" || path.charAt(0) !== "/" || path.charAt(1) === "/" || path.indexOf("://") !== -1 || path.indexOf("\\") !== -1 || path.indexOf("#") !== -1) {
          fail("unsafe_route", 0);
        }
        if (!plainObject(config) || config.credentials !== "same-origin" || config.cache !== "no-store" || config.redirect !== "error"
          || config.mode !== "same-origin" || config.referrerPolicy !== "no-referrer") {
          fail("unsafe_request_options", 0);
        }
        Object.keys(config).forEach(function (name) {
          if (["method", "headers", "body", "credentials", "cache", "redirect", "mode", "referrerPolicy", "signal", "operation", "idempotencyKey"].indexOf(name) === -1) {
            fail("unsafe_request_option", 0);
          }
        });
        var operationName = typeof config.operation === "string" ? config.operation : "";
        var spec = OPERATION_MAP[operationName];
        if (!spec) fail("unknown_operation", 0);
        if (config.method !== spec.method) fail("invalid_method", 0);
        var pathParts = path.split("?");
        if (pathParts.length > 2 || pathParts[0] !== spec.path) fail("unsafe_route", 0);
        var query = {};
        if (pathParts[1]) {
          pathParts[1].split("&").forEach(function (part) {
            if (!part) fail("invalid_query", 0);
            var pair = part.split("=");
            var key;
            var value;
            try {
              key = decodeURIComponent(pair.shift() || "");
              value = decodeURIComponent(pair.join("="));
            } catch (_) {
              fail("invalid_query", 0);
            }
            if (!key || Object.prototype.hasOwnProperty.call(query, key)) fail("invalid_query", 0);
            query[key] = value;
          });
        }
        var parsedBody;
        if (config.body !== undefined) {
          if (typeof config.body !== "string") fail("invalid_body", 0);
          try { parsedBody = JSON.parse(config.body); }
          catch (_) { fail("invalid_body", 0); }
          if (!plainObject(parsedBody)) fail("invalid_body", 0);
        }
        var canonical = createRouteAdapter().resolve(operationName, {query: query, body: parsedBody});
        if (canonical.path !== path) fail("noncanonical_route", 0);
        var headers = config.headers || {};
        if (!plainObject(headers)) fail("unsafe_request_headers", 0);
        Object.keys(headers).forEach(function (name) {
          if (SAFE_HEADER_NAMES.indexOf(name) === -1) fail("unsafe_request_header", 0);
        });
        if (headers.Accept !== "application/json") fail("json_accept_required", 0);
        if (spec.mutation) {
          if (headers["Content-Type"] !== "application/json") fail("json_content_type_required", 0);
          var headerIdempotencyKey = normalizeIdempotencyKey(headers["Idempotency-Key"]);
          if (config.idempotencyKey && config.idempotencyKey !== headerIdempotencyKey) fail("idempotency_key_mismatch", 0);
          safeCsrfToken(headers["X-CSRF-Token"]);
        } else if (headers["X-CSRF-Token"] !== undefined || headers["Idempotency-Key"] !== undefined || headers["Content-Type"] !== undefined) {
          fail("unexpected_mutation_header", 0);
        }
        var response;
        try {
          response = await fetchImpl(path, {
            method: config.method,
            headers: headers,
            body: config.body,
            credentials: config.credentials,
            cache: config.cache,
            redirect: config.redirect,
            mode: config.mode,
            referrerPolicy: config.referrerPolicy,
            signal: config.signal
          });
        } catch (error) {
          if (config.signal && config.signal.aborted) fail("stale_response", 0);
          fail("lost_response", 0, {recoverable: true, idempotencyKey: config.idempotencyKey || ""});
        }
        if (config.signal && config.signal.aborted) fail("stale_response", 0);
        var textValue = "";
        try {
          textValue = await response.text();
        } catch (_) {
          fail("unreadable_response", Number(response && response.status || 0));
        }
        var payload;
        try {
          payload = textValue ? JSON.parse(textValue) : {};
        } catch (_) {
          fail("unreadable_response", Number(response && response.status || 0));
        }
        if (!plainObject(payload)) fail("invalid_response", Number(response && response.status || 0));
        if (!response.ok || payload.ok === false) {
          var problem = plainObject(payload.error) ? payload.error : {};
          fail(safeCode(problem.code, "request_failed"), Number(response.status || 0));
        }
        return payload;
      }
    });
  }

  function createSessionAuthority() {
    var csrfValue = "";
    var established = false;
    return Object.freeze({
      establish: function (value) {
        if (!plainObject(value)) fail("csrf_required", 403);
        csrfValue = safeCsrfToken(value.csrfToken);
        established = true;
      },
      csrfToken: function () { return csrfValue; },
      active: function () { return established; },
      clear: function () { csrfValue = ""; established = false; }
    });
  }

  function normalizePermissions(value) {
    var source = plainObject(value) ? value : {};
    var output = {};
    Object.keys(PERMISSIONS).forEach(function (key) {
      var name = PERMISSIONS[key];
      output[name] = source[name] === true;
    });
    output.mockData = source.mockData === true;
    return Object.freeze(output);
  }

  function normalizeMembership(item) {
    if (!plainObject(item)) fail("invalid_membership", 422);
    var authorityId = safeString(item.authorityId, false);
    var companyId = safeString(item.companyId, false);
    return Object.freeze({
      authorityId: authorityId,
      companyId: companyId,
      companyLabel: typeof item.companyLabel === "string" ? item.companyLabel : "",
      membershipLabel: typeof item.membershipLabel === "string" ? item.membershipLabel : "",
      mockData: item.mockData === true
    });
  }

  function normalizeResourceContext(value) {
    if (!plainObject(value)) fail("resource_context_required", 422);
    var context = {
      authorityId: safeString(value.authorityId === undefined ? "" : value.authorityId, true),
      companyId: safeString(value.companyId === undefined ? "" : value.companyId, true),
      workspaceId: safeString(value.workspaceId === undefined ? "" : value.workspaceId, true),
      projectId: safeString(value.projectId === undefined ? "" : value.projectId, true),
      contextVersion: safeString(value.contextVersion, false),
      mockData: value.mockData === true
    };
    if ((!context.authorityId && (context.companyId || context.workspaceId || context.projectId))
      || (!context.companyId && (context.workspaceId || context.projectId))
      || (!context.workspaceId && context.projectId)) {
      fail("invalid_resource_context", 422);
    }
    return Object.freeze(context);
  }

  function normalizeSessionEnvelope(payload, options) {
    var config = options || {};
    if (!plainObject(payload) || payload.ok !== true) fail("invalid_session_envelope", 422);
    var csrfToken = payload.csrfToken;
    try { delete payload.csrfToken; } catch (_) {
      try { payload.csrfToken = ""; } catch (_) {}
    }
    csrfToken = safeCsrfToken(csrfToken);
    if (payload.csrfTokenRotated !== true) fail("csrf_rotation_required", 409);
    if (config.fullRotation && payload.sessionRotated !== true) fail("session_rotation_required", 409);
    if (config.previousCsrf && csrfToken === config.previousCsrf) fail("csrf_not_rotated", 409);
    if (!plainObject(payload.account) || !plainObject(payload.humanSession) || !Array.isArray(payload.memberships)) {
      fail("incomplete_session_envelope", 422);
    }
    var accountId = safeString(payload.account.humanAccountId, false);
    var username = safeString(payload.account.username, false);
    var sessionId = safeString(payload.humanSession.humanAccountSessionId, false);
    if (payload.humanSession.humanAccountId !== accountId || payload.humanSession.username !== username) {
      fail("session_account_mismatch", 422);
    }
    var memberships = payload.memberships.map(normalizeMembership);
    var membershipIds = {};
    memberships.forEach(function (membership) {
      if (membershipIds[membership.authorityId]) fail("duplicate_membership", 422);
      membershipIds[membership.authorityId] = true;
    });
    var context = normalizeResourceContext(payload.resourceContext);
    if (context.authorityId) {
      var selected = memberships.filter(function (item) { return item.authorityId === context.authorityId; });
      if (selected.length !== 1 || selected[0].companyId !== context.companyId) fail("selected_membership_mismatch", 422);
    }
    if (payload.humanSession.selectedAuthorityId !== context.authorityId
      || payload.humanSession.selectedCompanyId !== context.companyId) {
      fail("selected_context_mismatch", 422);
    }
    var envelope = Object.freeze({
      account: Object.freeze({
        humanAccountId: accountId,
        username: username,
        displayName: typeof payload.account.displayName === "string" ? payload.account.displayName : username,
        mockData: payload.account.mockData === true
      }),
      humanSession: Object.freeze({
        humanAccountSessionId: sessionId,
        humanAccountId: accountId,
        username: username,
        selectedAuthorityId: context.authorityId,
        selectedCompanyId: context.companyId,
        expiresAt: typeof payload.humanSession.expiresAt === "string" ? payload.humanSession.expiresAt : "",
        mockData: payload.humanSession.mockData === true
      }),
      memberships: Object.freeze(memberships),
      resourceContext: context,
      permissions: normalizePermissions(payload.permissions),
      mockData: payload.mockData === true
    });
    return Object.freeze({envelope: envelope, csrfToken: csrfToken});
  }

  function normalizeCatalog(payload, expectedContextVersion) {
    if (!plainObject(payload) || payload.ok !== true || !Array.isArray(payload.workspaces)) fail("invalid_context_catalog", 422);
    if (Object.prototype.hasOwnProperty.call(payload, "csrfToken") || payload.csrfTokenRotated === true) fail("unexpected_csrf_rotation", 409);
    if (payload.sessionRotated === true) fail("unexpected_session_rotation", 409);
    if (payload.contextVersion !== expectedContextVersion) fail("stale_context", 409);
    var workspaceIds = {};
    var workspaces = payload.workspaces.map(function (workspace) {
      if (!plainObject(workspace)) fail("invalid_context_catalog", 422);
      var workspaceId = safeString(workspace.workspaceId, false);
      if (workspaceIds[workspaceId]) fail("duplicate_workspace", 422);
      workspaceIds[workspaceId] = true;
      var projectIds = {};
      var projects = Array.isArray(workspace.projects) ? workspace.projects.map(function (project) {
        if (!plainObject(project)) fail("invalid_context_catalog", 422);
        var projectId = safeString(project.projectId, false);
        if (projectIds[projectId]) fail("duplicate_project", 422);
        projectIds[projectId] = true;
        return Object.freeze({
          projectId: projectId,
          label: typeof project.label === "string" ? project.label : project.projectId,
          mockData: project.mockData === true
        });
      }) : [];
      return Object.freeze({
        workspaceId: workspaceId,
        label: typeof workspace.label === "string" ? workspace.label : workspaceId,
        projects: Object.freeze(projects),
        mockData: workspace.mockData === true
      });
    });
    return Object.freeze({
      contextVersion: expectedContextVersion,
      workspaces: Object.freeze(workspaces),
      mockData: payload.mockData === true
    });
  }

  function responseContextVersion(payload) {
    return plainObject(payload) && typeof payload.contextVersion === "string" ? payload.contextVersion : "";
  }

  function createIntegrationAdapter(overrides) {
    var source = overrides || {};
    ["scrub", "contextChanged", "operationResult"].forEach(function (name) {
      if (source[name] !== undefined && typeof source[name] !== "function") throw new TypeError("adapter." + name + " must be a function");
    });
    return Object.freeze({
      scrub: source.scrub || function () {},
      contextChanged: source.contextChanged || function () {},
      operationResult: source.operationResult || function () {}
    });
  }

  function required(root, selector) {
    var value = root.querySelector(selector);
    if (!value) throw new Error("Missing human operational element: " + selector);
    return value;
  }

  function clearNode(node) {
    if (!node) return;
    if (typeof node.replaceChildren === "function") node.replaceChildren();
    else while (node.firstChild) node.removeChild(node.firstChild);
  }

  function setInert(node, value) {
    if (!node) return;
    node.hidden = Boolean(value);
    try { node.inert = Boolean(value); } catch (_) {}
    if (value) {
      node.setAttribute("inert", "");
      node.setAttribute("aria-hidden", "true");
    } else {
      node.removeAttribute("inert");
      node.removeAttribute("aria-hidden");
    }
  }

  function clearControl(control) {
    if (!control) return;
    if (control.value !== undefined) control.value = "";
    if (control.checked !== undefined) control.checked = false;
    if (control.removeAttribute) control.removeAttribute("aria-invalid");
  }

  function safeMessage(error) {
    var code = String(error && error.code || "request_failed");
    if (/session|csrf/.test(code) || Number(error && error.status) === 401) return "Your human session is no longer available. Sign in again.";
    if (/context|stale/.test(code)) return "The selected resource context expired. Revalidate before continuing.";
    if (/permission|forbidden/.test(code) || Number(error && error.status) === 403) return "Your selected company membership does not allow that operation.";
    if (/lost/.test(code) || Number(error && error.status) === 0) return "The request outcome is unknown. Retry only with the same idempotency key.";
    if (/invalid|unknown|required|unsupported/.test(code)) return "Check the selected values and try again.";
    return "The operation could not be completed safely.";
  }

  function create(options) {
    options = options || {};
    var root = options.root;
    if (!root) throw new TypeError("root is required");
    var surface = String(options.surface || (root.getAttribute && root.getAttribute("data-human-operational-surface")) || "");
    if (["console", "knowledge"].indexOf(surface) === -1) throw new TypeError("surface must be console or knowledge");
    var windowRef = options.windowRef || (typeof window !== "undefined" ? window : null);
    var documentRef = options.documentRef || root.ownerDocument;
    var demoMode = options.demoMode === true || Boolean(root.hasAttribute && root.hasAttribute("data-human-operational-demo"));
    var transport = options.transport;
    if (!transport) {
      if (demoMode) transport = createDemoTransport(options.demoTransportOptions);
      else {
        var fetchImpl = options.fetchImpl || (windowRef && typeof windowRef.fetch === "function" ? windowRef.fetch.bind(windowRef) : null);
        transport = createTransport(fetchImpl);
      }
    }
    if (!transport || typeof transport.request !== "function") throw new TypeError("transport.request is required");
    if (demoMode && transport.demoTransport !== true) throw new TypeError("Demo requires the zero-network Demo transport");
    if (!demoMode && transport.demoTransport === true) throw new TypeError("Production cannot use the Demo transport");
    var authority = options.sessionAuthority || createSessionAuthority();
    var adapter = createIntegrationAdapter(options.adapter);
    var routes = createRouteAdapter();
    var navigate = options.navigate || function (path) {
      if (windowRef && windowRef.location && typeof windowRef.location.assign === "function") windowRef.location.assign(path);
    };
    var requestedReturnPath = options.returnPath || (root.getAttribute && root.getAttribute("data-human-operational-return-path")) || "";
    var returnPath = normalizeReturnPath(requestedReturnPath, surface);
    var elements = {
      status: required(root, SELECTORS.status),
      account: required(root, SELECTORS.account),
      companyForm: required(root, SELECTORS.companyForm),
      authoritySelect: required(root, SELECTORS.authoritySelect),
      workspaceForm: required(root, SELECTORS.workspaceForm),
      workspaceSelect: required(root, SELECTORS.workspaceSelect),
      projectForm: required(root, SELECTORS.projectForm),
      projectSelect: required(root, SELECTORS.projectSelect),
      context: required(root, SELECTORS.context),
      protected: required(root, SELECTORS.protected),
      logout: required(root, SELECTORS.logout),
      retry: required(root, SELECTORS.retry),
      demoLabel: required(root, SELECTORS.demoLabel),
      demoReset: required(root, SELECTORS.demoReset)
    };
    var state = {
      phase: PHASES.LOCKED,
      outcome: OUTCOMES.IDLE,
      envelope: null,
      catalog: null,
      permissions: normalizePermissions({}),
      lastOperation: "",
      mounted: false,
      destroyed: false
    };
    var epoch = 0;
    var activeControllers = [];
    var activeMutationToken = null;

    function setStatus(message, tone) {
      elements.status.textContent = String(message || "");
      elements.status.dataset.status = String(tone || "");
    }

    function setPhase(value) {
      state.phase = value;
      root.dataset.humanOperationalState = value;
    }

    function setOutcome(value) {
      state.outcome = value;
      root.dataset.humanOperationalOutcome = value;
    }

    function optionNode(value, label) {
      var node = documentRef.createElement("option");
      node.value = value;
      node.textContent = label;
      return node;
    }

    function replaceOptions(select, placeholder, items, valueKey, labelKey) {
      clearNode(select);
      select.appendChild(optionNode("", placeholder));
      (items || []).forEach(function (item) {
        select.appendChild(optionNode(item[valueKey], item[labelKey] || item[valueKey]));
      });
    }

    function selectedWorkspaceCatalog() {
      var context = state.envelope && state.envelope.resourceContext;
      if (!context || !state.catalog) return null;
      return state.catalog.workspaces.filter(function (item) { return item.workspaceId === context.workspaceId; })[0] || null;
    }

    function renderShell() {
      var envelope = state.envelope;
      var context = envelope && envelope.resourceContext;
      elements.demoLabel.hidden = !demoMode;
      elements.demoReset.hidden = !demoMode;
      elements.account.textContent = envelope
        ? ((envelope.account.displayName || envelope.account.username) + " · authenticated human")
        : "";
      replaceOptions(elements.authoritySelect, "Choose a company", envelope ? envelope.memberships : [], "authorityId", "companyLabel");
      if (context && context.authorityId) elements.authoritySelect.value = context.authorityId;
      elements.companyForm.hidden = !envelope || envelope.memberships.length === 0;

      var workspaces = state.catalog ? state.catalog.workspaces : [];
      replaceOptions(elements.workspaceSelect, "Choose a workspace", workspaces, "workspaceId", "label");
      if (context && context.workspaceId) elements.workspaceSelect.value = context.workspaceId;
      elements.workspaceForm.hidden = !context || !context.companyId || workspaces.length === 0;

      var workspace = selectedWorkspaceCatalog();
      var projects = workspace ? workspace.projects : [];
      replaceOptions(elements.projectSelect, "No project selected", projects, "projectId", "label");
      if (context && context.projectId) elements.projectSelect.value = context.projectId;
      elements.projectForm.hidden = !context || !context.workspaceId;

      if (!context || !context.companyId) elements.context.textContent = "Choose a company to continue.";
      else if (!context.workspaceId) elements.context.textContent = "Company selected. Choose a workspace explicitly.";
      else if (!context.projectId) elements.context.textContent = "Workspace selected. No project is selected.";
      else elements.context.textContent = "Workspace and project selected.";

      var ready = state.phase === PHASES.READY;
      setInert(elements.protected, !ready);
      elements.logout.hidden = !envelope;
      elements.retry.hidden = state.phase !== PHASES.CONTEXT_EXPIRED && state.phase !== PHASES.SESSION_EXPIRED;
      delete root.dataset.humanOperationalContextVersion;
    }

    function abortActive() {
      activeControllers.forEach(function (controller) {
        try { controller.abort(); } catch (_) {}
      });
      activeControllers = [];
    }

    function closeDialogs() {
      if (!root.querySelectorAll) return;
      Array.prototype.forEach.call(root.querySelectorAll("dialog"), function (dialog) {
        if (dialog.open && typeof dialog.close === "function") {
          try { dialog.close(); } catch (_) { dialog.removeAttribute("open"); }
        } else if (dialog.removeAttribute) dialog.removeAttribute("open");
      });
    }

    function clearPrivateControls() {
      if (!root.querySelectorAll) return;
      Array.prototype.forEach.call(root.querySelectorAll("input, textarea"), clearControl);
      Array.prototype.forEach.call(root.querySelectorAll("select"), function (select) {
        if (select.value !== undefined) select.value = "";
        if (select.selectedIndex !== undefined) select.selectedIndex = 0;
      });
      Array.prototype.forEach.call(root.querySelectorAll(SELECTORS.privateOutput), clearNode);
      Array.prototype.forEach.call(root.querySelectorAll("pre"), function (node) { node.textContent = ""; });
    }

    function scrub(reason, nextPhase) {
      epoch += 1;
      abortActive();
      activeMutationToken = null;
      authority.clear();
      state.envelope = null;
      state.catalog = null;
      state.permissions = normalizePermissions({});
      state.lastOperation = "";
      setOutcome(OUTCOMES.IDLE);
      clearPrivateControls();
      closeDialogs();
      setPhase(nextPhase || PHASES.LOCKED);
      setInert(elements.protected, true);
      try { adapter.scrub({root: root, surface: surface, reason: String(reason || ""), epoch: epoch}); } catch (_) {}
      renderShell();
      if (reason) setStatus(reason, "neutral");
      return epoch;
    }

    function currentContext() {
      return state.envelope ? state.envelope.resourceContext : null;
    }

    function contextSnapshot() {
      return state.envelope ? copy({
        account: state.envelope.account,
        humanSession: state.envelope.humanSession,
        memberships: state.envelope.memberships,
        resourceContext: state.envelope.resourceContext,
        permissions: state.permissions,
        mockData: state.envelope.mockData
      }) : null;
    }

    function permission(operationName) {
      var spec = OPERATION_MAP[operationName];
      if (!spec) return false;
      return !spec.permission || state.permissions[spec.permission] === true;
    }

    function newAbortController() {
      if (typeof options.abortControllerFactory === "function") return options.abortControllerFactory();
      if (typeof AbortController !== "undefined") return new AbortController();
      return {signal: {aborted: false}, abort: function () { this.signal.aborted = true; }};
    }

    async function dispatch(operationName, input, dispatchOptions) {
      var config = dispatchOptions || {};
      var descriptor = routes.resolve(operationName, input === undefined ? {} : input);
      var spec = descriptor.spec;
      var requestEpoch = config.epoch === undefined ? epoch : config.epoch;
      if (requestEpoch !== epoch) fail("stale_response", 0);
      var headers = {Accept: "application/json"};
      var bodyText;
      if (descriptor.body !== undefined) {
        headers["Content-Type"] = "application/json";
        bodyText = JSON.stringify(descriptor.body);
      }
      var idempotencyKey = "";
      if (spec.mutation) {
        var csrfValue = config.csrfOverride || authority.csrfToken();
        if (!csrfValue) fail("csrf_required", 403);
        idempotencyKey = config.idempotencyKey === undefined
          ? createIdempotencyKey(operationName)
          : normalizeIdempotencyKey(config.idempotencyKey);
        headers["X-CSRF-Token"] = csrfValue;
        headers["Idempotency-Key"] = idempotencyKey;
      }
      var controller = newAbortController();
      activeControllers.push(controller);
      try {
        var payload = await transport.request(descriptor.path, {
          method: descriptor.method,
          headers: headers,
          body: bodyText,
          credentials: "same-origin",
          cache: "no-store",
          redirect: "error",
          mode: "same-origin",
          referrerPolicy: "no-referrer",
          signal: controller.signal,
          operation: operationName,
          idempotencyKey: idempotencyKey
        });
        if (requestEpoch !== epoch || controller.signal.aborted) fail("stale_response", 0);
        return {payload: payload, idempotencyKey: idempotencyKey};
      } catch (error) {
        if (requestEpoch !== epoch || controller.signal.aborted) fail("stale_response", 0);
        if (error && error.code === "lost_response" && !error.idempotencyKey) {
          throw new OperationalError("lost_response", 0, {recoverable: true, idempotencyKey: idempotencyKey});
        }
        throw error;
      } finally {
        activeControllers = activeControllers.filter(function (item) { return item !== controller; });
      }
    }

    function establishSession(result, config) {
      var normalized = normalizeSessionEnvelope(result.payload, config);
      authority.establish({csrfToken: normalized.csrfToken});
      state.envelope = normalized.envelope;
      state.permissions = normalized.envelope.permissions;
      return normalized.envelope;
    }

    function applyError(error) {
      var value = error instanceof OperationalError ? error : new OperationalError("request_failed", 0);
      var code = value.code;
      if (code === "stale_response") return value;
      if (/session/.test(code) || /csrf/.test(code) || value.status === 401) {
        scrub("Your human session is no longer available.", PHASES.SESSION_EXPIRED);
        setOutcome(OUTCOMES.ERROR);
        setStatus(safeMessage(value), "error");
        if (!demoMode) navigate(returnPath);
        return value;
      }
      if (/context/.test(code) || /stale/.test(code)) {
        scrub("The selected resource context is no longer current.", PHASES.CONTEXT_EXPIRED);
        setOutcome(OUTCOMES.STALE);
        setStatus(safeMessage(value), "error");
        return value;
      }
      if (/permission|forbidden/.test(code) || value.status === 403) {
        setOutcome(OUTCOMES.PERMISSION_DENIED);
        setStatus(safeMessage(value), "error");
        return value;
      }
      if (code === "lost_response") {
        setOutcome(OUTCOMES.LOST_RESPONSE);
        setStatus(safeMessage(value), "error");
        return value;
      }
      if (/invalid|unknown|required|unsupported/.test(code)) {
        setOutcome(OUTCOMES.VALIDATION_ERROR);
        setStatus(safeMessage(value), "error");
        return value;
      }
      setOutcome(OUTCOMES.ERROR);
      setStatus(safeMessage(value), "error");
      return value;
    }

    async function loadCatalog(requestEpoch) {
      var context = currentContext();
      if (!context || !context.companyId) fail("selected_company_required", 409);
      var result = await dispatch("contextCatalog", {}, {epoch: requestEpoch});
      state.catalog = normalizeCatalog(result.payload, context.contextVersion);
      renderShell();
      return state.catalog;
    }

    async function settleEnvelope(requestEpoch) {
      var context = currentContext();
      if (!context.authorityId) {
        state.catalog = null;
        setPhase(state.envelope.memberships.length ? PHASES.CHOOSING_COMPANY : PHASES.EMPTY);
        setOutcome(state.envelope.memberships.length ? OUTCOMES.SUCCESS : OUTCOMES.EMPTY);
        renderShell();
        setStatus(state.envelope.memberships.length ? "Choose a linked company to continue." : "No linked companies are available.", state.envelope.memberships.length ? "neutral" : "empty");
        return contextSnapshot();
      }
      await loadCatalog(requestEpoch);
      if (!state.catalog.workspaces.length) {
        setPhase(PHASES.EMPTY);
        setOutcome(OUTCOMES.EMPTY);
        renderShell();
        setStatus("No workspaces are available for the selected company.", "empty");
        return contextSnapshot();
      }
      if (!context.workspaceId) {
        setPhase(PHASES.CHOOSING_RESOURCE);
        setOutcome(OUTCOMES.SUCCESS);
        renderShell();
        setStatus("Choose a workspace explicitly. Project selection remains optional.", "neutral");
        return contextSnapshot();
      }
      if (!state.catalog.workspaces.some(function (item) { return item.workspaceId === context.workspaceId; })) fail("selected_workspace_not_in_catalog", 409);
      if (context.projectId) {
        var workspace = state.catalog.workspaces.filter(function (item) { return item.workspaceId === context.workspaceId; })[0];
        if (!workspace.projects.some(function (item) { return item.projectId === context.projectId; })) fail("selected_project_not_in_catalog", 409);
      }
      setPhase(PHASES.READY);
      setOutcome(OUTCOMES.SUCCESS);
      renderShell();
      try { adapter.contextChanged(contextSnapshot()); }
      catch (_) {
        scrub("The renderer could not accept the selected context.", PHASES.LOCKED);
        fail("renderer_context_failed", 0);
      }
      setStatus("Human operational context is ready.", "success");
      return contextSnapshot();
    }

    async function revalidate() {
      if (state.destroyed) fail("controller_destroyed", 0);
      var previousCsrf = authority.csrfToken();
      var requestEpoch = scrub("Revalidating your human session…", PHASES.REVALIDATING);
      try {
        var result = await dispatch("sessionInspect", {}, {epoch: requestEpoch});
        establishSession(result, {previousCsrf: previousCsrf});
        return await settleEnvelope(requestEpoch);
      } catch (error) {
        applyError(error);
        throw error;
      }
    }

    async function selectCompany(authorityId) {
      try {
        safeString(authorityId, false);
        if (!state.envelope || !state.envelope.memberships.some(function (item) { return item.authorityId === authorityId; })) {
          fail("unknown_authority", 422);
        }
        var previousContextVersion = state.envelope.resourceContext.contextVersion;
        var previousCsrf = authority.csrfToken();
        var requestEpoch = scrub("Switching companies…", PHASES.SWITCHING_COMPANY);
        var result = await dispatch("companySelect", {body: {authorityId: authorityId}}, {epoch: requestEpoch, csrfOverride: previousCsrf});
        var envelope = establishSession(result, {previousCsrf: previousCsrf, fullRotation: true});
        if (envelope.resourceContext.authorityId !== authorityId || !envelope.resourceContext.companyId
          || envelope.resourceContext.workspaceId || envelope.resourceContext.projectId) {
          fail("company_transition_context_invalid", 409);
        }
        if (envelope.resourceContext.contextVersion === previousContextVersion) fail("context_version_not_rotated", 409);
        return await settleEnvelope(requestEpoch);
      } catch (error) {
        applyError(error);
        throw error;
      }
    }

    function validateResourceSelection(workspaceId, projectId) {
      safeString(workspaceId, false);
      safeString(projectId, true);
      if (!state.envelope || !state.envelope.resourceContext.companyId || !state.catalog) fail("context_catalog_required", 409);
      var workspace = state.catalog.workspaces.filter(function (item) { return item.workspaceId === workspaceId; })[0];
      if (!workspace) fail("unknown_workspace", 422);
      if (projectId && !workspace.projects.some(function (item) { return item.projectId === projectId; })) fail("unknown_project", 422);
    }

    async function selectResource(workspaceId, projectId) {
      projectId = projectId === undefined || projectId === null ? "" : projectId;
      try {
        validateResourceSelection(workspaceId, projectId);
        var previousContext = currentContext();
        var expectedAuthority = previousContext.authorityId;
        var expectedCompany = previousContext.companyId;
        var previousContextVersion = previousContext.contextVersion;
        var previousCsrf = authority.csrfToken();
        var requestEpoch = scrub("Switching resource context…", PHASES.SWITCHING_RESOURCE);
        var body = {workspaceId: workspaceId};
        if (projectId) body.projectId = projectId;
        var result = await dispatch("resourceContextSelect", {body: body}, {epoch: requestEpoch, csrfOverride: previousCsrf});
        var envelope = establishSession(result, {previousCsrf: previousCsrf, fullRotation: true});
        var next = envelope.resourceContext;
        if (next.authorityId !== expectedAuthority || next.companyId !== expectedCompany
          || next.workspaceId !== workspaceId || next.projectId !== projectId) {
          fail("resource_transition_context_invalid", 409);
        }
        if (next.contextVersion === previousContextVersion) fail("context_version_not_rotated", 409);
        return await settleEnvelope(requestEpoch);
      } catch (error) {
        applyError(error);
        throw error;
      }
    }

    async function request(operationName, input, requestOptions) {
      var mutationToken = null;
      try {
        if (requestOptions !== undefined) {
          if (!plainObject(requestOptions)) fail("invalid_request_options", 0);
          Object.keys(requestOptions).forEach(function (name) {
            if (name !== "idempotencyKey") fail("unknown_request_option", 0);
          });
        }
        var spec = OPERATION_MAP[operationName];
        if (!spec || spec.transition || spec.terminal || operationName === "contextCatalog") fail("operation_not_available", 0);
        var context = currentContext();
        if (state.phase !== PHASES.READY || !context) fail("resource_context_required", 409);
        if (spec.requiresCompany && !context.companyId) fail("selected_company_required", 409);
        if (spec.requiresResource && !context.workspaceId) fail("selected_workspace_required", 409);
        if (!permission(operationName)) fail("permission_denied", 403);
        if (spec.mutation) {
          if (activeMutationToken) fail("mutation_in_progress", 409);
          mutationToken = {};
          activeMutationToken = mutationToken;
        }
        var expectedVersion = context.contextVersion;
        var result = await dispatch(operationName, input === undefined ? {} : input, {
          epoch: epoch,
          idempotencyKey: requestOptions && requestOptions.idempotencyKey
        });
        if (responseContextVersion(result.payload) !== expectedVersion) fail("stale_context", 409);
        if (Object.prototype.hasOwnProperty.call(result.payload, "csrfToken") || result.payload.csrfTokenRotated === true) {
          fail("unexpected_csrf_rotation", 409);
        }
        if (result.payload.sessionRotated === true) fail("unexpected_session_rotation", 409);
        if (spec.mutation) {
          if (result.payload.csrfTokenRotated !== false) {
            fail("unexpected_csrf_rotation", 409);
          }
        }
        state.lastOperation = operationName;
        var empty = (Array.isArray(result.payload.items) && result.payload.items.length === 0)
          || result.payload.empty === true;
        setOutcome(empty ? OUTCOMES.EMPTY : OUTCOMES.SUCCESS);
        setStatus(empty ? "The operation completed with no matching records." : "The operation completed successfully.", empty ? "empty" : "success");
        try { adapter.operationResult({operation: operationName, payload: result.payload, context: contextSnapshot()}); }
        catch (_) {
          scrub("The operation completed, but its renderer could not update safely.", PHASES.LOCKED);
          setOutcome(OUTCOMES.ERROR);
          setStatus("Revalidate before using this renderer again.", "error");
        }
        return result.payload;
      } catch (error) {
        applyError(error);
        throw error;
      } finally {
        if (mutationToken && activeMutationToken === mutationToken) activeMutationToken = null;
      }
    }

    async function logout() {
      if (state.destroyed) return null;
      var csrfValue = authority.csrfToken();
      var requestEpoch = scrub("Signing out…", PHASES.SIGNING_OUT);
      var result = null;
      try {
        if (csrfValue) result = await dispatch("sessionLogout", {body: {}}, {epoch: requestEpoch, csrfOverride: csrfValue});
      } catch (_) {
        result = null;
      }
      scrub("Signed out.", PHASES.LOCKED);
      if (!demoMode) navigate(returnPath);
      return result && result.payload;
    }

    async function resetDemo() {
      if (!demoMode || typeof transport.reset !== "function") fail("demo_reset_unavailable", 0);
      scrub("Resetting Demo…", PHASES.REVALIDATING);
      transport.reset();
      return revalidate();
    }

    function onPageHide() {
      scrub("Human operational state cleared for navigation.", PHASES.LOCKED);
    }

    function onPageShow(event) {
      if (!event || event.persisted !== true || state.destroyed) return;
      scrub("Restored page state cleared. Revalidating…", PHASES.REVALIDATING);
      revalidate().catch(function () {});
    }

    function onCompanySubmit(event) {
      event.preventDefault();
      selectCompany(String(elements.authoritySelect.value || "")).catch(function () {});
    }

    function onWorkspaceSubmit(event) {
      event.preventDefault();
      selectResource(String(elements.workspaceSelect.value || ""), "").catch(function () {});
    }

    function onProjectSubmit(event) {
      event.preventDefault();
      var context = currentContext();
      selectResource(context ? context.workspaceId : "", String(elements.projectSelect.value || "")).catch(function () {});
    }

    function onLogout() { logout(); }
    function onRetry() { revalidate().catch(function () {}); }
    function onDemoReset() { resetDemo().catch(function () {}); }

    function mount() {
      if (state.destroyed) fail("controller_destroyed", 0);
      if (state.mounted) return Promise.resolve(contextSnapshot());
      state.mounted = true;
      elements.companyForm.addEventListener("submit", onCompanySubmit);
      elements.workspaceForm.addEventListener("submit", onWorkspaceSubmit);
      elements.projectForm.addEventListener("submit", onProjectSubmit);
      elements.logout.addEventListener("click", onLogout);
      elements.retry.addEventListener("click", onRetry);
      elements.demoReset.addEventListener("click", onDemoReset);
      if (windowRef && typeof windowRef.addEventListener === "function") {
        windowRef.addEventListener("pagehide", onPageHide);
        windowRef.addEventListener("pageshow", onPageShow);
      }
      renderShell();
      if (options.autoRevalidate === false) return Promise.resolve(contextSnapshot());
      return revalidate();
    }

    function destroy() {
      if (state.destroyed) return;
      scrub("Human operational interface closed.", PHASES.DESTROYED);
      state.destroyed = true;
      state.mounted = false;
      elements.companyForm.removeEventListener("submit", onCompanySubmit);
      elements.workspaceForm.removeEventListener("submit", onWorkspaceSubmit);
      elements.projectForm.removeEventListener("submit", onProjectSubmit);
      elements.logout.removeEventListener("click", onLogout);
      elements.retry.removeEventListener("click", onRetry);
      elements.demoReset.removeEventListener("click", onDemoReset);
      if (windowRef && typeof windowRef.removeEventListener === "function") {
        windowRef.removeEventListener("pagehide", onPageHide);
        windowRef.removeEventListener("pageshow", onPageShow);
      }
    }

    function getSnapshot() {
      var context = currentContext();
      return Object.freeze({
        phase: state.phase,
        outcome: state.outcome,
        mounted: state.mounted,
        destroyed: state.destroyed,
        authenticated: Boolean(state.envelope),
        membershipCount: state.envelope ? state.envelope.memberships.length : 0,
        companySelected: Boolean(context && context.companyId),
        workspaceSelected: Boolean(context && context.workspaceId),
        projectSelected: Boolean(context && context.projectId),
        contextVersion: context ? context.contextVersion : "",
        lastOperation: state.lastOperation,
        demoMode: demoMode,
        returnPath: returnPath
      });
    }

    return Object.freeze({
      mount: mount,
      revalidate: revalidate,
      selectCompany: selectCompany,
      selectResource: selectResource,
      request: request,
      permission: permission,
      context: contextSnapshot,
      scrub: function (reason) { return scrub(reason || "Human operational state cleared.", PHASES.LOCKED); },
      logout: logout,
      resetDemo: resetDemo,
      getSnapshot: getSnapshot,
      destroy: destroy
    });
  }

  function demoRecord(value) {
    return Object.assign({}, value, {mockData: true});
  }

  function initialDemoRepository() {
    return {
      signedIn: true,
      sequence: 0,
      csrfToken: "mock-csrf-initial",
      sessionId: "mock-human-session-initial",
      selectedAuthorityId: "",
      selectedCompanyId: "",
      workspaceId: "",
      projectId: "",
      contextVersion: "mock-context-initial",
      account: demoRecord({
        humanAccountId: "mock-human-account",
        username: "mock-human",
        displayName: "MemoryEndpoints Human (Mock)"
      }),
      memberships: [
        demoRecord({authorityId: "mock-authority-alpha", companyId: "mock-company-alpha", companyLabel: "Endpoint Ecosystem (Mock)"}),
        demoRecord({authorityId: "mock-authority-beta", companyId: "mock-company-beta", companyLabel: "Documentation Lab (Mock)"})
      ],
      catalogs: {
        "mock-company-alpha": [
          demoRecord({
            workspaceId: "mock-workspace-memory",
            label: "Memory Operations (Mock)",
            projects: [
              demoRecord({projectId: "mock-project-site", label: "MemoryEndpoints.com (Mock)"}),
              demoRecord({projectId: "mock-project-local", label: "LocalEndpoint education (Mock)"})
            ]
          })
        ],
        "mock-company-beta": []
      },
      permissions: {
        canReadOperationalWorkspace: true,
        canSearchOperationalMemory: true,
        canSubmitOperationalMemory: true,
        canReadOperationalKnowledge: true,
        canReadOperationalExternalLinks: true,
        canSearchOperationalInternet: true,
        mockData: true
      },
      memories: [demoRecord({
        eventId: "mock-memory-one",
        title: "Human cookie-session boundary (Mock)",
        summary: "The browser uses a human session and explicit resource context. (Mock)",
        memoryType: "decision",
        scope: "workspace"
      })],
      documents: [demoRecord({
        searchDocumentId: "mock-knowledge-one",
        title: "Human operational tour (Mock)",
        routeOrPath: "/tour/knowledge/project/memoryendpoints/human-operational-tour",
        description: "A session-only explanation of the authenticated renderer boundary. (Mock)",
        searchableText: "All records on this route are clearly labeled mock data.",
        scope: "project",
        knowledgeStatus: "current",
        authorityLevel: "reviewed"
      })],
      links: [demoRecord({
        externalLinkId: "mock-link-one",
        siteName: "UAIX.org (Mock reference)",
        pageTitle: "Portable agent guidance (Mock)",
        url: "https://uaix.org"
      })]
    };
  }

  function cloneDemoPlans(source) {
    var output = {};
    Object.keys(source || {}).forEach(function (name) {
      output[name] = Array.isArray(source[name]) ? source[name].slice() : source[name];
    });
    return output;
  }

  function requireDemoLabels(value) {
    if (Array.isArray(value)) {
      value.forEach(requireDemoLabels);
      return;
    }
    if (!plainObject(value)) return;
    if (value.mockData !== true) fail("mock_label_required", 422);
    Object.keys(value).forEach(function (name) {
      if (name !== "mockData") requireDemoLabels(value[name]);
    });
  }

  function createDemoTransport(options) {
    options = options || {};
    var demoRoutes = createRouteAdapter();
    var repository = initialDemoRepository();
    var initial = copy(repository);
    var calls = [];
    var initialPlans = cloneDemoPlans(options.plans || {});
    var plans = cloneDemoPlans(initialPlans);
    var idempotency = {};

    function rotate(full) {
      repository.sequence += 1;
      repository.csrfToken = "mock-csrf-" + repository.sequence;
      repository.contextVersion = "mock-context-" + repository.sequence;
      if (full) repository.sessionId = "mock-human-session-" + repository.sequence;
    }

    function demoEnvelope(fullRotation) {
      return {
        ok: true,
        account: copy(repository.account),
        humanSession: demoRecord({
          humanAccountSessionId: repository.sessionId,
          humanAccountId: repository.account.humanAccountId,
          username: repository.account.username,
          selectedAuthorityId: repository.selectedAuthorityId,
          selectedCompanyId: repository.selectedCompanyId,
          expiresAt: "Demo session"
        }),
        memberships: copy(repository.memberships),
        resourceContext: demoRecord({
          authorityId: repository.selectedAuthorityId,
          companyId: repository.selectedCompanyId,
          workspaceId: repository.workspaceId,
          projectId: repository.projectId,
          contextVersion: repository.contextVersion
        }),
        permissions: copy(repository.permissions),
        csrfToken: repository.csrfToken,
        csrfTokenRotated: true,
        sessionRotated: fullRotation === true,
        valuesRedacted: true,
        rawCredentialExposed: false,
        rawPayloadExposed: false,
        mockData: true
      };
    }

    function parsePath(path) {
      if (typeof path !== "string" || path.charAt(0) !== "/" || path.charAt(1) === "/"
        || path.indexOf("://") !== -1 || path.indexOf("\\") !== -1 || path.indexOf("#") !== -1) {
        fail("unsafe_route", 0);
      }
      var pieces = path.split("?");
      if (pieces.length > 2) fail("invalid_query", 0);
      var query = {};
      if (pieces[1]) {
        pieces[1].split("&").forEach(function (part) {
          if (!part) fail("invalid_query", 0);
          var pair = part.split("=");
          var key;
          var decodedValue;
          try {
            key = decodeURIComponent(pair.shift() || "");
            decodedValue = decodeURIComponent(pair.join("="));
          } catch (_) {
            fail("invalid_query", 0);
          }
          if (!key || Object.prototype.hasOwnProperty.call(query, key)) fail("invalid_query", 0);
          query[key] = decodedValue;
        });
      }
      return {pathname: pieces[0], query: query};
    }

    function operationFor(pathname, method) {
      var names = Object.keys(OPERATION_MAP).filter(function (name) {
        return OPERATION_MAP[name].path === pathname;
      });
      if (names.length !== 1) fail("operation_not_available", 404);
      if (method !== OPERATION_MAP[names[0]].method) fail("invalid_method", 0);
      return names[0];
    }

    function bodyFrom(optionsValue) {
      if (optionsValue.body === undefined) return undefined;
      if (typeof optionsValue.body !== "string") fail("invalid_body", 0);
      try {
        var parsed = JSON.parse(optionsValue.body);
        if (!plainObject(parsed)) fail("invalid_body", 0);
        return parsed;
      } catch (error) {
        if (error instanceof OperationalError) throw error;
        fail("invalid_body", 0);
      }
    }

    function planFor(name) {
      var value = plans[name];
      if (Array.isArray(value)) return value.length ? value.shift() : null;
      return value || null;
    }

    function ensureContext() {
      if (!repository.selectedCompanyId) fail("selected_company_required", 409);
      if (!repository.workspaceId) fail("selected_workspace_required", 409);
    }

    function operationResponse(name, query, body) {
      if (name === "sessionInspect") {
        if (!repository.signedIn) fail("human_session_required", 401);
        rotate(false);
        return demoEnvelope(false);
      }
      if (name === "companySelect") {
        var membership = repository.memberships.filter(function (item) { return item.authorityId === body.authorityId; })[0];
        if (!membership) fail("unknown_authority", 422);
        repository.selectedAuthorityId = membership.authorityId;
        repository.selectedCompanyId = membership.companyId;
        repository.workspaceId = "";
        repository.projectId = "";
        rotate(true);
        return demoEnvelope(true);
      }
      if (name === "contextCatalog") {
        if (!repository.selectedCompanyId) fail("selected_company_required", 409);
        return {
          ok: true,
          contextVersion: repository.contextVersion,
          workspaces: copy(repository.catalogs[repository.selectedCompanyId] || []),
          valuesRedacted: true,
          rawCredentialExposed: false,
          rawPayloadExposed: false,
          mockData: true
        };
      }
      if (name === "resourceContextSelect") {
        if (!repository.selectedCompanyId) fail("selected_company_required", 409);
        var workspace = (repository.catalogs[repository.selectedCompanyId] || []).filter(function (item) { return item.workspaceId === body.workspaceId; })[0];
        if (!workspace) fail("unknown_workspace", 422);
        if (body.projectId && !workspace.projects.some(function (item) { return item.projectId === body.projectId; })) fail("unknown_project", 422);
        repository.workspaceId = workspace.workspaceId;
        repository.projectId = body.projectId || "";
        rotate(true);
        return demoEnvelope(true);
      }
      if (name === "sessionLogout") {
        repository.signedIn = false;
        repository.selectedAuthorityId = "";
        repository.selectedCompanyId = "";
        repository.workspaceId = "";
        repository.projectId = "";
        return {ok: true, signedOut: true, valuesRedacted: true, rawCredentialExposed: false, rawPayloadExposed: false, mockData: true};
      }

      ensureContext();
      if (name === "workspaceRead") {
        return {
          ok: true,
          contextVersion: repository.contextVersion,
          workspace: demoRecord({
            workspaceId: repository.workspaceId,
            companyId: repository.selectedCompanyId,
            label: "Memory Operations (Mock)",
            projects: copy((repository.catalogs[repository.selectedCompanyId] || [])[0].projects)
          }),
          mockData: true
        };
      }
      if (name === "memorySearch") {
        return {ok: true, contextVersion: repository.contextVersion, items: copy(repository.memories), count: repository.memories.length, mockData: true};
      }
      if (name === "memorySubmit") {
        var memory = demoRecord({
          eventId: "mock-memory-created-" + (repository.memories.length + 1),
          title: body.title + " (Mock)",
          summary: body.summary + " (Mock data; session-only.)",
          memoryType: body.memoryType,
          scope: body.scope,
          tags: (body.tags || []).concat(["mock-data"])
        });
        repository.memories.push(memory);
        return {ok: true, contextVersion: repository.contextVersion, csrfTokenRotated: false, event: copy(memory), mockData: true};
      }
      if (name === "knowledgeTree") {
        return {
          ok: true,
          contextVersion: repository.contextVersion,
          tree: demoRecord({levels: [demoRecord({scope: "project", documents: copy(repository.documents)})]}),
          mockData: true
        };
      }
      if (name === "knowledgeDocuments") {
        return {ok: true, contextVersion: repository.contextVersion, items: copy(repository.documents), count: repository.documents.length, mockData: true};
      }
      if (name === "externalLinks") {
        return {ok: true, contextVersion: repository.contextVersion, items: copy(repository.links), count: repository.links.length, mockData: true};
      }
      if (name === "internetSearch") {
        return {ok: true, contextVersion: repository.contextVersion, items: copy(repository.links), count: repository.links.length, mockData: true};
      }
      fail("operation_not_available", 404);
    }

    return Object.freeze({
      demoTransport: true,
      mockData: true,
      request: async function (path, requestOptions) {
        var config = requestOptions || {};
        if (!plainObject(config) || config.credentials !== "same-origin" || config.cache !== "no-store" || config.redirect !== "error"
          || config.mode !== "same-origin" || config.referrerPolicy !== "no-referrer") {
          fail("unsafe_request_options", 0);
        }
        Object.keys(config).forEach(function (optionName) {
          if (["method", "headers", "body", "credentials", "cache", "redirect", "mode", "referrerPolicy", "signal", "operation", "idempotencyKey"].indexOf(optionName) === -1) {
            fail("unsafe_request_option", 0);
          }
        });
        var descriptor = parsePath(path);
        if (config.method !== "GET" && config.method !== "POST") fail("invalid_method", 0);
        var name = operationFor(descriptor.pathname, config.method);
        if (config.operation !== name) fail("operation_mismatch", 0);
        var spec = OPERATION_MAP[name];
        if (config.signal && config.signal.aborted) fail("stale_response", 0);
        var receivedContextVersion = repository.contextVersion;
        var body = bodyFrom(config);
        var canonical = demoRoutes.resolve(name, {query: descriptor.query, body: body});
        if (canonical.path !== path) fail("noncanonical_route", 0);
        var headers = plainObject(config.headers) ? config.headers : {};
        Object.keys(headers).forEach(function (headerName) {
          if (SAFE_HEADER_NAMES.indexOf(headerName) === -1) fail("unsafe_request_header", 0);
        });
        if (headers.Accept !== "application/json") fail("json_accept_required", 0);
        var idempotencyKey = "";
        if (spec.mutation) {
          if (headers["Content-Type"] !== "application/json") fail("json_content_type_required", 0);
          idempotencyKey = normalizeIdempotencyKey(headers["Idempotency-Key"]);
          if (config.idempotencyKey && config.idempotencyKey !== idempotencyKey) fail("idempotency_key_mismatch", 0);
        } else if (headers["X-CSRF-Token"] !== undefined || headers["Idempotency-Key"] !== undefined || headers["Content-Type"] !== undefined) {
          fail("unexpected_mutation_header", 0);
        }
        var signature = JSON.stringify({name: name, query: descriptor.query, body: body || {}});
        calls.push(demoRecord({
          operation: name,
          method: spec.method,
          path: descriptor.pathname,
          queryKeys: Object.keys(descriptor.query).sort(),
          bodyKeys: Object.keys(body || {}).sort(),
          idempotencyKey: idempotencyKey,
          credentials: config.credentials,
          cache: config.cache,
          redirect: config.redirect,
          mode: config.mode,
          referrerPolicy: config.referrerPolicy
        }));
        if (spec.mutation) {
          if (idempotency[idempotencyKey]) {
            if (idempotency[idempotencyKey].signature !== signature) fail("idempotency_conflict", 409);
            return copy(idempotency[idempotencyKey].payload);
          }
          if (headers["X-CSRF-Token"] !== repository.csrfToken) fail("csrf_invalid", 403);
        }

        var plan = planFor(name);
        if (typeof plan === "function") plan = await plan({operation: name, query: copy(descriptor.query), body: copy(body || {})});
        if (config.signal && config.signal.aborted) fail("stale_response", 0);
        if (spec.path.indexOf("/api/matm/human/operational/") === 0 && repository.contextVersion !== receivedContextVersion) {
          fail("stale_context", 409);
        }
        if (plan && plan.type === "error") fail(safeCode(plan.code, "request_failed"), Number(plan.status || 400));
        if (plan && plan.type === "lost_before") fail("lost_response", 0, {recoverable: true, idempotencyKey: idempotencyKey});

        var payload = plan && plainObject(plan.payload) ? copy(plan.payload) : operationResponse(name, descriptor.query, body || {});
        if (plan && plan.type === "empty") {
          payload = {ok: true, contextVersion: repository.contextVersion, items: [], count: 0, empty: true, mockData: true};
          if (spec.mutation) payload.csrfTokenRotated = false;
        }
        if (plan && plan.type === "stale") payload.contextVersion = "mock-stale-context";
        requireDemoLabels(payload);
        if (spec.mutation) idempotency[idempotencyKey] = {signature: signature, payload: copy(payload)};
        if (plan && plan.type === "lost_after") fail("lost_response", 0, {recoverable: true, idempotencyKey: idempotencyKey});
        return copy(payload);
      },
      setPlan: function (name, plan) {
        if (!OPERATION_MAP[name]) fail("unknown_operation", 0);
        plans[name] = plan;
      },
      setPermission: function (name, value) {
        if (Object.keys(PERMISSIONS).map(function (key) { return PERMISSIONS[key]; }).indexOf(name) === -1) fail("unknown_permission", 0);
        repository.permissions[name] = value === true;
      },
      reset: function () {
        repository = copy(initial);
        calls.length = 0;
        plans = cloneDemoPlans(initialPlans);
        idempotency = {};
      },
      inspect: function () {
        return Object.freeze({
          mockData: true,
          networkRequestCount: 0,
          callCount: calls.length,
          calls: copy(calls),
          signedIn: repository.signedIn,
          companySelected: Boolean(repository.selectedCompanyId),
          workspaceSelected: Boolean(repository.workspaceId),
          projectSelected: Boolean(repository.projectId),
          memoryCount: repository.memories.length
        });
      }
    });
  }

  return Object.freeze({
    ROUTES: ROUTES,
    OPERATION_MAP: OPERATION_MAP,
    SELECTORS: SELECTORS,
    PERMISSIONS: PERMISSIONS,
    PHASES: PHASES,
    OUTCOMES: OUTCOMES,
    ALLOWED_RETURN_PATHS: ALLOWED_RETURN_PATHS,
    OperationalError: OperationalError,
    createIdempotencyKey: createIdempotencyKey,
    normalizeReturnPath: normalizeReturnPath,
    createRouteAdapter: createRouteAdapter,
    createTransport: createTransport,
    createSessionAuthority: createSessionAuthority,
    createIntegrationAdapter: createIntegrationAdapter,
    createDemoTransport: createDemoTransport,
    create: create
  });
});
