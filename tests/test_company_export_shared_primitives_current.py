"""Shared current edge coverage for deterministic company exports.

The implementation is byte-identical in both services, so this suite is kept
byte-identical as well.
"""

import unittest

from memoryendpoints import company_export as export


class SharedCompanyExportPrimitivesCurrentTests(unittest.TestCase):
    def test_sanitizer_identity_and_small_helpers_cover_remaining_boundaries(self):
        self.assertFalse(export._is_sensitive_field(""))
        self.assertFalse(export._is_sensitive_field("tokenId"))
        self.assertFalse(export._is_sensitive_field("tokenCount"))
        self.assertTrue(export._is_sensitive_field("access-token"))
        self.assertTrue(export._is_credential_collection("customCredentialTable"))
        self.assertEqual(0, export._record_count(None))
        self.assertEqual(1, export._record_count({"item": 1}))
        self.assertEqual(2, export._record_count(["one", "two"]))
        self.assertEqual(1, export._record_count("one"))
        self.assertEqual("company", export._safe_filename_component("..."))
        self.assertEqual(80, len(export._safe_filename_component("A" * 120)))

        stats = {
            "removedCollectionCount": 0,
            "removedFieldCount": 0,
            "redactedStringCount": 0,
        }
        sanitized = export._sanitize(
            {
                "__proto__": "removed",
                "prototype": "removed",
                "constructor": "removed",
                "safe": "kept",
                "safeAgentTokenId": "public-id",
                "credentials": [{"token": "removed"}],
            },
            stats,
        )
        self.assertEqual(
            {"safe": "kept", "safeAgentTokenId": "public-id"},
            sanitized,
        )
        self.assertGreaterEqual(stats["removedFieldCount"], 3)
        self.assertEqual(1, stats["removedCollectionCount"])

        identity = export._derive_identity(
            {"companies": [{"id": "company-one", "name": "Company One"}]},
            None,
            None,
        )
        self.assertEqual(("company-one", "Company One"), identity)
        with self.assertRaises(export.CompanyExportError):
            export._derive_identity({}, None, None)
        with self.assertRaises(export.CompanyExportError):
            export._derive_identity({"companyId": "company-one"}, None, None)
        with self.assertRaises(export.CompanyExportError):
            export._canonical_json_bytes(object())

    def test_export_rejects_missing_controls_and_preserves_audit_projection(self):
        snapshot = {
            "companies": [{"id": "company-one", "name": "Company One"}],
            "auditActor": {"actorType": "human_owner", "actorId": "owner-one"},
            "workspaces": [],
        }
        result = export.assemble_company_export(
            snapshot,
            generated_at="2026-01-03T00:00:00Z",
            schema_version="custom.export.v1",
        )
        self.assertEqual("custom.export.v1", result["schemaVersion"])
        self.assertEqual("company-one", result["companyId"])
        self.assertEqual("Company One", result["companyLabel"])
        self.assertIn(b"auditActor", result["body"])
        for kwargs in (
            {"snapshot": None, "generated_at": "2026-01-03T00:00:00Z"},
            {"snapshot": {}, "generated_at": ""},
            {"snapshot": {}, "generated_at": "2026-01-03T00:00:00Z"},
            {
                "snapshot": {"companyId": "company-one", "companyLabel": "Company One"},
                "generated_at": "2026-01-03T00:00:00Z",
                "schema_version": "",
            },
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(export.CompanyExportError):
                    export.assemble_company_export(**kwargs)
        with self.assertRaises(export.CompanyExportError):
            export.assemble_company_export(
                {"companyId": "me_agent_v1.agent-record." + ("s" * 43), "companyLabel": "Company One"},
                generated_at="2026-01-03T00:00:00Z",
            )


if __name__ == "__main__":
    unittest.main()
