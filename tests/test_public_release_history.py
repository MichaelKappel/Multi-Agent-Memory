import copy
import json
import re
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

from scripts import render_multiagentmemory_release_history as release_renderer


ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = ROOT / "sites" / "multiagentmemory.com"
RELEASE_PAGE = SITE_ROOT / "releases" / "index.html"
RELEASE_LEDGER = SITE_ROOT / "releases.json"
CANONICAL_RELEASE_URL = "https://multiagentmemory.com/releases/"
MACHINE_RELEASE_URL = "https://multiagentmemory.com/releases.json"
SOURCE_TAG_URL = "https://github.com/MichaelKappel/Multi-Agent-Memory/tree/multiagentmemory-site-v1.0.0"


class ReleasePageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.h1_count = 0
        self.canonicals = []
        self.json_ld_parts = []
        self._inside_json_ld = False
        self.release_records = 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "h1":
            self.h1_count += 1
        if tag == "link" and values.get("rel") == "canonical":
            self.canonicals.append(values.get("href"))
        if tag == "script" and values.get("type") == "application/ld+json":
            self._inside_json_ld = True
        if "data-release-record" in values:
            self.release_records += 1

    def handle_endtag(self, tag):
        if tag == "script" and self._inside_json_ld:
            self._inside_json_ld = False

    def handle_data(self, data):
        if self._inside_json_ld:
            self.json_ld_parts.append(data)


def all_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from all_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from all_strings(child)


class PublicReleaseHistoryTests(unittest.TestCase):
    def load_ledger(self):
        return json.loads(RELEASE_LEDGER.read_text(encoding="utf-8"))

    def test_machine_ledger_is_deterministic_and_exactly_populated(self):
        raw = RELEASE_LEDGER.read_text(encoding="utf-8")
        payload = json.loads(raw)
        self.assertEqual(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", raw)
        self.assertEqual(
            [
                "schema",
                "schemaVersion",
                "site",
                "canonicalUrl",
                "machineUrl",
                "recordPolicy",
                "versionScopes",
                "currentProductionWebsiteVersion",
                "releaseCount",
                "releases",
            ],
            list(payload),
        )
        self.assertEqual(
            "multiagentmemory.public-release-history.v1", payload["schema"]
        )
        self.assertEqual("1.0", payload["schemaVersion"])
        self.assertEqual("MultiAgentMemory.com", payload["site"])
        self.assertEqual(CANONICAL_RELEASE_URL, payload["canonicalUrl"])
        self.assertEqual(MACHINE_RELEASE_URL, payload["machineUrl"])
        self.assertEqual("1.0.0", payload["currentProductionWebsiteVersion"])
        self.assertEqual(1, payload["releaseCount"])
        self.assertEqual(1, len(payload["releases"]))
        release = payload["releases"][0]
        self.assertEqual(
            [
                "version",
                "activationDate",
                "activationTimezone",
                "status",
                "title",
                "summary",
                "changes",
                "milestones",
                "evidence",
            ],
            list(release),
        )
        self.assertEqual("1.0.0", release["version"])
        self.assertEqual("2026-08-03", release["activationDate"])
        self.assertEqual("UTC", release["activationTimezone"])
        self.assertEqual("deployed", release["status"])
        self.assertEqual(
            [
                "Release history",
                "Discovery and SEO",
                "Responsive accessibility",
                "Public verification",
            ],
            [item["area"] for item in release["changes"]],
        )
        self.assertEqual(
            "First evidence-bound website version", release["milestones"][0]["name"]
        )
        self.assertEqual(
            [
                {
                    "type": "source_tag",
                    "label": "Source tag multiagentmemory-site-v1.0.0",
                    "url": SOURCE_TAG_URL,
                }
            ],
            release["evidence"],
        )

    def test_record_policy_excludes_unverified_and_nonproduction_work(self):
        policy = self.load_ledger()["recordPolicy"]
        self.assertEqual(
            {
                "productionActivatedOnly": True,
                "exactWebsiteSemanticVersionRequired": True,
                "revisionBoundActivationDateRequired": True,
                "activationDateMustEqualSuccessfulUploadUtcDate": True,
                "sourceTagRevisionBindingRequired": True,
                "explicitReleaseStatusRequired": True,
                "sourceCandidatesPublished": False,
                "plannedWorkPublished": False,
                "publicEvidenceRequired": True,
            },
            policy,
        )

    def test_version_scopes_label_the_website_identity_without_borrowing_other_scopes(
        self,
    ):
        scopes = self.load_ledger()["versionScopes"]
        self.assertEqual(
            {"website", "endpointApi", "releaseHistorySchema", "packageSource"},
            set(scopes),
        )
        self.assertEqual("1.0.0", scopes["website"]["currentProductionVersion"])
        self.assertIsNone(scopes["endpointApi"]["currentProductionVersion"])
        self.assertIsNone(scopes["packageSource"]["currentProductionVersion"])
        self.assertEqual("1.0", scopes["releaseHistorySchema"]["version"])
        self.assertIn(
            "not a website release version", scopes["releaseHistorySchema"]["meaning"]
        )
        self.assertIn("never inherited", scopes["endpointApi"]["meaning"])

    def test_ledger_contains_only_the_exact_website_semver_and_activation_date(self):
        text = RELEASE_LEDGER.read_text(encoding="utf-8") + RELEASE_PAGE.read_text(
            encoding="utf-8"
        )
        self.assertEqual({"1.0.0"}, set(re.findall(r"\b\d+\.\d+\.\d+\b", text)))
        self.assertEqual(
            {"2026-08-03"}, set(re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", text))
        )

    def test_machine_ledger_is_public_safe(self):
        payload = self.load_ledger()
        combined = "\n".join(all_strings(payload))
        forbidden = (
            r"(?i)\b[a-z]:[\\/]",
            r"(?i)\bfile://",
            r"(?i)bearer\s+[a-z0-9._~+/=-]{20,}",
            r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----",
            r"(?i)password\s*[:=]\s*[^,\s]{8,}",
        )
        for pattern in forbidden:
            self.assertIsNone(re.search(pattern, combined), msg=pattern)

    def test_human_page_has_one_canonical_h1_and_one_deployed_record(self):
        text = RELEASE_PAGE.read_text(encoding="utf-8")
        parser = ReleasePageParser()
        parser.feed(text)
        self.assertEqual(1, parser.h1_count)
        self.assertEqual([CANONICAL_RELEASE_URL], parser.canonicals)
        self.assertEqual(1, parser.release_records)
        graph = json.loads("".join(parser.json_ld_parts))["@graph"]
        by_type = {item["@type"]: item for item in graph}
        self.assertIn("CollectionPage", by_type)
        self.assertIn("ItemList", by_type)
        self.assertIn("BreadcrumbList", by_type)
        self.assertEqual(1, by_type["ItemList"]["numberOfItems"])
        item = by_type["ItemList"]["itemListElement"][0]
        self.assertEqual(1, item["position"])
        self.assertEqual("1.0.0", item["item"]["version"])
        self.assertEqual("2026-08-03", item["item"]["datePublished"])
        self.assertEqual("deployed", item["item"]["additionalProperty"]["value"])
        self.assertEqual([SOURCE_TAG_URL], item["item"]["sameAs"])
        self.assertIn('aria-current="page">Releases</a>', text)
        self.assertIn('href="/releases.json"', text)
        self.assertIn('data-version="1.0.0"', text)
        self.assertIn('data-release-status="deployed"', text)
        self.assertIn("Website version 1.0.0", text)
        self.assertIn("Deployed", text)
        self.assertIn("August 3, 2026 (UTC)", text)
        self.assertIn(SOURCE_TAG_URL, text)

    def test_renderer_validates_explicit_status_and_supports_historical_withdrawal(
        self,
    ):
        payload = self.load_ledger()
        release_renderer.validate_ledger(payload)
        withdrawn = copy.deepcopy(payload)
        withdrawn["releases"][0]["status"] = "withdrawn"
        withdrawn["currentProductionWebsiteVersion"] = None
        withdrawn["versionScopes"]["website"]["currentProductionVersion"] = None
        release_renderer.validate_ledger(withdrawn)
        invalid = copy.deepcopy(payload)
        invalid["releases"][0]["status"] = "candidate"
        with self.assertRaises(release_renderer.ReleaseProjectionError):
            release_renderer.validate_ledger(invalid)

    def test_authoritative_ledger_projects_deterministically_and_detects_drift(self):
        payload, drift = release_renderer.projection_drift(SITE_ROOT)
        self.assertEqual("1.0.0", payload["currentProductionWebsiteVersion"])
        self.assertEqual([], drift)
        projected = release_renderer.projected_files(SITE_ROOT, payload)
        for path, expected in projected.items():
            self.assertEqual(expected, path.read_bytes(), msg=path)
        with tempfile.TemporaryDirectory() as tmp:
            copied_site = Path(tmp) / "site"
            shutil.copytree(SITE_ROOT, copied_site)
            llms_path = copied_site / "llms.txt"
            llms_path.write_text(
                llms_path.read_text(encoding="utf-8").replace(
                    "Current production website version: 1.0.0.",
                    "Current production website version: 9.9.9.",
                ),
                encoding="utf-8",
            )
            _payload, copied_drift = release_renderer.projection_drift(copied_site)
        self.assertEqual(["llms.txt"], copied_drift)

    def test_machine_and_text_projections_report_version_count_status_and_source_binding(
        self,
    ):
        manifest = json.loads(
            (SITE_ROOT / "ai-manifest.json").read_text(encoding="utf-8")
        )
        history = manifest["releaseHistory"]
        self.assertEqual("1.0.0", history["currentProductionWebsiteVersion"])
        self.assertEqual(1, history["releaseCount"])
        self.assertEqual("deployed", history["latestReleaseStatus"])
        self.assertEqual(SOURCE_TAG_URL, history["sourceTag"])
        for rel in ("llms.txt", "ai.txt"):
            text = (SITE_ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("1.0.0", text, msg=rel)
            self.assertIn("release status: deployed", text.lower(), msg=rel)
            self.assertIn(SOURCE_TAG_URL, text, msg=rel)
        readme = (SITE_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(
            "current website version is `1.0.0` with 1 verified release", readme
        )

    def test_release_history_is_in_every_human_navigation_and_footer(self):
        human_pages = (
            SITE_ROOT / "index.html",
            SITE_ROOT / "docs" / "how-it-works.html",
            SITE_ROOT / "docs" / "api-reference.html",
            SITE_ROOT / "docs" / "memory-boundary.html",
            RELEASE_PAGE,
        )
        for path in human_pages:
            text = path.read_text(encoding="utf-8")
            self.assertGreaterEqual(text.count('href="/releases/"'), 2, msg=path)
            self.assertIn("/static/site.css?v=ui4", text, msg=path)

    def test_sitemap_contains_human_canonical_routes_only(self):
        root = ET.fromstring((SITE_ROOT / "sitemap.xml").read_text(encoding="utf-8"))
        namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls = [node.text for node in root.findall("s:url/s:loc", namespace)]
        self.assertEqual(
            [
                "https://multiagentmemory.com/",
                "https://multiagentmemory.com/docs/how-it-works.html",
                "https://multiagentmemory.com/docs/api-reference.html",
                "https://multiagentmemory.com/docs/memory-boundary.html",
                CANONICAL_RELEASE_URL,
            ],
            urls,
        )
        self.assertNotIn(MACHINE_RELEASE_URL, urls)

    def test_discovery_surfaces_expose_both_canonical_release_routes(self):
        for rel in (
            "llms.txt",
            "ai.txt",
            "ai-manifest.json",
            ".well-known/ai-agent.json",
            ".well-known/mcp.json",
        ):
            text = (SITE_ROOT / rel).read_text(encoding="utf-8")
            self.assertIn(CANONICAL_RELEASE_URL, text, msg=rel)
            self.assertIn(MACHINE_RELEASE_URL, text, msg=rel)

    def test_no_legacy_or_alias_release_artifact_exists(self):
        aliases = (
            "release.html",
            "releases.html",
            "release-notes.html",
            "changelog.html",
            "release",
            "release-notes",
            "changelog",
            "api/releases.json",
        )
        for rel in aliases:
            self.assertFalse((SITE_ROOT / rel).exists(), msg=rel)


if __name__ == "__main__":
    unittest.main()
