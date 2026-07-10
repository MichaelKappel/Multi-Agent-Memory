import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HumanVerifierAccountScriptTests(unittest.TestCase):
    def test_company_account_boundary_seed_matches_verification_search(self):
        text = (ROOT / "scripts" / "create_human_verifier_account.py").read_text(encoding="utf-8")

        self.assertIn("Company/account boundary verification seeded", text)
        self.assertIn("company/account boundary is visible to the human verifier", text)
        self.assertIn('"verification", "company", "account", "boundary"', text)
        self.assertIn('"backendAgentId": "MemoryEndpoints-Backend-Agent"', text)
        self.assertIn("target_backend_agent", text)


if __name__ == "__main__":
    unittest.main()
