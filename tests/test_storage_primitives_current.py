"""Focused current-contract coverage for storage validators and projections."""

from __future__ import annotations

import base64
import datetime
import os
import tempfile
import time
import unittest
from pathlib import Path

from memoryendpoints import storage
from memoryendpoints import connector_pairing


def _secret(fill):
    return base64.urlsafe_b64encode(bytes([fill]) * 32).decode("ascii").rstrip("=")


class StoragePrimitivesCurrentTests(unittest.TestCase):
    def test_bootstrap_digests_and_canonical_secret_shapes_are_fail_closed(self):
        capability = _secret(7)
        self.assertEqual(64, len(storage.bootstrap_capability_digest(capability)))
        self.assertEqual(64, len(storage.bootstrap_idempotency_digest(capability)))
        self.assertIsNone(storage.bootstrap_capability_digest(capability + "="))
        self.assertIsNone(storage.bootstrap_capability_digest("not-a-capability"))
        self.assertNotEqual(
            storage.bootstrap_request_digest({"b": 2, "a": 1}),
            storage.bootstrap_request_digest({"b": 3, "a": 1}),
        )

    def test_invite_and_bootstrap_body_validators_preserve_exact_secret_contracts(self):
        invite = "me_invite_v1.invite-" + ("a" * 20) + "." + _secret(1)
        agent = "me_agent_v1.agenttoken-" + ("b" * 20) + "." + _secret(2)
        invite_body = {
            "schemaVersion": "memoryendpoints.agent_invite_redemption.v1",
            "inviteSecret": invite,
            "candidateAgentTokenSecret": agent,
        }
        normalized_invite = storage.validate_agent_invite_redemption_body(invite_body)
        self.assertEqual(invite_body, normalized_invite)
        self.assertTrue(storage.agent_invite_redemption_request_digest(invite_body))
        self.assertTrue(storage.agent_invite_redemption_idempotency_digest("invite-key-0001"))
        self.assertIsNone(
            storage.validate_agent_invite_redemption_body({**invite_body, "extra": True})
        )

        bootstrap_body = {
            "schemaVersion": "memoryendpoints.bootstrap_account_request.v1",
            "companyLabel": "Example Company",
            "workspaceLabel": "Main Workspace",
            "projectLabel": "Memory Project",
            "candidateCompanyMasterTokenSecret": "me_master_v1.masterkey-" + ("c" * 20) + "." + _secret(3),
            "candidateHumanOwnerRecoverySecret": "me_human_v1.humancred-" + ("d" * 20) + "." + _secret(4),
        }
        normalized_bootstrap = storage.validate_bootstrap_account_body(bootstrap_body)
        self.assertEqual("masterkey-" + ("c" * 20), normalized_bootstrap["companyMasterCredentialId"])
        self.assertEqual("humancred-" + ("d" * 20), normalized_bootstrap["humanOwnerCredentialId"])
        self.assertIsNone(
            storage.validate_bootstrap_account_body({**bootstrap_body, "companyLabel": "bad\nlabel"})
        )

    def test_idempotency_and_public_projection_helpers_are_deterministic(self):
        pending = storage._idempotency_pending_payload("claim-1")
        self.assertEqual("claim-1", storage._idempotency_pending_claim(pending))
        self.assertEqual("", storage._idempotency_pending_claim(None))
        self.assertTrue(storage._idempotency_claim_is_stale("not-a-date"))
        future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=5)).isoformat()
        self.assertFalse(storage._idempotency_claim_is_stale(future))
        self.assertEqual(7, storage._json_size({"x": 1}))
        self.assertEqual(
            {"safe": "ok", "payload": "password: [REDACTED_SECRET]"},
            storage._public_value({"safe": "ok", "payload": "password: synthetic-password-value"}),
        )
        self.assertEqual(["hello", "world"], storage._search_tokens("Hello, x world"))
        delegation_hash = storage._company_master_delegation_idempotency_hash("a" * 8)
        self.assertTrue(delegation_hash.startswith("sha256:"))
        self.assertEqual(71, len(delegation_hash))
        self.assertIsNone(storage._company_master_delegation_idempotency_hash("short"))

    def test_connector_rate_policy_and_persistent_windows_are_fail_closed(self):
        self.assertEqual(10, storage._connector_rate_now_epoch(10.9))
        self.assertEqual(10, storage._connector_rate_now_epoch(datetime.datetime.fromtimestamp(10, datetime.timezone.utc)))
        with self.assertRaisesRegex(ValueError, "time_invalid"):
            storage._connector_rate_now_epoch(True)
        with self.assertRaisesRegex(ValueError, "time_invalid"):
            storage._connector_rate_now_epoch(datetime.datetime(2026, 1, 1))
        with self.assertRaisesRegex(ValueError, "bucket_invalid"):
            storage._connector_rate_policy("unknown", 1, 1)
        with self.assertRaisesRegex(ValueError, "policy_invalid"):
            storage._connector_rate_policy("search", 0, 1)
        self.assertEqual((3, 60), storage._connector_rate_policy("search", "3", "60"))
        with tempfile.TemporaryDirectory() as tmp:
            store = storage.FileStore(Path(tmp) / "rate.json")
            first = store.consume_connector_rate_limit("search", "partition-a", 1, 60, now=100)
            denied = store.consume_connector_rate_limit("search", "partition-a", 1, 60, now=101)
            reset = store.consume_connector_rate_limit("search", "partition-a", 1, 60, now=161)
        self.assertTrue(first["allowed"])
        self.assertFalse(denied["allowed"])
        self.assertEqual("search", denied["bucket"])
        self.assertGreaterEqual(denied["retryAfterSeconds"], 1)
        self.assertTrue(reset["allowed"])

    def test_connector_sqlite_lock_helpers_add_mysql_locks_only_when_needed(self):
        class Result:
            def fetchone(self):
                return "one"

        class Connection:
            dialect = "sqlite"

            def __init__(self):
                self.sql = []

            def execute(self, statement, params=()):
                self.sql.append((statement, params))
                return Result()

        sqlite = Connection()
        self.assertTrue(storage._connector_begin_immediate(sqlite))
        self.assertEqual("one", storage._connector_select_for_update(sqlite, "SELECT 1;", (1,)))
        mysql = Connection()
        mysql.dialect = "mysql"
        self.assertFalse(storage._connector_begin_immediate(mysql))
        storage._connector_select_for_update(mysql, "SELECT 1;", ())
        self.assertTrue(mysql.sql[-1][0].endswith("FOR UPDATE"))

    def test_connector_selector_refs_bind_session_resource_and_expiry(self):
        previous = os.environ.get("MEMORYENDPOINTS_CREDENTIAL_PEPPER")
        os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = "synthetic-storage-pepper-" + ("x" * 48)
        self.addCleanup(
            lambda: os.environ.__setitem__("MEMORYENDPOINTS_CREDENTIAL_PEPPER", previous)
            if previous is not None
            else os.environ.pop("MEMORYENDPOINTS_CREDENTIAL_PEPPER", None)
        )
        actor = {
            "humanAccountSessionId": "session-1",
            "humanAccountId": "account-1",
            "companyId": "company-1",
            "selectedAuthorityId": "authority-1",
        }
        public_request_ref = connector_pairing.generate_public_request_ref()
        expiry = int(time.time()) + 120
        workspace = {"workspaceId": "workspace-1", "companyId": "company-1", "status": "active"}
        workspace_ref = storage._connector_workspace_ref(actor, public_request_ref, "workspace-1", expiry)
        self.assertEqual(expiry, storage._connector_selector_ref_expiry(workspace_ref, storage._CONNECTOR_WORKSPACE_REF_PATTERN))
        resolved, error = storage._connector_resolve_workspace_ref(actor, public_request_ref, workspace_ref, [workspace])
        self.assertEqual((workspace, None), (resolved, error))
        self.assertEqual((None, "workspace_ref_invalid"), storage._connector_resolve_workspace_ref(actor, public_request_ref, "bad", [workspace]))
        expired = storage._connector_workspace_ref(actor, public_request_ref, "workspace-1", int(time.time()) - 1)
        self.assertEqual((None, "workspace_ref_expired"), storage._connector_resolve_workspace_ref(actor, public_request_ref, expired, [workspace]))
        company_ref = storage._connector_company_ref(actor, public_request_ref, "authority-1", "company-1", expiry)
        authority = {"authorityId": "authority-1", "companyId": "company-1", "humanAccountId": "account-1", "status": "active"}
        resolved_authority, error = storage._connector_resolve_company_ref(actor, public_request_ref, company_ref, [authority], {"company-1": {"status": "active"}})
        self.assertEqual((authority, None), (resolved_authority, error))
        self.assertEqual((None, "company_ref_invalid"), storage._connector_resolve_company_ref(actor, public_request_ref, "bad", [authority], {}))
        with self.assertRaisesRegex(ValueError, "selector_ref_kind_invalid"):
            storage._connector_selector_ref("other", actor, public_request_ref, "resource", "binding", expiry)

    def test_connector_idempotency_audit_and_projection_helpers_cover_replays(self):
        previous = os.environ.get("MEMORYENDPOINTS_CREDENTIAL_PEPPER")
        os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = "synthetic-storage-pepper-" + ("y" * 48)
        self.addCleanup(
            lambda: os.environ.__setitem__("MEMORYENDPOINTS_CREDENTIAL_PEPPER", previous)
            if previous is not None
            else os.environ.pop("MEMORYENDPOINTS_CREDENTIAL_PEPPER", None)
        )
        digest = "sha256-v1:" + ("a" * 64)
        self.assertEqual((None, None), storage._connector_idempotency_material("bad key\n", digest))
        record = {}
        first = storage._connector_action_replay(record, "approve", "key-1", digest)
        self.assertEqual("first", first[0])
        storage._connector_record_action(record, "approve", first[1], digest, first[2])
        self.assertEqual("exact", storage._connector_action_replay(record, "approve", "key-1", digest)[0])
        self.assertEqual("conflict", storage._connector_action_replay(record, "approve", "key-1", "sha256-v1:" + ("b" * 64))[0])
        self.assertEqual("used", storage._connector_action_replay(record, "approve", "other-key", digest)[0])
        self.assertTrue(storage._connector_audit_reference("request", "private-ref").startswith("connector-request-ref-"))
        self.assertEqual("connector-subject", storage._connector_audit_reference("bad key", ""))
        details = storage._connector_audit_details("workspace-1", {"scopeDigest": digest, "publicRequestRef": "private-ref"})
        self.assertEqual(digest, details["scopeDigest"])
        self.assertFalse(details["privateIdentifiersLogged"])
        self.assertEqual(("id", "proof"), storage._parse_connector_credential("me_connector_v1.id.proof"))
        self.assertEqual((None, None), storage._parse_connector_credential("bad"))
        self.assertEqual("pairing_error", storage._connector_pairing_error("pairing_error")["status"])

    def test_uai_summary_and_knowledge_excerpt_bound_text_and_firewall(self):
        self.assertEqual((None, "summary_required"), storage._validate_uai_collaboration_summary(" ", "summary")[:2])
        self.assertEqual((None, "summary_too_long"), storage._validate_uai_collaboration_summary("x" * 1001, "summary")[:2])
        rejected = storage._validate_uai_collaboration_summary("javascript:alert(1)", "summary")
        self.assertEqual("uai_collaboration_summary_rejected_by_memory_firewall", rejected[1])
        self.assertEqual("short text", storage._knowledge_excerpt(" short\ntext ", "", 50))
        long_text = "prefix " * 30 + "needle " + "suffix " * 100
        excerpt = storage._knowledge_excerpt(long_text, "needle", 30)
        self.assertTrue(excerpt.startswith("..."))
        self.assertTrue(excerpt.endswith("..."))

    def test_memory_and_external_search_ranking_covers_empty_slug_linked_and_partial_queries(self):
        event = {
            "title": "Managed memory rollout",
            "subject": "tenant isolation",
            "tags": ["release", "safety"],
            "summary": "The guarded rollout is complete.",
            "source": "memoryendpoints://release",
            "memoryType": "note",
            "actorAgentId": "release-agent",
            "eventId": "event-1",
        }
        linked = {
            "title": "Tenant operations guide",
            "keywords": ["rollouts"],
            "taxonomyPaths": [["Operations", "Safety"]],
            "description": "A public guide.",
            "searchableText": "guarded deployment",
        }
        self.assertEqual(0, storage._memory_text_match("", event)["score"])
        self.assertEqual(200, storage._memory_text_match("release-agent", event)["score"])
        match = storage._memory_text_match("rollout operations missing", event, linked)
        self.assertIn("rollout", match["matchedTerms"])
        self.assertIn("operation", match["linkedKnowledgeMatchedTerms"])
        self.assertEqual(0, storage._memory_text_match("title subject summary", event)["score"])
        external = {
            "pageTitle": "Operations rollout guide",
            "siteName": "Example",
            "keywords": ["safety"],
            "description": "Guarded deployment reference",
            "host": "example.com",
            "url": "https://example.com/guide",
        }
        ranked = storage._external_link_search_match(
            external,
            [{"anchorText": "rollout", "taxonomyPathLabels": ["Operations > Safety"]}],
            "rollout safety",
        )
        self.assertGreater(ranked["score"], 0)
        self.assertEqual([], storage._external_link_search_match(external, [], "")["matchedTerms"])

    def test_scope_authorization_matrix_rejects_missing_foreign_and_non_agent_principals(self):
        for store_type, suffix in ((storage.FileStore, ".json"), (storage.SQLiteStore, ".sqlite3")):
            with self.subTest(backend=store_type.__name__), tempfile.TemporaryDirectory() as tmp:
                store = store_type(Path(tmp) / ("scope" + suffix))
                workspace_id, _master_key, master_secret, _account, company_id, _project, _recovery = store.create_free_account(
                    "Scope Workspace", "Scope Company", "Scope Project"
                )
                master = store.authenticate_company_master(master_secret)
                self.assertTrue(store.auth_allows_scope(master, "workspace", workspace_id))
                self.assertFalse(store.auth_allows_scope(master, "workspace", "other-workspace"))
                self.assertFalse(store.auth_allows_scope({"credentialType": "human"}, "workspace", workspace_id))
                self.assertFalse(store.auth_allows_scope({"credentialType": "agent", "agentTokenId": "missing"}, "workspace", workspace_id))
                self.assertFalse(store.auth_allows_scope(None, "workspace", workspace_id))
                self.assertEqual(company_id, master["companyId"])

    def test_access_lifecycle_projection_and_quota_helpers_cover_terminal_shapes(self):
        invite = {
            "inviteId": "invite-1",
            "requestId": "request-1",
            "companyId": "company-1",
            "agentIdentityId": "identity-1",
            "agentId": "agent-1",
            "agentName": "Agent One",
            "scopeType": "project",
            "scopeId": "project-1",
            "status": "redeemed",
            "createdAt": "2026-09-11T12:00:00Z",
            "expiresAt": "2026-09-12T12:00:00Z",
            "redeemedAt": "2026-09-11T12:01:00Z",
            "grantId": "grant-1",
            "agentTokenId": "token-1",
            "assignmentContext": {"projectId": "project-1", "secret": "hidden"},
        }
        identity = {
            "agentIdentityId": "identity-1",
            "agentId": "agent-1",
            "agentName": "Agent One",
            "displayName": "Agent One",
        }
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
        onboarding = {"workspaceId": "workspace-1", "entryRoom": {"roomId": "room-1"}}
        success = storage._agent_invite_redemption_success(
            invite, identity, grant, token, onboarding, False
        )
        self.assertTrue(success["ok"])
        receipt = storage._agent_invite_redemption_receipt(
            invite, identity, grant, token, onboarding
        )
        replay = storage._agent_invite_redemption_result_from_receipt(receipt, True)
        self.assertTrue(replay["_idempotentReplay"])
        for mutation in (
            None,
            {**receipt, "rawPayloadExposed": True},
            {**receipt, "extra": True},
            {**receipt, "principal": []},
        ):
            with self.subTest(mutation=mutation):
                self.assertIsNone(
                    storage._agent_invite_redemption_result_from_receipt(mutation, False)
                )

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
        self.assertTrue(storage._is_npc_agent_name("npc-agent-1"))
        self.assertFalse(storage._is_npc_agent_name("human-agent-1"))
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
            {"safe": "ok", "passwordHash": "secret", "items": [{"token_hash": "secret", "value": 1}]}
        )
        self.assertEqual({"safe": "ok", "passwordHash": "secret", "items": [{"value": 1}]}, nested)
        self.assertEqual("sha256:" + "a" * 64, storage._human_replacement_idempotency_material("key", "sha256:" + "a" * 64)[1])
        self.assertEqual((None, None), storage._human_replacement_idempotency_material("", "digest"))
        self.assertEqual((None, None), storage._human_replacement_idempotency_material("key", ""))

        self.assertEqual("active", storage._public_company_master_key({})["status"])
        self.assertEqual("revoked", storage._public_company_master_key({"revokedAt": "now"})["status"])
        public_request = storage._public_agent_access_request({"agentName": "agent"})
        self.assertEqual("agent", public_request["requestedName"])
        self.assertEqual("agent", public_request["displayName"])
        public_invite = storage._public_agent_invite(invite)
        self.assertTrue(public_invite["singleUse"])
        public_principal = storage._public_agent_principal(identity, grant, token)
        self.assertFalse(public_principal["canInvite"])
        self.assertEqual(["agent_inventory_read"], storage._human_membership_permissions("member"))
        self.assertIn("company_lifecycle", storage._human_membership_permissions("owner"))
        self.assertIsNone(storage._public_human_membership({"role": "owner"})["companyStatus"])
        self.assertEqual("user", storage._public_human_account({"username": "user"})["displayName"])
        self.assertEqual("revoked", storage._public_human_agent_token({"revokedAt": "now"}, {}, {})["status"])
        self.assertTrue(storage._public_agent_token_replacement({"status": "prepared"})["predecessorRemainsActive"])
        self.assertFalse(storage._public_agent_token_replacement({"status": "confirmed"})["predecessorRemainsActive"])


if __name__ == "__main__":
    unittest.main()
