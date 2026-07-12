import json
import re
import unittest
from pathlib import Path

from memoryendpoints.site_data import ROUTE_TABLE


ROOT = Path(__file__).resolve().parents[1]
ROUTE_INVENTORY = ROOT / "docs" / "route-inventory.md"
API_CONTRACT = ROOT / "docs" / "api-contract.md"
SYSTEM_ARCHITECTURE = ROOT / "docs" / "system-architecture.md"
COMPANION_API = ROOT / "sites" / "multiagentmemory.com" / "docs" / "api-reference.html"
COMPANION_MANIFEST = ROOT / "sites" / "multiagentmemory.com" / "ai-manifest.json"


class DocumentationFreshnessTests(unittest.TestCase):
    def test_route_inventory_matches_source_route_table(self):
        text = ROUTE_INVENTORY.read_text(encoding="utf-8")
        for item in ROUTE_TABLE:
            expected = "| `{}` | {} | {} |".format(
                item["route"],
                ", ".join(item["methods"]),
                item["purpose"],
            )
            self.assertIn(expected, text, msg="route inventory drift for %s" % item["route"])

    def test_api_contract_mentions_every_source_route(self):
        text = API_CONTRACT.read_text(encoding="utf-8")
        for item in ROUTE_TABLE:
            self.assertIn("`%s`" % item["route"], text, msg="API contract missing %s" % item["route"])

    def test_companion_api_reference_contains_every_source_route_and_method(self):
        text = COMPANION_API.read_text(encoding="utf-8")
        for item in ROUTE_TABLE:
            row = re.compile(
                r"<tr><td[^>]*><code>%s</code></td><td[^>]*>%s</td>"
                % (re.escape(item["route"]), re.escape(", ".join(item["methods"]))),
            )
            self.assertRegex(text, row, msg="companion API reference drift for %s" % item["route"])

    def test_current_operating_docs_do_not_emit_tracked_report_snapshots(self):
        for rel in ("README.md", "docs/deployment.md", "docs/verification.md"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertNotRegex(text, r"--json-out\s+docs[\\/]reports", msg=rel)

    def test_current_docs_avoid_known_stale_release_counts(self):
        paths = (
            ROOT / "docs" / "deployment.md",
            ROOT / "docs" / "verification.md",
            ROOT / "docs" / "long-term-memory" / "release-verification-summary.md",
        )
        forbidden = ("21 checked routes", "21 required public routes", "uploaded 81 files")
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for phrase in forbidden:
                self.assertNotIn(phrase, text, msg="stale release count in %s" % path)

    def test_architecture_covers_critical_implemented_boundaries(self):
        text = SYSTEM_ARCHITECTURE.read_text(encoding="utf-8")
        required = (
            "project -> workspace -> company",
            "matm_external_link_mentions",
            "matm_routing_decisions",
            "matm_sync_revisions",
            "Readback And Evidence",
            "Local `.uai` remains active startup memory",
            "Bulk archive import is not the dogfood path",
            "Tracked `docs/reports/` files are historical snapshots",
        )
        for value in required:
            self.assertIn(value, text)

    def test_companion_manifest_advertises_current_reference_and_freshness_gate(self):
        manifest = json.loads(COMPANION_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(
            "https://multiagentmemory.com/docs/api-reference.html",
            manifest["humanRoutes"]["apiReference"],
        )
        self.assertTrue(manifest["documentationFreshness"]["testEnforced"])
        self.assertTrue(manifest["documentationFreshness"]["trackedReportsArePointInTime"])

    def test_checked_in_engineering_markdown_links_resolve(self):
        excluded_parts = {"reports", "prompts"}
        paths = [ROOT / name for name in ("README.md", "AGENTS.md", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md")]
        paths.extend(
            path
            for path in (ROOT / "docs").rglob("*.md")
            if not excluded_parts.intersection(path.relative_to(ROOT / "docs").parts)
        )
        link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for target in link_pattern.findall(text):
                target = target.strip().strip("<>")
                if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                    continue
                local_target = target.split("#", 1)[0]
                resolved = (path.parent / local_target).resolve()
                self.assertTrue(resolved.exists(), msg="broken link %s in %s" % (target, path.relative_to(ROOT)))

    def test_companion_internal_links_resolve(self):
        site_root = ROOT / "sites" / "multiagentmemory.com"
        href_pattern = re.compile(r'href="(/[^"]*)"')
        for path in site_root.rglob("*.html"):
            for href in href_pattern.findall(path.read_text(encoding="utf-8")):
                route = href.split("?", 1)[0].split("#", 1)[0]
                target = site_root / ("index.html" if route == "/" else route.lstrip("/"))
                self.assertTrue(target.exists(), msg="broken companion link %s in %s" % (href, path.name))


if __name__ == "__main__":
    unittest.main()
