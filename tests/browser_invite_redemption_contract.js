"use strict";

const assert = require("node:assert");
const fs = require("node:fs");
const vm = require("node:vm");
const {webcrypto} = require("node:crypto");

const scriptPath = process.argv[2];
if (!scriptPath) {
  throw new Error("Usage: node tests/browser_invite_redemption_contract.js static/js/site.js");
}
const source = fs.readFileSync(scriptPath, "utf8");

function clone(value) {
  return value === undefined ? undefined : structuredClone(value);
}

class FakeIndexedDB {
  constructor() {
    this.records = new Map();
    this.created = false;
    this.pauseNextWrite = false;
    this.pausedWrites = [];
    this.cloneProofs = [];
  }

  open() {
    const request = {};
    setImmediate(() => {
      const database = new FakeDatabase(this);
      request.result = database;
      if (!this.created) {
        this.created = true;
        if (request.onupgradeneeded) request.onupgradeneeded({target: request});
      }
      if (request.onsuccess) request.onsuccess({target: request});
    });
    return request;
  }

  releasePausedWrites() {
    const pending = this.pausedWrites.splice(0);
    for (const complete of pending) complete();
  }
}

class FakeDatabase {
  constructor(owner) {
    this.owner = owner;
    this.objectStoreNames = {contains: () => owner.created};
  }

  createObjectStore() {
    return {};
  }

  transaction(_storeName, mode) {
    return new FakeTransaction(this.owner, mode);
  }

  close() {}
}

class FakeTransaction {
  constructor(owner, mode) {
    this.owner = owner;
    this.mode = mode;
    this.operations = [];
    this.oncomplete = null;
    this.onerror = null;
    this.onabort = null;
    setImmediate(() => this.scheduleCompletion());
  }

  objectStore() {
    return {
      get: (id) => {
        const request = {result: clone(this.owner.records.get(id))};
        return request;
      },
      put: (value) => {
        const copied = clone(value);
        this.owner.cloneProofs.push({original: value, copied});
        this.operations.push({kind: "put", id: copied.id, value: copied});
      },
      clear: () => {
        this.operations.push({kind: "clear"});
      },
    };
  }

  scheduleCompletion() {
    const finish = () => {
      for (const operation of this.operations) {
        if (operation.kind === "clear") this.owner.records.clear();
        if (operation.kind === "put") this.owner.records.set(operation.id, operation.value);
      }
      if (this.oncomplete) this.oncomplete({target: this});
    };
    if (this.mode === "readwrite" && this.owner.pauseNextWrite) {
      this.owner.pauseNextWrite = false;
      this.owner.pausedWrites.push(finish);
      return;
    }
    finish();
  }
}

class Element {
  constructor() {
    this.attributes = {};
    this.checked = false;
    this.classList = {toggle() {}};
    this.disabled = false;
    this.hidden = false;
    this.listeners = {};
    this.textContent = "";
    this.type = "";
    this.value = "";
    this.focusCount = 0;
  }

  addEventListener(type, listener) {
    (this.listeners[type] ||= []).push(listener);
  }

  dispatch(type, values) {
    const event = Object.assign({
      target: this,
      preventDefault() { this.defaultPrevented = true; },
    }, values || {});
    for (const listener of this.listeners[type] || []) listener(event);
    return event;
  }

  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null; }
  removeAttribute(name) { delete this.attributes[name]; }
  focus() { this.focusCount += 1; }
  select() {}
}

function createResponse(ok, payload, status) {
  return {
    ok,
    status: status || (ok ? 200 : 400),
    text: async () => JSON.stringify(payload),
  };
}

function createHarness(options) {
  options = options || {};
  const indexedDB = options.indexedDB;
  const fetchCalls = [];
  const lifecycle = {};
  const assignedLocations = [];
  const selectors = new Map();
  const root = new Element();
  root.querySelector = (selector) => selectors.get(selector) || null;
  const add = (selector) => {
    const element = new Element();
    selectors.set(selector, element);
    return element;
  };
  const heading = add("[data-human-invite-redemption-heading]");
  const form = add("[data-human-invite-redemption-form]");
  const submit = add("[data-human-invite-redemption-submit]");
  const status = add("[data-human-invite-redemption-status]");
  const result = add("[data-human-invite-redemption-result]");
  const resultHeading = add("[data-human-invite-redemption-result-heading]");
  const token = add("[data-human-invite-token]");
  token.type = "password";
  const tokenToggle = add("[data-human-invite-token-toggle]");
  const tokenCopy = add("[data-human-invite-token-copy]");
  const tokenSaved = add("[data-human-invite-token-saved]");
  const tokenContinue = add("[data-human-invite-token-continue]");
  const tokenClear = add("[data-human-invite-token-clear]");

  const location = {
    pathname: "/agent-setup",
    search: "",
    hash: options.inviteSecret ? "#invite=" + encodeURIComponent(options.inviteSecret) : "",
    origin: "https://intranet.example.test",
    assign(value) { assignedLocations.push(value); },
  };
  const history = {
    replaceState(_state, _title, value) {
      location.hash = "";
      location.lastReplacement = value;
    },
  };
  const documentRef = {
    body: {classList: {add() {}}},
    querySelector(selector) {
      return selector === "[data-human-invite-redemption]" ? root : null;
    },
    addEventListener() {},
  };
  const fetchImplementation = options.fetch || (async () => createResponse(true, {}));
  const windowRef = {
    crypto: options.crypto === false ? undefined : webcrypto,
    indexedDB: options.storageUnavailable ? undefined : indexedDB,
    TextEncoder,
    TextDecoder,
    location,
    history,
    navigator: {},
    btoa(value) { return Buffer.from(value, "binary").toString("base64"); },
    addEventListener(type, listener) { (lifecycle[type] ||= []).push(listener); },
    fetch(pathname, requestOptions) {
      fetchCalls.push({pathname, options: clone(requestOptions)});
      return fetchImplementation(pathname, requestOptions);
    },
  };
  windowRef.window = windowRef;
  const sandbox = {
    Array,
    Buffer,
    Error,
    JSON,
    Object,
    Promise,
    String,
    TextDecoder,
    TextEncoder,
    Uint8Array,
    console,
    document: documentRef,
    navigator: windowRef.navigator,
    setTimeout,
    clearTimeout,
    window: windowRef,
  };
  vm.runInNewContext(source, sandbox, {filename: scriptPath});
  return {
    assignedLocations,
    fetchCalls,
    form,
    heading,
    lifecycle,
    result,
    resultHeading,
    status,
    submit,
    token,
    tokenClear,
    tokenContinue,
    tokenCopy,
    tokenSaved,
    tokenToggle,
  };
}

async function waitFor(predicate, message) {
  for (let index = 0; index < 400; index += 1) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 2));
  }
  throw new Error(message || "timed out waiting for browser contract state");
}

function dispatchLifecycle(harness, type, values) {
  for (const listener of harness.lifecycle[type] || []) {
    listener(Object.assign({persisted: false}, values || {}));
  }
}

function successPayload(requestBody) {
  const credentialId = requestBody.candidateAgentTokenSecret.split(".")[1];
  return {
    ok: true,
    candidateCredentialAccepted: true,
    credentialReturnedOnce: false,
    idempotencySupported: true,
    replaySafe: true,
    rawCredentialExposed: false,
    principal: {
      agentId: "browser-agent",
      displayName: "Browser Agent",
      credentialType: "agent_token",
      credentialId,
      grant: {immutable: true, scopeType: "project", scopeId: "project-one"},
      resourceContext: {workspaceId: "workspace-one", projectId: "project-one"},
    },
  };
}

async function run() {
  const inviteSecret = "me_invite_v1.browserinvite." + "A".repeat(43);
  const durableStore = new FakeIndexedDB();
  durableStore.pauseNextWrite = true;
  const lostCalls = [];
  const first = createHarness({
    indexedDB: durableStore,
    inviteSecret,
    fetch: async (_pathname, requestOptions) => {
      lostCalls.push(clone(requestOptions));
      throw new Error("simulated lost response");
    },
  });

  await waitFor(() => durableStore.pausedWrites.length === 1, "durable write transaction never reached commit");
  assert.strictEqual(durableStore.records.size, 0, "uncommitted IndexedDB writes became visible");
  assert.strictEqual(first.fetchCalls.length, 0, "network ran before the durable transaction completed");
  assert.strictEqual(first.submit.disabled, true, "redemption enabled before durable transaction completion");
  durableStore.releasePausedWrites();
  await waitFor(() => first.submit.disabled === false, "redemption did not enable after transaction completion and readback");

  const keyRecord = durableStore.records.get("active-key");
  const stageRecord = durableStore.records.get("active-stage");
  assert(keyRecord && stageRecord, "encrypted durable records were not committed");
  assert.strictEqual(keyRecord.key.extractable, false, "durable CryptoKey became extractable");
  await assert.rejects(webcrypto.subtle.exportKey("raw", keyRecord.key), /extractable|InvalidAccess/i);
  const keyCloneProof = durableStore.cloneProofs.find((proof) => proof.original.id === "active-key");
  assert(keyCloneProof, "CryptoKey was not sent through structured-clone storage");
  assert.notStrictEqual(keyCloneProof.original, keyCloneProof.copied, "record was retained by reference instead of structured cloning");
  assert.notStrictEqual(keyCloneProof.original.key, keyCloneProof.copied.key, "CryptoKey was retained by reference instead of structured cloning");
  assert.strictEqual(keyCloneProof.copied.key.extractable, false, "structured-cloned CryptoKey changed extractability");
  assert.deepStrictEqual(
    Object.keys(stageRecord).sort(),
    ["algorithm", "ciphertext", "id", "iv", "keyId", "schemaVersion"].sort(),
    "durable stage contains fields beyond ciphertext metadata",
  );
  const serializedDurableState = JSON.stringify(Array.from(durableStore.records.entries()));
  assert(!serializedDurableState.includes(inviteSecret), "plaintext invitation leaked to durable storage");
  assert(!serializedDurableState.includes("candidateAgentTokenSecret"), "plaintext candidate field leaked to durable storage");
  assert(!serializedDurableState.includes("idempotencyKey"), "plaintext retry-key field leaked to durable storage");

  first.form.dispatch("submit");
  await waitFor(() => lostCalls.length === 1 && first.submit.disabled === false, "lost-response path did not retain an exact retry");
  const firstRequest = lostCalls[0];
  const firstBody = firstRequest.body;
  const firstKey = firstRequest.headers["Idempotency-Key"];
  assert.strictEqual(durableStore.records.size, 2, "unknown outcome discarded durable recovery state");
  assert(first.status.textContent.includes("same encrypted candidate and retry key"), "unknown outcome did not advertise exact recovery");

  dispatchLifecycle(first, "pagehide");
  assert.strictEqual(durableStore.records.size, 2, "page exit discarded durable recovery state");
  const replayCalls = [];
  const reloaded = createHarness({
    indexedDB: durableStore,
    fetch: async (_pathname, requestOptions) => {
      replayCalls.push(clone(requestOptions));
      return createResponse(true, successPayload(JSON.parse(requestOptions.body)));
    },
  });
  await waitFor(() => reloaded.submit.textContent === "Resume exact redemption" && !reloaded.submit.disabled, "reload did not recover the durable request");
  reloaded.form.dispatch("submit");
  await waitFor(() => replayCalls.length === 1 && !reloaded.result.hidden, "reloaded exact request did not reach verified success");
  assert.strictEqual(replayCalls[0].body, firstBody, "lost-response retry changed the request body");
  assert.strictEqual(replayCalls[0].headers["Idempotency-Key"], firstKey, "lost-response retry changed the idempotency key");
  assert.strictEqual(reloaded.token.value, JSON.parse(firstBody).candidateAgentTokenSecret, "verified candidate was not presented as the one-time credential");
  assert.strictEqual(durableStore.records.size, 2, "verified response discarded state before the user confirmed saving it");
  reloaded.tokenSaved.checked = true;
  reloaded.tokenSaved.dispatch("change");
  reloaded.tokenContinue.dispatch("click");
  await waitFor(() => durableStore.records.size === 0, "confirmed saved credential did not retire durable state");
  assert.deepStrictEqual(reloaded.assignedLocations, ["/console"], "successful disposition did not continue safely");

  let unavailableFetches = 0;
  const unavailable = createHarness({
    indexedDB: new FakeIndexedDB(),
    inviteSecret,
    storageUnavailable: true,
    fetch: async () => { unavailableFetches += 1; return createResponse(true, {}); },
  });
  await waitFor(() => unavailable.submit.textContent === "Managed installer required", "secure-storage failure did not lock redemption");
  unavailable.form.dispatch("submit");
  await new Promise((resolve) => setImmediate(resolve));
  assert.strictEqual(unavailableFetches, 0, "secure-storage failure allowed a network request");

  const terminalStore = new FakeIndexedDB();
  const terminal = createHarness({
    indexedDB: terminalStore,
    inviteSecret,
    fetch: async () => createResponse(false, {error: {code: "invalid_invite", detail: "Invitation is invalid."}}, 404),
  });
  await waitFor(() => !terminal.submit.disabled, "terminal scenario did not durably stage");
  terminal.form.dispatch("submit");
  await waitFor(() => terminalStore.records.size === 0, "terminal disposition did not retire durable state");
  assert.strictEqual(terminal.submit.textContent, "Invitation unavailable");

  const payload = {
    ok: true,
    assertions: {
      transactionCompletionBeforeNetwork: true,
      nonExtractableCryptoKeyStructuredClone: true,
      ciphertextOnlyDurableStage: true,
      reloadRecovery: true,
      noFetchWithoutSecureStorage: true,
      exactLostResponseRetry: true,
      cleanupOnlyAfterVerifiedOrTerminalDisposition: true,
    },
    networkCalls: first.fetchCalls.length + reloaded.fetchCalls.length + terminal.fetchCalls.length,
  };
  process.stdout.write(JSON.stringify(payload));
}

run().catch((error) => {
  process.stderr.write((error && error.stack) ? error.stack : String(error));
  process.exitCode = 1;
});
