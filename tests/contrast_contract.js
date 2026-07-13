"use strict";

const assert = require("assert");
const fs = require("fs");

const cssPath = process.argv[2];
if (!cssPath) {
  throw new Error("Usage: node tests/contrast_contract.js static/css/site.css");
}
const css = fs.readFileSync(cssPath, "utf8");

assert(css.includes("width: min(100%, calc(100vw - 20px))"), "console and knowledge shells must stay liquid");
assert(!css.includes("max-width: 1180px"), "console shell must not return to a narrow fixed desktop cap");
assert(css.includes("grid-template-columns: repeat(auto-fit, minmax(172px, 1fr))"), "operator metrics must auto-fit available space");
assert(css.includes("[data-console-card-action]"), "actionable console cards must have visible affordances");
assert(css.includes("[data-console-badge-action]"), "actionable count badges must have visible affordances");
assert(css.includes("--topbar-sticky-height"), "sticky console controls must share a topbar offset token");

function variable(name) {
  const match = css.match(new RegExp("--" + name + ":\\s*(#[0-9a-fA-F]{6})"));
  if (!match) {
    throw new Error("Missing color variable --" + name);
  }
  return match[1];
}

function channel(value) {
  const normalized = value / 255;
  return normalized <= 0.04045
    ? normalized / 12.92
    : Math.pow((normalized + 0.055) / 1.055, 2.4);
}

function luminance(hex) {
  const value = hex.slice(1);
  return 0.2126 * channel(parseInt(value.slice(0, 2), 16))
    + 0.7152 * channel(parseInt(value.slice(2, 4), 16))
    + 0.0722 * channel(parseInt(value.slice(4, 6), 16));
}

function contrast(foreground, background) {
  const lighter = Math.max(luminance(foreground), luminance(background));
  const darker = Math.min(luminance(foreground), luminance(background));
  return (lighter + 0.05) / (darker + 0.05);
}

const pairs = [
  { name: "body ink", foreground: variable("ink"), background: variable("surface") },
  { name: "muted text", foreground: variable("muted"), background: variable("surface") },
  { name: "eyebrow", foreground: variable("accent-2"), background: variable("surface") },
  { name: "primary action", foreground: "#ffffff", background: variable("accent") },
  { name: "primary action deep", foreground: "#ffffff", background: variable("accent-deep") },
  { name: "warm demo action", foreground: "#15323a", background: variable("warm") },
];

const indicatorPairs = [
  { name: "focus ring on surface", foreground: "#0b7285", background: variable("surface") },
  { name: "focus ring on panel", foreground: "#0b7285", background: variable("panel") },
  { name: "knowledge focus ring on accent soft", foreground: "#0b7285", background: variable("accent-soft") },
  { name: "skip-link focus ring", foreground: variable("warm"), background: variable("accent-deep") },
];

let minimum = Infinity;
pairs.forEach((pair) => {
  pair.ratio = contrast(pair.foreground, pair.background);
  minimum = Math.min(minimum, pair.ratio);
  assert(
    pair.ratio >= 4.5,
    pair.name + " contrast " + pair.ratio.toFixed(2) + " is below WCAG AA for normal text"
  );
});

let minimumIndicator = Infinity;
indicatorPairs.forEach((pair) => {
  pair.ratio = contrast(pair.foreground, pair.background);
  minimumIndicator = Math.min(minimumIndicator, pair.ratio);
  assert(
    pair.ratio >= 3,
    pair.name + " contrast " + pair.ratio.toFixed(2) + " is below the WCAG non-text contrast threshold"
  );
});

process.stdout.write(JSON.stringify({
  ok: true,
  minimumContrast: Number(minimum.toFixed(2)),
  minimumIndicatorContrast: Number(minimumIndicator.toFixed(2)),
  pairCount: pairs.length + indicatorPairs.length,
}) + "\n");
