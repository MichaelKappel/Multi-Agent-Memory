import copy
import json
import unittest
from pathlib import Path

from memoryendpoints import __version__
from scripts import verify_static_site


ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = ROOT / "sites" / "multiagentmemory.com"
GITHUB_REPO = "https://github.com/MichaelKappel/Multi-Agent-Memory"
ENDPOINT_SITE = "https://memoryendpoints.com"


class MultiAgentMemoryStaticSiteTests(unittest.TestCase):
    def test_homepage_links_to_endpoint_and_github(self):
        text = (SITE_ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn(GITHUB_REPO, text)
        self.assertIn(ENDPOINT_SITE, text)
        self.assertIn("/docs/how-it-works.html", text)
        self.assertIn("/docs/api-reference.html", text)
        self.assertIn("/releases.html", text)
        self.assertIn(f"Public edition v{__version__}", text)

    def test_release_catalog_is_closed_current_and_visible_on_every_page(self):
        catalog_text = (SITE_ROOT / "releases.json").read_text(encoding="utf-8")
        catalog = verify_static_site.strict_json_loads(catalog_text)
        self.assertEqual("multiagentmemory.public_releases.v1", catalog["schemaVersion"])
        self.assertEqual(verify_static_site.RELEASE_CATALOG_TOP_LEVEL_KEYS, set(catalog))
        self.assertEqual(__version__, catalog["currentVersion"])
        self.assertEqual("2026-08-04", catalog["currentReleaseDate"])
        self.assertIs(True, catalog["valuesRedacted"])
        self.assertEqual(__version__, catalog["releases"][0]["version"])
        self.assertEqual("current", catalog["releases"][0]["status"])
        self.assertEqual(len(catalog["releases"]), len({item["version"] for item in catalog["releases"]}))
        for release in catalog["releases"]:
            self.assertEqual(verify_static_site.RELEASE_ENTRY_KEYS, set(release))
        release_page = (SITE_ROOT / "releases.html").read_text(encoding="utf-8")
        manifest_text = (SITE_ROOT / "ai-manifest.json").read_text(encoding="utf-8")
        changelog_text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertEqual(
            [],
            verify_static_site.validate_release_surfaces(
                catalog,
                release_page,
                manifest_text,
                changelog_text,
            ),
        )
        self.assertIn(f"v{__version__}", release_page)
        self.assertIn("August 4, 2026", release_page)
        for relative in (
            "index.html",
            "docs/how-it-works.html",
            "docs/api-reference.html",
            "docs/memory-boundary.html",
        ):
            text = (SITE_ROOT / relative).read_text(encoding="utf-8")
            self.assertIn(f"Public edition v{__version__}", text)
            self.assertIn("/releases.html", text)

    def test_release_catalog_rejects_ambiguous_extended_or_divergent_documents(self):
        source = (SITE_ROOT / "releases.json").read_text(encoding="utf-8")
        with self.assertRaises(ValueError):
            verify_static_site.strict_json_loads('{"currentVersion":"0.2.0","currentVersion":"9.9.9"}')
        with self.assertRaises(ValueError):
            verify_static_site.strict_json_loads('{"value":NaN}')
        with self.assertRaises(ValueError):
            verify_static_site.strict_json_loads('{} trailing')
        self.assertEqual(("", "invalid_utf8"), verify_static_site.decode_utf8(b"\xff"))
        self.assertEqual(
            [],
            verify_static_site.release_catalog_content_type_failures("application/json", live=True),
        )
        self.assertTrue(
            verify_static_site.release_catalog_content_type_failures("text/plain", live=True)
        )

        catalog = verify_static_site.strict_json_loads(source)
        mutations = []
        unknown_top = copy.deepcopy(catalog)
        unknown_top["privatePath"] = "/home/example"
        mutations.append(unknown_top)
        unknown_release = copy.deepcopy(catalog)
        unknown_release["releases"][0]["token"] = "not-public"
        mutations.append(unknown_release)
        invalid_status = copy.deepcopy(catalog)
        invalid_status["releases"][0]["status"] = "draft"
        mutations.append(invalid_status)
        wrong_order = copy.deepcopy(catalog)
        wrong_order["releases"] = list(reversed(wrong_order["releases"]))
        mutations.append(wrong_order)
        wrong_type = copy.deepcopy(catalog)
        wrong_type["releases"][0]["changes"] = [{"summary": "nested"}]
        mutations.append(wrong_type)
        invalid_version_type = copy.deepcopy(catalog)
        invalid_version_type["releases"][0]["version"] = {"value": "0.2.0"}
        mutations.append(invalid_version_type)
        invalid_entry_type = copy.deepcopy(catalog)
        invalid_entry_type["releases"] = ["not-an-object"]
        mutations.append(invalid_entry_type)
        for mutation in mutations:
            self.assertTrue(verify_static_site.validate_release_catalog(mutation))

    def test_how_it_works_documents_static_site_and_matm_roles(self):
        text = (SITE_ROOT / "docs" / "how-it-works.html").read_text(encoding="utf-8")
        self.assertIn("static companion documentation site", text)
        self.assertIn(GITHUB_REPO, text)
        self.assertIn("MemoryEndpoints.com", text)
        self.assertIn(".uai/", text)
        self.assertIn("/api/matm/memory-events/submit", text)
        self.assertIn("/api/matm/routing-decisions", text)
        self.assertIn("/api/matm/sync/capabilities", text)
        self.assertIn("/api/matm/uai-memory/contract", text)
        self.assertIn("Accountless-browser exception", text)
        self.assertIn("Local collaboration overlay", text)

    def test_api_reference_covers_current_advanced_contracts(self):
        text = (SITE_ROOT / "docs" / "api-reference.html").read_text(encoding="utf-8")
        self.assertIn("/api/matm/external-links/upsert", text)
        self.assertIn("/api/matm/meeting-messages/promote", text)
        self.assertIn("/api/matm/routing-decisions", text)
        self.assertIn("/api/matm/sync/mutations", text)
        self.assertIn("/api/matm/uai-memory/records", text)
        self.assertIn("/api/matm/uai-memory/edit-claims/complete", text)
        self.assertIn("stores no file body", text)
        self.assertIn("Tracked reports are point-in-time evidence", text)

    def test_mobile_tables_have_labels_and_fixed_hero_type(self):
        css = (SITE_ROOT / "static" / "site.css").read_text(encoding="utf-8")
        home = (SITE_ROOT / "index.html").read_text(encoding="utf-8")
        guide = (SITE_ROOT / "docs" / "how-it-works.html").read_text(encoding="utf-8")
        self.assertIn("content: attr(data-label)", css)
        self.assertIn("@media (max-width: 760px)", css)
        self.assertNotIn("font-size: clamp", css)
        self.assertIn('/static/site.css?v=ui3', home)
        self.assertIn('data-label="Surface"', home)
        self.assertIn('data-label="Layer"', guide)

    def test_ai_manifest_exposes_repo_and_endpoint(self):
        manifest = json.loads((SITE_ROOT / "ai-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(GITHUB_REPO, manifest["sourceRepository"])
        self.assertEqual(ENDPOINT_SITE, manifest["primaryEndpointSite"])
        self.assertEqual("sites/multiagentmemory.com/", manifest["repositoryMap"]["companionSite"])
        self.assertEqual(__version__, manifest["releaseVersion"])
        self.assertEqual("2026-08-04", manifest["releaseDate"])
        self.assertEqual("https://multiagentmemory.com/releases.json", manifest["releaseCatalog"])
        self.assertEqual("https://multiagentmemory.com/releases.html", manifest["humanRoutes"]["releases"])
        self.assertEqual(
            "https://memoryendpoints.com/api/matm/uai-memory/contract",
            manifest["evidence"]["uaiMemoryContract"],
        )


if __name__ == "__main__":
    unittest.main()
