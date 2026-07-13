"use strict";

const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync(process.argv[2], "utf8");

class ClassList {
  constructor() { this.values = new Set(); }
  add(value) { this.values.add(value); }
  remove(value) { this.values.delete(value); }
  toggle(value, force) {
    if (force === undefined) force = !this.values.has(value);
    if (force) this.values.add(value);
    else this.values.delete(value);
    return force;
  }
  contains(value) { return this.values.has(value); }
}

class Element {
  constructor(tagName) {
    this.tagName = String(tagName || "div").toUpperCase();
    this.children = [];
    this.attributes = {};
    this.listeners = {};
    this.dataset = {};
    this.classList = new ClassList();
    this.hidden = false;
    this.textContent = "";
    this.value = "";
    this.elements = {};
  }
  get firstChild() { return this.children[0] || null; }
  appendChild(child) { this.children.push(child); child.parentNode = this; return child; }
  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index >= 0) this.children.splice(index, 1);
    return child;
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null; }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
  dispatch(type, values) {
    const event = Object.assign({preventDefault() {}, target: this}, values || {});
    (this.listeners[type] || []).forEach((listener) => listener(event));
  }
  focus() { this.focused = true; }
  scrollIntoView() { this.scrolled = true; }
}

function formData(form) {
  return {
    get(name) {
      const control = form.elements[name];
      return control ? control.value : "";
    },
  };
}

const authForm = new Element("form");
authForm.elements = {
  workspaceId: {value: "mock-workspace-test"},
  workspaceKey: {value: ["workspace", "key", "value"].join("-")},
};
const searchForm = new Element("form");
searchForm.elements = {
  q: {value: ""},
  scope: {value: ""},
  category: {value: ""},
  knowledgeStatus: {value: ""},
  authorityLevel: {value: ""},
};
const refreshButton = new Element("button");
const privateEl = new Element("div");
privateEl.hidden = true;
const layoutEl = new Element("section");
const treeEl = new Element("aside");
const articleEl = new Element("article");
const resultsEl = new Element("aside");
const statusEl = new Element("output");
const pageMode = new Element("button");
pageMode.dataset.knowledgeMode = "pages";
pageMode.setAttribute("aria-pressed", "true");
const webMode = new Element("button");
webMode.dataset.knowledgeMode = "web";
webMode.setAttribute("aria-pressed", "false");

const selectorMap = new Map([
  ["[data-knowledge-auth]", authForm],
  ["[data-knowledge-search]", searchForm],
  ["[data-knowledge-refresh]", refreshButton],
  ["[data-knowledge-private]", privateEl],
  [".knowledge-layout", layoutEl],
  ["[data-knowledge-tree]", treeEl],
  ["[data-knowledge-article]", articleEl],
  ["[data-knowledge-results]", resultsEl],
  ["[data-knowledge-status]", statusEl],
]);
const app = new Element("section");
app.dataset.knowledgeDemoMode = "false";
app.dataset.initialRoute = "";
app.querySelector = (selector) => selectorMap.get(selector) || null;
app.querySelectorAll = (selector) => selector === "[data-knowledge-mode]" ? [pageMode, webMode] : [];

const windowListeners = {};
const fetchCalls = [];
const windowObject = {
  MemoryEndpointsMockTransport: null,
  location: {pathname: "/knowledge"},
  history: {pushState() {}},
  matchMedia() { return {matches: false}; },
  addEventListener(type, listener) { (windowListeners[type] ||= []).push(listener); },
};

const context = {
  document: {
    querySelector(selector) { return selector === "[data-knowledge-app]" ? app : null; },
    createElement(tagName) { return new Element(tagName); },
  },
  window: windowObject,
  FormData: formData,
  URLSearchParams,
  Promise,
  Error,
  console: {log() { throw new Error("knowledge UI logged a credential"); }},
  fetch(url, options) {
    fetchCalls.push({url, options});
    const pathname = String(url).split("?", 1)[0];
    const payload = pathname === "/api/matm/knowledge-tree"
      ? {ok: true, tree: {levels: []}}
      : {ok: true, items: [], count: 0};
    return Promise.resolve({
      ok: true,
      status: 200,
      statusText: "OK",
      json() { return Promise.resolve(payload); },
    });
  },
};
context.globalThis = context;
vm.createContext(context);
vm.runInContext(source, context, {filename: process.argv[2]});

async function flush() {
  for (let index = 0; index < 8; index += 1) await Promise.resolve();
}

function dispatchWindow(type, values) {
  (windowListeners[type] || []).forEach((listener) => listener(Object.assign({persisted: false}, values || {})));
}

async function main() {
  const firstKey = authForm.elements.workspaceKey.value;
  authForm.dispatch("submit");
  await flush();

  if (fetchCalls.length !== 1 || !fetchCalls[0].options.headers.Authorization.endsWith(firstKey)) {
    throw new Error("authenticated knowledge request did not use the entered key exactly once");
  }
  if (authForm.elements.workspaceKey.value !== "" || privateEl.hidden) {
    throw new Error("knowledge authentication did not clear the visible key or reveal the private surface");
  }

  webMode.dispatch("click");
  await flush();
  if (webMode.getAttribute("aria-pressed") !== "true" || pageMode.getAttribute("aria-pressed") !== "false") {
    throw new Error("knowledge search-mode button group did not update aria-pressed");
  }

  const fetchCountBeforeHide = fetchCalls.length;
  dispatchWindow("pagehide");
  if (!privateEl.hidden || authForm.elements.workspaceId.value !== "" || authForm.elements.workspaceKey.value !== "") {
    throw new Error("pagehide did not scrub the knowledge credential and private UI");
  }
  refreshButton.dispatch("click");
  await flush();
  if (fetchCalls.length !== fetchCountBeforeHide) {
    throw new Error("scrubbed knowledge state attempted another authenticated request");
  }

  authForm.elements.workspaceId.value = "mock-workspace-test";
  authForm.elements.workspaceKey.value = ["second", "workspace", "value"].join("-");
  authForm.dispatch("submit");
  await flush();
  dispatchWindow("pagehide");
  dispatchWindow("pageshow", {persisted: true});
  if (!privateEl.hidden || !statusEl.textContent.includes("Workspace key cleared")) {
    throw new Error("BFCache restore did not remain locked after credential scrub");
  }

  process.stdout.write(JSON.stringify({
    ok: true,
    visibleKeyCleared: true,
    pagehideScrubbed: true,
    bfcacheRelocked: true,
    modeSemantics: "button-group",
  }));
}

main().catch((error) => {
  process.stderr.write(error.stack || String(error));
  process.exitCode = 1;
});
