"use strict";

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const scriptPath = process.argv[2];
const cssPath = process.argv[3];
if (!scriptPath || !cssPath) throw new Error("Usage: node tests/human_access_ui_contract.js static/js/human-access.js static/css/human-access.css");

const source = fs.readFileSync(scriptPath, "utf8");
const css = fs.readFileSync(cssPath, "utf8");
const api = require(path.resolve(scriptPath));

for (const forbidden of ["local" + "Storage", "session" + "Storage", "indexed" + "DB", "send" + "Beacon", "document" + ".cookie", "Author" + "ization", "inner" + "HTML", "outer" + "HTML", "predecessor" + "Token", "old" + "Token"]) {
  assert(!source.includes(forbidden), `forbidden browser surface or predecessor secret field: ${forbidden}`);
}
assert(source.includes('credentials: "same-origin"'));
assert(source.includes('cache: "no-store"'));
assert(source.includes("windowRef.fetch.bind(windowRef)"));
assert(source.includes("scrubProtectedState"));
assert(source.includes("revalidateHumanSession"));
assert(css.includes("min-block-size: 44px"));
assert(css.includes("repeat(auto-fit, minmax(min(100%, 320px), 1fr))"));
assert(css.includes("dialog::backdrop"));
assert(css.includes("overflow-wrap: anywhere"));
for (const className of ["human-access-auth-grid", "human-access-card", "human-access-hero", "human-access-toolbar", "human-access-toolbar-actions", "human-access-actions", "human-access-section-heading", "human-access-dialog-actions", "human-access-check", "human-access-roster-list", "human-access-live", "human-access-field.compact"]) {
  assert(css.includes(className), `missing renderer CSS coverage: ${className}`);
}

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
    this.textContent = "";
    this.value = "";
    this.type = this.tagName === "INPUT" ? "text" : "";
    this.checked = false;
    this.disabled = false;
    this.open = false;
    this.elements = {};
    this.isConnected = true;
    this.focusCount = 0;
    this.className = "";
  }
  get firstChild() { return this.children[0] || null; }
  appendChild(child) { child.parentNode = this; child.isConnected = true; this.children.push(child); return child; }
  removeChild(child) { const index = this.children.indexOf(child); if (index >= 0) this.children.splice(index, 1); child.parentNode = null; return child; }
  replaceChildren(...children) { this.children.forEach((child) => { child.parentNode = null; }); this.children = []; children.forEach((child) => this.appendChild(child)); }
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
  focus() { this.focusCount += 1; this.ownerDocument.activeElement = this; }
  showModal() { this.open = true; this.attributes.open = ""; }
  close() { this.open = false; delete this.attributes.open; }
}

class Document {
  constructor() { this.activeElement = null; }
  createElement(tagName) { return new Element(tagName, this); }
}

function input(documentRef, type) { const item = new Element("input", documentRef); item.type = type || "text"; return item; }
function form(documentRef, controls) { const item = new Element("form", documentRef); item.elements = controls || {}; return item; }

function createHarness(options) {
  const documentRef = new Document();
  const root = new Element("section", documentRef);
  const selectors = new Map();
  root.querySelector = (selector) => selectors.get(selector) || null;
  root.dataset = {};

  function add(selector, element) { selectors.set(selector, element); root.appendChild(element); return element; }
  const status = add(api.SELECTORS.status, new Element("output", documentRef));
  const locked = add(api.SELECTORS.locked, new Element("section", documentRef));
  const accountStep = add(api.SELECTORS.accountStep, new Element("section", documentRef));
  const protectedEl = add(api.SELECTORS.protected, new Element("section", documentRef));
  const demoLabel = add(api.SELECTORS.demoLabel, new Element("p", documentRef));
  const master = input(documentRef, "password");
  const proofForm = add(api.SELECTORS.masterProofForm, form(documentRef, {companyMasterTokenSecret: master}));
  const accountPassword = input(documentRef, "password");
  const accountConfirmation = input(documentRef, "password");
  const accountForm = add(api.SELECTORS.accountForm, form(documentRef, {username: input(documentRef), displayName: input(documentRef), password: accountPassword, passwordConfirmation: accountConfirmation}));
  const loginPassword = input(documentRef, "password");
  const loginForm = add(api.SELECTORS.loginForm, form(documentRef, {username: input(documentRef), password: loginPassword}));
  const logout = add(api.SELECTORS.logout, new Element("button", documentRef));
  const membershipList = add(api.SELECTORS.membershipList, new Element("select", documentRef));
  const membershipForm = add(api.SELECTORS.membershipForm, form(documentRef, {authorityId: membershipList}));
  const linkCompany = add(api.SELECTORS.linkCompany, new Element("button", documentRef));
  const linkDialog = add(api.SELECTORS.linkDialog, new Element("dialog", documentRef));
  const linkMaster = input(documentRef, "password");
  const linkProofForm = add(api.SELECTORS.linkProofForm, form(documentRef, {companyMasterTokenSecret: linkMaster}));
  const linkCancel = add(api.SELECTORS.linkCancel, new Element("button", documentRef));
  const rosterList = add(api.SELECTORS.rosterList, new Element("div", documentRef));
  const rosterEmpty = add(api.SELECTORS.rosterEmpty, new Element("p", documentRef));
  const rosterRefresh = add(api.SELECTORS.rosterRefresh, new Element("button", documentRef));
  const agentMasterSetting = add(api.SELECTORS.agentMasterSetting, input(documentRef, "checkbox"));
  const agentMasterSettingForm = add(api.SELECTORS.agentMasterSettingForm, form(documentRef, {enabled: agentMasterSetting}));
  const agentMasterSettingStatus = add(api.SELECTORS.agentMasterSettingStatus, new Element("span", documentRef));
  const reauthPassword = input(documentRef, "password");
  const reauthDialog = add(api.SELECTORS.reauthDialog, new Element("dialog", documentRef));
  const reauthForm = add(api.SELECTORS.reauthForm, form(documentRef, {password: reauthPassword}));
  const reauthCancel = add(api.SELECTORS.reauthCancel, new Element("button", documentRef));
  const replacementDialog = add(api.SELECTORS.replacementDialog, new Element("dialog", documentRef));
  const replacementSummary = add(api.SELECTORS.replacementSummary, new Element("p", documentRef));
  const replacementStatus = add(api.SELECTORS.replacementStatus, new Element("p", documentRef));
  const successorToken = add(api.SELECTORS.successorToken, input(documentRef, "password"));
  successorToken.setAttribute("data-human-access-secret-control", "");
  const successorShow = add(api.SELECTORS.successorShow, new Element("button", documentRef));
  const successorCopy = add(api.SELECTORS.successorCopy, new Element("button", documentRef));
  const successorSaved = add(api.SELECTORS.successorSaved, input(documentRef, "checkbox"));
  const successorClear = add(api.SELECTORS.successorClear, new Element("button", documentRef));
  const possessionToken = add(api.SELECTORS.possessionToken, input(documentRef, "password"));
  const possessionForm = add(api.SELECTORS.possessionForm, form(documentRef, {successorTokenProof: possessionToken}));
  const replacementRetry = add(api.SELECTORS.replacementRetry, new Element("button", documentRef));
  const replacementCancel = add(api.SELECTORS.replacementCancel, new Element("button", documentRef));

  const lifecycle = {};
  const windowRef = {
    navigator: {},
    addEventListener(type, listener) { (lifecycle[type] ||= []).push(listener); },
    removeEventListener(type, listener) { lifecycle[type] = (lifecycle[type] || []).filter((item) => item !== listener); },
  };
  const clipboard = {
    last: "",
    writes: 0,
    async writeText(value) { this.last = value; this.writes += 1; },
    clear() { this.last = ""; },
  };
  const transport = options && options.transport || api.createDemoTransport(options);
  const controller = api.create({root, documentRef, windowRef, clipboard, transport, sessionAuthority: options && options.sessionAuthority, demoMode: true});
  controller.mount();
  return {
    accountConfirmation, accountForm, accountPassword, agentMasterSetting, agentMasterSettingForm, agentMasterSettingStatus, clipboard, controller, demoLabel, documentRef, lifecycle,
    linkCancel, linkCompany, linkDialog, linkMaster, linkProofForm, locked, loginForm, loginPassword, logout, master, membershipForm, membershipList, possessionForm, possessionToken,
    protectedEl, proofForm, reauthCancel, reauthDialog, reauthForm, reauthPassword, replacementCancel,
    replacementDialog, replacementRetry, rosterEmpty, rosterList, rosterRefresh, root, status, successorClear,
    successorCopy, successorSaved, successorShow, successorToken, transport,
  };
}

function createPreauthHarness(options) {
  options = options || {};
  const documentRef = new Document();
  const root = new Element("section", documentRef);
  const selectors = new Map();
  root.querySelector = (selector) => selectors.get(selector) || null;
  root.dataset = {};
  function add(selector, element) { selectors.set(selector, element); root.appendChild(element); return element; }
  const status = add(api.SELECTORS.status, new Element("output", documentRef));
  const locked = add(api.SELECTORS.locked, new Element("section", documentRef));
  const accountStep = add(api.SELECTORS.accountStep, new Element("section", documentRef));
  const master = input(documentRef, "password");
  const proofForm = add(api.SELECTORS.masterProofForm, form(documentRef, {companyMasterTokenSecret: master}));
  const accountPassword = input(documentRef, "password");
  const accountConfirmation = input(documentRef, "password");
  const accountForm = add(api.SELECTORS.accountForm, form(documentRef, {username: input(documentRef), displayName: input(documentRef), password: accountPassword, passwordConfirmation: accountConfirmation}));
  const loginPassword = input(documentRef, "password");
  const loginForm = add(api.SELECTORS.loginForm, form(documentRef, {username: input(documentRef), password: loginPassword}));
  const lifecycle = {};
  const fetchCalls = [];
  const windowRef = {
    addEventListener(type, listener) { (lifecycle[type] ||= []).push(listener); },
    removeEventListener(type, listener) { lifecycle[type] = (lifecycle[type] || []).filter((item) => item !== listener); },
    async fetch(pathname, requestOptions) {
      const body = requestOptions.body ? JSON.parse(requestOptions.body) : {};
      fetchCalls.push({pathname, method: requestOptions.method, bodyKeys: Object.keys(body).sort(), credentials: requestOptions.credentials, cache: requestOptions.cache});
      return {
        ok: true,
        status: 200,
        async json() {
          return {ok: true, account: {humanAccountId: "live-shaped-account", username: body.username || "owner", displayName: "Owner"}, memberships: [{authorityId: "live-shaped-authority", companyId: "live-shaped-company", companyLabel: "Company", role: "owner", permissions: ["credential_admin"]}], humanSession: {humanAccountSessionId: "live-shaped-session", selectedCompanyId: null, expiresAt: "later"}, selectedCompanyId: null, csrfToken: "LIVE-SHAPED-CSRF-CANARY"};
        },
      };
    },
  };
  const navigateCalls = [];
  const transport = options.useWindowFetch ? null : api.createDemoTransport();
  const controllerOptions = {root, documentRef, windowRef, sessionAuthority: api.createSessionAuthority(), navigate(pathname) { navigateCalls.push(pathname); }};
  if (transport) controllerOptions.transport = transport;
  const controller = api.createPreauth(controllerOptions);
  controller.mount();
  return {accountConfirmation, accountForm, accountPassword, accountStep, controller, fetchCalls, lifecycle, locked, loginForm, loginPassword, master, navigateCalls, proofForm, root, status, transport};
}

async function settle() {
  for (let index = 0; index < 12; index += 1) await Promise.resolve();
  await new Promise((resolve) => setImmediate(resolve));
}

function dispatchLifecycle(harness, type, values) {
  for (const listener of harness.lifecycle[type] || []) listener(Object.assign({persisted: false}, values || {}));
}

function scanDom(node, canaries, allowedValueElement) {
  const strings = [node.textContent, ...Object.values(node.attributes || {}), ...Object.values(node.dataset || {})].map(String);
  for (const canary of canaries) for (const value of strings) assert(!value.includes(canary), `secret escaped into DOM metadata: ${canary}`);
  if (node !== allowedValueElement) for (const canary of canaries) assert(!String(node.value || "").includes(canary), `secret escaped into non-designated value: ${canary}`);
  for (const child of node.children || []) scanDom(child, canaries, allowedValueElement);
}

async function login(harness, username, password, selectCompany = true) {
  harness.loginForm.elements.username.value = username || "demo-owner";
  harness.loginPassword.value = password || "HUMAN-PASSWORD-CANARY";
  harness.loginForm.dispatch("submit");
  assert.strictEqual(harness.loginPassword.value, "", "password was not cleared synchronously");
  await settle();
  assert.strictEqual(harness.controller.getSnapshot().sessionState, api.SESSION_STATES.CHOOSING_COMPANY);
  if (selectCompany) {
    harness.membershipList.value = "mock-authority-owner";
    harness.membershipForm.dispatch("submit");
    assert.strictEqual(harness.controller.getSnapshot().sessionState, api.SESSION_STATES.SWITCHING_COMPANY);
    await settle();
  }
}

async function prepareReplacement(harness) {
  const opener = new Element("button", harness.documentRef);
  harness.documentRef.activeElement = opener;
  harness.controller.beginReplacement("mock-credential-frontend-agent", opener);
  assert.strictEqual(harness.reauthDialog.open, true);
  harness.reauthPassword.value = "REAUTH-PASSWORD-CANARY";
  harness.reauthForm.dispatch("submit");
  assert.strictEqual(harness.reauthPassword.value, "", "reauth password was not cleared synchronously");
  await settle();
  return opener;
}

async function main() {
  const livePreauth = createPreauthHarness({useWindowFetch: true});
  livePreauth.loginForm.elements.username.value = "owner";
  livePreauth.loginPassword.value = "LIVE-PREAUTH-PASSWORD";
  livePreauth.loginForm.dispatch("submit");
  assert.strictEqual(livePreauth.loginPassword.value, "");
  await settle();
  assert.deepStrictEqual(livePreauth.navigateCalls, ["/human"]);
  assert.deepStrictEqual(livePreauth.fetchCalls.map((call) => call.pathname), ["/api/matm/human/session"]);
  assert.strictEqual(livePreauth.fetchCalls[0].credentials, "same-origin");
  assert.strictEqual(livePreauth.fetchCalls[0].cache, "no-store");
  scanDom(livePreauth.root, ["LIVE-PREAUTH-PASSWORD", "LIVE-SHAPED-CSRF-CANARY"], null);

  const preauthLogin = createPreauthHarness();
  preauthLogin.loginForm.elements.username.value = "demo-owner";
  preauthLogin.loginPassword.value = "PREAUTH-LOGIN-PASSWORD";
  preauthLogin.loginForm.dispatch("submit");
  assert.strictEqual(preauthLogin.loginPassword.value, "");
  await settle();
  assert.deepStrictEqual(preauthLogin.navigateCalls, ["/human"]);

  const preauthEnrollment = createPreauthHarness();
  preauthEnrollment.master.value = "PREAUTH-MASTER-CANARY";
  preauthEnrollment.proofForm.dispatch("submit");
  assert.strictEqual(preauthEnrollment.master.value, "");
  await settle();
  preauthEnrollment.accountForm.elements.username.value = "demo-owner";
  preauthEnrollment.accountForm.elements.displayName.value = "Demo Owner";
  preauthEnrollment.accountPassword.value = "PREAUTH-ACCOUNT-PASSWORD";
  preauthEnrollment.accountConfirmation.value = "PREAUTH-ACCOUNT-PASSWORD";
  preauthEnrollment.accountForm.dispatch("submit");
  assert.strictEqual(preauthEnrollment.accountPassword.value, "");
  assert.strictEqual(preauthEnrollment.accountConfirmation.value, "");
  await settle();
  assert.deepStrictEqual(preauthEnrollment.navigateCalls, ["/human"]);

  const validation = createHarness();
  validation.proofForm.dispatch("submit");
  await settle();
  assert.strictEqual(validation.controller.getSnapshot().sessionState, api.SESSION_STATES.VALIDATION_ERROR);

  const injectedSessionAuthority = api.createSessionAuthority();
  const enrollment = createHarness({sessionAuthority: injectedSessionAuthority});
  const rawMaster = "RAW-MASTER-CANARY";
  const accountPassword = "ACCOUNT-PASSWORD-CANARY";
  enrollment.master.value = rawMaster;
  enrollment.proofForm.dispatch("submit");
  assert.strictEqual(enrollment.master.value, "", "master credential was not cleared before transport settled");
  await settle();
  assert.strictEqual(enrollment.controller.getSnapshot().sessionState, api.SESSION_STATES.PROOF_READY);
  enrollment.accountForm.elements.username.value = "demo-owner";
  enrollment.accountForm.elements.displayName.value = "Demo Owner";
  enrollment.accountPassword.value = accountPassword;
  enrollment.accountConfirmation.value = accountPassword;
  enrollment.accountForm.dispatch("submit");
  assert.strictEqual(enrollment.accountPassword.value, "");
  assert.strictEqual(enrollment.accountConfirmation.value, "");
  await settle();
  assert.strictEqual(enrollment.controller.getSnapshot().sessionState, api.SESSION_STATES.CHOOSING_COMPANY);
  assert.strictEqual(enrollment.controller.getSnapshot().accountIdPresent, true);
  assert.strictEqual(enrollment.controller.getSnapshot().membershipCount, 1);
  assert.strictEqual(enrollment.controller.getSnapshot().rosterCount, 0);
  enrollment.membershipList.value = "mock-authority-owner";
  enrollment.membershipForm.dispatch("submit");
  await settle();
  assert.strictEqual(enrollment.controller.getSnapshot().rosterCount, 1);
  assert.strictEqual(enrollment.protectedEl.hidden, false);
  assert.deepStrictEqual(injectedSessionAuthority.inspect(), {csrfAvailable: true});
  assert(enrollment.demoLabel.textContent.includes("Demo"));
  const retainedEnrollment = JSON.stringify(enrollment.transport.inspect());
  assert(!retainedEnrollment.includes(rawMaster));
  assert(!retainedEnrollment.includes(accountPassword));
  scanDom(enrollment.root, [rawMaster, accountPassword], null);

  const empty = createHarness({plans: {roster: {payload: {ok: true, items: [], mockData: true}}}});
  await login(empty);
  assert.strictEqual(empty.controller.getSnapshot().sessionState, api.SESSION_STATES.EMPTY);
  assert.strictEqual(empty.rosterEmpty.hidden, false);

  const linker = createHarness();
  await login(linker);
  linker.linkCompany.dispatch("click");
  assert.strictEqual(linker.reauthDialog.open, true);
  linker.reauthPassword.value = "LINK-REAUTH-PASSWORD";
  linker.reauthForm.dispatch("submit");
  assert.strictEqual(linker.reauthPassword.value, "");
  await settle();
  assert.strictEqual(linker.linkDialog.open, true);
  const linkMasterCanary = "LINK-RAW-MASTER-CANARY";
  linker.linkMaster.value = linkMasterCanary;
  linker.linkProofForm.dispatch("submit");
  assert.strictEqual(linker.linkMaster.value, "", "link master credential was not cleared synchronously");
  await settle();
  assert.strictEqual(linker.controller.getSnapshot().membershipCount, 2);
  assert.strictEqual(linker.controller.getSnapshot().selectedCompanyPresent, true);
  assert.strictEqual(linker.linkDialog.open, false);
  const linkCalls = linker.transport.inspect().calls.slice(-3);
  assert.deepStrictEqual(linkCalls.map((call) => call.operation), ["sessionReauth", "masterProof", "membershipLink"]);
  assert.deepStrictEqual(linkCalls[2].bodyKeys, ["companyMasterProofSecret"]);
  assert.strictEqual(linkCalls[2].csrfAccepted, true);
  assert(!JSON.stringify(linker.transport.inspect()).includes(linkMasterCanary));
  scanDom(linker.root, [linkMasterCanary, "LINK-REAUTH-PASSWORD"], null);

  const reauthEscape = createHarness();
  await login(reauthEscape);
  const reauthEscapeOpener = new Element("button", reauthEscape.documentRef);
  reauthEscape.controller.beginReplacement("mock-credential-frontend-agent", reauthEscapeOpener);
  reauthEscape.reauthPassword.value = "ESCAPE-REAUTH-PASSWORD-CANARY";
  const reauthCancelEvent = reauthEscape.reauthDialog.dispatch("cancel");
  assert.strictEqual(reauthCancelEvent.defaultPrevented, true);
  assert.strictEqual(reauthEscape.reauthPassword.value, "");
  assert.strictEqual(reauthEscape.reauthDialog.open, false);
  assert.strictEqual(reauthEscape.controller.getSnapshot().replacementState, api.REPLACEMENT_STATES.IDLE);
  assert(reauthEscapeOpener.focusCount >= 1, "reauth Escape did not restore focus");
  scanDom(reauthEscape.root, ["ESCAPE-REAUTH-PASSWORD-CANARY"], null);

  const linkEscape = createHarness();
  await login(linkEscape);
  linkEscape.linkCompany.dispatch("click");
  linkEscape.reauthPassword.value = "ESCAPE-LINK-REAUTH-CANARY";
  linkEscape.reauthForm.dispatch("submit");
  await settle();
  linkEscape.linkMaster.value = "ESCAPE-LINK-MASTER-CANARY";
  const linkCancelEvent = linkEscape.linkDialog.dispatch("cancel");
  assert.strictEqual(linkCancelEvent.defaultPrevented, true);
  assert.strictEqual(linkEscape.linkMaster.value, "");
  assert.strictEqual(linkEscape.linkDialog.open, false);
  assert.strictEqual(linkEscape.controller.getSnapshot().sessionState, api.SESSION_STATES.READY);
  assert(linkEscape.linkCompany.focusCount >= 1, "link-company Escape did not restore focus");
  scanDom(linkEscape.root, ["ESCAPE-LINK-REAUTH-CANARY", "ESCAPE-LINK-MASTER-CANARY"], null);

  assert.strictEqual(linker.transport.inspect().membershipCount, 2);
  linker.transport.reset();
  assert.strictEqual(linker.transport.inspect().membershipCount, 1, "Demo reset retained a linked mock company");
  assert.strictEqual(linker.transport.inspect().networkRequestCount, 0);

  const permission = createHarness({plans: {replacementPrepare: {error: {code: "human_permission_required", status: 403}}}});
  await login(permission);
  await prepareReplacement(permission);
  assert.strictEqual(permission.controller.getSnapshot().sessionState, api.SESSION_STATES.PERMISSION_ERROR);

  const expiry = createHarness({plans: {replacementPrepare: {error: {code: "replacement_expired", status: 410}}}});
  await login(expiry);
  await prepareReplacement(expiry);
  assert.strictEqual(expiry.controller.getSnapshot().replacementState, api.REPLACEMENT_STATES.EXPIRED);

  const cancel = createHarness();
  await login(cancel);
  const cancelOpener = await prepareReplacement(cancel);
  assert.strictEqual(cancel.controller.getSnapshot().replacementState, api.REPLACEMENT_STATES.REVEALED_UNSAVED);
  assert.strictEqual(cancel.successorToken.type, "password");
  cancel.replacementCancel.dispatch("click");
  await settle();
  assert.strictEqual(cancel.controller.getSnapshot().replacementState, api.REPLACEMENT_STATES.CANCELED);
  assert.strictEqual(cancel.successorToken.value, "");
  assert(cancelOpener.focusCount >= 1, "replacement cancel did not restore focus");

  const replacement = createHarness({plans: {replacementConfirm: [{lostResponse: true}]}});
  await login(replacement);
  await prepareReplacement(replacement);
  const successor = replacement.successorToken.value;
  assert(successor.includes("NOT A CREDENTIAL"));
  scanDom(replacement.root, [successor], replacement.successorToken);
  replacement.successorCopy.dispatch("click");
  await settle();
  assert.strictEqual(replacement.clipboard.last, successor);
  replacement.clipboard.clear();
  replacement.successorSaved.checked = true;
  replacement.successorSaved.dispatch("change");
  assert.strictEqual(replacement.successorToken.value, "");
  assert.strictEqual(replacement.successorSaved.checked, true, "saved acknowledgement was cleared with the one-time reveal");
  assert.strictEqual(replacement.controller.getSnapshot().successorAvailable, false);
  replacement.possessionToken.value = successor;
  replacement.possessionForm.dispatch("submit");
  assert.strictEqual(replacement.possessionToken.value, "", "successor proof was not cleared synchronously");
  await settle();
  assert.strictEqual(replacement.controller.getSnapshot().replacementState, api.REPLACEMENT_STATES.OUTCOME_UNKNOWN);
  assert.strictEqual(replacement.successorSaved.checked, true, "unknown confirm outcome cleared the saved acknowledgement");
  replacement.replacementRetry.dispatch("click");
  await settle();
  assert.strictEqual(replacement.controller.getSnapshot().replacementState, api.REPLACEMENT_STATES.SAVED_CLEARED);
  assert.strictEqual(replacement.successorSaved.checked, true, "status recovery cleared the saved acknowledgement");
  let confirmCalls = replacement.transport.inspect().calls.filter((call) => call.operation === "replacementConfirm");
  assert.strictEqual(confirmCalls.length, 1, "lost confirm recovery retried before checking status");
  const statusIndex = replacement.transport.inspect().calls.findIndex((call) => call.operation === "replacementStatus");
  assert(statusIndex > replacement.transport.inspect().calls.findIndex((call) => call.operation === "replacementConfirm"));
  replacement.possessionToken.value = successor;
  replacement.possessionForm.dispatch("submit");
  assert.strictEqual(replacement.possessionToken.value, "");
  await settle();
  assert.strictEqual(replacement.controller.getSnapshot().replacementState, api.REPLACEMENT_STATES.CONFIRMED);
  assert.strictEqual(replacement.controller.getSnapshot().replacementPending, false);
  assert.strictEqual(replacement.successorSaved.checked, false, "terminal confirmation retained the saved acknowledgement");
  confirmCalls = replacement.transport.inspect().calls.filter((call) => call.operation === "replacementConfirm");
  assert.deepStrictEqual(confirmCalls[0].bodyKeys, ["successorTokenProof"]);
  assert.deepStrictEqual(confirmCalls[1].bodyKeys, ["successorTokenProof"]);
  assert.strictEqual(confirmCalls[0].idempotencyKey, confirmCalls[1].idempotencyKey, "exact confirm recovery did not reuse its operation key");
  const prepareCall = replacement.transport.inspect().calls.find((call) => call.operation === "replacementPrepare");
  assert.notStrictEqual(prepareCall.idempotencyKey, confirmCalls[0].idempotencyKey, "prepare and confirm shared an idempotency key");
  assert(replacement.transport.inspect().calls.every((call) => !call.bodyKeys.some((key) => /old|predecessor/i.test(key))));
  scanDom(replacement.root, [successor], null);

  const acknowledgedCancel = createHarness();
  await login(acknowledgedCancel);
  await prepareReplacement(acknowledgedCancel);
  acknowledgedCancel.successorSaved.checked = true;
  acknowledgedCancel.successorSaved.dispatch("change");
  assert.strictEqual(acknowledgedCancel.successorSaved.checked, true);
  acknowledgedCancel.replacementCancel.dispatch("click");
  await settle();
  assert.strictEqual(acknowledgedCancel.controller.getSnapshot().replacementState, api.REPLACEMENT_STATES.CANCELED);
  assert.strictEqual(acknowledgedCancel.successorSaved.checked, false, "replacement cancellation retained the saved acknowledgement");

  const lostPrepare = createHarness({plans: {
    replacementPrepare: [
      {lostResponse: true},
      {payload: {ok: true, replacement: {replacementId: "mock-lost-prepare", credentialId: "mock-credential-frontend-agent", status: "prepared", predecessorRemainsActive: true}, successorTokenSecret: "RECOVERED-SUCCESSOR-CANARY", mockData: true}},
    ],
    replacementStatus: {payload: {ok: true, replacement: {replacementId: "mock-lost-prepare", credentialId: "mock-credential-frontend-agent", status: "prepared", predecessorRemainsActive: true}, mockData: true}},
  }});
  await login(lostPrepare);
  await prepareReplacement(lostPrepare);
  assert.strictEqual(lostPrepare.controller.getSnapshot().replacementState, api.REPLACEMENT_STATES.OUTCOME_UNKNOWN);
  assert.strictEqual(lostPrepare.controller.getSnapshot().recoveryOperation, "prepare");
  lostPrepare.replacementRetry.dispatch("click");
  await settle();
  assert.strictEqual(lostPrepare.controller.getSnapshot().replacementState, api.REPLACEMENT_STATES.CANCELED);
  assert.strictEqual(lostPrepare.controller.getSnapshot().replacementPending, false);
  assert.strictEqual(lostPrepare.successorToken.value, "");
  scanDom(lostPrepare.root, ["RECOVERED-SUCCESSOR-CANARY"], null);
  const lostPrepareCalls = lostPrepare.transport.inspect().calls.filter((call) => ["replacementPrepare", "replacementStatus", "replacementCancel"].includes(call.operation));
  assert.deepStrictEqual(lostPrepareCalls.map((call) => call.operation), ["replacementPrepare", "replacementPrepare", "replacementStatus", "replacementCancel"]);
  assert.strictEqual(lostPrepareCalls[0].idempotencyKey, lostPrepareCalls[1].idempotencyKey);
  assert.notStrictEqual(lostPrepareCalls[1].idempotencyKey, lostPrepareCalls[3].idempotencyKey);

  const lostCancel = createHarness({plans: {replacementCancel: [{lostResponse: true}]}});
  await login(lostCancel);
  await prepareReplacement(lostCancel);
  lostCancel.replacementCancel.dispatch("click");
  await settle();
  assert.strictEqual(lostCancel.controller.getSnapshot().replacementState, api.REPLACEMENT_STATES.OUTCOME_UNKNOWN);
  lostCancel.replacementRetry.dispatch("click");
  await settle();
  assert.strictEqual(lostCancel.controller.getSnapshot().replacementState, api.REPLACEMENT_STATES.CANCELED);
  const lostCancelCalls = lostCancel.transport.inspect().calls.filter((call) => ["replacementCancel", "replacementStatus"].includes(call.operation));
  assert.deepStrictEqual(lostCancelCalls.map((call) => call.operation), ["replacementCancel", "replacementStatus", "replacementCancel"]);
  assert.strictEqual(lostCancelCalls[0].idempotencyKey, lostCancelCalls[2].idempotencyKey);

  const lifecycle = createHarness();
  await login(lifecycle);
  assert.strictEqual(lifecycle.controller.getSnapshot().agentMasterEnabled, true);
  assert.strictEqual(lifecycle.agentMasterSetting.checked, true);
  lifecycle.agentMasterSetting.checked = false;
  lifecycle.agentMasterSettingForm.dispatch("submit");
  await settle();
  assert.strictEqual(lifecycle.controller.getSnapshot().agentMasterEnabled, false);
  assert.match(lifecycle.agentMasterSettingStatus.textContent, /disabled/i);
  const settingCalls = lifecycle.transport.inspect().calls.filter((call) => call.operation === "agentMasterSettingUpdate");
  assert.strictEqual(settingCalls.length, 1);
  assert.strictEqual(settingCalls[0].csrfAccepted, true);
  assert.deepStrictEqual(settingCalls[0].bodyKeys, ["enabled"]);
  const callsBeforeHide = lifecycle.transport.inspect().calls.length;
  dispatchLifecycle(lifecycle, "pagehide");
  assert.strictEqual(lifecycle.controller.getSnapshot().sessionState, api.SESSION_STATES.LOCKED);
  assert.strictEqual(lifecycle.controller.getSnapshot().rosterCount, 0);
  assert.strictEqual(lifecycle.rosterList.children.length, 0);
  lifecycle.rosterRefresh.dispatch("click");
  await settle();
  assert.strictEqual(lifecycle.transport.inspect().calls.length, callsBeforeHide, "locked UI attempted a protected refresh");
  dispatchLifecycle(lifecycle, "pageshow", {persisted: true});
  assert.strictEqual(lifecycle.controller.getSnapshot().sessionState, api.SESSION_STATES.REVALIDATING);
  assert.strictEqual(lifecycle.protectedEl.hidden, true);
  await settle();
  assert.strictEqual(lifecycle.controller.getSnapshot().rosterCount, 1);
  const inspectCalls = lifecycle.transport.inspect().calls.filter((call) => call.operation === "sessionInspect");
  assert.strictEqual(inspectCalls.length, 1, "BFCache restore did not revalidate exactly once");
  lifecycle.logout.dispatch("click");
  assert.strictEqual(lifecycle.controller.getSnapshot().sessionState, api.SESSION_STATES.LOCKED);
  await settle();
  assert.strictEqual(lifecycle.controller.getSnapshot().membershipCount, 0);

  const sessionExpiry = createHarness({plans: {roster: {error: {code: "human_session_required", status: 401}}}});
  await login(sessionExpiry);
  assert.strictEqual(sessionExpiry.controller.getSnapshot().sessionState, api.SESSION_STATES.LOCKED);
  assert.strictEqual(sessionExpiry.controller.getSnapshot().rosterCount, 0);

  const switcher = createHarness();
  await login(switcher);
  const inspectCountBeforeSwitch = switcher.transport.inspect().calls.filter((call) => call.operation === "sessionInspect").length;
  switcher.membershipList.value = "mock-authority-owner";
  switcher.membershipForm.dispatch("submit");
  assert.strictEqual(switcher.controller.getSnapshot().sessionState, api.SESSION_STATES.SWITCHING_COMPANY);
  assert.strictEqual(switcher.controller.getSnapshot().rosterCount, 0);
  assert.strictEqual(switcher.protectedEl.hidden, true);
  await settle();
  assert.strictEqual(switcher.controller.getSnapshot().rosterCount, 1);
  const switchCalls = switcher.transport.inspect().calls;
  const finalSelection = switchCalls.filter((call) => call.operation === "membershipSelect").slice(-1)[0];
  assert.deepStrictEqual(finalSelection.bodyKeys, ["authorityId"]);
  assert.strictEqual(finalSelection.csrfAccepted, true);
  assert.strictEqual(switchCalls.filter((call) => call.operation === "sessionInspect").length, inspectCountBeforeSwitch, "company selection issued a blind session revalidation");

  for (const harness of [preauthLogin, preauthEnrollment, validation, enrollment, empty, linker, reauthEscape, linkEscape, permission, expiry, cancel, replacement, acknowledgedCancel, lostPrepare, lostCancel, lifecycle, sessionExpiry, switcher]) {
    const inspection = harness.transport.inspect();
    assert.strictEqual(inspection.networkRequestCount, 0);
    assert(inspection.calls.every((call) => call.path.startsWith("/api/matm/human/")));
    assert(inspection.calls.every((call) => !String(call.path).includes("CANARY")));
    assert(inspection.calls.filter((call) => call.csrfPresent).every((call) => call.csrfAccepted), "a protected mutation used stale rotated CSRF authority");
  }

  process.stdout.write(JSON.stringify({
    ok: true,
    scenarioCount: 20,
    centralizedRoutes: Object.keys(api.ROUTES).length,
    zeroNetworkDemo: true,
    zeroSecretRetention: true,
    bfcacheRevalidation: true,
    statusFirstReplacementRecovery: true,
    lostCancelRecovery: true,
    linkCompanyProofFlow: true,
    preauthOnlyMount: true,
    noExistingTokenInput: true,
    cssTargetAndCardContracts: true,
  }) + "\n");
}

main().catch((error) => {
  process.stderr.write(error.stack || String(error));
  process.exitCode = 1;
});
