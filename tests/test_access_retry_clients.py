import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AccessRetryClientContractTests(unittest.TestCase):
    def test_console_adds_keys_only_to_public_safe_access_mutations(self):
        source = (ROOT / "static" / "js" / "site.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("function accessIdempotencyKey(action, target)", source)
        self.assertIn('typeof cryptoApi.randomUUID === "function"', source)
        self.assertIn("cryptoApi.getRandomValues(words)", source)
        self.assertNotIn("Math.random()", source)
        self.assertIn(
            'accessIdempotencyKey("decision", requestId + "-" + decision)',
            source,
        )
        self.assertIn(
            'accessIdempotencyKey(isToken ? "token-revoke" : "invite-revoke", id)',
            source,
        )
        self.assertIn(
            'accessIdempotencyKey("name-request", body.requestedName)', source
        )

        issue_section = source.split(
            "function issueAccessInvite(requestId, expiresInSeconds)", 1
        )[1].split("function revokeAccessResource", 1)[0]
        self.assertNotIn("Idempotency-Key", issue_section)
        redemption_section = source.split(
            'window.fetch("/api/matm/access/invites/redeem"', 1
        )[1].split("}).then(function (response)", 1)[0]
        self.assertNotIn("Idempotency-Key", redemption_section)

    def test_dogfood_reuses_stable_keys_for_its_exact_retries(self):
        source = (
            ROOT / "scripts" / "dogfood_memoryendpoints.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'HTTP_IDEMPOTENCY_KEY="dogfood-access-request-" + requested_name',
            source,
        )
        self.assertIn(
            'HTTP_IDEMPOTENCY_KEY="dogfood-access-decision-" + request_id',
            source,
        )
        issue_section = source.split(
            '"/api/matm/access/invites",', 1
        )[1].split('"/api/matm/access/invites/redeem",', 1)[0]
        self.assertIn("headers=master_auth", issue_section)
        self.assertNotIn("HTTP_IDEMPOTENCY_KEY", issue_section)


if __name__ == "__main__":
    unittest.main()
