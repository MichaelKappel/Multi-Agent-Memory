const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const sourcePath = process.argv[2];
if (!sourcePath) {
  throw new Error("Usage: node tests/setup_ui_contract.js static/js/site.js");
}
const source = fs.readFileSync(sourcePath, "utf8");

function node(initial) {
  const listeners = {};
  const attributes = {};
  const classes = new Set();
  return Object.assign({
    attributes,
    checked: false,
    classList: {
      toggle(name, enabled) {
        if (enabled) {
          classes.add(name);
        } else {
          classes.delete(name);
        }
      },
    },
    disabled: false,
    focused: false,
    hidden: false,
    selected: false,
    textContent: "",
    type: "text",
    value: "",
    addEventListener(type, handler) {
      listeners[type] = handler;
    },
    emit(type, event) {
      return listeners[type] ? listeners[type](event || {}) : undefined;
    },
    focus() {
      this.focused = true;
    },
    getAttribute(name) {
      return Object.prototype.hasOwnProperty.call(attributes, name) ? attributes[name] : null;
    },
    removeAttribute(name) {
      delete attributes[name];
    },
    select() {
      this.selected = true;
    },
    setAttribute(name, value) {
      attributes[name] = String(value);
    },
  }, initial || {});
}

async function settle() {
  for (let index = 0; index < 8; index += 1) {
    await Promise.resolve();
  }
  await new Promise((resolve) => setImmediate(resolve));
}

function response(status, payload, rawText) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text() {
      return Promise.resolve(rawText === undefined ? JSON.stringify(payload) : rawText);
    },
  };
}

function createHarness(fetchImpl, options) {
  options = options || {};
  const companyLabel = node({ value: "  Example Company  " });
  const workspaceLabel = node({ value: "  Agent Operations  " });
  const projectLabel = node({ value: "  Memory Integration  " });
  const submit = node({ textContent: "Create workspace" });
  const form = node();
  form.elements = { companyLabel, label: workspaceLabel, projectLabel };
  form.reset = function () {
    companyLabel.value = "";
    workspaceLabel.value = "";
    projectLabel.value = "";
  };
  const status = node();
  const result = node({ hidden: true });
  const resultHeading = node();
  const key = node({ type: "password" });
  const keyToggle = node({ textContent: "Show key" });
  const copyKey = node();
  const keySaved = node();
  const recovery = node({ type: "password" });
  const recoveryToggle = node({ textContent: "Show recovery secret" });
  const copyRecovery = node();
  const recoverySaved = node();
  const continueButton = node({ disabled: true });
  const resetButton = node();
  const accountId = node();
  const companyId = node();
  const workspaceId = node();
  const projectId = node();
  const companyMasterDefaultPath = ".local-secrets/memoryendpoints-company-master.json";
  const selectorMap = {
    "[data-agent-setup-form]": form,
    "[data-agent-setup-submit]": submit,
    "[data-agent-setup-status]": status,
    "[data-agent-setup-result]": result,
    "[data-agent-setup-result-heading]": resultHeading,
    "[data-agent-setup-key]": key,
    "[data-agent-setup-key-toggle]": keyToggle,
    "[data-agent-setup-copy-key]": copyKey,
    "[data-agent-setup-key-saved]": keySaved,
    "[data-agent-setup-recovery]": recovery,
    "[data-agent-setup-recovery-toggle]": recoveryToggle,
    "[data-agent-setup-copy-recovery]": copyRecovery,
    "[data-agent-setup-recovery-saved]": recoverySaved,
    "[data-agent-setup-continue]": continueButton,
    "[data-agent-setup-reset]": resetButton,
    "[data-agent-setup-account-id]": accountId,
    "[data-agent-setup-company-id]": companyId,
    "[data-agent-setup-workspace-id]": workspaceId,
    "[data-agent-setup-project-id]": projectId,
  };
  const root = {
    getAttribute(name) {
      return name === "data-company-master-default-path" ? companyMasterDefaultPath : null;
    },
    querySelector(selector) {
      return selectorMap[selector] || null;
    },
  };
  const fetchCalls = [];
  const copiedValues = [];
  const windowListeners = {};
  const assignedLocations = [];
  const confirmCalls = [];
  const confirmResponses = (options.confirmResponses || []).slice();
  const window = {
    addEventListener(type, handler) {
      windowListeners[type] = handler;
    },
    confirm(message) {
      confirmCalls.push(message);
      return confirmResponses.length ? confirmResponses.shift() : true;
    },
    fetch(url, options) {
      fetchCalls.push({ url, options });
      return fetchImpl(url, options, fetchCalls.length);
    },
    location: {
      assign(url) {
        assignedLocations.push(url);
      },
    },
  };
  const document = {
    querySelector(selector) {
      if (selector === "[data-agent-setup]") {
        return root;
      }
      return null;
    },
  };
  const navigator = {
    clipboard: {
      writeText(value) {
        copiedValues.push(value);
        return Promise.resolve();
      },
    },
  };
  vm.runInNewContext(source, { document, navigator, window }, { filename: sourcePath });
  return {
    accountId,
    assignedLocations,
    companyId,
    companyMasterDefaultPath,
    companyLabel,
    confirmCalls,
    continueButton,
    copiedValues,
    copyKey,
    copyRecovery,
    fetchCalls,
    form,
    key,
    keySaved,
    keyToggle,
    recovery,
    recoverySaved,
    recoveryToggle,
    projectId,
    projectLabel,
    resetButton,
    result,
    resultHeading,
    status,
    submit,
    windowListeners,
    workspaceId,
    workspaceLabel,
  };
}

function submit(harness) {
  let prevented = false;
  harness.form.emit("submit", {
    preventDefault() {
      prevented = true;
    },
  });
  assert.strictEqual(prevented, true);
}

(async function run() {
  const oneTimeValue = ["me", "test", "one", "time", "value"].join("_");
  const recoveryValue = ["me", "test", "exceptional", "recovery"].join("_");
  const successPayload = {
    accountId: "account-1",
    companyMasterTokenSecret: oneTimeValue,
    companyId: "company-1",
    credentialType: "company_master",
    humanOwnerRecoverySecret: recoveryValue,
    idempotencySupported: false,
    projectId: "project-1",
    rawCredentialPersisted: false,
    showCredentialOnce: true,
    workspaceId: "workspace-1",
  };
  const success = createHarness(() => Promise.resolve(response(201, successPayload)));
  submit(success);
  submit(success);
  assert.strictEqual(success.fetchCalls.length, 1, "pending setup must not duplicate");
  await settle();
  assert.strictEqual(
    success.status.textContent.includes(success.companyMasterDefaultPath),
    true,
    success.status.textContent
  );
  submit(success);
  assert.strictEqual(success.fetchCalls.length, 1, "successful setup must remain locked");
  const call = success.fetchCalls[0];
  assert.strictEqual(call.url, "/api/matm/agent-setup/free-account");
  assert.strictEqual(call.options.method, "POST");
  assert.strictEqual(call.options.cache, "no-store");
  assert.strictEqual(call.options.credentials, "same-origin");
  assert.strictEqual(call.options.headers.Accept, "application/json");
  assert.strictEqual(call.options.headers["Content-Type"], "application/json");
  assert.strictEqual(call.options.headers.Authorization, undefined);
  assert.deepStrictEqual(JSON.parse(call.options.body), {
    companyLabel: "Example Company",
    label: "Agent Operations",
    projectLabel: "Memory Integration",
  });
  assert.strictEqual(success.key.value, oneTimeValue);
  assert.strictEqual(success.recovery.value, recoveryValue);
  assert.strictEqual(success.result.hidden, false);
  assert.strictEqual(success.submit.disabled, true);
  assert.strictEqual(success.accountId.textContent, "account-1");
  assert.strictEqual(success.companyId.textContent, "company-1");
  assert.strictEqual(success.workspaceId.textContent, "workspace-1");
  assert.strictEqual(success.projectId.textContent, "project-1");
  assert.strictEqual(success.status.textContent.includes(oneTimeValue), false);
  let beforeUnloadPrevented = false;
  const beforeUnloadEvent = {
    returnValue: undefined,
    preventDefault() {
      beforeUnloadPrevented = true;
    },
  };
  assert.strictEqual(success.windowListeners.beforeunload(beforeUnloadEvent), "");
  assert.strictEqual(beforeUnloadPrevented, true);
  assert.strictEqual(beforeUnloadEvent.returnValue, "");

  success.keyToggle.emit("click");
  assert.strictEqual(success.key.type, "text");
  assert.strictEqual(success.keyToggle.attributes["aria-pressed"], "true");
  success.copyKey.emit("click");
  success.recoveryToggle.emit("click");
  assert.strictEqual(success.recovery.type, "text");
  assert.strictEqual(success.recoveryToggle.attributes["aria-pressed"], "true");
  success.copyRecovery.emit("click");
  await settle();
  assert.deepStrictEqual(success.copiedValues, [oneTimeValue, recoveryValue]);
  assert.strictEqual(success.continueButton.disabled, true);
  success.keySaved.checked = true;
  success.keySaved.emit("change");
  assert.strictEqual(success.continueButton.disabled, true);
  success.recoverySaved.checked = true;
  success.recoverySaved.emit("change");
  assert.strictEqual(success.continueButton.disabled, false);
  beforeUnloadPrevented = false;
  const savedBeforeUnloadEvent = {
    returnValue: undefined,
    preventDefault() {
      beforeUnloadPrevented = true;
    },
  };
  assert.strictEqual(success.windowListeners.beforeunload(savedBeforeUnloadEvent), undefined);
  assert.strictEqual(beforeUnloadPrevented, false);
  assert.strictEqual(savedBeforeUnloadEvent.returnValue, undefined);
  success.continueButton.emit("click");
  assert.strictEqual(success.key.value, "");
  assert.strictEqual(success.recovery.value, "");
  assert.deepStrictEqual(success.assignedLocations, ["/human"]);

  const resetCancelled = createHarness(() => Promise.resolve(response(201, successPayload)), { confirmResponses: [false] });
  submit(resetCancelled);
  await settle();
  resetCancelled.resetButton.emit("click");
  assert.strictEqual(resetCancelled.confirmCalls.length, 1);
  assert.strictEqual(resetCancelled.key.value, oneTimeValue);
  assert.strictEqual(resetCancelled.recovery.value, recoveryValue);
  assert.strictEqual(resetCancelled.result.hidden, false);
  assert.strictEqual(resetCancelled.status.textContent.includes("Reset cancelled"), true);

  const resetConfirmed = createHarness(() => Promise.resolve(response(201, successPayload)), { confirmResponses: [true] });
  submit(resetConfirmed);
  await settle();
  resetConfirmed.resetButton.emit("click");
  assert.strictEqual(resetConfirmed.confirmCalls.length, 1);
  assert.strictEqual(resetConfirmed.key.value, "");
  assert.strictEqual(resetConfirmed.recovery.value, "");
  assert.strictEqual(resetConfirmed.result.hidden, true);

  const pageLifecycle = createHarness(() => Promise.resolve(response(201, successPayload)));
  submit(pageLifecycle);
  await settle();
  pageLifecycle.windowListeners.pagehide({});
  assert.strictEqual(pageLifecycle.key.value, "");
  assert.strictEqual(pageLifecycle.recovery.value, "");

  const bfcache = createHarness(() => Promise.resolve(response(201, successPayload)));
  submit(bfcache);
  await settle();
  bfcache.windowListeners.pageshow({ persisted: true });
  assert.strictEqual(bfcache.key.value, "");
  assert.strictEqual(bfcache.recovery.value, "");
  assert.strictEqual(bfcache.result.hidden, true);

  const safeError = createHarness(() => Promise.resolve(response(422, {
    error: { title: "Invalid labels", detail: "Company label is required." },
  })));
  submit(safeError);
  await settle();
  assert.strictEqual(safeError.status.textContent.includes("Company label is required."), true);
  assert.strictEqual(safeError.submit.disabled, false);

  const safeNoWorkspace = createHarness(() => Promise.resolve(response(503, {
    ok: false,
    safeNoOp: true,
    valuesRedacted: true,
    error: {
      code: "credential_system_not_configured",
      title: "Credential system not configured",
      detail: "Credential system is not configured.",
      safeNoOp: true,
      valuesRedacted: true,
    },
  })));
  submit(safeNoWorkspace);
  await settle();
  assert.strictEqual(safeNoWorkspace.key.value, "");
  assert.strictEqual(safeNoWorkspace.recovery.value, "");
  assert.strictEqual(safeNoWorkspace.submit.disabled, false);
  assert.strictEqual(safeNoWorkspace.status.textContent.includes("no workspace was created"), true);
  submit(safeNoWorkspace);
  assert.strictEqual(safeNoWorkspace.fetchCalls.length, 2, "confirmed no-workspace-created must allow retry after configuration");

  const unknown = createHarness(() => Promise.reject(new Error("network unavailable")));
  submit(unknown);
  await settle();
  assert.strictEqual(unknown.submit.disabled, true);
  assert.strictEqual(unknown.status.textContent.includes("Do not submit again"), true);
  submit(unknown);
  assert.strictEqual(unknown.fetchCalls.length, 1);

  const partial = createHarness(() => Promise.resolve(response(201, {
    companyMasterTokenSecret: oneTimeValue,
    humanOwnerRecoverySecret: recoveryValue,
    showCredentialOnce: true,
  })));
  submit(partial);
  await settle();
  assert.strictEqual(partial.key.value, oneTimeValue, "received key must survive secondary warnings");
  assert.strictEqual(partial.recovery.value, recoveryValue, "received recovery secret must survive secondary warnings");
  assert.strictEqual(partial.result.hidden, false);
  assert.strictEqual(partial.status.textContent.includes("some setup confirmation fields were missing"), true);

  const missingRecovery = createHarness(() => Promise.resolve(response(201, {
    companyMasterTokenSecret: oneTimeValue,
    showCredentialOnce: true,
  })));
  submit(missingRecovery);
  await settle();
  assert.strictEqual(missingRecovery.key.value, "");
  assert.strictEqual(missingRecovery.recovery.value, "");
  assert.strictEqual(missingRecovery.result.hidden, true);
  assert.strictEqual(missingRecovery.submit.disabled, true);
  assert.strictEqual(missingRecovery.status.textContent.includes("outcome is unknown"), true);

  assert.strictEqual(/localStorage|sessionStorage|window\.name|document\.cookie|console\.log/.test(source), false);
  process.stdout.write(JSON.stringify({
    ok: true,
    exactSinglePost: true,
    oneTimeKeyPreservedAndScrubbed: true,
    bothOneTimeValuesPreservedAndScrubbed: true,
    unsavedBeforeUnloadGuarded: true,
    resetRequiresConfirmation: true,
    safeNoOpNoWorkspaceRetry: true,
    outcomeUnknownLocked: true,
    storageAvoided: true,
  }) + "\n");
})().catch((error) => {
  process.stderr.write(error.stack + "\n");
  process.exitCode = 1;
});
