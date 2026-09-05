import hashlib
import multiprocessing
import os
import secrets
import unittest
import uuid

from memoryendpoints.storage import MySQLStore, _mysql_config_from_env
from tests.governed_test_support import DeterministicCredentialPepperMixin


_MYSQL_TEST_ENABLED = "MEMORYENDPOINTS_AGENT_INVITES_MYSQL_TEST"
_MYSQL_TEST_MUTATION_ACK = "MEMORYENDPOINTS_AGENT_INVITES_MYSQL_TEST_ALLOW_MUTATION"
_MYSQL_TEST_DATABASE_FINGERPRINT = (
    "MEMORYENDPOINTS_AGENT_INVITES_MYSQL_TEST_DATABASE_SHA256"
)
_EXPECTED_MUTATION_ACK = "isolated-disposable-database"


def _candidate():
    return "me_agent_v1.agenttoken-%s.%s" % (
        secrets.token_hex(10),
        secrets.token_urlsafe(32),
    )


def _redeem_worker(body, key, gate, output):
    try:
        gate.wait(30)
        output.put(
            {"kind": "ok", "result": MySQLStore().redeem_agent_invite(body, key)}
        )
    except BaseException as exc:
        output.put(
            {
                "kind": "error",
                "errorType": exc.__class__.__name__,
                "errorCode": getattr(exc, "code", None),
            }
        )


@unittest.skipUnless(
    os.environ.get(_MYSQL_TEST_ENABLED) == "1",
    "real MySQL invitation contract requires explicit opt-in",
)
class AgentInvitationMySQLContractTests(
    DeterministicCredentialPepperMixin, unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if os.environ.get(_MYSQL_TEST_MUTATION_ACK) != _EXPECTED_MUTATION_ACK:
            raise AssertionError(
                "%s must acknowledge an isolated disposable database"
                % _MYSQL_TEST_MUTATION_ACK
            )
        database = str(_mysql_config_from_env().get("database") or "")
        if database.lower() in (
            "",
            "mysql",
            "information_schema",
            "performance_schema",
            "sys",
        ):
            raise AssertionError(
                "The real MySQL invitation contract requires a non-system database."
            )
        expected = os.environ.get(_MYSQL_TEST_DATABASE_FINGERPRINT) or ""
        actual = hashlib.sha256(database.encode("utf-8")).hexdigest()
        if not expected or expected != actual:
            raise AssertionError(
                "%s must exactly match the selected isolated database"
                % _MYSQL_TEST_DATABASE_FINGERPRINT
            )

    def _issue(self, label):
        store = MySQLStore()
        account = store.create_free_account(
            "MySQL Invite Workspace " + label,
            "MySQL Invite Company " + label,
            "MySQL Invite Project " + label,
        )
        workspace_id, _master_key_id, master_token, _account_id, company_id = (
            account[:5]
        )
        requested = store.request_agent_access(
            company_id,
            "mysql-invite-agent-" + label,
            "workspace",
            workspace_id,
            display_name="MySQL Invite Agent",
            justification="Disposable MySQL invitation contract test",
        )
        self.assertTrue(requested["ok"], requested)
        request_id = requested["request"]["requestId"]
        approved = store.decide_agent_access_request(
            master_token, request_id, "approved", "Disposable test approval"
        )
        self.assertTrue(approved["ok"], approved)
        invitation = store.issue_agent_invite(master_token, request_id, 900)
        self.assertTrue(invitation["ok"], invitation)
        return store, invitation["inviteSecret"]

    def test_two_process_exact_replay_creates_one_credential_graph(self):
        label = uuid.uuid4().hex[:12]
        store, invite_secret = self._issue(label)
        candidate = _candidate()
        body = {
            "schemaVersion": "memoryendpoints.agent_invite_redemption.v1",
            "inviteSecret": invite_secret,
            "candidateAgentTokenSecret": candidate,
        }
        key = "mysql-invite-redeem-" + uuid.uuid4().hex
        context = multiprocessing.get_context("spawn")
        gate = context.Barrier(2)
        output = context.Queue()
        processes = [
            context.Process(
                target=_redeem_worker,
                args=(body, key, gate, output),
            )
            for _index in range(2)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(60)
        try:
            self.assertTrue(all(not process.is_alive() for process in processes))
            self.assertEqual([0, 0], [process.exitcode for process in processes])
            results = [output.get(timeout=5) for _index in range(2)]
            self.assertEqual(["ok", "ok"], sorted(item["kind"] for item in results))
            payloads = [item["result"] for item in results]
            self.assertTrue(all(item["ok"] for item in payloads), payloads)
            self.assertEqual(
                1,
                sum(not item["_idempotentReplay"] for item in payloads),
                payloads,
            )
            self.assertEqual(payloads[0]["principal"], payloads[1]["principal"])
            self.assertEqual(
                {key: value for key, value in payloads[0].items() if key != "_idempotentReplay"},
                {key: value for key, value in payloads[1].items() if key != "_idempotentReplay"},
            )
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(5)

        credential_id = candidate.split(".")[1]
        with store._open_connection() as connection:
            token_count = connection.execute(
                "SELECT COUNT(*) AS item_count FROM matm_agent_tokens "
                "WHERE agent_token_id = ?",
                (credential_id,),
            ).fetchone()
            audits = connection.execute(
                "SELECT COUNT(*) AS item_count FROM matm_audit_log "
                "WHERE action = ? AND target = ?",
                ("agent_invite.redeem", invite_secret.split(".")[1]),
            ).fetchone()
        self.assertEqual(1, int(token_count["item_count"]))
        self.assertEqual(1, int(audits["item_count"]))
        self.assertIsNotNone(MySQLStore().authenticate_agent_token(candidate))

        invite_id = invite_secret.split(".")[1]
        room_id = payloads[0]["onboarding"]["entryRoom"]["roomId"]
        with store._open_connection() as connection:
            receipt_before = connection.execute(
                "SELECT redemption_receipt_json FROM matm_agent_invites "
                "WHERE invite_id = ?",
                (invite_id,),
            ).fetchone()["redemption_receipt_json"]
            connection.execute(
                "UPDATE matm_agent_tokens SET revoked_at = CURRENT_TIMESTAMP "
                "WHERE agent_token_id = ?",
                (credential_id,),
            )
            connection.execute(
                "UPDATE matm_agent_access_grants SET status = 'revoked', "
                "revoked_at = CURRENT_TIMESTAMP WHERE grant_id = ?",
                (payloads[0]["principal"]["grantId"],),
            )
            connection.execute(
                "UPDATE matm_meeting_rooms SET status = 'archived' "
                "WHERE room_id = ?",
                (room_id,),
            )
            connection.commit()

        replay_after_state_change = MySQLStore().redeem_agent_invite(body, key)
        self.assertTrue(replay_after_state_change["ok"])
        self.assertTrue(replay_after_state_change["_idempotentReplay"])
        self.assertEqual(
            {key: value for key, value in payloads[0].items() if key != "_idempotentReplay"},
            {
                key: value
                for key, value in replay_after_state_change.items()
                if key != "_idempotentReplay"
            },
        )
        with store._open_connection() as connection:
            receipt_after = connection.execute(
                "SELECT redemption_receipt_json FROM matm_agent_invites "
                "WHERE invite_id = ?",
                (invite_id,),
            ).fetchone()["redemption_receipt_json"]
        self.assertEqual(receipt_before, receipt_after)
        self.assertIsNone(MySQLStore().authenticate_agent_token(candidate))

        changed = dict(body, candidateAgentTokenSecret=_candidate())
        conflict = MySQLStore().redeem_agent_invite(changed, key)
        self.assertEqual("idempotency_conflict", conflict["status"])
        different_key = MySQLStore().redeem_agent_invite(
            body, "mysql-invite-redeem-changed-" + uuid.uuid4().hex
        )
        self.assertEqual("idempotency_conflict", different_key["status"])

        _second_store, second_invite = self._issue(uuid.uuid4().hex[:12])
        second_body = {
            "schemaVersion": "memoryendpoints.agent_invite_redemption.v1",
            "inviteSecret": second_invite,
            "candidateAgentTokenSecret": _candidate(),
        }
        rebound = MySQLStore().redeem_agent_invite(second_body, key)
        self.assertEqual("idempotency_conflict", rebound["status"])

    def test_two_process_different_invites_same_candidate_has_one_typed_conflict(self):
        _first_store, first_invite = self._issue(uuid.uuid4().hex[:12])
        store, second_invite = self._issue(uuid.uuid4().hex[:12])
        candidate = _candidate()
        bodies = [
            {
                "schemaVersion": "memoryendpoints.agent_invite_redemption.v1",
                "inviteSecret": invite_secret,
                "candidateAgentTokenSecret": candidate,
            }
            for invite_secret in (first_invite, second_invite)
        ]
        keys = [
            "mysql-candidate-race-" + uuid.uuid4().hex,
            "mysql-candidate-race-" + uuid.uuid4().hex,
        ]
        context = multiprocessing.get_context("spawn")
        gate = context.Barrier(2)
        output = context.Queue()
        processes = [
            context.Process(
                target=_redeem_worker,
                args=(body, key, gate, output),
            )
            for body, key in zip(bodies, keys)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(60)
        try:
            self.assertTrue(all(not process.is_alive() for process in processes))
            self.assertEqual([0, 0], [process.exitcode for process in processes])
            results = [output.get(timeout=5) for _index in range(2)]
            self.assertEqual(["ok", "ok"], sorted(item["kind"] for item in results))
            payloads = [item["result"] for item in results]
            self.assertEqual(1, sum(item["ok"] for item in payloads), payloads)
            conflicts = [item for item in payloads if not item["ok"]]
            self.assertEqual(1, len(conflicts), payloads)
            self.assertEqual(
                "candidate_agent_token_conflict", conflicts[0]["status"]
            )
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(5)

        invite_ids = [value.split(".")[1] for value in (first_invite, second_invite)]
        with store._open_connection() as connection:
            statuses = sorted(
                row["status"]
                for row in connection.execute(
                    "SELECT status FROM matm_agent_invites "
                    "WHERE invite_id IN (?, ?)",
                    tuple(invite_ids),
                )
            )
            token_count = connection.execute(
                "SELECT COUNT(*) AS item_count FROM matm_agent_tokens "
                "WHERE agent_token_id = ?",
                (candidate.split(".")[1],),
            ).fetchone()
        self.assertEqual(["issued", "redeemed"], statuses)
        self.assertEqual(1, int(token_count["item_count"]))
        self.assertIsNotNone(MySQLStore().authenticate_agent_token(candidate))


if __name__ == "__main__":
    unittest.main()
