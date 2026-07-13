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
CONNECTOR_CONTRACT = ROOT / "docs" / "connector-pairing-v1.md"
CONNECTOR_THREAT_MODEL = ROOT / "docs" / "connector-pairing-threat-model.md"
COMPANION_MANIFEST = ROOT / "sites" / "multiagentmemory.com" / "ai-manifest.json"
READINESS_REPORT_BUILDER = ROOT / "scripts" / "build_readiness_reports.py"


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

    def test_connector_publications_share_the_body_only_claim_contract(self):
        publications = (API_CONTRACT, ROUTE_INVENTORY, COMPANION_API, CONNECTOR_CONTRACT)
        required = (
            "/connect/authorize/{publicRequestRef}",
            "/api/matm/connector-pairings/authorization-code-claims",
            "pairref_",
            "wakeUpUrl",
            "PairingSummary",
            "RotationSummary",
            "claimExpiresAt",
            "activationExpiresInSeconds",
            "credentialDeliveredToAuthorizedRecipient=true",
            "rawCredentialPersisted=false",
            "showCredentialOnce=true",
            "idempotencyKeyReserved=false",
            "canInvite=false",
            "lastUsedAt",
            "connector:self:readback",
            "memory:public-safe:submit",
            "sha256-v1:1358698c6ddba1a74a688d3718a739f78e4ef50d0773b22c96e025b38aa86594",
            "16 KiB",
            "32 KiB",
            "64 KiB",
        )
        for path in publications:
            text = path.read_text(encoding="utf-8")
            for value in required:
                self.assertIn(value, text, msg="connector publication drift in %s" % path)
            self.assertNotIn("{opaqueRequestHandle}", text, msg=path)
            self.assertNotIn("/tour/connect/authorize/{state}", text, msg=path)
            self.assertNotIn("callback contains only", text.lower(), msg=path)
            self.assertNotIn("authorizationCodeExpiresAt", text, msg=path)

    def test_connector_verification_example_uses_exact_public_summary_allowlists(self):
        text = API_CONTRACT.read_text(encoding="utf-8")
        section = text.split("### Exact verification response", 1)[1].split(
            "### Credential lifecycle", 1
        )[0]
        match = re.search(r"```json\s*(\{.*?\})\s*```", section, re.DOTALL)
        self.assertIsNotNone(match, msg="connector verification JSON example missing")
        payload = json.loads(match.group(1))
        pairing = payload["pairing"]
        self.assertEqual(
            {
                "pairingId",
                "status",
                "workspaceId",
                "agentId",
                "credentialId",
                "approvedScopes",
                "scopeDigest",
                "grant",
                "workspace",
                "agent",
            },
            set(pairing),
        )
        self.assertEqual({"workspaceId", "readable"}, set(pairing["workspace"]))
        self.assertEqual({"agentId", "readable"}, set(pairing["agent"]))
        self.assertEqual(
            {
                "credentialType",
                "scopeType",
                "scopeId",
                "workspaceId",
                "agentId",
                "approvedScopes",
                "scopeDigest",
                "active",
                "revoked",
                "canInvite",
                "canRevoke",
            },
            set(pairing["grant"]),
        )
        self.assertFalse(pairing["grant"]["canInvite"])
        self.assertFalse(pairing["grant"]["canRevoke"])

        forbidden_public_keys = {
            "authorizationCodeExpiresAt",
            "requestId",
            "companyId",
            "projectId",
            "predecessorCredentialId",
            "predecessorTokenId",
        }

        def assert_public_keys(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden_public_keys.intersection(value))
                for child in value.values():
                    assert_public_keys(child)
            elif isinstance(value, list):
                for child in value:
                    assert_public_keys(child)

        assert_public_keys(payload)

    def test_connector_threat_model_covers_release_blocking_boundaries(self):
        text = CONNECTOR_THREAT_MODEL.read_text(encoding="utf-8")
        for value in (
            "URL/history/referrer leakage",
            "Claim theft or replay",
            "Secure-store failure",
            "Scope escalation/confused deputy",
            "Browser script exfiltration",
            "CSRF",
            "Authorization-server mix-up",
            "Custom-protocol hijacking or loopback listener race",
            "Open redirect",
            "SSRF",
            "Response overexposure",
            "Oversized/parser abuse",
            "403 connector_scope_forbidden",
            "16 KiB",
            "32 KiB",
            "64 KiB",
            "authorized exact-SHA deployment",
        ):
            self.assertIn(value, text)

    def test_current_operating_docs_do_not_emit_tracked_report_snapshots(self):
        for rel in ("README.md", "docs/deployment.md", "docs/verification.md"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertNotRegex(text, r"--json-out\s+docs[\\/]reports", msg=rel)

    def test_current_docs_avoid_known_stale_release_counts(self):
        paths = (
            ROOT / "docs" / "deployment.md",
            ROOT / "docs" / "verification.md",
            ROOT / "docs" / "long-term-memory" / "release-verification-summary.md",
            READINESS_REPORT_BUILDER,
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
            "matm_uai_packages",
            "matm_uai_record_revisions",
            "matm_uai_collaboration_heads",
            "matm_uai_edit_claims",
            "Accountless Browser Exception",
            "Local Multi-Agent Collaboration Overlay",
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
        self.assertFalse(manifest["supportBoundary"]["accountlessBrowserVirtualMemoryIsAnonymous"])
        self.assertFalse(manifest["supportBoundary"]["localUaiContentsStoredForCollaboration"])
        self.assertFalse(manifest["supportBoundary"]["uaiEditClaimsPerformAutomaticMerge"])

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
