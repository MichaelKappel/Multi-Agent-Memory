import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AccessRetryClientContractTests(unittest.TestCase):
    @staticmethod
    def _browser_redemption_source():
        return (ROOT / "static" / "js" / "site.js").read_text(
            encoding="utf-8"
        )

    @staticmethod
    def _console_redemption_section(source):
        return source.split(
            "if (redemptionForm && redemptionSubmit)", 1
        )[1].split("var consoleRoot", 1)[0]

    @staticmethod
    def _durable_redemption_section(source):
        return source.split(
            'var redemptionStoreName = "multiagentmemory-agent-redemption-v1"',
            1,
        )[1].split("var consoleRoot", 1)[0]

    def test_console_uses_safe_idempotency_for_access_mutations(self):
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
    def test_console_redemption_sends_only_the_canonical_v1_request(self):
        source = (ROOT / "static" / "js" / "site.js").read_text(
            encoding="utf-8"
        )
        redemption_section = self._console_redemption_section(source)
        self.assertIn(
            '"memoryendpoints.agent_invite_redemption.v1"',
            redemption_section,
        )
        self.assertIn("candidateAgentTokenSecret", redemption_section)
        self.assertIn('"Idempotency-Key"', redemption_section)
        self.assertNotIn(
            "JSON.stringify({inviteSecret:", redemption_section
        )

    def test_console_redemption_prepares_candidate_before_network(self):
        source = (ROOT / "static" / "js" / "site.js").read_text(
            encoding="utf-8"
        )
        redemption_section = self._console_redemption_section(source)
        fetch_offset = redemption_section.index(
            'window.fetch("/api/matm/access/invites/redeem"'
        )
        self.assertIn("candidateAgentTokenSecret", redemption_section)
        self.assertLess(
            redemption_section.index("candidateAgentTokenSecret"),
            fetch_offset,
            "the candidate must be generated and protected before the request",
        )
    def test_console_redemption_never_consumes_server_returned_credential(self):
        source = (ROOT / "static" / "js" / "site.js").read_text(
            encoding="utf-8"
        )
        redemption_section = self._console_redemption_section(source)
        self.assertNotIn("payload.agentTokenSecret", redemption_section)

    def test_console_redemption_does_not_forbid_an_exact_retry(self):
        source = self._browser_redemption_source()
        redemption_section = self._console_redemption_section(source)
        self.assertNotIn("Do not retry from this page", redemption_section)

    def test_browser_redemption_is_durably_encrypted_before_any_request(self):
        source = self._browser_redemption_source()
        durable_section = self._durable_redemption_section(source)
        submit_section = self._console_redemption_section(source)

        self.assertIn("window.indexedDB.open", durable_section)
        self.assertIn('cryptoApi.subtle.generateKey(', durable_section)
        self.assertIn('{name: "AES-GCM", length: 256}', durable_section)
        self.assertIn('\n        false,\n        ["encrypt", "decrypt"]', durable_section)
        self.assertIn("cryptoApi.subtle.encrypt(", durable_section)
        self.assertIn("cryptoApi.subtle.decrypt(", durable_section)
        self.assertIn(
            'redemptionTransaction(database, "readwrite"', durable_section
        )
        self.assertIn("return loadDurableRedemptionMaterial();", durable_section)
        self.assertNotIn("localStorage", durable_section)
        self.assertNotIn("sessionStorage", durable_section)

        durable_readback = submit_section.index(
            "requireDurableRedemptionMaterial().then"
        )
        network_request = submit_section.index(
            'window.fetch("/api/matm/access/invites/redeem"'
        )
        self.assertLess(durable_readback, network_request)
        self.assertIn(
            "if (!redemptionDurableStageReady)",
            submit_section[durable_readback:network_request],
        )

    def test_browser_crash_and_lost_response_resume_the_exact_staged_request(self):
        source = self._browser_redemption_source()
        durable_section = self._durable_redemption_section(source)

        pagehide = durable_section.split(
            'window.addEventListener("pagehide"', 1
        )[1].split('window.addEventListener("pageshow"', 1)[0]
        pageshow = durable_section.split(
            'window.addEventListener("pageshow"', 1
        )[1].split("if (redemptionTokenToggle", 1)[0]
        self.assertIn("clearRedemptionSecrets();", pagehide)
        self.assertNotIn("clearDurableRedemptionMaterial", pagehide)
        self.assertIn("initializeDurableRedemption()", pageshow)
        self.assertIn("adoptDurableRedemptionMaterial(existing)", durable_section)
        self.assertIn("Resume exact redemption", durable_section)
        self.assertIn(
            "same encrypted candidate and retry key remain available after a tab or browser restart",
            durable_section,
        )

    def test_unavailable_secure_storage_disables_redemption_before_network(self):
        source = self._browser_redemption_source()
        durable_section = self._durable_redemption_section(source)
        submit_section = self._console_redemption_section(source)

        feature_gate = durable_section.split(
            "function redemptionCryptoApi()", 1
        )[1].split("function openRedemptionStore()", 1)[0]
        for required in (
            "window.indexedDB",
            "cryptoApi.subtle",
            "cryptoApi.subtle.generateKey",
            "window.TextEncoder",
            "window.TextDecoder",
        ):
            self.assertIn(required, feature_gate)
        installer_gate = durable_section.split(
            "function requireManagedInstaller(error)", 1
        )[1].split("function initializeDurableRedemption()", 1)[0]
        self.assertIn('lockRedemption("installer_required"', installer_gate)
        self.assertIn("no redemption request was sent", installer_gate)
        self.assertIn("if (error && error.installerRequired)", submit_section)
        self.assertLess(
            submit_section.index("requireDurableRedemptionMaterial().then"),
            submit_section.index('window.fetch("/api/matm/access/invites/redeem"'),
        )

    def test_durable_redemption_cleanup_occurs_only_after_safe_disposition(self):
        source = self._browser_redemption_source()
        durable_section = self._durable_redemption_section(source)

        continue_handler = durable_section.split(
            'redemptionTokenContinue.addEventListener("click"', 1
        )[1].split("if (redemptionTokenClear)", 1)[0]
        clear_handler = durable_section.split(
            'redemptionTokenClear.addEventListener("click"', 1
        )[1].split("if (redemptionForm && redemptionSubmit)", 1)[0]
        success_handler = durable_section.split(
            ").then(function (payload)", 1
        )[1].split(").catch(function (error)", 1)[0]
        failure_handler = durable_section.split(
            ").catch(function (error)", 1
        )[-1]

        self.assertIn("clearDurableRedemptionMaterial()", continue_handler)
        self.assertIn("clearDurableRedemptionMaterial()", clear_handler)
        self.assertNotIn("clearDurableRedemptionMaterial()", success_handler)
        self.assertIn(
            'var safeTerminalCodes = ["invalid_invite", "invite_expired", "invite_revoked"]',
            failure_handler,
        )
        self.assertIn("clearDurableRedemptionMaterial()", failure_handler)
        recovery_section = failure_handler.split(
            "var recoveryRequiredCodes", 1
        )[1].split("redemptionState = \"ready\"", 1)[0]
        self.assertNotIn("clearDurableRedemptionMaterial()", recovery_section)
        self.assertIn("Encrypted recovery state was retained", recovery_section)

    def test_browser_redemption_executes_durable_exact_retry_contract(self):
        completed = subprocess.run(
            [
                "node",
                str(ROOT / "tests" / "browser_invite_redemption_contract.js"),
                str(ROOT / "static" / "js" / "site.js"),
            ],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            timeout=30,
        )
        self.assertEqual(
            0,
            completed.returncode,
            msg=completed.stderr or completed.stdout,
        )
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(
            {
                "transactionCompletionBeforeNetwork": True,
                "nonExtractableCryptoKeyStructuredClone": True,
                "ciphertextOnlyDurableStage": True,
                "reloadRecovery": True,
                "noFetchWithoutSecureStorage": True,
                "exactLostResponseRetry": True,
                "cleanupOnlyAfterVerifiedOrTerminalDisposition": True,
            },
            payload["assertions"],
        )

    def test_dogfood_reuses_stable_keys_for_its_exact_retries(self):
        source = (
            ROOT / "scripts" / "dogfood_memoryendpoints.py"
        ).read_text(encoding="utf-8")
        provision_section = source.split(
            "def provision_workspace_agent", 1
        )[1].split("def retryable_status", 1)[0]
        self.assertIn(
            'HTTP_IDEMPOTENCY_KEY="dogfood-access-request-" + requested_name',
            provision_section,
        )
        self.assertIn(
            'HTTP_IDEMPOTENCY_KEY="dogfood-access-decision-" + request_id',
            provision_section,
        )
        issue_section = provision_section.split(
            '"/api/matm/access/invites",', 1
        )[1].split('"/api/matm/access/invites/redeem",', 1)[0]
        self.assertIn("headers=master_auth", issue_section)
        self.assertNotIn("HTTP_IDEMPOTENCY_KEY", issue_section)
        redemption_section = provision_section.split(
            '"/api/matm/access/invites/redeem",', 1
        )[1]
        redeem_offset = provision_section.index(
            '"/api/matm/access/invites/redeem",'
        )
        self.assertLess(provision_section.index("candidate ="), redeem_offset)
        self.assertLess(provision_section.index("idempotency_key ="), redeem_offset)
        self.assertIn("HTTP_IDEMPOTENCY_KEY", redemption_section)
        self.assertIn(
            '"schemaVersion": "memoryendpoints.agent_invite_redemption.v1"',
            redemption_section,
        )
        self.assertIn("candidateAgentTokenSecret", redemption_section)
        self.assertIn('if "agentTokenSecret" in redeemed:', redemption_section)
        self.assertIn(
            "dict(redeemed, agentTokenSecret=candidate)", redemption_section
        )

    def test_publications_define_the_same_canonical_redemption(self):
        paths = (
            ROOT / "docs" / "api-contract.md",
            ROOT / "docs" / "route-inventory.md",
            ROOT
            / "sites"
            / "multiagentmemory.com"
            / "docs"
            / "api-reference.html",
        )
        required = (
            "memoryendpoints.agent_invite_redemption.v1",
            "candidateAgentTokenSecret",
            "Idempotency-Key",
            "idempotency_conflict",
            "The server never returns the raw credential",
        )
        for path in paths:
            text = re.sub(
                r"\s+", " ", path.read_text(encoding="utf-8")
            )
            for value in required:
                self.assertIn(value, text, msg="redemption drift in %s" % path)


if __name__ == "__main__":
    unittest.main()
