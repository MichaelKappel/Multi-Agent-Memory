import base64
import datetime
import hashlib
import multiprocessing
import os
import unittest
import uuid

from memoryendpoints.storage import (
    BootstrapAccountError,
    MySQLStore,
    _bootstrap_account_ids,
    _mysql_config_from_env,
    bootstrap_capability_digest,
    bootstrap_idempotency_digest,
    bootstrap_request_digest,
)
from tests.governed_test_support import DeterministicCredentialPepperMixin


_MYSQL_TEST_ENABLED = "MEMORYENDPOINTS_BOOTSTRAP_MYSQL_TEST"
_MYSQL_TEST_MUTATION_ACK = "MEMORYENDPOINTS_BOOTSTRAP_MYSQL_TEST_ALLOW_MUTATION"
_MYSQL_TEST_DATABASE_FINGERPRINT = (
    "MEMORYENDPOINTS_BOOTSTRAP_MYSQL_TEST_DATABASE_SHA256"
)
_EXPECTED_MUTATION_ACK = "isolated-disposable-database"


def _secret(label):
    return base64.urlsafe_b64encode(
        hashlib.sha256(label.encode("utf-8")).digest()
    ).decode("ascii").rstrip("=")


def _body(label):
    return {
        "schemaVersion": "memoryendpoints.bootstrap_account_request.v1",
        "companyLabel": "MySQL Bootstrap Company " + label,
        "workspaceLabel": "MySQL Bootstrap Workspace " + label,
        "projectLabel": "MySQL Bootstrap Project " + label,
        "candidateCompanyMasterTokenSecret": "me_master_v1.masterkey-%s.%s"
        % (hashlib.sha256((label + "-master-id").encode()).hexdigest()[:20], _secret(label + "-master")),
        "candidateHumanOwnerRecoverySecret": "me_human_v1.humancred-%s.%s"
        % (hashlib.sha256((label + "-human-id").encode()).hexdigest()[:20], _secret(label + "-human")),
    }


def _future_expiry():
    return (
        datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(minutes=5)
    ).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bootstrap_worker(body, capability, idempotency, expiry, gate, output):
    try:
        gate.wait(30)
        result = MySQLStore().create_bootstrap_account(
            body,
            bootstrap_capability_digest(capability),
            bootstrap_idempotency_digest(idempotency),
            bootstrap_request_digest(body),
            expiry,
        )
        output.put({"kind": "ok", "result": result})
    except BaseException as exc:
        output.put(
            {
                "kind": "error",
                "errorType": exc.__class__.__name__,
                "errorCode": getattr(exc, "code", None),
                "errorNumber": (
                    exc.args[0]
                    if getattr(exc, "args", ()) and type(exc.args[0]) is int
                    else None
                ),
            }
        )


@unittest.skipUnless(
    os.environ.get(_MYSQL_TEST_ENABLED) == "1",
    "real MySQL bootstrap contract requires explicit opt-in",
)
class BootstrapAccountMySQLContractTests(
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
        config = _mysql_config_from_env()
        database = str(config.get("database") or "")
        if database.lower() in (
            "",
            "mysql",
            "information_schema",
            "performance_schema",
            "sys",
        ):
            raise AssertionError(
                "The real MySQL bootstrap contract requires a non-system database."
            )
        expected = os.environ.get(_MYSQL_TEST_DATABASE_FINGERPRINT) or ""
        actual = hashlib.sha256(database.encode("utf-8")).hexdigest()
        if not expected or expected != actual:
            raise AssertionError(
                "%s must exactly match the selected isolated database"
                % _MYSQL_TEST_DATABASE_FINGERPRINT
            )

    def _material(self, prefix):
        label = "%s-%s" % (prefix, uuid.uuid4().hex[:12])
        return (
            _body(label),
            _secret(label + "-capability"),
            _secret(label + "-idempotency"),
            _future_expiry(),
        )

    @staticmethod
    def _create(store, material):
        body, capability, idempotency, expiry = material
        return store.create_bootstrap_account(
            body,
            bootstrap_capability_digest(capability),
            bootstrap_idempotency_digest(idempotency),
            bootstrap_request_digest(body),
            expiry,
        )

    def test_schema_persistence_replay_and_candidate_authentication(self):
        store = MySQLStore()
        self.assertTrue(store.healthcheck())
        material = self._material("persistence")
        first = self._create(store, material)
        replay = self._create(MySQLStore(), material)
        self.assertEqual(first, replay)
        self.assertEqual("memoryendpoints.bootstrap_account.v1", first["schemaVersion"])
        self.assertTrue(first["candidateCredentialsAccepted"])
        self.assertFalse(first["credentialValuesReturned"])
        body = material[0]
        self.assertTrue(
            MySQLStore().authenticate_company_master(
                body["candidateCompanyMasterTokenSecret"], first["companyId"]
            )
        )
        self.assertTrue(
            MySQLStore().authenticate_human_owner(
                body["candidateHumanOwnerRecoverySecret"], first["companyId"]
            )
        )
        with store._open_connection() as connection:
            table = connection.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = DATABASE() "
                "AND table_name = 'matm_bootstrap_account_setups'"
            ).fetchone()
            setup = connection.execute(
                "SELECT * FROM matm_bootstrap_account_setups "
                "WHERE capability_digest_sha256 = ?",
                (bootstrap_capability_digest(material[1]),),
            ).fetchone()
            audits = connection.execute(
                "SELECT COUNT(*) AS item_count FROM matm_audit_log "
                "WHERE workspace_id = ? AND action = ?",
                (first["workspaceId"], "workspace.create_bootstrap_account"),
            ).fetchone()
        self.assertIsNotNone(table)
        self.assertEqual("complete", setup["status"])
        self.assertEqual(1, int(audits["item_count"]))
        serialized = repr(dict(setup))
        self.assertNotIn(material[1], serialized)
        self.assertNotIn(material[2], serialized)
        self.assertNotIn(body["companyLabel"], serialized)
        self.assertNotIn(body["candidateCompanyMasterTokenSecret"], serialized)
        self.assertNotIn(body["candidateHumanOwnerRecoverySecret"], serialized)

    def test_two_process_exact_call_is_one_graph_and_conflicts_stay_noop(self):
        material = self._material("concurrent")
        context = multiprocessing.get_context("spawn")
        gate = context.Barrier(2)
        output = context.Queue()
        processes = [
            context.Process(
                target=_bootstrap_worker,
                args=material + (gate, output),
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
            self.assertEqual(["ok", "ok"], sorted(item["kind"] for item in results), results)
            self.assertEqual(results[0]["result"], results[1]["result"])
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(5)

        body, capability, idempotency, expiry = material
        different = dict(body, projectLabel=body["projectLabel"] + " changed")
        with self.assertRaises(BootstrapAccountError) as conflict:
            MySQLStore().create_bootstrap_account(
                different,
                bootstrap_capability_digest(capability),
                bootstrap_idempotency_digest(idempotency),
                bootstrap_request_digest(different),
                expiry,
            )
        self.assertEqual("bootstrap_account_conflict", conflict.exception.code)
        ids = _bootstrap_account_ids(
            bootstrap_capability_digest(capability),
            body["candidateCompanyMasterTokenSecret"].split(".")[1],
            body["candidateHumanOwnerRecoverySecret"].split(".")[1],
        )
        with MySQLStore()._open_connection() as connection:
            accounts = connection.execute(
                "SELECT COUNT(*) AS item_count FROM matm_accounts WHERE account_id = ?",
                (ids["accountId"],),
            ).fetchone()
            audits = connection.execute(
                "SELECT COUNT(*) AS item_count FROM matm_audit_log "
                "WHERE workspace_id = ? AND action = ?",
                (ids["workspaceId"], "workspace.create_bootstrap_account"),
            ).fetchone()
        self.assertEqual(1, int(accounts["item_count"]))
        self.assertEqual(1, int(audits["item_count"]))

    def test_failure_rolls_back_and_layered_rate_is_source_first(self):
        material = self._material("rollback")
        store = MySQLStore()
        tables = (
            "matm_bootstrap_account_setups",
            "matm_accounts",
            "matm_companies",
            "matm_account_companies",
            "matm_workspaces",
            "matm_projects",
            "matm_company_master_keys",
            "matm_human_owner_credentials",
            "matm_meeting_rooms",
            "matm_audit_log",
        )
        with store._open_connection() as connection:
            before = {
                table: int(
                    connection.execute(
                        "SELECT COUNT(*) AS item_count FROM %s" % table
                    ).fetchone()["item_count"]
                )
                for table in tables
            }

        original = store._ensure_default_meeting_rooms_sql

        def fail_after_graph(_connection, _workspace_id):
            raise RuntimeError("synthetic bootstrap failure")

        store._ensure_default_meeting_rooms_sql = fail_after_graph
        try:
            with self.assertRaisesRegex(RuntimeError, "synthetic bootstrap failure"):
                self._create(store, material)
        finally:
            store._ensure_default_meeting_rooms_sql = original
        with MySQLStore()._open_connection() as connection:
            after = {
                table: int(
                    connection.execute(
                        "SELECT COUNT(*) AS item_count FROM %s" % table
                    ).fetchone()["item_count"]
                )
                for table in tables
            }
        self.assertEqual(before, after)

        suffix = uuid.uuid4().hex
        capability_partition = "capability-" + suffix
        limiter_a = MySQLStore()
        for _index in range(2):
            admitted = limiter_a.consume_commons_layered_rate_limit(
                "bootstrapSourceRequest",
                "source-a-" + suffix,
                2,
                600,
                "bootstrapCapabilityRequest",
                capability_partition,
                4,
                600,
                128,
            )
            self.assertTrue(admitted["allowed"])
        denied = MySQLStore().consume_commons_layered_rate_limit(
            "bootstrapSourceRequest",
            "source-a-" + suffix,
            2,
            600,
            "bootstrapCapabilityRequest",
            capability_partition,
            4,
            600,
            128,
        )
        self.assertFalse(denied["allowed"])
        self.assertEqual("source", denied["deniedLayer"])
        second_source = MySQLStore().consume_commons_layered_rate_limit(
            "bootstrapSourceRequest",
            "source-b-" + suffix,
            2,
            600,
            "bootstrapCapabilityRequest",
            capability_partition,
            4,
            600,
            128,
        )
        self.assertTrue(second_source["allowed"])


if __name__ == "__main__":
    unittest.main()
