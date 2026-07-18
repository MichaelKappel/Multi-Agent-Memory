"use strict";

const nodeAssert = require("node:assert");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

let assertionCount = 0;
let scenarioCount = 0;
const assert = new Proxy(function (...args) {
  assertionCount += 1;
  return nodeAssert(...args);
}, {
  get(_target, property) {
    const value = nodeAssert[property];
    if (typeof value !== "function") return value;
    return function (...args) {
      assertionCount += 1;
      return value(...args);
    };
  }
});

async function scenario(action) {
  scenarioCount += 1;
  return action();
}

const scriptPath = process.argv[2];
if (!scriptPath) throw new Error("Usage: node tests/connector_authorize_client_contract.js static/js/connector-authorize.js");
const source = fs.readFileSync(scriptPath, "utf8");
const api = require(path.resolve(scriptPath));

const SCHEMA = "memoryendpoints.connector_pairing.v1";
const PUBLIC_REQUEST_REF = "pairref_" + "A".repeat(43);
const WORKSPACE_REF = "workref_" + "B".repeat(43);
const WAKE_UP_URL = "http://127.0.0.1:53682/memoryendpoints/callback";
const SCOPES = [
  "connector:self:readback",
  "agent:self:register",
  "memory:public-safe:submit",
  "memory:search:read"
];
const SCOPE_LABELS = {
  "connector:self:readback": "Verify this exact connector, workspace, and agent binding.",
  "agent:self:register": "Register the exact LocalEndpoint agent during activation.",
  "memory:public-safe:submit": "Submit public-safe memory as this exact connector agent.",
  "memory:search:read": "Search memory readable by this exact connector grant."
};
const EXPECTED_SCOPE_DIGEST = "sha256-v1:" + crypto.createHash("sha256").update(
  JSON.stringify({schemaVersion: SCHEMA, scopes: SCOPES}), "utf8"
).digest("hex");

for (const forbidden of [
  "local" + "Storage", "session" + "Storage", "indexed" + "DB", "XML" + "HttpRequest",
  "Web" + "Socket", "send" + "Beacon", "document" + ".cookie", "inner" + "HTML",
  "outer" + "HTML", "console" + ".log", "console" + ".error"
]) assert(!source.includes(forbidden), `forbidden browser persistence, transport, or logging surface: ${forbidden}`);
for (const browserForbidden of ["pairingRequestProof", "authorizationCode", "callbackUrl", "approvedAgentId", "requestId", "workspaceId", "authorityId", "companyId", "agentId"]) {
  assert(!source.includes(browserForbidden), `browser client must not receive or serialize ${browserForbidden}`);
}
assert(source.includes('credentials: "same-origin"'));
assert(source.includes('cache: "no-store"'));
assert(source.includes('redirect: "error"'));
assert(source.includes('referrerPolicy: "no-referrer"'));
assert(source.includes("scrubProtectedState"));
assert(source.includes("revalidateSession"));
assert(source.includes("connectorAuthorization.selectCompany"));
assert(source.includes("connectorAuthorization.reauthenticate"));
assert(source.includes("connectorAuthorization.returnToDesktop"));

function response(status, payload, contentType) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: {get(name) { return String(name).toLowerCase() === "content-type" ? (contentType || "application/json; charset=utf-8") : null; }},
    async text() { return JSON.stringify(payload); }
  };
}

class Element {
  constructor(tagName) {
    this.tagName = String(tagName || "div").toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.attributes = {};
    this.dataset = {};
    this.listeners = {};
    this.textContent = "";
    this.value = "";
    this.type = this.tagName === "INPUT" ? "text" : "";
    this.checked = false;
    this.disabled = false;
    this.hidden = false;
    this.focused = false;
  }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  replaceChildren(...children) { this.children.forEach((item) => { item.parentNode = null; }); this.children = []; children.forEach((item) => this.appendChild(item)); }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === "disabled") this.disabled = true;
    if (name === "hidden") this.hidden = true;
  }
  getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null; }
  hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attributes, name); }
  removeAttribute(name) {
    delete this.attributes[name];
    if (name === "disabled") this.disabled = false;
    if (name === "hidden") this.hidden = false;
  }
  focus() { this.focused = true; }
  addEventListener(name, handler) { (this.listeners[name] ||= []).push(handler); }
  removeEventListener(name, handler) { this.listeners[name] = (this.listeners[name] || []).filter((item) => item !== handler); }
}

function namedInput(name, value, type) {
  const input = new Element("input");
  input.setAttribute("name", name);
  input.value = value || "";
  input.type = type || "text";
  return input;
}

function actionButton(method, options) {
  options = options || {};
  const button = new Element("button");
  button.setAttribute("data-client-method", `connectorAuthorization.${method}`);
  button.setAttribute("data-connector-mutation-action", "");
  if (options.auth) button.setAttribute("data-connector-auth-action", "");
  if (options.account) button.setAttribute("data-connector-account-action", "");
  if (options.disabled) button.setAttribute("disabled", "");
  return button;
}

function container(controls) {
  const item = new Element("div");
  item._controls = controls || [];
  item.querySelector = (selector) => {
    const match = selector.match(/^\[name="([^"]+)"\]$/);
    if (match) return item._controls.find((control) => control.getAttribute("name") === match[1]) || null;
    return null;
  };
  item.querySelectorAll = (selector) => {
    if (selector === "input,button,select,textarea") return item._controls.slice();
    const match = selector.match(/^\[name="([^"]+)"\]$/);
    if (match) return item._controls.filter((control) => control.getAttribute("name") === match[1]);
    return [];
  };
  item._controls.forEach((control) => item.appendChild(control));
  return item;
}

function harness(config, transport, controllerOptions) {
  const root = new Element("section");
  const status = new Element("output");
  const configElement = new Element("script");
  const username = namedInput("username", "mock-owner");
  const loginPassword = namedInput("password", "A-demo-password-1234", "password");
  const login = container([username, loginPassword]);
  login.setAttribute("data-enter-action", "connectorAuthorization.login");
  const loginButton = actionButton("login");
  login.appendChild(loginButton);
  const loginError = new Element("p");
  loginError.setAttribute("data-error-for", "login");
  login.appendChild(loginError);
  const master = namedInput("companyMasterTokenSecret", "MOCK-MASTER-CANARY-1234567890", "password");
  const proof = container([master]);
  proof.setAttribute("data-enter-action", "connectorAuthorization.beginEnrollment");
  const proofButton = actionButton("beginEnrollment");
  proof.appendChild(proofButton);
  const enrollmentError = new Element("p");
  proof.appendChild(enrollmentError);
  const existing = namedInput("workspaceMode", "existing", "radio"); existing.checked = true;
  const createNew = namedInput("workspaceMode", "new", "radio");
  const workspace = namedInput("workspaceRef", WORKSPACE_REF);
  const workspaceLabel = namedInput("workspaceLabel", "");
  const canonical = namedInput("canonicalAgentApproved", "true", "checkbox"); canonical.checked = true;
  const scopeImpact = namedInput("scopeImpactApproved", "true", "checkbox"); scopeImpact.checked = true;
  const approval = container([existing, createNew, workspace, workspaceLabel, canonical, scopeImpact]);
  approval.setAttribute("data-enter-action", "connectorAuthorization.approve");
  const approveButton = actionButton("approve", {auth: true, disabled: true});
  const cancelButton = actionButton("cancel", {auth: true, disabled: true});
  approval.appendChild(approveButton); approval.appendChild(cancelButton);
  const workspaceError = new Element("p"); workspaceError.setAttribute("data-error-for", "workspace"); approval.appendChild(workspaceError);
  const canonicalError = new Element("p"); canonicalError.setAttribute("data-error-for", "canonicalAgentApproved"); approval.appendChild(canonicalError);
  const scopeError = new Element("p"); scopeError.setAttribute("data-error-for", "scopeImpactApproved"); approval.appendChild(scopeError);
  const validationSummary = new Element("div"); validationSummary.setAttribute("data-validation-summary", ""); approval.appendChild(validationSummary);
  const reauthPassword = namedInput("password", "A-demo-password-1234", "password");
  const reauth = container([reauthPassword]);
  reauth.setAttribute("data-enter-action", "connectorAuthorization.reauthenticate");
  const reauthButton = actionButton("reauthenticate", {auth: true, disabled: true});
  reauth.appendChild(reauthButton);
  const reauthError = new Element("p");
  reauth.appendChild(reauthError);
  const companyRef = namedInput("companyRef", "companyref_" + "C".repeat(43));
  const companySelection = container([companyRef]);
  companySelection.setAttribute("data-enter-action", "connectorAuthorization.selectCompany");
  const companyButton = actionButton("selectCompany", {auth: true, disabled: true});
  companySelection.appendChild(companyButton);
  const companyError = new Element("p"); companyError.setAttribute("data-error-for", "companyRef"); companySelection.appendChild(companyError);
  const accountUsername = namedInput("username", "mock-owner-two");
  const accountPassword = namedInput("password", "A-demo-password-9876", "password");
  const accountConfirmation = namedInput("passwordConfirmation", "A-demo-password-9876", "password");
  const accountCreateButton = actionButton("completeEnrollment", {account: true, disabled: true});
  const account = container([accountUsername, accountPassword, accountConfirmation, accountCreateButton]);
  account.setAttribute("data-enter-action", "connectorAuthorization.completeEnrollment");
  account.setAttribute("hidden", "");
  for (const item of account._controls) item.setAttribute("disabled", "");
  const returnAction = new Element("a");
  if (["approved", "replay"].includes(config.viewState)) {
    returnAction.setAttribute("href", controllerOptions && controllerOptions.terminalWakeUpUrl || WAKE_UP_URL);
  }
  const map = new Map([
    ["[data-connector-status]", status],
    ["[data-connector-authorization-config]", configElement],
    ["[data-connector-login]", login],
    ["[data-connector-login-error]", loginError],
    ["[data-connector-master-proof]", proof],
    ["[data-connector-enrollment-error]", enrollmentError],
    ["[data-connector-approval-form]", approval],
    ["[data-validation-summary]", validationSummary],
    ['[data-error-for="workspace"]', workspaceError],
    ['[data-error-for="canonicalAgentApproved"]', canonicalError],
    ['[data-error-for="scopeImpactApproved"]', scopeError],
    ["[data-connector-reauth]", reauth],
    ["[data-connector-reauth-error]", reauthError],
    ["[data-connector-company-selection]", companySelection],
    ['[data-error-for="companyRef"]', companyError],
    ["[data-connector-return-action]", returnAction],
    ["[data-connector-account-create]", account],
    ['[data-connector-account-create] [name="username"]', accountUsername],
    ['[data-connector-account-create] [name="password"]', accountPassword],
    ['[data-connector-account-create] [name="passwordConfirmation"]', accountConfirmation]
  ]);
  const allControls = [username, loginPassword, master, existing, createNew, workspace, workspaceLabel, canonical, scopeImpact, reauthPassword, companyRef, accountUsername, accountPassword, accountConfirmation];
  const mutationActions = [loginButton, proofButton, accountCreateButton, companyButton, reauthButton, approveButton, cancelButton];
  const allErrors = [loginError, enrollmentError, workspaceError, canonicalError, scopeError, reauthError, companyError];
  root.querySelector = (selector) => map.get(selector) || null;
  root.querySelectorAll = (selector) => {
    if (selector === "input,select,textarea") return allControls;
    if (selector === "[data-connector-mutation-action]") return mutationActions;
    if (selector === "[data-error-for]") return allErrors;
    if (selector === '[aria-invalid="true"]') return allControls.filter((item) => item.getAttribute("aria-invalid") === "true");
    return [];
  };
  for (const child of [status, configElement, login, proof, approval, reauth, companySelection, account, returnAction]) root.appendChild(child);
  const lifecycle = {};
  const windowRef = {
    addEventListener(name, handler) { (lifecycle[name] ||= []).push(handler); },
    removeEventListener(name, handler) { lifecycle[name] = (lifecycle[name] || []).filter((item) => item !== handler); }
  };
  let reloads = 0;
  const navigations = [];
  const demoStateNavigations = [];
  const controller = api.create(Object.assign({
    root, windowRef, documentRef: {}, config, transport,
    reload() { reloads += 1; },
    navigate(target) { navigations.push(target); },
    demoStateNavigate(state) { demoStateNavigations.push(`/tour/connect/authorize/${state}`); }
  }, controllerOptions || {}));
  return {account, accountConfirmation, accountCreateButton, accountPassword, accountUsername, approval, approveButton, cancelButton, canonical, canonicalError, companyButton, companyError, companyRef, companySelection, controller, demoStateNavigations, enrollmentError, lifecycle, login, loginButton, loginError, loginPassword, loginUsername: username, master, navigations, proof, proofButton, reauth, reauthButton, reauthError, reauthPassword, reloads: () => reloads, returnAction, root, scopeError, scopeImpact, status, validationSummary, workspace, workspaceError, workspaceLabel};
}

async function settle() {
  for (let index = 0; index < 10; index += 1) await Promise.resolve();
  await new Promise((resolve) => setImmediate(resolve));
}

function assertExactApprovalBody(body, workspaceSelection) {
  assert.deepStrictEqual(Object.keys(body).sort(), ["approvedScopes", "canonicalAgentApproved", "schemaVersion", "workspaceSelection"]);
  assert.strictEqual(body.schemaVersion, SCHEMA);
  assert.strictEqual(body.canonicalAgentApproved, true);
  assert.deepStrictEqual(body.approvedScopes, SCOPES);
  assert.deepStrictEqual(body.workspaceSelection, workspaceSelection);
}

async function productionContract() {
  const calls = [];
  const transport = api.createProductionTransport(async (route, options) => {
    calls.push({route, options});
    return response(200, {ok: true, csrfToken: "csrf-returned-to-memory", wakeUpUrl: WAKE_UP_URL});
  }, {randomKey: () => "connector-ui-test-idempotency-key-1234567890"});
  await transport.request("sessionLogin", {body: {username: "owner", password: "PASSWORD-CANARY"}});
  assert.strictEqual(calls[0].route, "/api/matm/human/session");
  assert.strictEqual(calls[0].options.credentials, "same-origin");
  assert.strictEqual(calls[0].options.cache, "no-store");
  assert.strictEqual(calls[0].options.redirect, "error");
  assert.strictEqual(calls[0].options.referrerPolicy, "no-referrer");
  assert.strictEqual(calls[0].options.keepalive, false);
  assert.strictEqual(calls[0].options.headers["Content-Type"], "application/json");
  assert.strictEqual(calls[0].options.headers["Idempotency-Key"], "connector-ui-test-idempotency-key-1234567890");
  assert(!Object.keys(calls[0].options.headers).some((key) => /authorization/i.test(key)));

  await transport.request("membershipSelect", {
    publicRequestRef: PUBLIC_REQUEST_REF,
    csrfToken: "csrf-company-selection",
    body: {schemaVersion: SCHEMA, companyRef: "companyref_" + "C".repeat(43)}
  });
  assert.strictEqual(
    calls[1].route,
    `/api/matm/human/connector-pairings/${PUBLIC_REQUEST_REF}/company-selection`
  );
  assert.deepStrictEqual(JSON.parse(calls[1].options.body), {
    schemaVersion: SCHEMA,
    companyRef: "companyref_" + "C".repeat(43)
  });
  assert.strictEqual(calls[1].options.headers["X-CSRF-Token"], "csrf-company-selection");

  const approvalBody = api.validateApproval({
    workspaceMode: "existing", workspaceRef: WORKSPACE_REF,
    canonicalAgentApproved: true, scopeImpactApproved: true
  });
  await transport.request("approve", {publicRequestRef: PUBLIC_REQUEST_REF, csrfToken: "csrf-canary", body: approvalBody});
  assert.strictEqual(calls[2].route, `/api/matm/human/connector-pairings/${PUBLIC_REQUEST_REF}/approve`);
  assert.strictEqual(calls[2].options.headers["X-CSRF-Token"], "csrf-canary");
  assertExactApprovalBody(JSON.parse(calls[2].options.body), {mode: "existing", workspaceRef: WORKSPACE_REF});

  const brokenType = api.createProductionTransport(async () => response(200, {ok: true}, "text/html"), {randomKey: () => "test-key-1234567890"});
  await assert.rejects(() => brokenType.request("sessionInspect"), (error) => error.code === "invalid_response");
  const redactedFailure = api.createProductionTransport(async () => response(403, {error: {code: "recent_reauthentication_required", detail: "PRIVATE BACKEND CANARY"}}), {randomKey: () => "test-key-1234567890"});
  await assert.rejects(() => redactedFailure.request("sessionInspect"), (error) => error.code === "recent_reauthentication_required" && !String(error.message).includes("CANARY"));
}

async function credentialFailureContract() {
  const signedOutConfig = {
    authenticated: false,
    viewState: "signed_out",
    transport: {kind: "same_origin_human_session", protectedNetworkAllowed: true}
  };

  async function rejectedLogin(privateDetail) {
    let requestCount = 0;
    const transport = api.createProductionTransport(async (route) => {
      requestCount += 1;
      assert.strictEqual(route, "/api/matm/human/session");
      return response(401, {error: {code: "human_login_failed", detail: privateDetail}});
    }, {randomKey: () => "credential-rejection-test-key-1234567890"});
    const ui = harness(signedOutConfig, transport);
    ui.controller.mount();
    ui.loginUsername.value = "known-owner";
    ui.loginPassword.value = "x";
    const pending = ui.controller.login();
    assert.strictEqual(ui.loginPassword.value, "", "rejected login did not clear the password synchronously");
    const result = await pending;
    assert.deepStrictEqual(result, {ok: false, state: api.STATES.LOGIN_FAILED, code: "human_login_failed"});
    assert.strictEqual(requestCount, 1, "a short authentication password was blocked by the new-account strength policy");
    assert.strictEqual(ui.controller.getSnapshot().state, api.STATES.LOGIN_FAILED);
    assert.strictEqual(ui.reloads(), 0, "credential rejection reloaded the page and erased its feedback");
    assert.deepStrictEqual(ui.demoStateNavigations, []);
    assert.deepStrictEqual(ui.navigations, []);
    assert(ui.root.children.length > 0, "credential rejection scrubbed the sign-in DOM");
    assert.strictEqual(ui.loginUsername.value, "known-owner");
    assert.strictEqual(ui.loginUsername.getAttribute("aria-invalid"), "true");
    assert.strictEqual(ui.loginPassword.getAttribute("aria-invalid"), "true");
    assert.strictEqual(ui.loginPassword.focused, true);
    assert.strictEqual(ui.loginError.textContent, api.SAFE_MESSAGES.login_failed);
    assert.strictEqual(ui.status.textContent, "", "form error was duplicated in the global polite status region");
    assert(!ui.loginError.textContent.includes(privateDetail), "private backend detail reached the credential error");
    return ui.loginError.textContent;
  }

  const unknownAccountMessage = await rejectedLogin("PRIVATE UNKNOWN-ACCOUNT CANARY");
  const wrongPasswordMessage = await rejectedLogin("PRIVATE WRONG-PASSWORD CANARY");
  assert.strictEqual(unknownAccountMessage, wrongPasswordMessage, "unknown account and wrong password became distinguishable");

  let malformedLoginRequests = 0;
  const malformedUi = harness(signedOutConfig, {
    async request() { malformedLoginRequests += 1; return {}; },
    scrub() {}
  });
  malformedUi.controller.mount();
  malformedUi.loginUsername.value = "not-an-email@example.com";
  malformedUi.loginPassword.value = "x";
  const malformed = await malformedUi.controller.login();
  assert.strictEqual(malformed.code, "login_input_invalid");
  assert.strictEqual(malformedLoginRequests, 0);
  assert.strictEqual(malformedUi.reloads(), 0);
  assert.strictEqual(malformedUi.loginUsername.value, "not-an-email@example.com");
  assert.strictEqual(malformedUi.loginUsername.getAttribute("aria-invalid"), "true");
  assert.strictEqual(malformedUi.loginUsername.focused, true);
  assert.strictEqual(malformedUi.loginPassword.value, "");
  assert.strictEqual(malformedUi.loginError.textContent, "Enter a valid MemoryEndpoints username and your password.");

  const transientLoginCases = [
    {
      label: "rate limit",
      expectedCode: "rate_limited",
      expectedMessage: /too many sign-in attempts/i,
      fetch: async () => response(429, {error: {code: "rate_limited", detail: "PRIVATE RATE CANARY"}})
    },
    {
      label: "service failure",
      expectedCode: "internal_error",
      expectedMessage: /temporarily unavailable/i,
      fetch: async () => response(503, {error: {code: "internal_error", detail: "PRIVATE SERVICE CANARY"}})
    },
    {
      label: "transport failure",
      expectedCode: "transport_unavailable",
      expectedMessage: /could not be reached/i,
      fetch: async () => { throw new Error("PRIVATE TRANSPORT CANARY"); }
    },
    {
      label: "malformed response",
      expectedCode: "invalid_response",
      expectedMessage: /unexpected sign-in response/i,
      fetch: async () => response(200, {detail: "PRIVATE MALFORMED CANARY"}, "text/html")
    }
  ];
  for (const item of transientLoginCases) {
    const ui = harness(signedOutConfig, api.createProductionTransport(item.fetch, {
      randomKey: () => `transient-${item.expectedCode}-test-key-1234567890`
    }));
    ui.controller.mount();
    ui.loginUsername.value = "known-owner";
    ui.loginPassword.value = "transient-password";
    const result = await ui.controller.login();
    assert.strictEqual(result.ok, false, item.label);
    assert.strictEqual(result.state, api.STATES.LOGIN_FAILED, item.label);
    assert.strictEqual(result.code, item.expectedCode, item.label);
    assert.strictEqual(ui.reloads(), 0, `${item.label} erased its inline guidance`);
    assert.strictEqual(ui.loginUsername.value, "known-owner");
    assert.strictEqual(ui.loginPassword.value, "");
    assert.strictEqual(ui.loginUsername.getAttribute("aria-invalid"), null, `${item.label} falsely marked the username invalid`);
    assert.strictEqual(ui.loginPassword.getAttribute("aria-invalid"), null, `${item.label} falsely marked the password invalid`);
    assert.match(ui.loginError.textContent, item.expectedMessage, item.label);
    assert(!ui.loginError.textContent.includes("CANARY"), `${item.label} reflected backend or transport detail`);
  }

  const rejectedMasterTransport = api.createProductionTransport(async (route) => {
    assert.strictEqual(route, "/api/matm/human/company-master-proofs");
    return response(401, {error: {code: "company_master_proof_invalid", detail: "PRIVATE MASTER CANARY"}});
  }, {randomKey: () => "master-rejection-test-key-1234567890"});
  const rejectedMasterUi = harness(signedOutConfig, rejectedMasterTransport);
  rejectedMasterUi.controller.mount();
  rejectedMasterUi.master.value = "REJECTED-MASTER-CANARY-1234567890";
  const pendingMaster = rejectedMasterUi.controller.beginEnrollment();
  assert.strictEqual(rejectedMasterUi.master.value, "", "rejected company master was not cleared synchronously");
  const rejectedMaster = await pendingMaster;
  assert.deepStrictEqual(rejectedMaster, {ok: false, state: api.STATES.VALIDATION_ERROR, code: "company_master_proof_invalid"});
  assert.strictEqual(rejectedMasterUi.reloads(), 0, "company-master rejection erased its guidance");
  assert.strictEqual(rejectedMasterUi.account.hidden, true);
  assert.strictEqual(rejectedMasterUi.master.getAttribute("aria-invalid"), "true");
  assert.strictEqual(rejectedMasterUi.master.focused, true);
  assert.match(rejectedMasterUi.enrollmentError.textContent, /company master token was not accepted/i);
  assert.match(rejectedMasterUi.enrollmentError.textContent, /do not use the LocalEndpoint pairing reference/i);
  assert(!rejectedMasterUi.enrollmentError.textContent.includes("PRIVATE MASTER CANARY"));
  assert.strictEqual(rejectedMasterUi.status.textContent, "");

  const authenticatedConfig = {
    authenticated: true,
    viewState: "reauth_required",
    publicRequestRef: PUBLIC_REQUEST_REF,
    scopeDigest: api.SCOPE_DIGEST,
    transport: {kind: "same_origin_human_session", protectedNetworkAllowed: true}
  };
  let reauthenticationRequests = 0;
  const reauthenticationTransport = api.createProductionTransport(async (route) => {
    if (route === "/api/matm/human/session") {
      return response(200, {
        ok: true,
        account: {username: "known-owner"},
        humanSession: {passwordReauthenticatedAt: null},
        csrfToken: "csrf-credential-failure-contract"
      });
    }
    if (route === "/api/matm/human/session/reauth") {
      reauthenticationRequests += 1;
      return response(403, {error: {code: "human_reauthentication_failed", detail: "PRIVATE REAUTH CANARY"}});
    }
    throw new Error(`Unexpected route: ${route}`);
  }, {randomKey: () => "reauth-rejection-test-key-1234567890"});
  const reauthenticationUi = harness(authenticatedConfig, reauthenticationTransport);
  reauthenticationUi.controller.mount();
  await settle();
  assert.strictEqual(reauthenticationUi.controller.getSnapshot().state, api.STATES.REAUTH_REQUIRED);
  reauthenticationUi.reauthPassword.value = "x";
  const pendingReauthentication = reauthenticationUi.controller.reauthenticate();
  assert.strictEqual(reauthenticationUi.reauthPassword.value, "", "rejected reauthentication did not clear the password synchronously");
  const rejectedReauthentication = await pendingReauthentication;
  assert.deepStrictEqual(rejectedReauthentication, {ok: false, state: api.STATES.REAUTHENTICATION_FAILED, code: "human_reauthentication_failed"});
  assert.strictEqual(reauthenticationRequests, 1, "a short authentication password was blocked before reauthentication");
  assert.strictEqual(reauthenticationUi.reloads(), 0);
  assert.deepStrictEqual(reauthenticationUi.navigations, []);
  assert(reauthenticationUi.root.children.length > 0, "reauthentication rejection scrubbed request-bound DOM");
  assert.strictEqual(reauthenticationUi.controller.getSnapshot().protectedIdentifiersRetained, true);
  assert.strictEqual(reauthenticationUi.reauthPassword.getAttribute("aria-invalid"), "true");
  assert.strictEqual(reauthenticationUi.reauthPassword.focused, true);
  assert.strictEqual(reauthenticationUi.reauthError.textContent, api.SAFE_MESSAGES.reauthentication_failed);
  assert(!reauthenticationUi.reauthError.textContent.includes("CANARY"));
  assert.strictEqual(reauthenticationUi.status.textContent, "");

  const unavailableReauthenticationTransport = api.createProductionTransport(async (route) => {
    if (route === "/api/matm/human/session") {
      return response(200, {
        ok: true,
        account: {username: "known-owner"},
        humanSession: {passwordReauthenticatedAt: null},
        csrfToken: "csrf-unavailable-reauth-contract"
      });
    }
    if (route === "/api/matm/human/session/reauth") {
      return response(503, {error: {code: "internal_error", detail: "PRIVATE REAUTH SERVICE CANARY"}});
    }
    throw new Error(`Unexpected route: ${route}`);
  }, {randomKey: () => "reauth-service-test-key-1234567890"});
  const unavailableReauthenticationUi = harness(authenticatedConfig, unavailableReauthenticationTransport);
  unavailableReauthenticationUi.controller.mount();
  await settle();
  unavailableReauthenticationUi.reauthPassword.value = "current-password";
  const unavailableReauthentication = await unavailableReauthenticationUi.controller.reauthenticate();
  assert.deepStrictEqual(unavailableReauthentication, {ok: false, state: api.STATES.REAUTHENTICATION_FAILED, code: "internal_error"});
  assert.strictEqual(unavailableReauthenticationUi.reloads(), 0);
  assert.match(unavailableReauthenticationUi.reauthError.textContent, /password confirmation is temporarily unavailable/i);
  assert(!unavailableReauthenticationUi.reauthError.textContent.includes("CANARY"));
  assert.strictEqual(unavailableReauthenticationUi.reauthPassword.getAttribute("aria-invalid"), null);
  assert.strictEqual(unavailableReauthenticationUi.reauthButton.disabled, false);
}

async function accessibilityInteractionContract() {
  const signedOutConfig = {
    authenticated: false,
    viewState: "signed_out",
    transport: {kind: "same_origin_human_session", protectedNetworkAllowed: true}
  };

  let loginFailureMountRequests = 0;
  const loginFailureUi = harness(Object.assign({}, signedOutConfig, {viewState: "login_failed"}), {
    async request() { loginFailureMountRequests += 1; throw new Error("login-failure mount must not request"); },
    scrub() {}
  });
  loginFailureUi.controller.mount();
  assert.strictEqual(loginFailureMountRequests, 0);
  assert.strictEqual(loginFailureUi.loginUsername.getAttribute("aria-invalid"), "true");
  assert.strictEqual(loginFailureUi.loginPassword.getAttribute("aria-invalid"), "true");
  assert.strictEqual(loginFailureUi.loginPassword.focused, true);
  assert.strictEqual(loginFailureUi.loginError.textContent, api.SAFE_MESSAGES.login_failed);

  let releaseLogin;
  let loginRequests = 0;
  const guardedLoginUi = harness(signedOutConfig, {
    async request(operation) {
      assert.strictEqual(operation, "sessionLogin");
      loginRequests += 1;
      await new Promise((resolve) => { releaseLogin = resolve; });
      throw new api.ConnectorAuthorizationError("human_login_failed", 401);
    },
    scrub() {}
  });
  guardedLoginUi.controller.mount();
  guardedLoginUi.loginUsername.value = "known-owner";
  guardedLoginUi.loginPassword.value = "first-password";
  const firstLogin = guardedLoginUi.controller.login();
  assert.strictEqual(loginRequests, 1);
  assert.strictEqual(guardedLoginUi.loginButton.disabled, true);
  assert.strictEqual(guardedLoginUi.login.getAttribute("aria-busy"), "true");
  assert.strictEqual(guardedLoginUi.controller.getSnapshot().busyAction, "login");
  guardedLoginUi.loginPassword.value = "second-password-must-not-be-consumed";
  const overlappingLogin = await guardedLoginUi.controller.login();
  assert.strictEqual(overlappingLogin.code, "operation_in_progress");
  assert.strictEqual(loginRequests, 1, "overlapping sign-in started a second request");
  assert.strictEqual(guardedLoginUi.loginPassword.value, "second-password-must-not-be-consumed");
  releaseLogin();
  assert.strictEqual((await firstLogin).state, api.STATES.LOGIN_FAILED);
  assert.strictEqual(guardedLoginUi.loginButton.disabled, false);
  assert.strictEqual(guardedLoginUi.login.getAttribute("aria-busy"), null);
  assert.strictEqual(guardedLoginUi.controller.getSnapshot().busyAction, "");
  guardedLoginUi.loginPassword.value = "";

  let releaseHydration;
  let inspectRequests = 0;
  let approvalRequests = 0;
  const pendingConfig = {
    authenticated: true,
    viewState: "pending",
    publicRequestRef: PUBLIC_REQUEST_REF,
    scopeDigest: api.SCOPE_DIGEST,
    transport: {kind: "same_origin_human_session", protectedNetworkAllowed: true}
  };
  const hydrationUi = harness(pendingConfig, {
    async request(operation) {
      if (operation === "sessionInspect") {
        inspectRequests += 1;
        await new Promise((resolve) => { releaseHydration = resolve; });
        return {
          ok: true,
          account: {username: "known-owner"},
          humanSession: {selectedCompanyRef: "companyref_" + "C".repeat(43), passwordReauthenticatedAt: "recent"},
          csrfToken: "csrf-hydration-gate"
        };
      }
      if (operation === "approve") approvalRequests += 1;
      throw new Error(`Unexpected operation: ${operation}`);
    },
    scrub() {}
  });
  hydrationUi.controller.mount();
  assert.strictEqual(inspectRequests, 1);
  assert.strictEqual(hydrationUi.root.getAttribute("aria-busy"), "true");
  for (const button of [hydrationUi.companyButton, hydrationUi.reauthButton, hydrationUi.approveButton, hydrationUi.cancelButton]) {
    assert.strictEqual(button.disabled, true, "authenticated action enabled before CSRF hydration");
  }
  const prematureApproval = await hydrationUi.controller.approve();
  assert.strictEqual(prematureApproval.code, "session_revalidating");
  assert.strictEqual(approvalRequests, 0);
  releaseHydration();
  await settle();
  assert.strictEqual(hydrationUi.controller.getSnapshot().sessionReady, true);
  assert.strictEqual(hydrationUi.root.getAttribute("aria-busy"), null);
  for (const button of [hydrationUi.companyButton, hydrationUi.reauthButton, hydrationUi.approveButton, hydrationUi.cancelButton]) {
    assert.strictEqual(button.disabled, false, "authenticated action stayed disabled after CSRF hydration");
  }

  const failureConfig = Object.assign({}, pendingConfig, {
    viewState: "reauthentication_failed",
    transport: {kind: "mock_browser_session", protectedNetworkAllowed: false}
  });
  const failureDemo = api.createDemoTransport();
  const failureUi = harness(failureConfig, failureDemo);
  failureUi.controller.mount();
  assert.strictEqual(failureUi.reauthButton.disabled, true);
  assert.strictEqual(failureUi.reauthPassword.getAttribute("aria-invalid"), "true");
  assert.strictEqual(failureUi.reauthPassword.focused, true);
  assert.strictEqual(failureUi.reauthError.textContent, api.SAFE_MESSAGES.reauthentication_failed);
  await settle();
  assert.strictEqual(failureUi.controller.getSnapshot().sessionReady, true);
  assert.strictEqual(failureUi.controller.getSnapshot().csrfAvailable, true);
  assert.strictEqual(failureUi.reauthButton.disabled, false);
  assert.strictEqual(failureUi.reauthError.textContent, api.SAFE_MESSAGES.reauthentication_failed);
  failureUi.reauthPassword.value = "current-password";
  assert.strictEqual((await failureUi.controller.reauthenticate()).ok, true, "server-rendered reauthentication failure was not retryable");
  assert.deepStrictEqual(failureUi.demoStateNavigations, ["/tour/connect/authorize/pending"]);

  const companyDemo = api.createDemoTransport({companySelected: false});
  const companyUi = harness(Object.assign({}, pendingConfig, {
    viewState: "company_selection",
    transport: {kind: "mock_browser_session", protectedNetworkAllowed: false}
  }), companyDemo);
  companyUi.controller.mount();
  await settle();
  companyUi.companyRef.value = "";
  const missingCompany = await companyUi.controller.selectCompany();
  assert.strictEqual(missingCompany.code, "company_selection_required");
  assert.strictEqual(companyDemo.inspect().calls.some((call) => call.operation === "membershipSelect"), false);
  assert.strictEqual(companyUi.companyRef.getAttribute("aria-invalid"), "true");
  assert.strictEqual(companyUi.companyRef.focused, true);
  assert.match(companyUi.companyError.textContent, /choose one linked company/i);

  const consentDemo = api.createDemoTransport({recentlyReauthenticated: true});
  const consentUi = harness(Object.assign({}, pendingConfig, {
    transport: {kind: "mock_browser_session", protectedNetworkAllowed: false}
  }), consentDemo);
  consentUi.controller.mount();
  await settle();
  consentUi.canonical.checked = false;
  let missingConsent = await consentUi.controller.approve();
  assert.strictEqual(missingConsent.code, "canonical_agent_approval_required");
  assert.strictEqual(consentDemo.inspect().calls.some((call) => call.operation === "approve"), false);
  assert.strictEqual(consentUi.canonical.getAttribute("aria-invalid"), "true");
  assert.strictEqual(consentUi.canonical.focused, true);
  assert.match(consentUi.canonicalError.textContent, /fixed LocalEndpoint Agent identity/i);
  assert.strictEqual(consentUi.validationSummary.textContent, consentUi.canonicalError.textContent);
  consentUi.canonical.checked = true;
  consentUi.scopeImpact.checked = false;
  missingConsent = await consentUi.controller.approve();
  assert.strictEqual(missingConsent.code, "scope_impact_approval_required");
  assert.strictEqual(consentUi.canonical.getAttribute("aria-invalid"), null);
  assert.strictEqual(consentUi.canonicalError.textContent, "");
  assert.strictEqual(consentUi.scopeImpact.getAttribute("aria-invalid"), "true");
  assert.strictEqual(consentUi.scopeImpact.focused, true);
  assert.match(consentUi.scopeError.textContent, /four listed capability impacts/i);

  function keyboardEvent(target, options) {
    options = options || {};
    return {
      target,
      key: options.key || "Enter",
      keyCode: options.keyCode || 13,
      defaultPrevented: false,
      repeat: Boolean(options.repeat),
      isComposing: Boolean(options.isComposing),
      preventDefault() { this.defaultPrevented = true; }
    };
  }
  function dispatch(ui, name, event) {
    for (const handler of ui.root.listeners[name] || []) handler(event);
  }

  const keyboardLoginDemo = api.createDemoTransport();
  const keyboardLoginUi = harness({
    authenticated: false,
    viewState: "signed_out",
    transport: {kind: "mock_browser_session", protectedNetworkAllowed: false}
  }, keyboardLoginDemo);
  keyboardLoginUi.controller.mount();
  keyboardLoginUi.loginUsername.value = "mock-owner";
  keyboardLoginUi.loginPassword.value = "keyboard-password";
  const composingEnter = keyboardEvent(keyboardLoginUi.loginPassword, {isComposing: true});
  const repeatedEnter = keyboardEvent(keyboardLoginUi.loginPassword, {repeat: true});
  dispatch(keyboardLoginUi, "keydown", composingEnter);
  dispatch(keyboardLoginUi, "keydown", repeatedEnter);
  assert.strictEqual(composingEnter.defaultPrevented, false);
  assert.strictEqual(repeatedEnter.defaultPrevented, false);
  assert.strictEqual(keyboardLoginDemo.inspect().calls.some((call) => call.operation === "sessionLogin"), false);
  const normalEnter = keyboardEvent(keyboardLoginUi.loginPassword);
  dispatch(keyboardLoginUi, "keydown", normalEnter);
  assert.strictEqual(normalEnter.defaultPrevented, true);
  await settle();
  assert.strictEqual(keyboardLoginDemo.inspect().calls.filter((call) => call.operation === "sessionLogin").length, 1);

  const cancelDemo = api.createDemoTransport({recentlyReauthenticated: true});
  const cancelUi = harness(Object.assign({}, pendingConfig, {
    transport: {kind: "mock_browser_session", protectedNetworkAllowed: false}
  }), cancelDemo);
  cancelUi.controller.mount();
  await settle();
  const cancelEnter = keyboardEvent(cancelUi.cancelButton);
  dispatch(cancelUi, "keydown", cancelEnter);
  assert.strictEqual(cancelEnter.defaultPrevented, false, "Enter on Cancel was intercepted as approval");
  assert.strictEqual(cancelDemo.inspect().calls.some((call) => call.operation === "approve"), false);
  const cancelClick = {target: cancelUi.cancelButton, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }};
  dispatch(cancelUi, "click", cancelClick);
  assert.strictEqual(cancelClick.defaultPrevented, true);
  await settle();
  assert.strictEqual(cancelDemo.inspect().calls.filter((call) => call.operation === "cancel").length, 1);
  assert.strictEqual(cancelDemo.inspect().calls.some((call) => call.operation === "approve"), false, "keyboard Cancel approved the request");
}

async function demoAndControllerContract() {
  const config = {authenticated: true, publicRequestRef: PUBLIC_REQUEST_REF, scopeDigest: api.SCOPE_DIGEST, transport: {kind: "mock_browser_session", protectedNetworkAllowed: false}};
  const demo = api.createDemoTransport();
  const ui = harness(config, demo);
  ui.controller.mount();
  await settle();
  assert.strictEqual(ui.controller.getSnapshot().state, api.STATES.REAUTH_REQUIRED);
  ui.reauthPassword.value = "REAUTH-PASSWORD-CANARY-123";
  const reauth = ui.controller.reauthenticate();
  assert.strictEqual(ui.reauthPassword.value, "", "reauth password was not cleared synchronously");
  assert.strictEqual((await reauth).ok, true);
  assert.strictEqual(ui.controller.getSnapshot().state, api.STATES.READY);
  assert.strictEqual(ui.controller.getSnapshot().csrfAvailable, false);
  assert.strictEqual(ui.controller.getSnapshot().protectedIdentifiersRetained, false);
  assert.strictEqual(ui.root.children.length, 0, "reauthentication transition retained its renderer DOM");
  assert.deepStrictEqual(ui.demoStateNavigations, ["/tour/connect/authorize/pending"]);
  assert.deepStrictEqual(ui.navigations, [], "reauthentication attempted external wake navigation");

  const approvalDemo = api.createDemoTransport({recentlyReauthenticated: true});
  const approvalUi = harness(Object.assign({}, config, {viewState: "pending"}), approvalDemo);
  approvalUi.controller.mount();
  await settle();
  const approved = await approvalUi.controller.approve();
  assert.strictEqual(approved.ok, true);
  assert.strictEqual(approvalUi.controller.getSnapshot().state, api.STATES.APPROVED);
  assert.strictEqual(approvalUi.navigations.length, 0, "approval attempted automatic desktop navigation");
  assert.deepStrictEqual(approvalUi.demoStateNavigations, ["/tour/connect/authorize/approved"]);
  assert.strictEqual(approvalUi.controller.getSnapshot().csrfAvailable, false);
  assert.strictEqual(approvalUi.controller.getSnapshot().protectedIdentifiersRetained, false);
  assert.strictEqual(approvalUi.controller.getSnapshot().wakeUpAvailable, false);
  assert.strictEqual(approvalUi.root.children.length, 0, "approval transition retained pending DOM");
  const approvedCall = approvalDemo.inspect().calls.find((call) => call.operation === "approve");
  assert.deepStrictEqual(approvedCall.bodyKeys, ["approvedScopes", "canonicalAgentApproved", "schemaVersion", "workspaceSelection"]);
  assert.strictEqual(approvalDemo.inspect().networkRequestCount, 0);
  assert(!JSON.stringify(demo.inspect()).includes("REAUTH-PASSWORD-CANARY"));
  assert.strictEqual(approvalUi.controller.returnToDesktop().ok, false, "scrubbed pending controller retained a wake target");

  const resetDemo = api.createDemoTransport({recentlyReauthenticated: true});
  const resetUi = harness(config, resetDemo);
  resetUi.controller.mount();
  await settle();
  assert.strictEqual(resetUi.controller.resetDemo().ok, true);
  assert.strictEqual(resetUi.controller.getSnapshot().csrfAvailable, false);
  assert.strictEqual(resetUi.controller.getSnapshot().protectedIdentifiersRetained, false);
  assert.strictEqual(resetUi.root.children.length, 0, "Demo reset retained request-bound DOM");
  assert.strictEqual(resetUi.controller.getSnapshot().state, api.STATES.SIGNED_OUT);
  assert.deepStrictEqual(resetUi.demoStateNavigations, ["/tour/connect/authorize/signed_out"]);
  assert.deepStrictEqual(resetUi.navigations, [], "Demo reset attempted external wake navigation");

  const cancelDemo = api.createDemoTransport({recentlyReauthenticated: true});
  const cancelUi = harness(config, cancelDemo);
  cancelUi.controller.mount();
  await settle();
  const canceled = await cancelUi.controller.cancel();
  assert.strictEqual(canceled.canceled, true);
  assert.strictEqual(cancelUi.controller.getSnapshot().state, api.STATES.CANCELED);
  assert.strictEqual(cancelUi.controller.getSnapshot().csrfAvailable, false);
  assert.strictEqual(cancelUi.controller.getSnapshot().protectedIdentifiersRetained, false);
  assert.strictEqual(cancelUi.root.children.length, 0, "cancel retained request-bound DOM");
  assert.strictEqual(cancelUi.returnAction.getAttribute("href"), null, "cancel retained the parameter-free wake target");
  assert.deepStrictEqual(cancelUi.demoStateNavigations, ["/tour/connect/authorize/canceled"]);
  assert.deepStrictEqual(cancelUi.navigations, [], "cancel attempted external wake navigation");
  assert.strictEqual(cancelDemo.inspect().networkRequestCount, 0);

  const selectDemo = api.createDemoTransport({plans: {sessionInspect: {payload: {
    ok: true,
    account: {username: "mock-owner"},
    humanSession: {selectedCompanyRef: "", passwordReauthenticatedAt: null},
    csrfToken: "MOCK CSRF - NOT A CREDENTIAL",
    mockData: true
  }}}});
  const selectionUi = harness(config, selectDemo);
  selectionUi.controller.mount();
  await settle();
  assert.strictEqual(selectionUi.controller.getSnapshot().state, api.STATES.COMPANY_SELECTION);
  assert.strictEqual((await selectionUi.controller.selectCompany()).ok, true);
  assert.strictEqual(selectionUi.controller.getSnapshot().state, api.STATES.REAUTH_REQUIRED);
  assert.strictEqual(selectionUi.controller.getSnapshot().csrfAvailable, false);
  assert.strictEqual(selectionUi.controller.getSnapshot().protectedIdentifiersRetained, false);
  assert.strictEqual(selectionUi.root.children.length, 0, "company transition retained its selector DOM");
  assert.deepStrictEqual(selectionUi.demoStateNavigations, ["/tour/connect/authorize/reauth_required"]);
  assert.deepStrictEqual(selectionUi.navigations, [], "company transition attempted external wake navigation");
  assert.strictEqual(selectDemo.inspect().networkRequestCount, 0);
  const selectionCall = selectDemo.inspect().calls.find((call) => call.operation === "membershipSelect");
  assert.deepStrictEqual(selectionCall.bodyKeys, ["companyRef", "schemaVersion"]);

  const staleDemo = api.createDemoTransport({plans: {sessionInspect: {payload: {
    ok: true,
    account: {username: "mock-owner"},
    humanSession: {selectedCompanyRef: "companyref_" + "C".repeat(43), passwordReauthenticatedAt: null},
    csrfToken: "MOCK CSRF - NOT A CREDENTIAL",
    mockData: true
  }}}});
  const staleUi = harness(Object.assign({}, config, {viewState: "pending"}), staleDemo);
  staleUi.controller.mount();
  await settle();
  assert.strictEqual(staleUi.controller.getSnapshot().state, api.STATES.REAUTH_REQUIRED, "stale pending markup overrode the fresh reauthentication state");

  let keyCount = 0;
  const retryDemo = api.createDemoTransport({
    recentlyReauthenticated: true,
    plans: {approve: [
      {lostResponse: true},
      {payload: {
        ok: true,
        schemaVersion: SCHEMA,
        status: "approved_awaiting_connector_claim",
        approvedScopes: SCOPES,
        scopeDigest: EXPECTED_SCOPE_DIGEST,
        wakeUpUrl: WAKE_UP_URL,
        mockData: true
      }}
    ]}
  });
  const retryUi = harness(config, retryDemo, {
    randomKey() { keyCount += 1; return "mock-approval-idempotency-key-" + keyCount; }
  });
  retryUi.controller.mount();
  await settle();
  assert.strictEqual((await retryUi.controller.approve()).ok, false);
  assert.strictEqual((await retryUi.controller.approve()).ok, true);
  assert.strictEqual(keyCount, 1, "lost-response retry did not reuse the logical approval idempotency key");
  assert(retryDemo.inspect().calls.filter((call) => call.operation === "approve").every((call) => call.idempotencyPresent));
  assert.strictEqual(retryUi.navigations.length, 0);
  assert.strictEqual(retryDemo.inspect().networkRequestCount, 0);

  const signedOutConfig = {authenticated: false, transport: {kind: "mock_browser_session", protectedNetworkAllowed: false}};
  const enrollmentDemo = api.createDemoTransport();
  const enrollmentUi = harness(signedOutConfig, enrollmentDemo);
  enrollmentUi.controller.mount();
  assert.strictEqual(enrollmentUi.account.hidden, true, "account fields were visible before company-master proof");
  for (const item of [enrollmentUi.accountUsername, enrollmentUi.accountPassword, enrollmentUi.accountConfirmation, enrollmentUi.accountCreateButton]) {
    assert.strictEqual(item.disabled, true, "account creation control was enabled before company-master proof");
  }
  const prematureAccount = await enrollmentUi.controller.completeEnrollment();
  assert.strictEqual(prematureAccount.ok, false);
  assert.strictEqual(enrollmentDemo.inspect().calls.some((call) => call.operation === "accountCreate"), false);
  assert.strictEqual(enrollmentUi.account.hidden, true);
  enrollmentUi.master.value = "RAW-MASTER-CANARY-1234567890";
  const proof = enrollmentUi.controller.beginEnrollment();
  assert.strictEqual(enrollmentUi.master.value, "", "master token was not cleared synchronously");
  assert.strictEqual((await proof).ok, true);
  assert.strictEqual(enrollmentUi.account.hidden, false, "account fields stayed hidden after company-master proof");
  for (const item of [enrollmentUi.accountUsername, enrollmentUi.accountPassword, enrollmentUi.accountConfirmation, enrollmentUi.accountCreateButton]) {
    assert.strictEqual(item.disabled, false, "account creation control stayed disabled after company-master proof");
  }
  assert.strictEqual(enrollmentUi.accountUsername.focused, true, "new username was not focused after company-master proof");
  enrollmentUi.accountPassword.value = "ACCOUNT-PASSWORD-CANARY-123";
  enrollmentUi.accountConfirmation.value = "ACCOUNT-PASSWORD-CANARY-123";
  const created = enrollmentUi.controller.completeEnrollment();
  assert.strictEqual(enrollmentUi.accountPassword.value, "", "account password was not cleared synchronously");
  assert.strictEqual(enrollmentUi.accountConfirmation.value, "", "password confirmation was not cleared synchronously");
  assert.strictEqual((await created).ok, true);
  assert.strictEqual(enrollmentUi.controller.getSnapshot().state, api.STATES.REAUTH_REQUIRED);
  assert.strictEqual(enrollmentUi.controller.getSnapshot().csrfAvailable, false);
  assert.strictEqual(enrollmentUi.controller.getSnapshot().protectedIdentifiersRetained, false);
  assert.strictEqual(enrollmentUi.root.children.length, 0, "account transition retained preauthentication DOM");
  assert.deepStrictEqual(enrollmentUi.demoStateNavigations, ["/tour/connect/authorize/reauth_required"]);
  assert.deepStrictEqual(enrollmentUi.navigations, [], "account transition attempted external wake navigation");
  const retained = JSON.stringify(enrollmentDemo.inspect());
  assert(!retained.includes("RAW-MASTER-CANARY"));
  assert(!retained.includes("ACCOUNT-PASSWORD-CANARY"));
  assert.deepStrictEqual(
    enrollmentDemo.inspect().calls.slice(0, 2).map((call) => call.operation),
    ["masterProof", "accountCreate"]
  );
  assert.strictEqual(enrollmentDemo.inspect().networkRequestCount, 0);

  const weakAccountDemo = api.createDemoTransport();
  const weakAccountUi = harness(signedOutConfig, weakAccountDemo);
  weakAccountUi.controller.mount();
  assert.strictEqual((await weakAccountUi.controller.beginEnrollment({companyMasterTokenSecret: "MOCK-MASTER-FOR-POLICY-1234567890"})).ok, true);
  weakAccountUi.accountPassword.value = "x";
  weakAccountUi.accountConfirmation.value = "x";
  const weakAccount = await weakAccountUi.controller.completeEnrollment();
  assert.strictEqual(weakAccount.code, "account_password_invalid", "new-account password strength policy was not enforced");
  assert.strictEqual(weakAccountDemo.inspect().calls.some((call) => call.operation === "accountCreate"), false);
  assert.strictEqual(weakAccountUi.accountPassword.value, "");
  assert.strictEqual(weakAccountUi.accountConfirmation.value, "");
  assert.strictEqual(weakAccountUi.account.hidden, false, "local account validation unnecessarily discarded the verified master proof");
  assert.strictEqual(weakAccountUi.accountPassword.getAttribute("aria-invalid"), "true");
  assert.strictEqual(weakAccountUi.accountPassword.focused, true);
  assert.match(weakAccountUi.enrollmentError.textContent, /at least 15 characters/i);
  weakAccountUi.accountPassword.value = "HIDDEN-PASSWORD-CANARY-123";
  weakAccountUi.accountConfirmation.value = "HIDDEN-PASSWORD-CANARY-123";
  const invalidatedProof = await weakAccountUi.controller.beginEnrollment({companyMasterTokenSecret: "too-short"});
  assert.strictEqual(invalidatedProof.code, "company_master_input_invalid");
  assert.strictEqual(weakAccountUi.controller.getSnapshot().proofReady, false);
  assert.strictEqual(weakAccountUi.account.hidden, true);
  assert.strictEqual(weakAccountUi.accountPassword.value, "", "invalidating account proof retained a hidden password");
  assert.strictEqual(weakAccountUi.accountConfirmation.value, "", "invalidating account proof retained a hidden password confirmation");

  const uncertainAccountDemo = api.createDemoTransport({plans: {
    accountCreate: {error: {code: "private_account_result_canary", status: 500}}
  }});
  const uncertainAccountUi = harness(signedOutConfig, uncertainAccountDemo);
  uncertainAccountUi.controller.mount();
  assert.strictEqual((await uncertainAccountUi.controller.beginEnrollment({companyMasterTokenSecret: "MOCK-MASTER-FOR-UNCERTAIN-RESULT-1234567890"})).ok, true);
  uncertainAccountUi.accountPassword.value = "UNCERTAIN-ACCOUNT-PASSWORD-123";
  uncertainAccountUi.accountConfirmation.value = "UNCERTAIN-ACCOUNT-PASSWORD-123";
  const uncertainAccount = await uncertainAccountUi.controller.completeEnrollment();
  assert.strictEqual(uncertainAccount.code, "private_account_result_canary");
  assert.match(uncertainAccountUi.enrollmentError.textContent, /could not be confirmed/i);
  assert.match(uncertainAccountUi.enrollmentError.textContent, /reload this page/i);
  assert(!uncertainAccountUi.enrollmentError.textContent.includes("canary"));
  assert(!uncertainAccountUi.enrollmentError.textContent.includes("Nothing was created"));

  const bfcacheDemo = api.createDemoTransport({recentlyReauthenticated: true});
  const bfcacheUi = harness(config, bfcacheDemo);
  bfcacheUi.controller.mount();
  await settle();
  const hideHandlers = bfcacheUi.lifecycle.pagehide || [];
  assert.strictEqual(hideHandlers.length, 1);
  hideHandlers[0]({persisted: true});
  assert.strictEqual(bfcacheUi.controller.getSnapshot().state, api.STATES.SCRUBBED);
  assert.strictEqual(bfcacheUi.controller.getSnapshot().csrfAvailable, false);
  assert.strictEqual(bfcacheUi.controller.getSnapshot().protectedIdentifiersRetained, false);
  assert.strictEqual(bfcacheUi.root.children.length, 0, "protected DOM was retained for BFCache restoration");
  const showHandlers = bfcacheUi.lifecycle.pageshow || [];
  assert.strictEqual(showHandlers.length, 1);
  showHandlers[0]({persisted: true});
  await settle();
  assert.strictEqual(bfcacheUi.reloads(), 1, "persisted Demo page was left blank instead of reloading its explicit route");
  assert.strictEqual(bfcacheUi.navigations.length, 0, "BFCache recovery attempted external wake navigation");
  assert.strictEqual(bfcacheDemo.inspect().networkRequestCount, 0, "BFCache recovery made a protected Demo request");
}

function validationContract() {
  assert.deepStrictEqual(api.REQUESTED_SCOPES, SCOPES);
  assert.deepStrictEqual(api.SCOPE_IMPACT_LABELS, SCOPE_LABELS);
  assert.strictEqual(api.SCOPE_DIGEST, EXPECTED_SCOPE_DIGEST);
  assert.match(api.SCOPE_DIGEST, /^sha256-v1:[a-f0-9]{64}$/);
  const validConfig = {
    authenticated: true,
    publicRequestRef: PUBLIC_REQUEST_REF,
    scopeDigest: EXPECTED_SCOPE_DIGEST,
    transport: {kind: "same_origin_human_session", protectedNetworkAllowed: true}
  };
  assert.deepStrictEqual(api.validateConfig(validConfig), validConfig);
  assert.throws(() => api.validateConfig(Object.assign({}, validConfig, {scopeDigest: "sha256-v1:" + "0".repeat(64)})), (error) => error.code === "scope_digest_invalid");
  assert.throws(() => api.validateConfig(Object.assign({}, validConfig, {publicRequestRef: "internal-request-id"})), (error) => error.code === "public_request_ref_invalid");
  assert.throws(() => api.validateConfig(Object.assign({}, validConfig, {workspaceId: "internal-workspace"})), (error) => error.code === "config_field_invalid");
  assert.throws(
    () => api.validateConfig(Object.assign({}, validConfig, {transport: Object.assign({}, validConfig.transport, {unexpectedPrivateField: "canary"})})),
    (error) => error.code === "config_field_invalid"
  );
  assert.throws(
    () => api.validateConfig(Object.assign({}, validConfig, {clientMethods: {approve: "untrusted.method"}})),
    (error) => error.code === "client_config_invalid"
  );
  const neutralTerminal = {authenticated: true, viewState: "canceled", transport: {kind: "same_origin_human_session", protectedNetworkAllowed: true}};
  assert.deepStrictEqual(api.validateConfig(neutralTerminal), neutralTerminal);
  assert.throws(
    () => api.validateConfig(Object.assign({}, neutralTerminal, {publicRequestRef: PUBLIC_REQUEST_REF, scopeDigest: EXPECTED_SCOPE_DIGEST})),
    (error) => error.code === "config_field_invalid"
  );
  assert.throws(
    () => api.validateConfig({authenticated: true, viewState: "pending", transport: {kind: "same_origin_human_session", protectedNetworkAllowed: true}}),
    (error) => error.code === "public_request_ref_invalid"
  );
  const loginFailure = {authenticated: false, viewState: "login_failed", transport: {kind: "same_origin_human_session", protectedNetworkAllowed: true}};
  assert.deepStrictEqual(api.validateConfig(loginFailure), loginFailure);
  const reauthenticationFailure = Object.assign({}, validConfig, {viewState: "reauthentication_failed"});
  assert.deepStrictEqual(api.validateConfig(reauthenticationFailure), reauthenticationFailure);
  for (const viewState of ["authorization_issued", "credential_prepared", "activated"]) {
    const postApproval = {authenticated: true, viewState, transport: {kind: "same_origin_human_session", protectedNetworkAllowed: true}};
    assert.deepStrictEqual(api.validateConfig(postApproval), postApproval);
    assert.throws(
      () => api.validateConfig(Object.assign({}, postApproval, {publicRequestRef: PUBLIC_REQUEST_REF, scopeDigest: EXPECTED_SCOPE_DIGEST})),
      (error) => error.code === "config_field_invalid"
    );
  }
  const legacyDemoAliases = {
    authorization_received: "authorization_issued",
    credential_delivered: "credential_prepared",
    connected: "activated"
  };
  for (const [legacyState, canonicalState] of Object.entries(legacyDemoAliases)) {
    const legacy = {
      authenticated: true,
      viewState: legacyState,
      transport: {kind: "mock_browser_session", protectedNetworkAllowed: false}
    };
    assert.deepStrictEqual(
      api.validateConfig(legacy),
      Object.assign({}, legacy, {viewState: canonicalState})
    );
    assert.throws(
      () => api.validateConfig({
        authenticated: true,
        viewState: legacyState,
        transport: {kind: "same_origin_human_session", protectedNetworkAllowed: true}
      }),
      (error) => error.code === "view_state_invalid"
    );
  }
  assert.strictEqual(api.STATES.AUTHORIZATION_RECEIVED, api.STATES.AUTHORIZATION_ISSUED);
  assert.strictEqual(api.STATES.CREDENTIAL_DELIVERED, api.STATES.CREDENTIAL_PREPARED);
  assert.strictEqual(api.STATES.CONNECTED, api.STATES.ACTIVATED);
  assert.deepStrictEqual(
    api.validateCompanySelection({companyRef: "companyref_" + "C".repeat(43)}),
    {schemaVersion: SCHEMA, companyRef: "companyref_" + "C".repeat(43)}
  );
  assert.throws(
    () => api.validateCompanySelection({companyRef: ""}),
    (error) => error.code === "company_selection_required" && error.status === 422
  );
  assert.throws(
    () => api.validateCompanySelection({companyRef: "company-internal-id"}),
    (error) => error.code === "company_ref_invalid"
  );
  assert.deepStrictEqual(
    api.validateApproval({workspaceMode: "existing", workspaceRef: WORKSPACE_REF, canonicalAgentApproved: true, scopeImpactApproved: true}),
    {schemaVersion: SCHEMA, canonicalAgentApproved: true, approvedScopes: SCOPES, workspaceSelection: {mode: "existing", workspaceRef: WORKSPACE_REF}}
  );
  assert.deepStrictEqual(
    api.validateApproval({workspaceMode: "new", workspaceLabel: "Connector Workspace", canonicalAgentApproved: true, scopeImpactApproved: true}),
    {schemaVersion: SCHEMA, canonicalAgentApproved: true, approvedScopes: SCOPES, workspaceSelection: {mode: "new", workspaceLabel: "Connector Workspace", projectLabel: "LocalEndpoint Pairing"}}
  );
  assert.throws(() => api.validateApproval({workspaceMode: "existing", workspaceRef: WORKSPACE_REF, canonicalAgentApproved: false, scopeImpactApproved: true}), (error) => error.code === "canonical_agent_approval_required");
  assert.throws(() => api.validateApproval({workspaceMode: "existing", workspaceRef: WORKSPACE_REF, canonicalAgentApproved: true, scopeImpactApproved: false}), (error) => error.code === "scope_impact_approval_required");
  assert.throws(() => api.validateApproval({workspaceMode: "existing", workspaceRef: WORKSPACE_REF, canonicalAgentApproved: true, scopeImpactApproved: true, approvedScopes: SCOPES.slice(0, 3)}), (error) => error.code === "approved_scopes_invalid");
  assert.throws(() => api.validateApproval({workspaceMode: "existing", workspaceRef: WORKSPACE_REF, canonicalAgentApproved: true, scopeImpactApproved: true, approvedScopes: SCOPES.slice().reverse()}), (error) => error.code === "approved_scopes_invalid");
  assert.throws(() => api.validateApproval({workspaceMode: "existing", workspaceRef: "workspace-internal-id", canonicalAgentApproved: true, scopeImpactApproved: true}), (error) => error.code === "workspace_ref_invalid");
  assert.throws(() => api.validateApproval({workspaceMode: "new", workspaceLabel: "  ", canonicalAgentApproved: true, scopeImpactApproved: true}), (error) => error.code === "workspace_name_invalid");

  assert.strictEqual(api.safeWakeUpUrl(WAKE_UP_URL), WAKE_UP_URL);
  assert.strictEqual(
    api.safeWakeUpUrl("localendpoint-connect://memoryendpoints/callback"),
    "localendpoint-connect://memoryendpoints/callback"
  );
  for (const unsafe of [
    `${WAKE_UP_URL}?code=not-allowed`, `${WAKE_UP_URL}#state`,
    "https://evil.example/callback", "localendpoint-connect://memoryendpoints/callback/"
  ]) assert.throws(() => api.safeWakeUpUrl(unsafe), (error) => error.code === "wake_up_url_invalid");
}

async function explicitProductionReturnContract() {
  const config = {authenticated: true, viewState: "pending", publicRequestRef: PUBLIC_REQUEST_REF, scopeDigest: api.SCOPE_DIGEST, transport: {kind: "same_origin_human_session", protectedNetworkAllowed: true}};
  const navigations = [];
  const transport = {
    async request(operation) {
      if (operation === "sessionInspect") return {ok: true, account: {username: "owner"}, humanSession: {passwordReauthenticatedAt: "recent"}, csrfToken: "csrf-explicit-return"};
      if (operation === "approve") return {
        ok: true,
        schemaVersion: SCHEMA,
        status: "approved_awaiting_connector_claim",
        approvedScopes: SCOPES,
        scopeDigest: EXPECTED_SCOPE_DIGEST,
        wakeUpUrl: WAKE_UP_URL
      };
      throw new Error(`Unexpected operation: ${operation}`);
    },
    scrub() {}
  };
  const ui = harness(config, transport, {navigate(target) { navigations.push(target); }});
  ui.controller.mount();
  await settle();
  assert.strictEqual((await ui.controller.approve()).ok, true);
  assert.deepStrictEqual(navigations, [], "approval automatically navigated to the desktop");
  assert.strictEqual(ui.reloads(), 1, "approved production response did not transition to the server-rendered approved view");
  assert.strictEqual(ui.root.children.length, 0, "approved production transition retained pending DOM");
  assert.strictEqual(ui.controller.getSnapshot().csrfAvailable, false);
  assert.strictEqual(ui.controller.getSnapshot().wakeUpAvailable, false);
  assert.strictEqual(ui.controller.getSnapshot().protectedIdentifiersRetained, false);
  assert.strictEqual(ui.returnAction.getAttribute("href"), null);
  assert.strictEqual(ui.controller.returnToDesktop().ok, false);
}

async function terminalRefreshContract() {
  for (const viewState of ["approved", "replay"]) {
    const config = {authenticated: true, viewState, publicRequestRef: PUBLIC_REQUEST_REF, scopeDigest: api.SCOPE_DIGEST, transport: {kind: "same_origin_human_session", protectedNetworkAllowed: true}};
    const navigations = [];
    const ui = harness(config, {request: async () => { throw new Error("terminal mount must not revalidate"); }, scrub() {}}, {
      navigate(target) { navigations.push(target); },
      terminalWakeUpUrl: "localendpoint-connect://memoryendpoints/callback"
    });
    ui.controller.mount();
    assert.strictEqual(ui.controller.getSnapshot().state, api.STATES[viewState === "approved" ? "APPROVED" : "REPLAY"]);
    assert.strictEqual(ui.controller.getSnapshot().wakeUpAvailable, true);
    assert.deepStrictEqual(navigations, [], "terminal mount automatically opened the desktop");
    assert.strictEqual(ui.controller.returnToDesktop().ok, true);
    assert.deepStrictEqual(navigations, ["localendpoint-connect://memoryendpoints/callback"]);
    (ui.lifecycle.pagehide || [])[0]({persisted: true});
    assert.strictEqual(ui.returnAction.getAttribute("href"), null, "detached terminal anchor retained its wake target");
    assert.strictEqual(ui.controller.getSnapshot().wakeUpAvailable, false);
    assert.strictEqual(ui.controller.getSnapshot().protectedIdentifiersRetained, false);
  }

  const unsafeConfig = {authenticated: true, viewState: "approved", publicRequestRef: PUBLIC_REQUEST_REF, scopeDigest: api.SCOPE_DIGEST, transport: {kind: "same_origin_human_session", protectedNetworkAllowed: true}};
  const unsafe = harness(unsafeConfig, {request: async () => { throw new Error("terminal mount must not revalidate"); }, scrub() {}}, {
    terminalWakeUpUrl: `${WAKE_UP_URL}?state=forbidden`
  });
  unsafe.controller.mount();
  assert.strictEqual(unsafe.controller.getSnapshot().state, api.STATES.ERROR);
  assert.strictEqual(unsafe.controller.getSnapshot().wakeUpAvailable, false);
  assert.strictEqual(unsafe.returnAction.getAttribute("href"), null);
  assert.strictEqual(unsafe.controller.returnToDesktop().ok, false);
  assert.deepStrictEqual(unsafe.navigations, []);

  const demoConfig = {authenticated: true, viewState: "approved", publicRequestRef: PUBLIC_REQUEST_REF, scopeDigest: api.SCOPE_DIGEST, transport: {kind: "mock_browser_session", protectedNetworkAllowed: false}};
  const demo = api.createDemoTransport({recentlyReauthenticated: true});
  const demoUi = harness(demoConfig, demo, {terminalWakeUpUrl: WAKE_UP_URL});
  demoUi.controller.mount();
  assert.strictEqual(demoUi.controller.returnToDesktop().mockNavigationPrevented, true);
  assert.deepStrictEqual(demoUi.navigations, []);
  assert.strictEqual(demo.inspect().networkRequestCount, 0);
}

async function neutralPostApprovalStateContract() {
  const states = {
    authorization_issued: api.STATES.AUTHORIZATION_ISSUED,
    credential_prepared: api.STATES.CREDENTIAL_PREPARED,
    activated: api.STATES.ACTIVATED
  };
  for (const [viewState, expectedState] of Object.entries(states)) {
    let networkRequests = 0;
    const config = {
      authenticated: true,
      viewState,
      transport: {kind: "same_origin_human_session", protectedNetworkAllowed: true}
    };
    const ui = harness(config, {
      async request() { networkRequests += 1; throw new Error("neutral post-approval state must not revalidate"); },
      scrub() {}
    });
    ui.controller.mount();
    await settle();
    assert.strictEqual(ui.controller.getSnapshot().state, expectedState);
    assert.strictEqual(networkRequests, 0, `${viewState} made a protected network request while mounting`);
    assert.strictEqual(ui.reloads(), 0);
    assert.deepStrictEqual(ui.navigations, []);
    assert.strictEqual(ui.controller.getSnapshot().protectedIdentifiersRetained, false);
    assert.strictEqual(ui.controller.getSnapshot().wakeUpAvailable, false);
  }
}

async function sessionExpiryScrubContract() {
  const config = {authenticated: true, viewState: "pending", publicRequestRef: PUBLIC_REQUEST_REF, scopeDigest: api.SCOPE_DIGEST, transport: {kind: "mock_browser_session", protectedNetworkAllowed: false}};
  const demo = api.createDemoTransport({plans: {sessionInspect: {error: {code: "human_session_required", status: 401}}}});
  const ui = harness(config, demo);
  ui.controller.mount();
  await settle();
  assert.strictEqual(ui.controller.getSnapshot().state, api.STATES.SIGNED_OUT);
  assert.strictEqual(ui.controller.getSnapshot().csrfAvailable, false);
  assert.strictEqual(ui.controller.getSnapshot().protectedIdentifiersRetained, false);
  assert.strictEqual(ui.controller.getSnapshot().wakeUpAvailable, false);
  assert.strictEqual(ui.root.children.length, 0, "session expiry retained protected DOM");
  assert.strictEqual(ui.returnAction.getAttribute("href"), null);
  assert.strictEqual(ui.navigations.length, 0, "session expiry attempted external wake navigation");
  assert.deepStrictEqual(ui.demoStateNavigations, ["/tour/connect/authorize/signed_out"]);
  assert.strictEqual(demo.inspect().networkRequestCount, 0);
}

async function main() {
  await scenario(() => validationContract());
  await scenario(() => productionContract());
  await scenario(() => credentialFailureContract());
  await scenario(() => accessibilityInteractionContract());
  await scenario(() => demoAndControllerContract());
  await scenario(() => explicitProductionReturnContract());
  await scenario(() => terminalRefreshContract());
  await scenario(() => neutralPostApprovalStateContract());
  await scenario(() => sessionExpiryScrubContract());
  process.stdout.write(JSON.stringify({
    ok: true,
    sharedController: true,
    productionSameOrigin: true,
    opaquePublicAndWorkspaceRefs: true,
    exactOrderedScopeConsent: true,
    parameterFreeExplicitWakeUp: true,
    zeroNetworkDemo: true,
    rawInputClearing: true,
    bfcacheDomScrub: true,
    scenarioCount,
    assertionCount,
    routeCount: Object.keys(api.ROUTES).length
  }) + "\n");
}

main().catch((error) => {
  process.stderr.write(error.stack || String(error));
  process.exitCode = 1;
});
