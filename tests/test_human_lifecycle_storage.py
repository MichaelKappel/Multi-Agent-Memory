import json
import os
from pathlib import Path
import tempfile
import unittest

from memoryendpoints.storage import FileStore, SQLiteStore


TEST_PEPPER = "human-lifecycle-test-pepper-0123456789-abcdefghijklmnopqrstuvwxyz"


class HumanLifecycleStorageMixin(object):
    store_class = None
    suffix = ""

    def setUp(self):
        self.previous_pepper = os.environ.get("MEMORYENDPOINTS_CREDENTIAL_PEPPER")
        os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = TEST_PEPPER
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = self.store_class(Path(self.tempdir.name) / ("store" + self.suffix))
        setup = self.store.create_free_account("Escape.GamesFor.me", "GamesFor.me", "mental Hospital")
        (
            self.workspace_id,
            self.master_key_id,
            self.master_secret,
            self.account_id,
            self.company_id,
            self.project_id,
            self.recovery_secret,
        ) = setup
        proof = self.store.create_company_master_proof(self.master_secret)
        self.assertTrue(proof["ok"], proof)
        account = self.store.create_human_account("escape-owner", "Correct-Horse-Battery-Staple-2026", proof["masterProofSecret"])
        self.assertTrue(account["ok"], account)
        self.human_session = self.store.login_human_account("escape-owner", "Correct-Horse-Battery-Staple-2026")
        self.session_secret = self.human_session["sessionSecret"]
        self.store.reauthenticate_human_account_session(self.session_secret, "Correct-Horse-Battery-Staple-2026")
        memberships = self.store.list_human_company_memberships(self.session_secret)
        selected = self.store.select_human_company_membership(self.session_secret, memberships["items"][0]["authorityId"])
        self.assertTrue(selected["ok"], selected)
        self.session_secret = selected["sessionSecret"]
        self.human_session = selected

    def tearDown(self):
        self.tempdir.cleanup()
        if self.previous_pepper is None:
            os.environ.pop("MEMORYENDPOINTS_CREDENTIAL_PEPPER", None)
        else:
            os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = self.previous_pepper

    def _intent(self, purpose):
        result = self.store.create_company_closure_intent(self.session_secret, purpose, True)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["intentSecret"].startswith("me_closure_v1."))
        return result

    def test_setup_returns_exceptional_recovery_and_account_session_requires_valid_csrf(self):
        self.assertTrue(self.recovery_secret.startswith("me_human_v1."))
        owner = self.store.authenticate_human_owner(self.recovery_secret, self.company_id)
        self.assertEqual("human_owner_recovery", owner["credentialType"])
        self.assertIsNotNone(self.store.authenticate_human_account_session(self.session_secret))
        self.assertIsNotNone(
            self.store.authenticate_human_account_session(
                self.session_secret,
                self.human_session["csrfToken"],
                require_csrf=True,
            )
        )
        self.assertIsNone(self.store.authenticate_human_account_session(self.session_secret, "wrong", require_csrf=True))

    def test_membership_selection_rotates_session_and_preserves_recent_reauthentication(self):
        login = self.store.login_human_account("escape-owner", "Correct-Horse-Battery-Staple-2026")
        old_secret = login["sessionSecret"]
        reauthenticated = self.store.reauthenticate_human_account_session(old_secret, "Correct-Horse-Battery-Staple-2026")
        memberships = self.store.list_human_company_memberships(old_secret)
        selected = self.store.select_human_company_membership(old_secret, memberships["items"][0]["authorityId"])
        self.assertTrue(selected["ok"], selected)
        self.assertTrue(selected["credentialReturnedOnce"])
        self.assertIsNone(self.store.authenticate_human_account_session(old_secret))
        rotated = self.store.authenticate_human_account_session(selected["sessionSecret"])
        self.assertEqual(self.company_id, rotated["companyId"])
        self.assertEqual(reauthenticated["passwordReauthenticatedAt"], rotated["passwordReauthenticatedAt"])

    def test_master_proof_is_required_single_use_expiring_and_never_persists_raw_master(self):
        without_proof = self.store.create_human_account(
            "orphan-owner",
            "Another-Sufficiently-Strong-Password-2026",
        )
        self.assertEqual("company_master_proof_required", without_proof["status"])
        invalid = self.store.create_human_account(
            "invalid-owner",
            "Another-Sufficiently-Strong-Password-2026",
            "me_masterproof_v1.invalid.invalid",
        )
        self.assertEqual("company_master_proof_invalid", invalid["status"])

        other_setup = self.store.create_free_account("Other", "Other Company", "Other Project")
        other_master = other_setup[2]
        other_company = other_setup[4]
        proof = self.store.create_company_master_proof(other_master)
        created = self.store.create_human_account(
            "other-owner",
            "Another-Sufficiently-Strong-Password-2026",
            proof["masterProofSecret"],
        )
        self.assertTrue(created["ok"], created)
        self.assertEqual(other_company, created["authority"]["companyId"])
        reused = self.store.create_human_account(
            "proof-reuser",
            "Another-Sufficiently-Strong-Password-2026",
            proof["masterProofSecret"],
        )
        self.assertEqual("company_master_proof_consumed", reused["status"])

        expiring_setup = self.store.create_free_account("Expired", "Expired Company", "Expired Project")
        expired_proof = self.store.create_company_master_proof(expiring_setup[2])
        proof_id = expired_proof["masterProofId"]
        if isinstance(self.store, SQLiteStore):
            with self.store._open_connection() as connection:
                with connection:
                    connection.execute("UPDATE matm_company_master_proofs SET expires_at = ? WHERE master_proof_id = ?", ("2000-01-01T00:00:00.000000Z", proof_id))
        else:
            payload = self.store._load()
            payload["companyMasterProofs"][proof_id]["expiresAt"] = "2000-01-01T00:00:00.000000Z"
            self.store._save(payload)
        expired = self.store.create_human_account(
            "expired-proof-owner",
            "Another-Sufficiently-Strong-Password-2026",
            expired_proof["masterProofSecret"],
        )
        self.assertEqual("company_master_proof_expired", expired["status"])

        if isinstance(self.store, SQLiteStore):
            with self.store._open_connection() as connection:
                row = connection.execute("SELECT password_verifier FROM matm_human_accounts WHERE username_normalized = ?", ("other-owner",)).fetchone()
                columns = {item["name"] for item in connection.execute("PRAGMA table_info(matm_human_accounts)")}
            self.assertTrue(row["password_verifier"].startswith("me_scrypt_v1$"))
            self.assertNotIn("password_salt", columns)
            persisted = self.store.path.read_bytes()
            self.assertNotIn(other_master.encode("utf-8"), persisted)
        else:
            payload = self.store._load()
            account = next(item for item in payload["humanAccounts"].values() if item["usernameNormalized"] == "other-owner")
            self.assertTrue(account["passwordVerifier"].startswith("me_scrypt_v1$"))
            self.assertNotIn("passwordSalt", account)
            self.assertNotIn(other_master, self.store.path.read_text(encoding="utf-8"))

    def test_export_snapshot_excludes_all_credential_and_verifier_material(self):
        snapshot = self.store.company_export_snapshot(self.session_secret)
        self.assertTrue(snapshot["ok"], snapshot)
        serialized = json.dumps(snapshot, sort_keys=True)
        for secret in (
            self.master_secret,
            self.recovery_secret,
            self.session_secret,
            self.human_session["csrfToken"],
        ):
            self.assertNotIn(secret, serialized)
        for forbidden in ("tokenHash", "sessionHash", "csrfHash", "secretHash", "intentHash"):
            self.assertNotIn(forbidden, serialized)
        self.assertTrue(snapshot["snapshot"]["credentialsExcluded"])
        self.assertTrue(snapshot["snapshot"]["verifierSecretsExcluded"])

    def test_soft_delete_retains_data_denies_governed_auth_and_restore_reactivates(self):
        request = self.store.request_agent_access(self.company_id, "escape-game-agent", "workspace", self.workspace_id)
        request_id = request["request"]["requestId"]
        self.store.decide_agent_access_request(self.master_secret, request_id, "approved")
        invite = self.store.issue_agent_invite(self.master_secret, request_id)
        agent = self.store.redeem_agent_invite(invite["inviteSecret"])
        agent_secret = agent["agentToken"]

        intent = self._intent("soft_delete")
        deleted = self.store.soft_delete_company(self.session_secret, intent["intentSecret"], "GamesFor.me")
        self.assertEqual("soft_deleted", deleted["status"])
        self.assertTrue(deleted["dataRetained"])
        self.assertIsNone(self.store.authenticate(self.master_secret, self.workspace_id))
        self.assertIsNone(self.store.authenticate(agent_secret, self.workspace_id))
        self.assertIsNotNone(self.store.authenticate_human_account_session(self.session_secret))

        replay = self.store.soft_delete_company(self.session_secret, intent["intentSecret"], "GamesFor.me")
        self.assertFalse(replay["ok"])
        restored = self.store.restore_company(self.session_secret)
        self.assertEqual("active", restored["status"])
        self.assertIsNotNone(self.store.authenticate(self.master_secret, self.workspace_id))
        self.assertIsNotNone(self.store.authenticate(agent_secret, self.workspace_id))

    def test_close_revokes_machine_credentials_but_preserves_human_export(self):
        intent = self._intent("close")
        closed = self.store.close_company(self.session_secret, intent["intentSecret"], "GamesFor.me")
        self.assertEqual("closed", closed["status"])
        self.assertIsNone(self.store.authenticate(self.master_secret, self.workspace_id))
        self.assertIsNotNone(self.store.authenticate_human_owner(self.recovery_secret))
        self.assertTrue(self.store.company_export_snapshot(self.session_secret)["ok"])

    def test_permanent_purge_requires_export_receipt_or_explicit_no_export_ack(self):
        close_intent = self._intent("close")
        self.store.close_company(self.session_secret, close_intent["intentSecret"], "GamesFor.me")
        purge_intent = self._intent("permanent_purge")
        denied = self.store.permanently_purge_company(
            self.session_secret,
            purge_intent["intentSecret"],
            "PERMANENTLY PURGE GamesFor.me",
        )
        self.assertEqual("export_receipt_or_no_export_acknowledgement_required", denied["status"])

        receipt = self.store.record_company_export_receipt(self.session_secret, "a" * 64)
        purged = self.store.permanently_purge_company(
            self.session_secret,
            purge_intent["intentSecret"],
            "PERMANENTLY PURGE GamesFor.me",
            export_receipt_id=receipt["receipt"]["exportReceiptId"],
        )
        self.assertEqual("purged", purged["status"])
        self.assertIsNone(self.store.authenticate_human_owner(self.recovery_secret))
        self.assertIsNone(self.store.human_actor_context(self.session_secret))
        self.assertIsNotNone(self.store.authenticate_human_account_session(self.session_secret))


class FileStoreHumanLifecycleStorageTests(HumanLifecycleStorageMixin, unittest.TestCase):
    store_class = FileStore
    suffix = ".json"


class SQLiteStoreHumanLifecycleStorageTests(HumanLifecycleStorageMixin, unittest.TestCase):
    store_class = SQLiteStore
    suffix = ".sqlite3"


if __name__ == "__main__":
    unittest.main()
