"""Shared current-contract tests for the two MemoryEndpoints storage backends."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from memoryendpoints import storage


class StorageSharedPrimitivesCurrentTests(unittest.TestCase):
    def test_credential_parsers_and_idempotency_material_are_strict(self):
        with patch.dict(
            os.environ,
            {"MEMORYENDPOINTS_CREDENTIAL_PEPPER": "synthetic-shared-pepper-" + ("x" * 48)},
        ):
            token, digest = storage._governed_credential(
                "agent", "company-1", "agent-token-1"
            )
            self.assertTrue(digest.startswith("v1:"))
            credential_id, secret = storage._parse_governed_credential(token, "agent")
            self.assertEqual("agent-token-1", credential_id)
            self.assertTrue(secret)
            self.assertEqual((None, None), storage._parse_governed_credential(token, "master"))
            self.assertEqual(
                ("masterkey-" + ("a" * 20), "b" * 43),
                storage._parse_delegated_company_master_candidate(
                    "me_master_v1." + "masterkey-" + ("a" * 20) + "." + ("b" * 43)
                ),
            )
            self.assertEqual((None, None), storage._parse_delegated_company_master_candidate("bad"))
            self.assertTrue(storage.credential_system_available())

        self.assertEqual("Company Label", storage._company_master_delegation_text("  Company   Label ", "fallback"))
        self.assertIsNone(storage._company_master_delegation_text("\x00", "fallback"))
        self.assertIsNone(storage._company_master_delegation_idempotency_hash("short"))
        self.assertTrue(storage._company_master_delegation_idempotency_hash("key-1234").startswith("sha256:"))
        self.assertIsNone(storage._human_replacement_idempotency_material("", "digest" )[0])
        self.assertEqual(
            ("sha256:" + storage._hash("key-1234"), "digest"),
            storage._human_replacement_idempotency_material("key-1234", "digest"),
        )

    def test_shared_public_projections_redact_and_preserve_identity_fields(self):
        exported = storage._safe_company_export_value(
            {"name": "Company", "tokenHash": "secret", "nested": [{"password": "secret"}]}
        )
        self.assertEqual("Company", exported["name"])
        self.assertNotIn("tokenHash", exported)
        self.assertNotIn("password", exported["nested"][0])

        master = storage._public_company_master_key(
            {"masterKeyId": "master-1", "companyId": "company-1", "issuedByAgentTokenId": "agent-token-1"}
        )
        self.assertEqual("agent", master["issuedByCredentialType"])
        self.assertEqual("active", master["status"])
        self.assertTrue(master["valuesRedacted"])
        invite = storage._public_agent_invite({"inviteId": "invite-1", "assignmentContext": {"goal": "private"}})
        self.assertEqual("invite-1", invite["inviteId"])
        self.assertNotIn("secret", invite)
        principal = storage._public_agent_principal(
            {"agentIdentityId": "identity-1", "agentId": "agent-1", "displayName": "Agent"},
            {"companyId": "company-1", "scopeType": "project", "scopeId": "project-1", "status": "active"},
            {"agentTokenId": "token-1"},
        )
        self.assertEqual("agent-1", principal["agentId"])
        self.assertFalse(principal["canInvite"])
        self.assertEqual("credential_admin", storage._human_membership_permissions("credential_admin")[1])
        account = storage._public_human_account({"humanAccountId": "human-1", "username": "owner"})
        self.assertEqual("owner", account["displayName"])
        self.assertFalse(account["rawCredentialExposed"])

    def test_shared_cursor_knowledge_and_external_ordering_contracts(self):
        items = [
            {"notification": {"notificationId": "n-1", "createdAt": "2026-01-01T00:00:00Z"}},
            {"notification": {"notificationId": "n-2", "createdAt": "2026-01-02T00:00:00Z"}},
        ]
        page = storage._cursor_page(items, "n-1", 1)
        self.assertEqual("n-1", page["cursor"])
        self.assertTrue(page["cursorAccepted"])
        expired = storage._cursor_page(items, "missing", 1)
        self.assertFalse(expired["cursorAccepted"])
        transcript = storage._meeting_transcript_page(
            [{"meetingMessageId": "m-1", "senderAgentId": "agent-1"}], None, 10
        )
        self.assertEqual("m-1", transcript["items"][0]["meetingMessageId"])

        document = {
            "title": "Operations Guide",
            "description": "Guarded rollout",
            "keywords": ["rollout"],
            "taxonomyPaths": [["Operations", "Safety"]],
            "status": "current",
            "scope": "project",
            "scopeId": "project-1",
            "content": "private content",
        }
        self.assertGreater(storage._knowledge_text_match("operations", document)["score"], 0)
        self.assertFalse(storage._knowledge_taxonomy_matches("Unknown", document))
        public = storage._public_knowledge_document(document, include_text=False, query="")
        self.assertNotIn("content", public)
        self.assertEqual("Operations Guide", public["title"])
        link = {"url": "https://example.com/guide", "pageTitle": "Operations Guide", "keywords": ["rollout"]}
        self.assertGreater(storage._external_link_search_match(link, [], "operations")["score"], 0)

    def test_shared_normalizers_and_human_audit_bindings_fail_closed(self):
        self.assertEqual(("agent-name", "agent-name"), storage._normalize_agent_access_name(" Agent-Name "))
        self.assertEqual("Agent Name", storage._normalize_agent_display_name(" Agent Name ", "fallback"))
        self.assertEqual("owner.name", storage._normalize_human_username(" Owner.Name "))
        self.assertIsNone(storage._normalize_human_username("bad name"))
        self.assertEqual(600, storage._bounded_ttl_seconds("bad", 600, 60, 3600))
        self.assertEqual(60, storage._bounded_ttl_seconds(1, 600, 60, 3600))
        self.assertEqual(3600, storage._bounded_ttl_seconds(9999, 600, 60, 3600))
        self.assertTrue(storage._custom_scope_parent_allowed("goal", "project"))
        self.assertFalse(storage._custom_scope_parent_allowed("workspace", "project"))
        context = storage._human_operational_resource_context(
            {"authorityId": "authority-1", "companyId": "company-1", "workspaceId": "workspace-1", "projectId": "project-1", "contextVersion": 2}
        )
        actor = storage._human_operational_audit_actor(
            {"humanAccountId": "human-1", "humanAccountSessionId": "session-1", "username": "owner"},
            {"authorityId": "authority-1", "companyId": "company-1", "workspaceId": "workspace-1", "projectId": "project-1"},
        )
        self.assertEqual(2, context["contextVersion"])
        self.assertTrue(storage._valid_human_operational_audit_actor(actor))
        self.assertFalse(storage._valid_human_operational_audit_actor({}))


if __name__ == "__main__":
    unittest.main()
