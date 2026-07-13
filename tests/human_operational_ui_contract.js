"use strict";

const nodeAssert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

let assertionCount = 0;
function assert(value, message) { assertionCount += 1; return nodeAssert(value, message); }
for (const name of ["strictEqual", "notStrictEqual", "deepStrictEqual", "throws"]) {
  assert[name] = function (...args) { assertionCount += 1; return nodeAssert[name](...args); };
}

const scriptPath = process.argv[2];
if (!scriptPath) throw new Error("Usage: node tests/human_operational_ui_contract.js static/js/human-operational.js");
const source = fs.readFileSync(scriptPath, "utf8");
const api = require(path.resolve(scriptPath));

for (const forbidden of [
  "local" + "Storage",
  "session" + "Storage",
  "indexed" + "DB",
  "Web" + "Socket",
  "send" + "Beacon",
  "document" + ".cookie",
  "Author" + "ization",
  "Bear" + "er",
  "workspace" + "Key",
  "company" + "Master",
  "inner" + "HTML",
  "outer" + "HTML"
]) assert(!source.includes(forbidden), `forbidden retention or credential surface: ${forbidden}`);

const expectedRoutes = {
  sessionInspect: ["GET", "/api/matm/human/session"],
  sessionLogout: ["POST", "/api/matm/human/session/logout"],
  companySelect: ["POST", "/api/matm/human/session/company"],
  contextCatalog: ["GET", "/api/matm/human/operational/context-catalog"],
  resourceContextSelect: ["POST", "/api/matm/human/session/resource-context"],
  workspaceRead: ["GET", "/api/matm/human/operational/workspace"],
  memorySearch: ["GET", "/api/matm/human/operational/search"],
  memorySubmit: ["POST", "/api/matm/human/operational/memory-events/submit"],
  knowledgeTree: ["GET", "/api/matm/human/operational/knowledge-tree"],
  knowledgeDocuments: ["GET", "/api/matm/human/operational/knowledge-documents"],
  externalLinks: ["GET", "/api/matm/human/operational/external-links"],
  internetSearch: ["GET", "/api/matm/human/operational/internet-search"]
};
assert.deepStrictEqual(Object.keys(api.ROUTES).sort(), Object.keys(expectedRoutes).sort());
for (const [name, [method, route]] of Object.entries(expectedRoutes)) {
  assert.strictEqual(api.ROUTES[name].method, method);
  assert.strictEqual(api.ROUTES[name].path, route);
}
for (const forbiddenOperation of ["sync", "review", "meeting", "routing", "message", "receipt", "audit", "history", "export", "lifecycle"]) {
  assert(!Object.keys(api.OPERATION_MAP).some((name) => name.toLowerCase().includes(forbiddenOperation)));
}
assert.deepStrictEqual(api.ALLOWED_RETURN_PATHS, ["/human", "/console", "/knowledge"]);
assert.deepStrictEqual(Object.values(api.PERMISSIONS).sort(), [
  "canReadOperationalExternalLinks",
  "canReadOperationalKnowledge",
  "canReadOperationalWorkspace",
  "canSearchOperationalInternet",
  "canSearchOperationalMemory",
  "canSubmitOperationalMemory"
].sort());

const expectedSelectors = {
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
};
assert.deepStrictEqual(api.SELECTORS, expectedSelectors);

class Element {
  constructor(tagName, documentRef) {
    this.tagName = String(tagName || "div").toUpperCase();
    this.ownerDocument = documentRef;
    this.children = [];
    this.parentNode = null;
    this.attributes = {};
    this.dataset = {};
    this.listeners = {};
    this.hidden = false;
    this.inert = false;
    this.textContent = "";
    this.value = "";
    this.checked = false;
    this.selectedIndex = 0;
    this.open = false;
    this.elements = {};
  }
  get firstChild() { return this.children[0] || null; }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index >= 0) this.children.splice(index, 1);
    child.parentNode = null;
    return child;
  }
  replaceChildren(...children) { this.children = []; children.forEach((child) => this.appendChild(child)); }
  setAttribute(name, value) { this.attributes[name] = String(value); if (name === "open") this.open = true; }
  getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null; }
  hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attributes, name); }
  removeAttribute(name) { delete this.attributes[name]; if (name === "open") this.open = false; }
  addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
  removeEventListener(type, listener) { this.listeners[type] = (this.listeners[type] || []).filter((item) => item !== listener); }
  dispatch(type, values) {
    const event = Object.assign({target: this, preventDefault() { this.defaultPrevented = true; }}, values || {});
    for (const listener of this.listeners[type] || []) listener(event);
    return event;
  }
  close() { this.open = false; delete this.attributes.open; }
}

class DocumentRef {
  createElement(tagName) { return new Element(tagName, this); }
}

function createWindow() {
  const listeners = {};
  const navigations = [];
  return {
    listeners,
    navigations,
    location: {assign(value) { navigations.push(value); }},
    addEventListener(type, listener) { (listeners[type] ||= []).push(listener); },
    removeEventListener(type, listener) { listeners[type] = (listeners[type] || []).filter((item) => item !== listener); },
    dispatch(type, values) { for (const listener of listeners[type] || []) listener(Object.assign({persisted: false}, values || {})); }
  };
}

function createHarness(options) {
  options = options || {};
  const documentRef = new DocumentRef();
  const windowRef = createWindow();
  const root = new Element("section", documentRef);
  root.setAttribute("data-human-operational-surface", options.surface || "console");
  root.setAttribute("data-human-operational-return-path", options.returnPath || (options.surface === "knowledge" ? "/knowledge" : "/console"));
  if (options.demoMode !== false) root.setAttribute("data-human-operational-demo", "");

  const elements = {};
  for (const name of Object.keys(expectedSelectors).filter((name) => !["root", "privateOutput"].includes(name))) {
    const tag = name.endsWith("Form") ? "form" : (name.endsWith("Select") ? "select" : (name === "logout" || name === "retry" || name === "demoReset" ? "button" : "div"));
    elements[name] = new Element(tag, documentRef);
  }
  const privateInput = new Element("input", documentRef);
  const privateTextarea = new Element("textarea", documentRef);
  const privateOutput = new Element("div", documentRef);
  const privatePre = new Element("pre", documentRef);
  const dialog = new Element("dialog", documentRef);
  const selectorMap = new Map();
  for (const [name, selector] of Object.entries(expectedSelectors)) {
    if (name === "root") selectorMap.set(selector, root);
    else if (name === "privateOutput") selectorMap.set(selector, privateOutput);
    else selectorMap.set(selector, elements[name]);
  }
  root.querySelector = (selector) => selectorMap.get(selector) || null;
  root.querySelectorAll = (selector) => {
    if (selector === "input, textarea") return [privateInput, privateTextarea];
    if (selector === "select") return [elements.authoritySelect, elements.workspaceSelect, elements.projectSelect];
    if (selector === expectedSelectors.privateOutput) return [privateOutput];
    if (selector === "pre") return [privatePre];
    if (selector === "dialog") return [dialog];
    return [];
  };

  let transport = options.transport;
  if (!transport) {
    const testTransport = api.createDemoTransport({plans: options.plans || {}});
    transport = options.demoMode === false ? Object.freeze({
      request: testTransport.request,
      setPlan: testTransport.setPlan,
      setPermission: testTransport.setPermission,
      reset: testTransport.reset,
      inspect: testTransport.inspect
    }) : testTransport;
  }
  const rendererState = {privateRows: [], scrubCount: 0, contextCount: 0, resultCount: 0};
  const adapter = api.createIntegrationAdapter(Object.assign({
    scrub() { rendererState.privateRows = []; rendererState.scrubCount += 1; },
    contextChanged() { rendererState.contextCount += 1; },
    operationResult() { rendererState.resultCount += 1; }
  }, options.adapterOverrides || {}));
  const controller = api.create({
    root,
    surface: options.surface || "console",
    returnPath: options.returnPath,
    documentRef,
    windowRef,
    transport,
    adapter,
    demoMode: options.demoMode !== false,
    autoRevalidate: false,
    navigate(value) { windowRef.navigations.push(value); }
  });
  return {root, elements, privateInput, privateTextarea, privateOutput, privatePre, dialog, documentRef, windowRef, transport, rendererState, controller};
}

async function settle(turns = 16) {
  for (let index = 0; index < turns; index += 1) await Promise.resolve();
}

async function expectCode(promise, code) {
  let captured = null;
  try { await promise; } catch (error) { captured = error; }
  assert(captured, `expected ${code} rejection`);
  assert.strictEqual(captured.code, code);
  assert.strictEqual(captured.safeNoOp, true);
  assert.strictEqual(captured.rawCredentialExposed, false);
  assert.strictEqual(captured.rawPayloadExposed, false);
  return captured;
}

async function chooseCompany(harness, authorityId = "mock-authority-alpha") {
  await harness.controller.selectCompany(authorityId);
  return harness.controller.getSnapshot();
}

async function makeReady(harness, projectId = "") {
  await harness.controller.mount();
  await harness.controller.revalidate();
  await chooseCompany(harness);
  await harness.controller.selectResource("mock-workspace-memory", projectId);
  return harness.controller.getSnapshot();
}

async function main() {
  let scenarios = 0;

  const routeAdapter = api.createRouteAdapter();
  assert.throws(() => routeAdapter.resolve("meetingMessages", {}), (error) => error.code === "unknown_operation");
  assert.throws(() => routeAdapter.resolve("memorySearch", {query: {workspace_id: "not-accepted"}}), (error) => error.code === "unknown_query_field");
  assert.throws(() => routeAdapter.resolve("memorySubmit", {body: {
    scope: "workspace", title: "Safe title", summary: "Safe summary", memoryType: "status", actorAgentId: "not-accepted"
  }}), (error) => error.code === "unknown_body_field");
  assert.throws(() => routeAdapter.resolve("resourceContextSelect", {body: {projectId: "project-only"}}), (error) => error.code === "body_field_required");
  assert.throws(() => routeAdapter.resolve("workspaceRead", {body: {}}), (error) => error.code === "body_not_allowed");
  assert.throws(() => routeAdapter.resolve("workspaceRead", 0), (error) => error.code === "invalid_operation_input");
  const exactResourceRoute = routeAdapter.resolve("resourceContextSelect", {body: {workspaceId: "workspace-one", projectId: "project-one"}});
  assert.deepStrictEqual(exactResourceRoute.body, {workspaceId: "workspace-one", projectId: "project-one"});
  scenarios += 1;

  const productionCalls = [];
  const productionTransport = api.createTransport(async (requestPath, requestOptions) => {
    productionCalls.push({requestPath, requestOptions});
    return {ok: true, status: 200, text: async () => JSON.stringify({ok: true, contextVersion: "opaque-version"})};
  });
  await productionTransport.request("/api/matm/human/operational/workspace", {
    method: "GET",
    headers: {Accept: "application/json"},
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    mode: "same-origin",
    referrerPolicy: "no-referrer",
    operation: "workspaceRead"
  });
  assert.strictEqual(productionCalls.length, 1);
  assert.strictEqual(productionCalls[0].requestOptions.credentials, "same-origin");
  assert.strictEqual(productionCalls[0].requestOptions.cache, "no-store");
  assert.strictEqual(productionCalls[0].requestOptions.redirect, "error");
  assert.strictEqual(productionCalls[0].requestOptions.mode, "same-origin");
  assert.strictEqual(productionCalls[0].requestOptions.referrerPolicy, "no-referrer");
  assert.strictEqual(Object.prototype.hasOwnProperty.call(productionCalls[0].requestOptions, "operation"), false);
  assert.strictEqual(Object.prototype.hasOwnProperty.call(productionCalls[0].requestOptions, "idempotencyKey"), false);
  await expectCode(productionTransport.request("https://outside.invalid/", {
    method: "GET", headers: {Accept: "application/json"}, credentials: "same-origin", cache: "no-store", redirect: "error", mode: "same-origin", referrerPolicy: "no-referrer", operation: "workspaceRead"
  }), "unsafe_route");
  await expectCode(productionTransport.request("/api/matm/human/session", {
    method: "GET", headers: {Accept: "application/json", "X-Unapproved": "value"}, credentials: "same-origin", cache: "no-store", redirect: "error", mode: "same-origin", referrerPolicy: "no-referrer", operation: "sessionInspect"
  }), "unsafe_request_header");
  await expectCode(productionTransport.request("/api/matm/human/operational/workspace?workspaceId=not-accepted", {
    method: "GET", headers: {Accept: "application/json"}, credentials: "same-origin", cache: "no-store", redirect: "error", mode: "same-origin", referrerPolicy: "no-referrer", operation: "workspaceRead"
  }), "unknown_query_field");
  await expectCode(productionTransport.request("/api/matm/human/operational/workspace", {
    method: "get", headers: {Accept: "application/json"}, credentials: "same-origin", cache: "no-store", redirect: "error", mode: "same-origin", referrerPolicy: "no-referrer", operation: "workspaceRead"
  }), "invalid_method");
  scenarios += 1;

  const chooser = createHarness();
  await chooser.controller.mount();
  await chooser.controller.revalidate();
  assert.strictEqual(chooser.controller.getSnapshot().phase, api.PHASES.CHOOSING_COMPANY);
  assert.strictEqual(chooser.controller.getSnapshot().companySelected, false);
  assert.strictEqual(chooser.controller.getSnapshot().workspaceSelected, false);
  assert.strictEqual(chooser.elements.protected.hidden, true);
  assert.strictEqual(chooser.elements.protected.inert, true);
  assert.strictEqual(chooser.elements.authoritySelect.children.length, 3);
  assert.strictEqual(chooser.transport.inspect().networkRequestCount, 0);
  scenarios += 1;

  const defaultDemoFixture = createHarness();
  defaultDemoFixture.controller.destroy();
  let defaultDemoFetchCount = 0;
  const defaultDemoController = api.create({
    root: defaultDemoFixture.root,
    surface: "console",
    returnPath: "/console",
    documentRef: defaultDemoFixture.documentRef,
    windowRef: defaultDemoFixture.windowRef,
    demoMode: true,
    autoRevalidate: false,
    fetchImpl: async () => {
      defaultDemoFetchCount += 1;
      throw new Error("Demo attempted a network request");
    },
    adapter: api.createIntegrationAdapter()
  });
  await defaultDemoController.mount();
  await defaultDemoController.revalidate();
  await defaultDemoController.selectCompany("mock-authority-alpha");
  await defaultDemoController.selectResource("mock-workspace-memory", "");
  assert.strictEqual(defaultDemoController.getSnapshot().phase, api.PHASES.READY);
  assert.strictEqual(defaultDemoFetchCount, 0);
  defaultDemoController.destroy();
  assert.throws(() => api.create({
    root: defaultDemoFixture.root,
    surface: "console",
    documentRef: defaultDemoFixture.documentRef,
    windowRef: defaultDemoFixture.windowRef,
    demoMode: true,
    transport: {request() { return Promise.resolve({ok: true}); }}
  }), /zero-network Demo transport/);
  const productionTransportFixture = createHarness({demoMode: false});
  productionTransportFixture.controller.destroy();
  assert.throws(() => api.create({
    root: productionTransportFixture.root,
    surface: "console",
    documentRef: productionTransportFixture.documentRef,
    windowRef: productionTransportFixture.windowRef,
    demoMode: false,
    transport: api.createDemoTransport()
  }), /Production cannot use the Demo transport/);
  scenarios += 1;

  const chooserCalls = chooser.transport.inspect().callCount;
  await expectCode(chooser.controller.selectCompany("unknown-authority"), "unknown_authority");
  assert.strictEqual(chooser.transport.inspect().callCount, chooserCalls);
  assert.strictEqual(chooser.controller.getSnapshot().outcome, api.OUTCOMES.VALIDATION_ERROR);
  await chooseCompany(chooser);
  assert.strictEqual(chooser.controller.getSnapshot().phase, api.PHASES.CHOOSING_RESOURCE);
  assert.strictEqual(chooser.controller.getSnapshot().companySelected, true);
  assert.strictEqual(chooser.controller.getSnapshot().workspaceSelected, false);
  assert.strictEqual(chooser.controller.getSnapshot().projectSelected, false);
  const companyCall = chooser.transport.inspect().calls.find((call) => call.operation === "companySelect");
  assert.deepStrictEqual(companyCall.bodyKeys, ["authorityId"]);
  assert(companyCall.idempotencyKey);
  scenarios += 1;

  function transportWithUnrotatedContext(targetOperation) {
    const base = api.createDemoTransport();
    let priorVersion = "";
    return Object.freeze({
      demoTransport: true,
      async request(requestPath, requestOptions) {
        const payload = await base.request(requestPath, requestOptions);
        if (requestOptions.operation === "sessionInspect" || requestOptions.operation === "companySelect") {
          if (requestOptions.operation === targetOperation) payload.resourceContext.contextVersion = priorVersion;
          else priorVersion = payload.resourceContext.contextVersion;
        } else if (requestOptions.operation === "resourceContextSelect") {
          if (targetOperation === "resourceContextSelect") payload.resourceContext.contextVersion = priorVersion;
          else priorVersion = payload.resourceContext.contextVersion;
        }
        return payload;
      },
      inspect() { return base.inspect(); },
      reset() { base.reset(); }
    });
  }

  const unrotatedCompany = createHarness({transport: transportWithUnrotatedContext("companySelect")});
  await unrotatedCompany.controller.mount();
  await unrotatedCompany.controller.revalidate();
  await expectCode(unrotatedCompany.controller.selectCompany("mock-authority-alpha"), "context_version_not_rotated");
  assert.strictEqual(unrotatedCompany.controller.getSnapshot().phase, api.PHASES.CONTEXT_EXPIRED);
  assert.strictEqual(unrotatedCompany.controller.getSnapshot().authenticated, false);
  scenarios += 1;

  const beforeUnknownWorkspace = chooser.transport.inspect().callCount;
  await expectCode(chooser.controller.selectResource("unknown-workspace", ""), "unknown_workspace");
  assert.strictEqual(chooser.transport.inspect().callCount, beforeUnknownWorkspace);
  await chooser.controller.selectResource("mock-workspace-memory", "");
  assert.strictEqual(chooser.controller.getSnapshot().phase, api.PHASES.READY);
  assert.strictEqual(chooser.controller.getSnapshot().workspaceSelected, true);
  assert.strictEqual(chooser.controller.getSnapshot().projectSelected, false, "workspace selection inferred a project");
  assert.strictEqual(chooser.elements.protected.hidden, false);
  assert.strictEqual(chooser.elements.protected.inert, false);
  let resourceCalls = chooser.transport.inspect().calls.filter((call) => call.operation === "resourceContextSelect");
  assert.deepStrictEqual(resourceCalls[0].bodyKeys, ["workspaceId"]);
  await chooser.controller.selectResource("mock-workspace-memory", "mock-project-site");
  assert.strictEqual(chooser.controller.getSnapshot().projectSelected, true);
  resourceCalls = chooser.transport.inspect().calls.filter((call) => call.operation === "resourceContextSelect");
  assert.deepStrictEqual(resourceCalls[1].bodyKeys, ["projectId", "workspaceId"]);
  assert.notStrictEqual(resourceCalls[0].idempotencyKey, resourceCalls[1].idempotencyKey);
  scenarios += 1;

  const unrotatedResource = createHarness({transport: transportWithUnrotatedContext("resourceContextSelect")});
  await unrotatedResource.controller.mount();
  await unrotatedResource.controller.revalidate();
  await chooseCompany(unrotatedResource);
  await expectCode(unrotatedResource.controller.selectResource("mock-workspace-memory", ""), "context_version_not_rotated");
  assert.strictEqual(unrotatedResource.controller.getSnapshot().phase, api.PHASES.CONTEXT_EXPIRED);
  assert.strictEqual(unrotatedResource.elements.protected.hidden, true);
  scenarios += 1;

  const emptyCompany = createHarness();
  await emptyCompany.controller.mount();
  await emptyCompany.controller.revalidate();
  await chooseCompany(emptyCompany, "mock-authority-beta");
  assert.strictEqual(emptyCompany.controller.getSnapshot().phase, api.PHASES.EMPTY);
  assert.strictEqual(emptyCompany.controller.getSnapshot().workspaceSelected, false);
  assert.strictEqual(emptyCompany.elements.protected.hidden, true);
  scenarios += 1;

  const success = createHarness();
  await makeReady(success);
  const readyVersion = success.controller.getSnapshot().contextVersion;
  const workspacePayload = await success.controller.request("workspaceRead", {});
  assert.strictEqual(workspacePayload.contextVersion, readyVersion);
  assert.strictEqual(success.rendererState.resultCount, 1);
  const emptySearchPlan = {type: "empty"};
  success.transport.setPlan("memorySearch", emptySearchPlan);
  const emptyPayload = await success.controller.request("memorySearch", {query: {q: "nothing", limit: 25}});
  assert.deepStrictEqual(emptyPayload.items, []);
  assert.strictEqual(success.controller.getSnapshot().outcome, api.OUTCOMES.EMPTY);
  scenarios += 1;

  const rendererFailure = createHarness({adapterOverrides: {
    operationResult() { throw new Error("renderer failed"); }
  }});
  await makeReady(rendererFailure);
  rendererFailure.privateOutput.appendChild(new Element("article", rendererFailure.documentRef));
  const committedRead = await rendererFailure.controller.request("workspaceRead", {});
  assert.strictEqual(committedRead.ok, true);
  assert.strictEqual(rendererFailure.controller.getSnapshot().phase, api.PHASES.LOCKED);
  assert.strictEqual(rendererFailure.controller.getSnapshot().authenticated, false);
  assert.strictEqual(rendererFailure.elements.protected.hidden, true);
  assert.strictEqual(rendererFailure.privateOutput.children.length, 0);
  scenarios += 1;

  const mutationBody = {
    scope: "workspace",
    title: "Session-bound submission",
    summary: "A public-safe mock submission.",
    tags: ["mock-data"],
    memoryType: "status",
    source: "MemoryEndpoints Demo"
  };
  const csrfVersionBeforeMutation = success.controller.getSnapshot().contextVersion;
  const mutationPayload = await success.controller.request("memorySubmit", {body: mutationBody}, {idempotencyKey: "stable-mutation-key"});
  assert.strictEqual(mutationPayload.csrfTokenRotated, false);
  assert.strictEqual(success.controller.getSnapshot().contextVersion, csrfVersionBeforeMutation);
  const mutationCall = success.transport.inspect().calls.filter((call) => call.operation === "memorySubmit").slice(-1)[0];
  assert.strictEqual(mutationCall.idempotencyKey, "stable-mutation-key");
  assert.deepStrictEqual(mutationCall.bodyKeys, ["memoryType", "scope", "source", "summary", "tags", "title"]);
  scenarios += 1;

  const serializedMutation = createHarness();
  await makeReady(serializedMutation);
  let releaseMutation;
  serializedMutation.transport.setPlan("memorySubmit", [
    () => new Promise((resolve) => { releaseMutation = resolve; }),
    null
  ]);
  const firstMutation = serializedMutation.controller.request("memorySubmit", {body: mutationBody}, {idempotencyKey: "serialized-first"});
  await settle(4);
  const callsWhilePending = serializedMutation.transport.inspect().calls.filter((call) => call.operation === "memorySubmit").length;
  await expectCode(serializedMutation.controller.request("memorySubmit", {body: mutationBody}, {idempotencyKey: "serialized-second"}), "mutation_in_progress");
  assert.strictEqual(serializedMutation.transport.inspect().calls.filter((call) => call.operation === "memorySubmit").length, callsWhilePending);
  releaseMutation(null);
  await firstMutation;
  const beforeInvalidKey = serializedMutation.transport.inspect().callCount;
  await expectCode(serializedMutation.controller.request("memorySubmit", {body: mutationBody}, {idempotencyKey: "bad key\n"}), "invalid_idempotency_key");
  assert.strictEqual(serializedMutation.transport.inspect().callCount, beforeInvalidKey);
  scenarios += 1;

  const abortedMutation = createHarness();
  await makeReady(abortedMutation);
  let releaseAbortedMutation;
  abortedMutation.transport.setPlan("memorySubmit", () => new Promise((resolve) => { releaseAbortedMutation = resolve; }));
  const pendingAbortedMutation = abortedMutation.controller.request("memorySubmit", {body: mutationBody}, {idempotencyKey: "aborted-mutation"});
  await settle(4);
  abortedMutation.windowRef.dispatch("pagehide");
  releaseAbortedMutation(null);
  await expectCode(pendingAbortedMutation, "stale_response");
  assert.strictEqual(abortedMutation.transport.inspect().memoryCount, 1);
  assert.strictEqual(abortedMutation.controller.getSnapshot().phase, api.PHASES.LOCKED);
  assert.strictEqual(abortedMutation.elements.protected.hidden, true);
  scenarios += 1;

  const permission = createHarness();
  permission.transport.setPermission(api.PERMISSIONS.memorySubmit, false);
  await makeReady(permission);
  const beforeDenied = permission.transport.inspect().callCount;
  await expectCode(permission.controller.request("memorySubmit", {body: mutationBody}), "permission_denied");
  assert.strictEqual(permission.transport.inspect().callCount, beforeDenied);
  assert.strictEqual(permission.controller.getSnapshot().outcome, api.OUTCOMES.PERMISSION_DENIED);
  assert.strictEqual(permission.elements.protected.hidden, false);
  scenarios += 1;

  const stale = createHarness();
  await makeReady(stale);
  stale.privateOutput.appendChild(new Element("span", stale.documentRef));
  stale.transport.setPlan("workspaceRead", {type: "stale"});
  await expectCode(stale.controller.request("workspaceRead", {}), "stale_context");
  assert.strictEqual(stale.controller.getSnapshot().phase, api.PHASES.CONTEXT_EXPIRED);
  assert.strictEqual(stale.controller.getSnapshot().authenticated, false);
  assert.strictEqual(stale.elements.protected.hidden, true);
  assert.strictEqual(stale.privateOutput.children.length, 0);
  scenarios += 1;

  const contextExpiry = createHarness();
  await makeReady(contextExpiry);
  contextExpiry.transport.setPlan("workspaceRead", {type: "error", code: "context_expired", status: 410});
  await expectCode(contextExpiry.controller.request("workspaceRead", {}), "context_expired");
  assert.strictEqual(contextExpiry.controller.getSnapshot().phase, api.PHASES.CONTEXT_EXPIRED);
  assert.strictEqual(contextExpiry.windowRef.navigations.length, 0);
  scenarios += 1;

  const unexpectedRotation = createHarness();
  await makeReady(unexpectedRotation);
  const unexpectedVersion = unexpectedRotation.controller.getSnapshot().contextVersion;
  unexpectedRotation.transport.setPlan("workspaceRead", {
    payload: {ok: true, contextVersion: unexpectedVersion, csrfTokenRotated: true, csrfToken: "mock-unexpected", mockData: true}
  });
  await expectCode(unexpectedRotation.controller.request("workspaceRead", {}), "unexpected_csrf_rotation");
  assert.strictEqual(unexpectedRotation.controller.getSnapshot().phase, api.PHASES.SESSION_EXPIRED);
  assert.strictEqual(unexpectedRotation.controller.getSnapshot().authenticated, false);
  scenarios += 1;

  const unexpectedSessionRotation = createHarness();
  await makeReady(unexpectedSessionRotation);
  const unexpectedSessionVersion = unexpectedSessionRotation.controller.getSnapshot().contextVersion;
  unexpectedSessionRotation.transport.setPlan("workspaceRead", {
    payload: {ok: true, contextVersion: unexpectedSessionVersion, sessionRotated: true, mockData: true}
  });
  await expectCode(unexpectedSessionRotation.controller.request("workspaceRead", {}), "unexpected_session_rotation");
  assert.strictEqual(unexpectedSessionRotation.controller.getSnapshot().phase, api.PHASES.SESSION_EXPIRED);
  assert.strictEqual(unexpectedSessionRotation.elements.protected.hidden, true);
  scenarios += 1;

  const lost = createHarness();
  await makeReady(lost);
  lost.transport.setPlan("memorySubmit", [{type: "lost_after"}, null]);
  const lostError = await expectCode(lost.controller.request("memorySubmit", {body: mutationBody}, {idempotencyKey: "recoverable-key"}), "lost_response");
  assert.strictEqual(lostError.recoverable, true);
  assert.strictEqual(lostError.idempotencyKey, "recoverable-key");
  assert.strictEqual(lost.controller.getSnapshot().phase, api.PHASES.READY);
  assert.strictEqual(lost.controller.getSnapshot().outcome, api.OUTCOMES.LOST_RESPONSE);
  const recovered = await lost.controller.request("memorySubmit", {body: mutationBody}, {idempotencyKey: "recoverable-key"});
  assert.strictEqual(recovered.ok, true);
  assert.strictEqual(lost.transport.inspect().memoryCount, 2, "lost-response retry duplicated the mutation");
  const recoveryCalls = lost.transport.inspect().calls.filter((call) => call.operation === "memorySubmit");
  assert.deepStrictEqual(recoveryCalls.map((call) => call.idempotencyKey), ["recoverable-key", "recoverable-key"]);
  scenarios += 1;

  const sessionExpiry = createHarness({demoMode: false, returnPath: "/console"});
  await makeReady(sessionExpiry);
  sessionExpiry.transport.setPlan("workspaceRead", {type: "error", code: "human_session_required", status: 401});
  await expectCode(sessionExpiry.controller.request("workspaceRead", {}), "human_session_required");
  assert.strictEqual(sessionExpiry.controller.getSnapshot().phase, api.PHASES.SESSION_EXPIRED);
  assert.deepStrictEqual(sessionExpiry.windowRef.navigations, ["/console"]);
  assert.strictEqual(sessionExpiry.elements.protected.hidden, true);
  scenarios += 1;

  const invalidReturn = createHarness({demoMode: false, returnPath: "/console?next=/knowledge"});
  assert.strictEqual(invalidReturn.controller.getSnapshot().returnPath, "/console");
  const knowledgeReturn = createHarness({demoMode: false, surface: "knowledge", returnPath: "https://outside.invalid"});
  assert.strictEqual(knowledgeReturn.controller.getSnapshot().returnPath, "/knowledge");
  scenarios += 1;

  const lifecycle = createHarness();
  await makeReady(lifecycle, "mock-project-site");
  lifecycle.privateInput.value = "private input";
  lifecycle.privateTextarea.value = "private textarea";
  lifecycle.privateOutput.appendChild(new Element("article", lifecycle.documentRef));
  lifecycle.privatePre.textContent = "private debug value";
  lifecycle.dialog.open = true;
  lifecycle.dialog.setAttribute("open", "");
  const scrubBeforeHide = lifecycle.rendererState.scrubCount;
  lifecycle.windowRef.dispatch("pagehide");
  assert.strictEqual(lifecycle.controller.getSnapshot().phase, api.PHASES.LOCKED);
  assert.strictEqual(lifecycle.privateInput.value, "");
  assert.strictEqual(lifecycle.privateTextarea.value, "");
  assert.strictEqual(lifecycle.privateOutput.children.length, 0);
  assert.strictEqual(lifecycle.privatePre.textContent, "");
  assert.strictEqual(lifecycle.dialog.open, false);
  assert.strictEqual(lifecycle.elements.protected.hidden, true);
  assert(lifecycle.rendererState.scrubCount > scrubBeforeHide);
  lifecycle.windowRef.dispatch("pageshow", {persisted: true});
  assert.strictEqual(lifecycle.controller.getSnapshot().phase, api.PHASES.REVALIDATING);
  assert.strictEqual(lifecycle.elements.protected.hidden, true);
  await settle(32);
  assert.strictEqual(lifecycle.controller.getSnapshot().phase, api.PHASES.READY);
  assert.strictEqual(lifecycle.elements.protected.hidden, false);
  scenarios += 1;

  const logout = createHarness({demoMode: false, returnPath: "/console"});
  await makeReady(logout);
  const pendingLogout = logout.controller.logout();
  assert.strictEqual(logout.controller.getSnapshot().authenticated, false, "logout did not synchronously scrub session state");
  assert.strictEqual(logout.elements.protected.hidden, true);
  await pendingLogout;
  assert.deepStrictEqual(logout.windowRef.navigations, ["/console"]);
  const logoutCall = logout.transport.inspect().calls.find((call) => call.operation === "sessionLogout");
  assert(logoutCall.idempotencyKey);
  scenarios += 1;

  const reset = createHarness();
  await makeReady(reset);
  await reset.controller.request("memorySubmit", {body: mutationBody}, {idempotencyKey: "reset-mutation"});
  assert.strictEqual(reset.transport.inspect().memoryCount, 2);
  await reset.controller.resetDemo();
  assert.strictEqual(reset.controller.getSnapshot().phase, api.PHASES.CHOOSING_COMPANY);
  assert.strictEqual(reset.transport.inspect().memoryCount, 1);
  assert.strictEqual(reset.transport.inspect().networkRequestCount, 0);
  assert.deepStrictEqual(reset.transport.inspect().calls.map((call) => call.operation), ["sessionInspect"]);
  scenarios += 1;

  const planReset = createHarness({plans: {
    sessionInspect: [{type: "error", code: "planned_demo_error", status: 400}, null]
  }});
  await planReset.controller.mount();
  await expectCode(planReset.controller.revalidate(), "planned_demo_error");
  planReset.transport.reset();
  await expectCode(planReset.controller.revalidate(), "planned_demo_error");
  assert.strictEqual(planReset.transport.inspect().networkRequestCount, 0);
  scenarios += 1;

  let resolveDeferred;
  const destroyed = createHarness();
  await makeReady(destroyed);
  destroyed.transport.setPlan("workspaceRead", () => new Promise((resolve) => { resolveDeferred = resolve; }));
  const pendingRead = destroyed.controller.request("workspaceRead", {});
  await settle(2);
  destroyed.controller.destroy();
  assert.strictEqual(destroyed.controller.getSnapshot().phase, api.PHASES.DESTROYED);
  assert.strictEqual(destroyed.elements.protected.hidden, true);
  resolveDeferred(null);
  await expectCode(pendingRead, "stale_response");
  assert.strictEqual(destroyed.controller.getSnapshot().phase, api.PHASES.DESTROYED, "an aborted stale response changed destroyed state");
  assert.strictEqual((destroyed.windowRef.listeners.pagehide || []).length, 0);
  assert.strictEqual((destroyed.windowRef.listeners.pageshow || []).length, 0);
  scenarios += 1;

  const malformedDemo = api.createDemoTransport();
  await expectCode(malformedDemo.request("https://outside.invalid", {
    method: "GET", headers: {Accept: "application/json"}, credentials: "same-origin", cache: "no-store", redirect: "error", mode: "same-origin", referrerPolicy: "no-referrer"
  }), "unsafe_route");
  await expectCode(malformedDemo.request("/api/matm/human/operational/not-real", {
    method: "GET", headers: {Accept: "application/json"}, credentials: "same-origin", cache: "no-store", redirect: "error", mode: "same-origin", referrerPolicy: "no-referrer"
  }), "operation_not_available");
  await expectCode(malformedDemo.request("/api/matm/human/operational/workspace", {
    method: "get", headers: {Accept: "application/json"}, credentials: "same-origin", cache: "no-store", redirect: "error", mode: "same-origin", referrerPolicy: "no-referrer", operation: "workspaceRead"
  }), "invalid_method");
  await expectCode(malformedDemo.request("/api/matm/human/operational/workspace", {
    method: "GET", headers: {Accept: "application/json"}, credentials: "same-origin", cache: "no-store", redirect: "error", mode: "same-origin", referrerPolicy: "no-referrer", operation: "memorySearch"
  }), "operation_mismatch");
  malformedDemo.setPlan("sessionInspect", {payload: {ok: true}});
  await expectCode(malformedDemo.request("/api/matm/human/session", {
    method: "GET", headers: {Accept: "application/json"}, credentials: "same-origin", cache: "no-store", redirect: "error", mode: "same-origin", referrerPolicy: "no-referrer", operation: "sessionInspect"
  }), "mock_label_required");
  assert.strictEqual(malformedDemo.inspect().networkRequestCount, 0);
  scenarios += 1;

  const allHarnesses = [chooser, unrotatedCompany, unrotatedResource, emptyCompany, success, rendererFailure, serializedMutation, abortedMutation, permission, stale, contextExpiry, unexpectedRotation, unexpectedSessionRotation, lost, sessionExpiry, invalidReturn, knowledgeReturn, lifecycle, logout, reset, planReset, destroyed];
  for (const harness of allHarnesses) {
    assert.strictEqual(harness.transport.inspect().networkRequestCount, 0);
    assert(harness.transport.inspect().calls.every((call) => call.mockData === true));
    assert(harness.transport.inspect().calls.every((call) => call.path.startsWith("/api/matm/human/")));
    assert(harness.transport.inspect().calls.every((call) => call.credentials === "same-origin" && call.cache === "no-store"
      && call.redirect === "error" && call.mode === "same-origin" && call.referrerPolicy === "no-referrer"));
  }

  process.stdout.write(JSON.stringify({
    ok: true,
    scenarioCount: scenarios,
    assertionCount,
    centralizedRoutes: Object.keys(api.ROUTES).length,
    selectorCount: Object.keys(api.SELECTORS).length,
    permissionCount: Object.keys(api.PERMISSIONS).length,
    noImplicitContext: true,
    transitionRotation: true,
    staleResultRejected: true,
    lostResponseRecoveredIdempotently: true,
    fullLifecycleScrub: true,
    bfcacheRevalidation: true,
    fixedReturnPaths: true,
    collaborationOperationsUnavailable: true,
    zeroNetworkDemo: true,
    deterministicReset: true
  }) + "\n");
}

main().catch((error) => {
  process.stderr.write(error.stack || String(error));
  process.exitCode = 1;
});
