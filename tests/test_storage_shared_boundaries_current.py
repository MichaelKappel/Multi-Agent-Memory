"""Shared boundary matrix for the storage projection and quota contract."""

from __future__ import annotations

import unittest

from memoryendpoints import storage


class StorageSharedBoundaryTests(unittest.TestCase):
    def test_normalizers_quota_and_public_projections_cover_bounded_shapes(self):
        self.assertEqual(("agent-one", "agent-one"), storage._normalize_agent_access_name(" Agent-One "))
        self.assertEqual((None, None), storage._normalize_agent_access_name("bad name"))
        self.assertEqual("Readable Name", storage._normalize_agent_display_name(" Readable   Name ", "fallback"))
        self.assertEqual("fallback", storage._normalize_agent_display_name("", "fallback"))
        self.assertIsNone(storage._normalize_agent_display_name("bad\x7fname", "fallback"))
        self.assertEqual(900, storage._agent_invite_ttl_seconds("not-a-number"))
        self.assertEqual(storage._MAX_AGENT_INVITE_TTL_SECONDS, storage._agent_invite_ttl_seconds(10**9))
        self.assertEqual(storage._MIN_AGENT_INVITE_TTL_SECONDS, storage._agent_invite_ttl_seconds(-1))
        self.assertTrue(storage._timestamp_expired(None))
        self.assertTrue(storage._timestamp_expired("not-a-date"))
        self.assertFalse(storage._timestamp_expired("2099-01-01T00:00:00Z"))
        self.assertEqual(900, storage._bounded_ttl_seconds("bad", 900, 60, 3600))
        self.assertEqual(3600, storage._bounded_ttl_seconds(9999, 900, 60, 3600))
        self.assertEqual(storage.PUBLIC_STORAGE_BYTES, storage._storage_limit_value(None))
        self.assertEqual(storage.PUBLIC_STORAGE_BYTES, storage._storage_limit_value("bad"))
        self.assertTrue(storage._storage_is_unlimited(-1))
        self.assertFalse(storage._storage_is_unlimited(0))
        self.assertTrue(storage._custom_scope_parent_allowed("goal", "project"))
        self.assertFalse(storage._custom_scope_parent_allowed("goal", "workspace"))
        self.assertTrue(storage._quota_allows(-1, 10**9, {"x": "y"}))
        self.assertFalse(storage._quota_allows(1, 0, {"large": "value"}))
        unlimited = storage._workspace_storage_fields("unknown", -1, -10)
        self.assertTrue(unlimited["storageUnlimited"])
        self.assertIsNone(unlimited["storageRemainingBytes"])
        limited = storage._workspace_storage_fields("free_agent", 100, 125)
        self.assertEqual(0, limited["storageRemainingBytes"])
        self.assertTrue(limited["quotaExceeded"])
        self.assertEqual(["unlimited_storage"], storage._workspace_plan_entitlement("free_agent", -1)["entitlements"])

        nested = storage._safe_company_export_value(
            {"safe": "ok", "password": "secret", "items": [{"token_hash": "secret", "value": 1}]}
        )
        self.assertEqual({"safe": "ok", "items": [{"value": 1}]}, nested)
        self.assertEqual(("sha256:" + "a" * 64), storage._human_replacement_idempotency_material("key", "sha256:" + "a" * 64)[1])
        self.assertEqual((None, None), storage._human_replacement_idempotency_material("", "digest"))
        self.assertEqual((None, None), storage._human_replacement_idempotency_material("key", ""))

    def test_public_identity_and_access_projections_preserve_safe_defaults(self):
        invite = {
            "inviteId": "invite-1",
            "requestId": "request-1",
            "companyId": "company-1",
            "agentIdentityId": "identity-1",
            "agentId": "agent-1",
            "agentName": "Agent One",
            "scopeType": "project",
            "scopeId": "project-1",
            "assignmentContext": {"projectId": "project-1"},
        }
        identity = {"agentIdentityId": "identity-1", "agentId": "agent-1", "displayName": "Agent One"}
        grant = {
            "grantId": "grant-1",
            "companyId": "company-1",
            "scopeType": "project",
            "scopeId": "project-1",
            "workspaceId": "workspace-1",
            "projectId": "project-1",
            "status": "active",
        }
        token = {"agentTokenId": "token-1", "agentIdentityId": "identity-1"}
        self.assertTrue(storage._public_agent_invite(invite)["singleUse"])
        self.assertEqual("agent", storage._public_agent_principal(identity, grant, token)["credentialType"])
        self.assertEqual("agent", storage._public_agent_access_request({"agentName": "agent"})["requestedName"])
        self.assertEqual("active", storage._public_company_master_key({})["status"])
        self.assertEqual("revoked", storage._public_company_master_key({"revokedAt": "now"})["status"])
        self.assertEqual(["agent_inventory_read"], storage._human_membership_permissions("member"))
        self.assertIn("company_lifecycle", storage._human_membership_permissions("owner"))
        self.assertIsNone(storage._public_human_membership({"role": "owner"})["companyStatus"])
        self.assertEqual("user", storage._public_human_account({"username": "user"})["displayName"])
        self.assertEqual("revoked", storage._public_human_agent_token({"revokedAt": "now"}, {}, {})["status"])
        self.assertTrue(storage._public_agent_token_replacement({"status": "prepared"})["predecessorRemainsActive"])
        self.assertFalse(storage._public_agent_token_replacement({"status": "confirmed"})["predecessorRemainsActive"])


if __name__ == "__main__":
    unittest.main()
