import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from memoryendpoints import app
from memoryendpoints.connector_pairing import CLIENT_ID, RATE_LIMIT_POLICIES
from memoryendpoints.storage import (
    FileStore,
    SQLiteStore,
    _connector_begin_immediate,
    _connector_select_for_update,
)


class ConnectorPersistentRateLimitTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="memoryendpoints-connector-rate-")
        self.root = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_file_store_exact_threshold_retry_reset_and_partition(self):
        store = FileStore(self.root / "matm.json")
        first = store.consume_connector_rate_limit(
            "tokenExchange", "203.0.113.10|localendpoint-connect", 2, 60, now=1000
        )
        second = store.consume_connector_rate_limit(
            "tokenExchange", "203.0.113.10|localendpoint-connect", 2, 60, now=1000
        )
        denied = store.consume_connector_rate_limit(
            "tokenExchange", "203.0.113.10|localendpoint-connect", 2, 60, now=1000
        )
        later_denied = store.consume_connector_rate_limit(
            "tokenExchange", "203.0.113.10|localendpoint-connect", 2, 60, now=1029
        )
        other_partition = store.consume_connector_rate_limit(
            "tokenExchange", "203.0.113.11|localendpoint-connect", 2, 60, now=1029
        )
        reset = store.consume_connector_rate_limit(
            "tokenExchange", "203.0.113.10|localendpoint-connect", 2, 60, now=1060
        )

        self.assertTrue(first["allowed"])
        self.assertEqual(1, first["remaining"])
        self.assertTrue(second["allowed"])
        self.assertEqual(0, second["remaining"])
        self.assertFalse(denied["allowed"])
        self.assertEqual(60, denied["retryAfterSeconds"])
        self.assertFalse(later_denied["allowed"])
        self.assertEqual(31, later_denied["retryAfterSeconds"])
        self.assertTrue(other_partition["allowed"])
        self.assertNotEqual(first["partitionHash"], other_partition["partitionHash"])
        self.assertTrue(reset["allowed"])
        self.assertEqual(1, reset["remaining"])

    def test_policy_limit_change_preserves_the_active_window_count(self):
        for store in (
            FileStore(self.root / "policy.json"),
            SQLiteStore(self.root / "policy.sqlite3"),
        ):
            first = store.consume_connector_rate_limit(
                "pairingRequest", "203.0.113.20|localendpoint-connect", 60, 600, now=4000
            )
            second = store.consume_connector_rate_limit(
                "pairingRequest", "203.0.113.20|localendpoint-connect", 3, 600, now=4001
            )
            denied = store.consume_connector_rate_limit(
                "pairingRequest", "203.0.113.20|localendpoint-connect", 3, 600, now=4002
            )
            final_denied = store.consume_connector_rate_limit(
                "pairingRequest", "203.0.113.20|localendpoint-connect", 3, 600, now=4003
            )
            self.assertTrue(first["allowed"])
            self.assertTrue(second["allowed"])
            self.assertEqual(1, second["remaining"])
            self.assertTrue(denied["allowed"])
            self.assertEqual(0, denied["remaining"])
            self.assertFalse(final_denied["allowed"])
            self.assertEqual(0, final_denied["remaining"])
            self.assertEqual(597, final_denied["retryAfterSeconds"])

    def test_connector_allowed_operation_policies_persist_and_reset_on_both_stores(self):
        expected = {
            "selfRegistration": {
                "limit": 5,
                "windowSeconds": 600,
                "partition": "connector_credential",
            },
            "publicSafeSubmit": {
                "limit": 60,
                "windowSeconds": 60,
                "partition": "connector_credential",
            },
            "search": {
                "limit": 120,
                "windowSeconds": 60,
                "partition": "connector_credential",
            },
        }
        self.assertEqual(expected, {key: RATE_LIMIT_POLICIES[key] for key in expected})

        for backend in ("file", "sqlite"):
            for index, (bucket, policy) in enumerate(expected.items()):
                with self.subTest(backend=backend, bucket=bucket):
                    suffix = "json" if backend == "file" else "sqlite3"
                    path = self.root / ("%s-%s.%s" % (backend, bucket, suffix))
                    factory = FileStore if backend == "file" else SQLiteStore
                    partition = "connector-credential-%s" % bucket
                    start = 10000 + (index * 1000)
                    first = factory(path).consume_connector_rate_limit(
                        bucket,
                        partition,
                        policy["limit"],
                        policy["windowSeconds"],
                        now=start,
                    )
                    persisted = factory(path).consume_connector_rate_limit(
                        bucket,
                        partition,
                        policy["limit"],
                        policy["windowSeconds"],
                        now=start + 1,
                    )
                    reset = factory(path).consume_connector_rate_limit(
                        bucket,
                        partition,
                        policy["limit"],
                        policy["windowSeconds"],
                        now=start + policy["windowSeconds"],
                    )
                    self.assertTrue(first["allowed"])
                    self.assertEqual(policy["limit"] - 1, first["remaining"])
                    self.assertEqual(policy["limit"] - 2, persisted["remaining"])
                    self.assertEqual(policy["limit"] - 1, reset["remaining"])
                    self.assertEqual(policy["limit"], reset["limit"])
                    self.assertEqual(policy["windowSeconds"], reset["windowSeconds"])
                    self.assertRegex(reset["partitionHash"], r"^[a-f0-9]{64}$")

    def test_file_store_persists_only_bounded_hash_keys_and_no_secret(self):
        path = self.root / "matm.json"
        store = FileStore(path)
        secret = "me_connector_v1.connector_record.private-secret-must-not-persist"
        result = store.consume_connector_rate_limit(
            "status", secret, 60, 60, now=2000
        )
        serialized = path.read_text(encoding="utf-8")
        payload = json.loads(serialized)
        self.assertNotIn(secret, serialized)
        self.assertNotIn("private-secret", serialized)
        self.assertRegex(result["partitionHash"], r"^[a-f0-9]{64}$")
        records = payload["connectorRateLimits"]
        self.assertEqual(1, len(records))
        key, record = next(iter(records.items()))
        self.assertRegex(key, r"^status:[a-f0-9]{64}$")
        self.assertLessEqual(len(key), 96)
        self.assertEqual(result["partitionHash"], record["partitionHash"])
        self.assertNotIn("partition", {name.lower() for name in record if name != "partitionHash"})
        self.assertFalse(record["rawCredentialExposed"])

    def test_two_sqlite_store_instances_share_one_atomic_threshold(self):
        path = self.root / "shared.sqlite3"
        first_store = SQLiteStore(path)
        second_store = SQLiteStore(path)
        first = first_store.consume_connector_rate_limit(
            "activation", "pending-grant-partition", 2, 600, now=3000
        )
        second = second_store.consume_connector_rate_limit(
            "activation", "pending-grant-partition", 2, 600, now=3000
        )
        denied = first_store.consume_connector_rate_limit(
            "activation", "pending-grant-partition", 2, 600, now=3000
        )
        self.assertTrue(first["allowed"])
        self.assertTrue(second["allowed"])
        self.assertFalse(denied["allowed"])
        self.assertEqual(600, denied["retryAfterSeconds"])

        connection = sqlite3.connect(str(path))
        try:
            row = connection.execute(
                "SELECT bucket, partition_hash, request_count, request_limit, window_seconds "
                "FROM matm_connector_rate_limits"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual("activation", row[0])
        self.assertRegex(row[1], r"^[a-f0-9]{64}$")
        self.assertEqual((2, 2, 600), row[2:])

    def test_sqlite_cleanup_is_bounded_and_does_not_store_partition_material(self):
        path = self.root / "cleanup.sqlite3"
        store = SQLiteStore(path)
        store.consume_connector_rate_limit("discovery", "initial", 60, 60, now=100)
        connection = sqlite3.connect(str(path))
        try:
            connection.execute("DELETE FROM matm_connector_rate_limits")
            connection.executemany(
                """
                INSERT INTO matm_connector_rate_limits (
                  bucket, partition_hash, window_started_at_epoch, expires_at_epoch,
                  request_count, request_limit, window_seconds, updated_at_epoch
                ) VALUES (?, ?, 1, 2, 1, 60, 60, 1)
                """,
                [("discovery", "%064x" % index) for index in range(200)],
            )
            connection.commit()
        finally:
            connection.close()
        secret = "one-time-code-value-must-not-persist"
        store.consume_connector_rate_limit("tokenExchange", secret, 10, 600, now=1000)
        connection = sqlite3.connect(str(path))
        try:
            expired_count = connection.execute(
                "SELECT COUNT(*) FROM matm_connector_rate_limits WHERE expires_at_epoch <= 1000"
            ).fetchone()[0]
            serialized_rows = json.dumps(
                connection.execute(
                    "SELECT bucket, partition_hash FROM matm_connector_rate_limits"
                ).fetchall()
            )
        finally:
            connection.close()
        self.assertEqual(72, expired_count)
        self.assertNotIn(secret, serialized_rows)

    def test_connector_transaction_helpers_use_sqlite_reservation_and_mysql_row_lock(self):
        path = self.root / "helper.sqlite3"
        connection = sqlite3.connect(str(path))
        try:
            self.assertTrue(_connector_begin_immediate(connection))
            self.assertTrue(connection.in_transaction)
            connection.rollback()
        finally:
            connection.close()

        class FakeResult:
            def fetchone(self):
                return {"ok": 1}

        class FakeMySQLConnection:
            dialect = "mysql"

            def __init__(self):
                self.statement = ""
                self.params = ()

            def execute(self, statement, params=()):
                self.statement = statement
                self.params = params
                return FakeResult()

        fake = FakeMySQLConnection()
        self.assertFalse(_connector_begin_immediate(fake))
        row = _connector_select_for_update(fake, "SELECT * FROM example WHERE id = ?", ("x",))
        self.assertEqual({"ok": 1}, row)
        self.assertTrue(fake.statement.endswith(" FOR UPDATE"))
        self.assertEqual(("x",), fake.params)


class ConnectorAppRateLimitBoundaryTests(unittest.TestCase):
    class CaptureStore:
        def __init__(self):
            self.calls = []

        def consume_connector_rate_limit(self, bucket, partition, limit, window_seconds):
            self.calls.append((bucket, partition, limit, window_seconds))
            return {
                "allowed": True,
                "retryAfterSeconds": 0,
                "valuesRedacted": True,
            }

    def test_every_connector_policy_bucket_uses_published_limits(self):
        store = self.CaptureStore()
        environ = {"REMOTE_ADDR": "198.51.100.22"}
        partitions = {
            "discovery": "ignored",
            "authorize": "attacker-request-handle",
            "pairingRequest": "attacker-state",
            "authorizationCodeClaim": "attacker-pairing-proof",
            "tokenExchange": "attacker-authorization-code",
            "activation": "pending-connector-token",
            "status": "active-connector-token",
            "credentialLifecycle": "active-or-master-token",
            "selfRegistration": "active-connector-token",
            "publicSafeSubmit": "active-connector-token",
            "search": "active-connector-token",
        }
        for bucket, partition in partitions.items():
            result = app._connector_operation_rate_limited(
                environ, bucket, partition, store=store
            )
            self.assertTrue(result["allowed"])
        self.assertEqual(set(RATE_LIMIT_POLICIES), {call[0] for call in store.calls})
        for bucket, partition, limit, window in store.calls:
            policy = RATE_LIMIT_POLICIES[bucket]
            self.assertEqual(policy["limit"], limit)
            self.assertEqual(policy["windowSeconds"], window)
            if bucket == "discovery":
                self.assertEqual("198.51.100.22", partition)
            elif bucket in (
                "authorize",
                "pairingRequest",
                "authorizationCodeClaim",
                "tokenExchange",
            ):
                self.assertEqual("198.51.100.22|" + CLIENT_ID, partition)

    def test_token_exchange_cannot_evade_partition_with_changed_code(self):
        store = self.CaptureStore()
        environ = {"REMOTE_ADDR": "192.0.2.44"}
        app._connector_operation_rate_limited(
            environ, "tokenExchange", "first-attacker-code", store=store
        )
        app._connector_operation_rate_limited(
            environ, "tokenExchange", "second-attacker-code", store=store
        )
        self.assertEqual(store.calls[0][1], store.calls[1][1])
        self.assertEqual("192.0.2.44|" + CLIENT_ID, store.calls[0][1])
        self.assertNotIn("attacker-code", repr(store.calls))

    def test_exact_retry_after_header_and_store_failure_are_safe(self):
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        body = b"".join(
            app._connector_rate_rejection(
                start_response,
                {"allowed": False, "retryAfterSeconds": 31},
            )
        )
        self.assertEqual("429 Too Many Requests", captured["status"])
        self.assertEqual("31", captured["headers"]["Retry-After"])
        self.assertEqual("rate_limited", json.loads(body)["error"]["code"])

        body = b"".join(
            app._connector_rate_rejection(
                start_response,
                {"allowed": False, "unavailable": True, "retryAfterSeconds": 5},
            )
        )
        self.assertEqual("503 Service Unavailable", captured["status"])
        self.assertEqual("5", captured["headers"]["Retry-After"])
        self.assertEqual("connector_service_unavailable", json.loads(body)["error"]["code"])

    def test_canonical_schema_has_persistent_bounded_rate_table(self):
        schema = (
            Path(__file__).resolve().parents[1] / "docs" / "database-schema-canonical.sql"
        ).read_text(encoding="utf-8")
        table = re.search(
            r"CREATE TABLE IF NOT EXISTS matm_connector_rate_limits \((.*?)\) ENGINE=InnoDB",
            schema,
            re.DOTALL,
        )
        self.assertIsNotNone(table)
        definition = table.group(1)
        self.assertIn("partition_hash CHAR(64) NOT NULL", definition)
        self.assertIn("PRIMARY KEY (bucket, partition_hash)", definition)
        self.assertNotIn("token", definition.lower())
        self.assertNotIn("code", definition.lower())


if __name__ == "__main__":
    unittest.main()
