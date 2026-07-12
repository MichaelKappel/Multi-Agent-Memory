import json
import unittest
from pathlib import Path


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
        self.assertEqual(
            "https://memoryendpoints.com/api/matm/uai-memory/contract",
            manifest["evidence"]["uaiMemoryContract"],
        )


if __name__ == "__main__":
    unittest.main()
