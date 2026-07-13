const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const sourcePath = process.argv[2];
if (!sourcePath) {
  throw new Error("Usage: node tests/site_nav_contract.js static/js/site.js");
}
const source = fs.readFileSync(sourcePath, "utf8");

assert(source.includes("function makeActionableCard"), "console summaries must use actionable card helper");
assert(source.includes("function makeActionableBadge"), "count badges must support actionable workflow targets");
assert(source.includes("data-console-card-action"), "console metric/checklist cards must expose workflow actions");
assert(source.includes("data-console-badge-action"), "count badges must expose workflow actions where drilldown exists");
assert(source.includes("function updateWorkflowSwitchLabels"), "workflow switcher must surface live counts");
assert(source.includes("Open current-message lanes"), "message metric must drill into the current-message workflow");

function eventTarget(attributes) {
  const listeners = {};
  const attrs = Object.assign({}, attributes || {});
  return {
    attrs,
    focused: false,
    addEventListener(type, handler) {
      listeners[type] = handler;
    },
    emit(type, event) {
      if (listeners[type]) {
        listeners[type](event || {});
      }
    },
    focus() {
      this.focused = true;
    },
    getAttribute(name) {
      return Object.prototype.hasOwnProperty.call(attrs, name) ? attrs[name] : null;
    },
    setAttribute(name, value) {
      attrs[name] = String(value);
    },
    removeAttribute(name) {
      delete attrs[name];
    },
  };
}

function runHarness(pathname, includeNavigation) {
  const documentListeners = {};
  const bodyClasses = new Set();
  const links = [
    eventTarget({ href: "/tour", class: "site-nav-demo" }),
    eventTarget({ href: "/docs" }),
    eventTarget({ href: "/console" }),
    eventTarget({ href: "/knowledge" }),
  ];
  const toggle = eventTarget({ "aria-expanded": "false" });
  const summary = eventTarget();
  const ecosystem = {
    open: false,
    contains(target) {
      return target === this || target === summary;
    },
    querySelector(selector) {
      return selector === "summary" ? summary : null;
    },
  };
  const nav = eventTarget();
  nav.querySelectorAll = function (selector) {
    return selector === 'a[href^="/"]' ? links : [];
  };
  nav.querySelector = function (selector) {
    return selector === ".ecosystem-menu[open]" && ecosystem.open ? ecosystem : null;
  };

  const document = {
    body: {
      classList: {
        add(name) {
          bodyClasses.add(name);
        },
      },
    },
    querySelector(selector) {
      if (!includeNavigation) {
        return null;
      }
      if (selector === "[data-site-nav]") {
        return nav;
      }
      if (selector === "[data-site-nav-toggle]") {
        return toggle;
      }
      return null;
    },
    addEventListener(type, handler) {
      documentListeners[type] = handler;
    },
  };
  const sandbox = {
    document,
    window: { location: { pathname } },
  };
  vm.runInNewContext(source, sandbox, { filename: sourcePath });
  return { bodyClasses, documentListeners, ecosystem, links, nav, summary, toggle };
}

const harness = runHarness("/tour/knowledge", true);
assert(harness.bodyClasses.has("site-nav-ready"));
assert.strictEqual(harness.links[0].attrs["aria-current"], "page");
assert.strictEqual(harness.links.filter((link) => link.attrs["aria-current"] === "page").length, 1);

harness.toggle.emit("click");
assert.strictEqual(harness.nav.attrs["data-open"], "true");
assert.strictEqual(harness.toggle.attrs["aria-expanded"], "true");

harness.ecosystem.open = true;
harness.documentListeners.keydown({ key: "Escape" });
assert.strictEqual(harness.nav.attrs["data-open"], undefined);
assert.strictEqual(harness.toggle.attrs["aria-expanded"], "false");
assert.strictEqual(harness.ecosystem.open, false);
assert.strictEqual(harness.toggle.focused, true);

harness.toggle.emit("click");
harness.links[1].emit("click");
assert.strictEqual(harness.nav.attrs["data-open"], undefined);

harness.ecosystem.open = true;
harness.documentListeners.click({ target: {} });
assert.strictEqual(harness.ecosystem.open, false);

const knowledgeHarness = runHarness("/knowledge", true);
assert.strictEqual(knowledgeHarness.links[3].attrs["aria-current"], "page");
assert.strictEqual(knowledgeHarness.links[0].attrs["aria-current"], undefined);

const missingNavigationHarness = runHarness("/", false);
assert.strictEqual(missingNavigationHarness.bodyClasses.has("site-nav-ready"), false);

process.stdout.write(JSON.stringify({
  ok: true,
  demoSubrouteActive: true,
  escapeClosesAndRestoresFocus: true,
  progressiveEnhancementGuarded: true,
}) + "\n");
