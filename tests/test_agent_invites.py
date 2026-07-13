import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest

from memoryendpoints.config import utc_now
from memoryendpoints.storage import FileStore, SQLiteStore


TEST_PEPPER = "storage-test-pepper-0123456789-abcdefghijklmnopqrstuvwxyz"


class AgentInviteContractMixin(object):
    store_class = None
    suffix = ""

    def setUp(self):
        self.previous_pepper = os.environ.get("MEMORYENDPOINTS_CREDENTIAL_PEPPER")
        os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = TEST_PEPPER
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = self.store_class(Path(self.tempdir.name) / ("store" + self.suffix))
        setup = self.store.create_free_account("Escape.GamesFor.me", "GamesFor.me", "mental Hospital")
        self.workspace_id, self.master_key_id, self.master_token, _account_id, self.company_id, self.project_id = setup[:6]

    def tearDown(self):
        self.tempdir.cleanup()
        if self.previous_pepper is None:
            os.environ.pop("MEMORYENDPOINTS_CREDENTIAL_PEPPER", None)
        else:
            os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = self.previous_pepper

    def _issue(self, name="escape-game-agent", scope_type="workspace", scope_id=None, **request_options):
        scope_id = scope_id or self.workspace_id
        requested = self.store.request_agent_access(
            self.company_id,
            name,
            scope_type,
            scope_id,
            display_name=request_options.pop("display_name", "Escape Game Agent"),
            justification=request_options.pop("justification", "Initial game setup"),
            assignment_context=request_options.pop("assignment_context", {"projectId": self.project_id, "taskLabel": "Initial game setup"}),
            **request_options,
        )
        self.assertTrue(requested["ok"], requested)
        request_id = requested["request"]["requestId"]
        approved = self.store.decide_agent_access_request(self.master_token, request_id, "approved", "Approved for setup")
        self.assertTrue(approved["ok"], approved)
        self.assertNotIn("inviteSecret", approved)
        invitation = self.store.issue_agent_invite(self.master_token, request_id, 900)
        self.assertTrue(invitation["ok"], invitation)
        return requested, approved, invitation

    def _counts(self):
        if isinstance(self.store, SQLiteStore):
            with self.store._open_connection() as connection:
                return {
                    "identities": connection.execute("SELECT COUNT(*) AS count FROM matm_agent_identities").fetchone()["count"],
                    "grants": connection.execute("SELECT COUNT(*) AS count FROM matm_agent_access_grants").fetchone()["count"],
                    "tokens": connection.execute("SELECT COUNT(*) AS count FROM matm_agent_tokens").fetchone()["count"],
                }
        data = self.store._load()
        return {
            "identities": len(data["agentIdentities"]),
            "grants": len(data["agentAccessGrants"]),
            "tokens": len(data["agentTokens"]),
        }

    def _add_sibling_project(self):
        project_id = "project-sibling"
        if isinstance(self.store, SQLiteStore):
            with self.store._open_connection() as connection:
                with connection:
                    connection.execute(
                        "INSERT INTO matm_projects (project_id, workspace_id, label, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (project_id, self.workspace_id, "Sibling", "active", utc_now(), None),
                    )
        else:
            data = self.store._load()
            data["projects"][project_id] = {
                "projectId": project_id,
                "workspaceId": self.workspace_id,
                "label": "Sibling",
                "status": "active",
                "createdAt": utc_now(),
            }
            self.store._save(data)
        return project_id

    def _human_authority_session(self):
        proof = self.store.create_company_master_proof(self.master_token)
        account = self.store.create_human_account(
            "credential-owner",
            "Correct-Horse-Battery-Staple-2026",
            proof["masterProofSecret"],
        )
        self.assertTrue(account["ok"], account)
        login = self.store.login_human_account("credential-owner", "Correct-Horse-Battery-Staple-2026")
        session_secret = login["sessionSecret"]
        self.store.reauthenticate_human_account_session(session_secret, "Correct-Horse-Battery-Staple-2026")
        memberships = self.store.list_human_company_memberships(session_secret)
        selected = self.store.select_human_company_membership(session_secret, memberships["items"][0]["authorityId"])
        return selected["sessionSecret"]

    def test_fresh_invite_redeems_once_and_exact_replay_is_terminal(self):
        _requested, _approved, invitation = self._issue()
        secret = invitation["inviteSecret"]
        first = self.store.redeem_agent_invite(secret)
        self.assertTrue(first["ok"], first)
        counts_after_first = self._counts()

        replay = self.store.redeem_agent_invite(secret)
        self.assertFalse(replay["ok"])
        self.assertEqual("invite_redeemed", replay["status"])
        self.assertEqual(counts_after_first, self._counts())
        self.assertEqual({"identities": 1, "grants": 1, "tokens": 1}, counts_after_first)
        self.assertIsNotNone(self.store.authenticate(first["agentToken"], self.workspace_id))

    def test_invite_replacement_is_atomically_active_and_never_delivers_a_pending_token(self):
        _requested, _approved, invitation = self._issue()
        predecessor = self.store.redeem_agent_invite(invitation["inviteSecret"])
        self.assertTrue(predecessor["ok"], predecessor)
        predecessor_secret = predecessor["agentToken"]
        predecessor_credential_id = predecessor["principal"]["credentialId"]
        immutable_grant_id = predecessor["principal"]["grantId"]

        _replacement_request, _replacement_approval, replacement_invitation = self._issue(
            supersedes_token_id=predecessor_credential_id,
            memory_transfer_from_token_id=predecessor_credential_id,
        )
        replacement = self.store.redeem_agent_invite(replacement_invitation["inviteSecret"])
        self.assertTrue(replacement["ok"], replacement)
        self.assertEqual("active", replacement["principal"]["credentialStatus"])
        self.assertEqual(immutable_grant_id, replacement["principal"]["grantId"])
        self.assertEqual(predecessor["principal"]["agentIdentityId"], replacement["principal"]["agentIdentityId"])
        self.assertEqual(predecessor_credential_id, replacement["principal"]["supersedesCredentialId"])
        self.assertEqual(predecessor_credential_id, replacement["principal"]["memoryTransferFromCredentialId"])
        self.assertIsNone(self.store.authenticate(predecessor_secret, self.workspace_id))
        self.assertIsNotNone(self.store.authenticate(replacement["agentToken"], self.workspace_id))

        if isinstance(self.store, SQLiteStore):
            with self.store._open_connection() as connection:
                successor_token = connection.execute(
                    "SELECT grant_id FROM matm_agent_tokens WHERE agent_token_id = ?",
                    (replacement["principal"]["credentialId"],),
                ).fetchone()
                successor_grant = connection.execute(
                    "SELECT status, pending_expires_at, activated_at FROM matm_agent_access_grants WHERE grant_id = ?",
                    (successor_token["grant_id"],),
                ).fetchone()
                predecessor_state = connection.execute(
                    "SELECT t.revoked_at AS token_revoked_at, g.status AS grant_status, g.revoked_at AS grant_revoked_at FROM matm_agent_tokens t JOIN matm_agent_access_grants g ON g.grant_id = t.grant_id WHERE t.agent_token_id = ?",
                    (predecessor_credential_id,),
                ).fetchone()
        else:
            data = self.store._load()
            successor_token = data["agentTokens"][replacement["principal"]["credentialId"]]
            successor_grant = data["agentAccessGrants"][successor_token["grantId"]]
            predecessor_token = data["agentTokens"][predecessor_credential_id]
            predecessor_grant = data["agentAccessGrants"][predecessor_token["grantId"]]
            predecessor_state = {
                "token_revoked_at": predecessor_token["revokedAt"],
                "grant_status": predecessor_grant["status"],
                "grant_revoked_at": predecessor_grant["revokedAt"],
            }
        self.assertEqual("active", successor_grant["status"])
        self.assertIsNone(successor_grant["pending_expires_at"] if isinstance(self.store, SQLiteStore) else successor_grant["pendingExpiresAt"])
        self.assertIsNotNone(successor_grant["activated_at"] if isinstance(self.store, SQLiteStore) else successor_grant["activatedAt"])
        self.assertIsNotNone(predecessor_state["token_revoked_at"])
        self.assertEqual("revoked", predecessor_state["grant_status"])
        self.assertIsNotNone(predecessor_state["grant_revoked_at"])

        replay = self.store.redeem_agent_invite(replacement_invitation["inviteSecret"])
        self.assertFalse(replay["ok"])
        self.assertEqual("invite_redeemed", replay["status"])

    def test_concurrent_redemption_has_exactly_one_winner(self):
        _requested, _approved, invitation = self._issue(name="concurrent-agent")
        secret = invitation["inviteSecret"]
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _index: self.store.redeem_agent_invite(secret), range(8)))
        self.assertEqual(1, sum(1 for result in results if result["ok"]))
        self.assertTrue(all(result["ok"] or result["status"] == "invite_redeemed" for result in results))
        self.assertEqual({"identities": 1, "grants": 1, "tokens": 1}, self._counts())

    def test_workspace_scope_excludes_company_and_includes_descendants(self):
        sibling_project = self._add_sibling_project()
        goal = self.store.register_scope_node(self.company_id, "goal", "goal-initial-game", "project", self.project_id)
        task = self.store.register_scope_node(self.company_id, "task", "task-initial-game", "goal", "goal-initial-game")
        self.assertTrue(goal["ok"], goal)
        self.assertTrue(task["ok"], task)
        _requested, _approved, invitation = self._issue(name="workspace-agent")
        redeemed = self.store.redeem_agent_invite(invitation["inviteSecret"])
        principal = redeemed["principal"]
        self.assertFalse(self.store.auth_allows_scope(principal, "company", self.company_id))
        self.assertTrue(self.store.auth_allows_scope(principal, "workspace", self.workspace_id))
        self.assertTrue(self.store.auth_allows_scope(principal, "project", self.project_id))
        self.assertTrue(self.store.auth_allows_scope(principal, "project", sibling_project))
        self.assertTrue(self.store.auth_allows_scope(principal, "goal", "goal-initial-game"))
        self.assertTrue(self.store.auth_allows_scope(principal, "task", "task-initial-game"))
        self.assertFalse(self.store.auth_allows_scope(principal, "task", "unparented-task"))

    def test_project_goal_and_task_grants_follow_ancestry_without_sibling_leaks(self):
        sibling_project = self._add_sibling_project()
        self.store.register_scope_node(self.company_id, "goal", "goal-one", "project", self.project_id)
        self.store.register_scope_node(self.company_id, "task", "task-one", "goal", "goal-one")

        _r, _a, project_invite = self._issue("project-agent", "project", self.project_id)
        project_principal = self.store.redeem_agent_invite(project_invite["inviteSecret"])["principal"]
        self.assertTrue(self.store.auth_allows_scope(project_principal, "goal", "goal-one"))
        self.assertTrue(self.store.auth_allows_scope(project_principal, "task", "task-one"))
        self.assertFalse(self.store.auth_allows_scope(project_principal, "project", sibling_project))
        self.assertFalse(self.store.auth_allows_scope(project_principal, "workspace", self.workspace_id))

        _r, _a, goal_invite = self._issue("goal-agent", "goal", "goal-one")
        goal_principal = self.store.redeem_agent_invite(goal_invite["inviteSecret"])["principal"]
        self.assertTrue(self.store.auth_allows_scope(goal_principal, "goal", "goal-one"))
        self.assertTrue(self.store.auth_allows_scope(goal_principal, "task", "task-one"))
        self.assertFalse(self.store.auth_allows_scope(goal_principal, "project", self.project_id))

        _r, _a, task_invite = self._issue("task-agent", "task", "task-one")
        task_principal = self.store.redeem_agent_invite(task_invite["inviteSecret"])["principal"]
        self.assertTrue(self.store.auth_allows_scope(task_principal, "task", "task-one"))
        self.assertFalse(self.store.auth_allows_scope(task_principal, "goal", "goal-one"))

    def test_master_only_management_and_immediate_revocation(self):
        requested, _approved, invitation = self._issue()
        redeemed = self.store.redeem_agent_invite(invitation["inviteSecret"])
        agent_token = redeemed["agentToken"]
        agent_token_id = redeemed["principal"]["agentTokenId"]
        denied = self.store.issue_agent_invite(agent_token, requested["request"]["requestId"])
        self.assertEqual("company_master_required", denied["status"])
        denied = self.store.revoke_agent_token(agent_token, agent_token_id)
        self.assertEqual("company_master_required", denied["status"])
        revoked = self.store.revoke_agent_token(self.master_token, agent_token_id)
        self.assertTrue(revoked["ok"], revoked)
        self.assertIsNone(self.store.authenticate(agent_token, self.workspace_id))

    def test_credentials_are_hmac_digests_and_raw_values_are_never_persisted(self):
        _requested, _approved, invitation = self._issue()
        redeemed = self.store.redeem_agent_invite(invitation["inviteSecret"])
        raw_values = [self.master_token, invitation["inviteSecret"], redeemed["agentToken"]]
        if isinstance(self.store, SQLiteStore):
            with self.store._open_connection() as connection:
                digests = [connection.execute("SELECT token_hash FROM matm_company_master_keys").fetchone()["token_hash"]]
                digests += [connection.execute("SELECT token_hash FROM matm_agent_invites").fetchone()["token_hash"]]
                digests += [connection.execute("SELECT token_hash FROM matm_agent_tokens").fetchone()["token_hash"]]
                self.assertEqual(0, connection.execute("SELECT COUNT(*) AS count FROM matm_api_keys").fetchone()["count"])
            serialized = " ".join(digests)
        else:
            serialized = self.store.path.read_text(encoding="utf-8")
            payload = json.loads(serialized)
            digests = [next(iter(payload["companyMasterKeys"].values()))["tokenHash"]]
            digests += [next(iter(payload["agentInvites"].values()))["secretHash"]]
            digests += [next(iter(payload["agentTokens"].values()))["tokenHash"]]
            self.assertEqual({}, payload["apiKeys"])
        self.assertTrue(all(digest.startswith("v1:") for digest in digests))
        for raw_value in raw_values:
            self.assertNotIn(raw_value, serialized)

    def test_company_scoped_name_uniqueness_and_cross_company_reuse(self):
        first = self.store.request_agent_access(self.company_id, "shared-agent", "workspace", self.workspace_id)
        self.assertTrue(first["ok"], first)
        duplicate = self.store.request_agent_access(self.company_id, "shared-agent", "workspace", self.workspace_id)
        self.assertEqual("agent_name_unavailable", duplicate["status"])

        other_workspace, _master_id, _master, _account, other_company, _project = self.store.create_free_account("Other", "Other Company", "Other Project")[:6]
        cross_company = self.store.request_agent_access(other_company, "shared-agent", "workspace", other_workspace)
        self.assertTrue(cross_company["ok"], cross_company)
        invalid = self.store.request_agent_access(self.company_id, "Opaque_Random.Agent", "workspace", self.workspace_id)
        self.assertEqual("agent_name_invalid", invalid["status"])

    def test_human_authorized_two_phase_replacement_never_requires_predecessor_proof(self):
        _requested, _approved, invitation = self._issue()
        predecessor = self.store.redeem_agent_invite(invitation["inviteSecret"])
        predecessor_secret = predecessor["agentToken"]
        predecessor_id = predecessor["principal"]["credentialId"]
        human_session = self._human_authority_session()

        prepared = self.store.prepare_agent_token_replacement(human_session, predecessor_id)
        self.assertTrue(prepared["ok"], prepared)
        successor_secret = prepared["successorTokenSecret"]
        self.assertIsNotNone(self.store.authenticate(predecessor_secret, self.workspace_id))
        self.assertIsNone(self.store.authenticate(successor_secret, self.workspace_id))

        confirmed = self.store.confirm_agent_token_replacement(successor_secret)
        self.assertTrue(confirmed["ok"], confirmed)
        self.assertFalse(confirmed["idempotentReplay"])
        self.assertIsNone(self.store.authenticate(predecessor_secret, self.workspace_id))
        self.assertIsNotNone(self.store.authenticate(successor_secret, self.workspace_id))
        replay = self.store.confirm_agent_token_replacement(successor_secret)
        self.assertTrue(replay["ok"], replay)
        self.assertTrue(replay["idempotentReplay"])

        cancelled_candidate = self.store.prepare_agent_token_replacement(
            human_session,
            prepared["successorCredentialId"],
        )
        self.assertTrue(cancelled_candidate["ok"], cancelled_candidate)
        cancelled = self.store.cancel_agent_token_replacement(
            human_session,
            cancelled_candidate["successorCredentialId"],
        )
        self.assertTrue(cancelled["ok"], cancelled)
        self.assertIsNotNone(self.store.authenticate(successor_secret, self.workspace_id))
        self.assertIsNone(self.store.authenticate(cancelled_candidate["successorTokenSecret"], self.workspace_id))


class FileStoreAgentInviteTests(AgentInviteContractMixin, unittest.TestCase):
    store_class = FileStore
    suffix = ".json"


class SQLiteStoreAgentInviteTests(AgentInviteContractMixin, unittest.TestCase):
    store_class = SQLiteStore
    suffix = ".sqlite3"


if __name__ == "__main__":
    unittest.main()
