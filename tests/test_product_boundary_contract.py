import unittest
from pathlib import Path

from memoryendpoints.site_data import PUBLIC_ROUTES, openapi_spec


ROOT = Path(__file__).resolve().parents[1]


class ProductBoundaryContractTests(unittest.TestCase):
    def read_text(self, relative_path):
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_license_notice_and_readme_define_private_intranet_no_resale_boundary(self):
        combined = "\n".join(
            [
                self.read_text("LICENSE"),
                self.read_text("NOTICE"),
                self.read_text("README.md"),
                self.read_text("docs/product-boundary.md"),
            ]
        ).lower()

        required_phrases = [
            "private-intranet",
            "one organization",
            "no resale",
            "public hosted",
            "memoryendpoints.com",
            "private commercial repository",
            "multiagentmemory.com",
            "paid or unlimited npc memory stores",
            "not an osi-approved open source license",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_public_discovery_omits_commercial_sponsored_setup_route(self):
        commercial_route = "/api/matm/agent-setup/dogfood-partner-account"

        self.assertNotIn(commercial_route, PUBLIC_ROUTES)
        self.assertNotIn(commercial_route, openapi_spec()["paths"])
