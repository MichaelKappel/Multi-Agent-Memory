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
  }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  replaceChildren(...children) { this.children.forEach((item) => { item.parentNode = null; }); this.children = []; children.forEach((item) => this.appendChild(item)); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null; }
  removeAttribute(name) { delete this.attributes[name]; }
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

function container(controls) {
  const item = new Element("div");
  item._controls = controls || [];
  item.querySelector = (selector) => {
    const match = selector.match(/^\[name="([^"]+)"\]$/);
    if (match) return item._controls.find((control) => control.getAttribute("name") === match[1]) || null;
    return null;
  };
  item.querySelectorAll = (selector) => {
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
  const master = namedInput("companyMasterTokenSecret", "MOCK-MASTER-CANARY-1234567890", "password");
  const proof = container([master]);
  const existing = namedInput("workspaceMode", "existing", "radio"); existing.checked = true;
  const createNew = namedInput("workspaceMode", "new", "radio");
  const workspace = namedInput("workspaceRef", WORKSPACE_REF);
  const workspaceLabel = namedInput("workspaceLabel", "");
  const canonical = namedInput("canonicalAgentApproved", "true", "checkbox"); canonical.checked = true;
  const scopeImpact = namedInput("scopeImpactApproved", "true", "checkbox"); scopeImpact.checked = true;
  const approval = container([existing, createNew, workspace, workspaceLabel, canonical, scopeImpact]);
  const reauthPassword = namedInput("password", "A-demo-password-1234", "password");
  const reauth = container([reauthPassword]);
  const companyRef = namedInput("companyRef", "companyref_" + "C".repeat(43));
  const companySelection = container([companyRef]);
  const accountUsername = namedInput("username", "mock-owner-two");
  const accountPassword = namedInput("password", "A-demo-password-9876", "password");
  const accountConfirmation = namedInput("passwordConfirmation", "A-demo-password-9876", "password");
  const account = container([accountUsername, accountPassword, accountConfirmation]);
  const returnAction = new Element("a");
  if (["approved", "replay"].includes(config.viewState)) {
    returnAction.setAttribute("href", controllerOptions && controllerOptions.terminalWakeUpUrl || WAKE_UP_URL);
  }
  const map = new Map([
    ["[data-connector-status]", status],
    ["[data-connector-authorization-config]", configElement],
    ["[data-connector-login]", login],
    ["[data-connector-master-proof]", proof],
    ["[data-connector-approval-form]", approval],
    ["[data-connector-reauth]", reauth],
    ["[data-connector-company-selection]", companySelection],
    ["[data-connector-return-action]", returnAction],
    ['[data-connector-account-create] [name="username"]', accountUsername],
    ['[data-connector-account-create] [name="password"]', accountPassword],
    ['[data-connector-account-create] [name="passwordConfirmation"]', accountConfirmation]
  ]);
  const allControls = [username, loginPassword, master, existing, createNew, workspace, workspaceLabel, canonical, scopeImpact, reauthPassword, companyRef, accountUsername, accountPassword, accountConfirmation];
  root.querySelector = (selector) => map.get(selector) || null;
  root.querySelectorAll = (selector) => selector === "input,select,textarea" ? allControls : [];
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
  return {accountConfirmation, accountPassword, approval, canonical, companyRef, companySelection, controller, demoStateNavigations, lifecycle, loginPassword, master, navigations, reauthPassword, reloads: () => reloads, returnAction, root, scopeImpact, status, workspace, workspaceLabel};
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
  enrollmentUi.master.value = "RAW-MASTER-CANARY-1234567890";
  const proof = enrollmentUi.controller.beginEnrollment();
  assert.strictEqual(enrollmentUi.master.value, "", "master token was not cleared synchronously");
  assert.strictEqual((await proof).ok, true);
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
  assert.deepStrictEqual(
    api.validateCompanySelection({companyRef: "companyref_" + "C".repeat(43)}),
    {schemaVersion: SCHEMA, companyRef: "companyref_" + "C".repeat(43)}
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
  await scenario(() => demoAndControllerContract());
  await scenario(() => explicitProductionReturnContract());
  await scenario(() => terminalRefreshContract());
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
