"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const [baseUrlArgument, outputDirectory, playwrightModule, executablePath] = process.argv.slice(2);
if (!baseUrlArgument || !outputDirectory || !playwrightModule || !executablePath) {
  throw new Error("Usage: node multiagentmemory_release_history_browser.cjs <base-url> <output-dir> <playwright-module> <browser>");
}

const { chromium } = require(playwrightModule);
const baseUrl = baseUrlArgument.replace(/\/$/, "");
const expectedOrigin = new URL(baseUrl).origin;
const canonicalUrl = "https://multiagentmemory.com/releases/";
const machineUrl = "https://multiagentmemory.com/releases.json";
const sourceTagUrl = "https://github.com/MichaelKappel/Multi-Agent-Memory/tree/multiagentmemory-site-v1.0.0";

const scenarios = [
  { name: "desktop-1440", viewport: { width: 1440, height: 1000 } },
  { name: "mobile-390", viewport: { width: 390, height: 844 }, isMobile: true },
  { name: "physical-320-text-200", viewport: { width: 320, height: 720 }, isMobile: true, textScale: 2 },
  { name: "forced-colors-1440", viewport: { width: 1440, height: 1000 }, forcedColors: "active" },
  { name: "no-js-mobile-390", viewport: { width: 390, height: 844 }, isMobile: true, javaScriptEnabled: false },
];

function parseRgb(value) {
  const match = value.match(/^rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)$/);
  if (!match) return null;
  return {
    r: Number(match[1]),
    g: Number(match[2]),
    b: Number(match[3]),
    a: match[4] === undefined ? 1 : Number(match[4]),
  };
}

function channel(value) {
  const normalized = value / 255;
  return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
}

function luminance(color) {
  return 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b);
}

function contrastRatio(first, second) {
  const light = Math.max(luminance(first), luminance(second));
  const dark = Math.min(luminance(first), luminance(second));
  return (light + 0.05) / (dark + 0.05);
}

async function contrastViolations(page) {
  const samples = await page.evaluate(() => {
    function effectiveBackground(element) {
      let current = element;
      while (current) {
        const style = getComputedStyle(current);
        const match = style.backgroundColor.match(/^rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)$/);
        if (match && (match[4] === undefined || Number(match[4]) > 0.98)) {
          return style.backgroundColor;
        }
        current = current.parentElement;
      }
      return "rgb(255, 255, 255)";
    }

    return [...document.querySelectorAll("h1, h2, h3, h4, p, dt, dd, a, code, time, strong, .policy-number, .release-deployment-status")]
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
      })
      .map((element) => {
        const style = getComputedStyle(element);
        return {
          label: (element.textContent || "").trim().replace(/\s+/g, " ").slice(0, 90),
          color: style.color,
          background: effectiveBackground(element),
          fontSize: Number.parseFloat(style.fontSize),
          fontWeight: Number.parseInt(style.fontWeight, 10) || 400,
        };
      })
      .filter((item) => item.label);
  });

  return samples.flatMap((sample) => {
    const foreground = parseRgb(sample.color);
    const background = parseRgb(sample.background);
    if (!foreground || !background) return [`unparseable color for ${sample.label}`];
    const largeText = sample.fontSize >= 24 || (sample.fontSize >= 18.66 && sample.fontWeight >= 700);
    const minimum = largeText ? 3 : 4.5;
    const ratio = contrastRatio(foreground, background);
    return ratio + 0.01 < minimum
      ? [`${sample.label}: ${ratio.toFixed(2)} < ${minimum.toFixed(1)}`]
      : [];
  });
}

async function assertAccessibilityTree(page) {
  const session = await page.context().newCDPSession(page);
  await session.send("Accessibility.enable");
  const tree = await session.send("Accessibility.getFullAXTree");
  await session.detach();
  const nodes = tree.nodes.filter((node) => !node.ignored);
  const hasRoleAndName = (role, name) => nodes.some(
    (node) => node.role && node.role.value === role && node.name && node.name.value === name,
  );
  assert(hasRoleAndName("heading", "What shipped, when, and from which exact source."), "release H1 missing from accessibility tree");
  assert(hasRoleAndName("heading", "Evidence-bound release history and public edition catalog"), "release record heading missing from accessibility tree");
  assert(hasRoleAndName("link", "Read the machine ledger"), "machine-ledger action missing from accessibility tree");
  assert(hasRoleAndName("link", "Source tag multiagentmemory-site-v1.0.0"), "source-tag evidence missing from accessibility tree");
  const navigationNodes = nodes
    .filter((node) => node.role && ["navigation", "DisclosureTriangle", "button"].includes(node.role.value))
    .map((node) => `${node.role.value}:${node.name ? node.name.value : ""}`);
  assert(
    hasRoleAndName("navigation", "Primary")
      || hasRoleAndName("DisclosureTriangle", "Menu")
      || hasRoleAndName("button", "Menu"),
    `desktop navigation or compact mobile menu missing from accessibility tree; observed ${navigationNodes.join(", ")}`,
  );
}

async function assertMachineLedger(context) {
  const response = await context.request.get(`${baseUrl}/releases.json`, { failOnStatusCode: false });
  assert.equal(response.status(), 200);
  assert.match(response.headers()["content-type"] || "", /^application\/json\b/);
  const payload = await response.json();
  assert.equal(payload.schema, "multiagentmemory.public-release-history.v1");
  assert.equal(payload.schemaVersion, "1.0");
  assert.equal(payload.site, "MultiAgentMemory.com");
  assert.equal(payload.canonicalUrl, canonicalUrl);
  assert.equal(payload.machineUrl, machineUrl);
  assert.equal(payload.currentProductionWebsiteVersion, "1.0.0");
  assert.equal(payload.publicEditionHistory.currentVersion, "0.2.0");
  assert.equal(payload.publicEditionHistory.releaseCount, 2);
  assert.deepEqual(payload.publicEditionHistory.releases.map((item) => item.version), ["0.2.0", "0.1.0"]);
  assert.deepEqual(payload.publicEditionHistory.releases.map((item) => item.status), ["current", "historical"]);
  assert.equal(payload.releaseCount, 1);
  assert.equal(payload.releases.length, 1);
  const release = payload.releases[0];
  assert.equal(release.version, "1.0.0");
  assert.equal(release.activationDate, "2026-08-29");
  assert.equal(release.activationTimezone, "UTC");
  assert.equal(release.status, "deployed");
  assert.equal(release.title, "Evidence-bound release history and public edition catalog");
  assert.deepEqual(release.changes.map((item) => item.area), [
    "Release history",
    "Discovery and SEO",
    "Responsive accessibility",
    "Public verification",
  ]);
  assert.equal(release.evidence.length, 1);
  assert.equal(release.evidence[0].type, "source_tag");
  assert.equal(release.evidence[0].url, sourceTagUrl);
  assert.equal(payload.recordPolicy.productionActivatedOnly, true);
  assert.equal(payload.recordPolicy.activationDateMustEqualSuccessfulUploadUtcDate, true);
  assert.equal(payload.recordPolicy.explicitReleaseStatusRequired, true);
  assert.equal(payload.recordPolicy.sourceTagRevisionBindingRequired, true);
  assert.equal(payload.recordPolicy.sourceCandidatesPublished, false);
  assert.equal(payload.recordPolicy.plannedWorkPublished, false);
}

async function assertReleaseSurface(page, context, scenario) {
  assert.equal(await page.locator("h1").count(), 1);
  assert.equal(await page.locator("main#main").count(), 1);
  assert.equal(await page.locator('nav[aria-label="Primary"]').count(), 1);
  assert.equal(await page.locator("details.release-mobile-navigation").count(), 1);
  assert.equal(await page.locator("footer").count(), 1);
  assert.equal(await page.locator("[data-release-record]").count(), 1);
  assert.equal(await page.locator("[data-public-edition-record]").count(), 2);
  const record = page.locator('[data-release-record][data-version="1.0.0"][data-release-status="deployed"]');
  assert.equal(await record.count(), 1);
  assert.equal(await page.locator('link[rel="canonical"]').getAttribute("href"), canonicalUrl);
  assert.equal(await page.locator('nav[aria-label="Primary"] a[aria-current="page"]').textContent(), "Releases");
  const mobileMenu = page.locator("details.release-mobile-navigation");
  const mobileMenuSummary = mobileMenu.locator("summary");
  if (scenario.viewport.width <= 760) {
    assert.equal(await mobileMenuSummary.isVisible(), true);
    assert.equal(await mobileMenu.getAttribute("open"), null);
    assert.deepEqual(
      await mobileMenu.locator("nav a").evaluateAll((links) => links.map((link) => link.getAttribute("href"))),
      [
        "/",
        "/docs/how-it-works.html",
        "/docs/api-reference.html",
        "/docs/memory-boundary.html",
        "/releases/",
        "https://github.com/MichaelKappel/Multi-Agent-Memory",
      ],
    );
  } else {
    assert.equal(await mobileMenuSummary.isVisible(), false);
  }
  await page.getByRole("heading", { name: "Evidence-bound release history and public edition catalog", exact: true }).waitFor();
  assert.equal((await record.locator(".release-deployment-status").textContent()).trim(), "Deployed");
  assert.equal(await record.locator("time").getAttribute("datetime"), "2026-08-29");
  assert.equal((await record.locator("time").textContent()).trim(), "August 29, 2026 (UTC)");
  assert.equal(await record.locator(".release-evidence a").getAttribute("href"), sourceTagUrl);

  const structuredData = JSON.parse(await page.locator('script[type="application/ld+json"]').textContent());
  const itemList = structuredData["@graph"].find((item) => item["@type"] === "ItemList");
  assert(itemList, "release ItemList missing");
  assert.equal(itemList.numberOfItems, 1);
  assert.equal(itemList.itemListElement.length, 1);
  assert.equal(itemList.itemListElement[0].item.version, "1.0.0");
  assert.equal(itemList.itemListElement[0].item.datePublished, "2026-08-29");
  assert.equal(itemList.itemListElement[0].item.additionalProperty.value, "deployed");
  assert.deepEqual(itemList.itemListElement[0].item.sameAs, [sourceTagUrl]);

  const executableScripts = await page.locator('script:not([type="application/ld+json"])').count();
  assert.equal(executableScripts, 0, "release page must remain fully useful without JavaScript");

  const targetProblems = await page.evaluate(() => [...document.querySelectorAll(
    "header a, header summary, .breadcrumbs a, .actions a, .release-evidence a, .release-machine-callout a",
  )].flatMap((element) => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    if (style.display === "none" || style.visibility === "hidden" || rect.width === 0 || rect.height === 0) return [];
    return rect.height + 0.5 < 44 || rect.width + 0.5 < 24
      ? [`${(element.textContent || "").trim()}:${rect.width.toFixed(1)}x${rect.height.toFixed(1)}`]
      : [];
  }));
  assert.deepEqual(targetProblems, [], `undersized interactive targets: ${targetProblems.join(", ")}`);

  const geometry = await page.evaluate(() => {
    const root = document.documentElement;
    const body = document.body;
    const viewportWidth = root.clientWidth;
    const outside = [...document.querySelectorAll("body *:not(.skip-link)")].flatMap((element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      if (style.display === "none" || style.visibility === "hidden" || rect.width === 0 || rect.height === 0) return [];
      return rect.left < -1 || rect.right > viewportWidth + 1
        ? [`${element.tagName.toLowerCase()}.${element.className || ""}:${rect.left.toFixed(1)}..${rect.right.toFixed(1)}`]
        : [];
    });
    const clipped = [...document.querySelectorAll("body *")].flatMap((element) => {
      const style = getComputedStyle(element);
      const clippedX = ["hidden", "clip"].includes(style.overflowX) && element.scrollWidth > element.clientWidth + 1;
      const clippedY = ["hidden", "clip"].includes(style.overflowY) && element.scrollHeight > element.clientHeight + 1;
      return clippedX || clippedY ? [`${element.tagName.toLowerCase()}.${element.className || ""}`] : [];
    });
    return {
      bodyOverflow: body.scrollWidth - body.clientWidth,
      rootOverflow: root.scrollWidth - root.clientWidth,
      outside,
      clipped,
      forcedColors: matchMedia("(forced-colors: active)").matches,
    };
  });
  assert(
    geometry.rootOverflow <= 1,
    `${scenario.name} root horizontal overflow: ${geometry.rootOverflow}px; outside=${geometry.outside.join(", ")}`,
  );
  assert(geometry.bodyOverflow <= 1, `${scenario.name} body horizontal overflow: ${geometry.bodyOverflow}px`);
  assert.deepEqual(geometry.outside, [], `${scenario.name} elements outside viewport: ${geometry.outside.join(", ")}`);
  assert.deepEqual(geometry.clipped, [], `${scenario.name} clipped content: ${geometry.clipped.join(", ")}`);
  assert.equal(geometry.forcedColors, scenario.forcedColors === "active");

  if (scenario.forcedColors !== "active") {
    const violations = await contrastViolations(page);
    assert.deepEqual(violations, [], `contrast violations: ${violations.join(" | ")}`);
  }

  await page.keyboard.press("Tab");
  assert.equal(await page.evaluate(() => document.activeElement.classList.contains("skip-link")), true);
  const focusStyle = await page.evaluate(() => {
    const style = getComputedStyle(document.activeElement);
    return { width: Number.parseFloat(style.outlineWidth), style: style.outlineStyle };
  });
  assert(focusStyle.width >= 2 && focusStyle.style !== "none", "skip link lacks a visible focus indicator");
  await page.evaluate(() => document.activeElement.blur());

  if (scenario.viewport.width <= 760) {
    await mobileMenuSummary.focus();
    const menuFocusStyle = await mobileMenuSummary.evaluate((element) => {
      const style = getComputedStyle(element);
      return { width: Number.parseFloat(style.outlineWidth), style: style.outlineStyle };
    });
    assert(menuFocusStyle.width >= 2 && menuFocusStyle.style !== "none", "mobile menu lacks a visible focus indicator");
    await page.evaluate(() => document.activeElement.blur());
  }

  await assertAccessibilityTree(page);
  await assertMachineLedger(context);
}

(async () => {
  fs.mkdirSync(outputDirectory, { recursive: true });
  const browser = await chromium.launch({ executablePath, headless: true });
  const results = [];
  try {
    for (const scenario of scenarios) {
      const context = await browser.newContext({
        viewport: scenario.viewport,
        isMobile: Boolean(scenario.isMobile),
        javaScriptEnabled: scenario.javaScriptEnabled !== false,
        forcedColors: scenario.forcedColors || "none",
        reducedMotion: "reduce",
      });
      const page = await context.newPage();
      const diagnostics = [];
      const unexpectedRequests = [];
      page.on("console", (message) => {
        if (["error", "warning"].includes(message.type())) diagnostics.push(`${message.type()}: ${message.text()}`);
      });
      page.on("pageerror", (error) => diagnostics.push(`pageerror: ${error.message}`));
      page.on("request", (request) => {
        const requestUrl = new URL(request.url());
        if (requestUrl.origin !== expectedOrigin || request.method() !== "GET") {
          unexpectedRequests.push(`${request.method()} ${request.url()}`);
        }
      });

      const response = await page.goto(`${baseUrl}/releases/`, { waitUntil: "networkidle" });
      assert(response, "release navigation returned no response");
      assert.equal(response.status(), 200);
      assert.match(response.headers()["content-type"] || "", /^text\/html\b/);
      if (scenario.textScale) {
        await page.addStyleTag({ content: `html { font-size: ${scenario.textScale * 100}% !important; }` });
      }

      await assertReleaseSurface(page, context, scenario);
      assert.deepEqual(diagnostics, [], `browser diagnostics: ${diagnostics.join(" | ")}`);
      assert.deepEqual(unexpectedRequests, [], `unexpected requests: ${unexpectedRequests.join(" | ")}`);

      const screenshot = path.join(outputDirectory, `${scenario.name}.png`);
      await page.screenshot({ path: screenshot, fullPage: true });
      results.push({
        name: scenario.name,
        screenshot,
        viewport: scenario.viewport,
        textScale: scenario.textScale || 1,
        forcedColors: scenario.forcedColors || "none",
        javaScriptEnabled: scenario.javaScriptEnabled !== false,
      });
      await context.close();
    }
  } finally {
    await browser.close();
  }
  process.stdout.write(JSON.stringify({ ok: true, scenarioCount: results.length, scenarios: results }));
})().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
