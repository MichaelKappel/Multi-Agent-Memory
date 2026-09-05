import hashlib
import datetime
import multiprocessing
import os
import unittest
import uuid

from memoryendpoints.commons import request_digest
from memoryendpoints.commons_storage import CommonsRepository
from memoryendpoints.storage import (
    MySQLStore,
    _DbConnection,
    _mysql_config_from_env,
)
from tests.governed_test_support import DeterministicCredentialPepperMixin


_MYSQL_TEST_ENABLED = "MEMORYENDPOINTS_COMMONS_MYSQL_TEST"
_MYSQL_TEST_MUTATION_ACK = "MEMORYENDPOINTS_COMMONS_MYSQL_TEST_ALLOW_MUTATION"
_MYSQL_TEST_DATABASE_FINGERPRINT = (
    "MEMORYENDPOINTS_COMMONS_MYSQL_TEST_DATABASE_SHA256"
)
_EXPECTED_MUTATION_ACK = "isolated-disposable-database"


class MySQLDatetimeParameterAdapterTests(unittest.TestCase):
    def test_only_datetime_column_parameters_are_converted(self):
        class Cursor:
            rowcount = 0

            def execute(self, statement, params=None):
                self.statement = statement
                self.params = params

        class Connection:
            def __init__(self):
                self.cursor_instance = Cursor()

            def cursor(self, **_options):
                return self.cursor_instance

        iso = "2026-09-05T02:00:36.334984Z"
        raw = Connection()
        connection = _DbConnection(raw, "mysql")
        connection.execute(
            "INSERT INTO example (created_at, content, updated_at) "
            "VALUES (?, ?, ?)",
            (iso, iso, iso),
        )
        self.assertIsInstance(raw.cursor_instance.params[0], datetime.datetime)
        self.assertEqual(iso, raw.cursor_instance.params[1])
        self.assertIsInstance(raw.cursor_instance.params[2], datetime.datetime)
        self.assertNotIn("?", raw.cursor_instance.statement)

        raw = Connection()
        connection = _DbConnection(raw, "mysql")
        connection.execute(
            "UPDATE example SET updated_at = ?, content = ? "
            "WHERE expires_at > ? AND item_id = ?",
            (iso, iso, iso, "item"),
        )
        self.assertIsInstance(raw.cursor_instance.params[0], datetime.datetime)
        self.assertEqual(iso, raw.cursor_instance.params[1])
        self.assertIsInstance(raw.cursor_instance.params[2], datetime.datetime)
        self.assertEqual("item", raw.cursor_instance.params[3])

        raw = Connection()
        connection = _DbConnection(raw, "mysql")
        connection.execute(
            "SELECT item_id FROM example WHERE label LIKE 'commons-%'"
        )
        self.assertIn("LIKE 'commons-%'", raw.cursor_instance.statement)

        raw = Connection()
        connection = _DbConnection(raw, "mysql")
        connection.execute(
            "SELECT item_id FROM example WHERE label LIKE 'commons-%' "
            "AND note = 'Is this literal?' AND created_at < ?",
            (iso,),
        )
        self.assertIn("LIKE 'commons-%%'", raw.cursor_instance.statement)
        self.assertIn("note = 'Is this literal?'", raw.cursor_instance.statement)
        self.assertIsInstance(raw.cursor_instance.params[0], datetime.datetime)

        raw = Connection()
        connection = _DbConnection(raw, "mysql")
        connection.execute(
            "INSERT INTO matm_outbound_mcp_project_policies "
            "(project_id, workspace_id, mode, forced_by_human, revision, updated_at) "
            "SELECT ?, ?, ?, ?, ?, ? WHERE NOT EXISTS (SELECT 1 FROM "
            "matm_outbound_mcp_project_policies WHERE workspace_id = ? "
            "AND project_id = ?)",
            ("project", iso, "autonomous", 0, 1, iso, "workspace", "project"),
        )
        self.assertEqual("project", raw.cursor_instance.params[0])
        self.assertEqual(iso, raw.cursor_instance.params[1])
        self.assertEqual("autonomous", raw.cursor_instance.params[2])
        self.assertEqual(0, raw.cursor_instance.params[3])
        self.assertEqual(1, raw.cursor_instance.params[4])
        self.assertIsInstance(raw.cursor_instance.params[5], datetime.datetime)
        self.assertEqual("workspace", raw.cursor_instance.params[6])
        self.assertEqual("project", raw.cursor_instance.params[7])

    def test_schema_convergence_uses_a_redacted_database_advisory_lock(self):
        class Result:
            def __init__(self, value):
                self.value = value

            def fetchone(self):
                return self.value

        class Connection:
            dialect = "mysql"

            def __init__(self):
                self.calls = []

            def execute(self, statement, params=None):
                self.calls.append((" ".join(statement.split()), params))
                return Result(
                    {"released": 1}
                    if "RELEASE_LOCK" in statement
                    else {"acquired": 1}
                )

        class Store(MySQLStore):
            def __init__(self):
                self.ensure_count = 0

            def _ensure_schema(self, _connection):
                self.ensure_count += 1

        store = Store()
        config = {
            "host": "127.0.0.1",
            "port": "43397",
            "database": "isolated-test-database",
            "user": "isolated-test-user",
            "password": "must-not-enter-lock-name",
            "unix_socket": "",
        }
        from memoryendpoints.storage import _MYSQL_SCHEMA_READY

        _MYSQL_SCHEMA_READY.discard(store._schema_cache_key(config))
        connection = Connection()
        store._ensure_schema_once(connection, config)
        self.assertEqual(1, store.ensure_count)
        self.assertEqual("SELECT GET_LOCK(?, 30) AS acquired", connection.calls[0][0])
        self.assertEqual(
            "SELECT RELEASE_LOCK(?) AS released", connection.calls[-1][0]
        )
        serialized_calls = repr(connection.calls)
        self.assertNotIn(config["database"], serialized_calls)
        self.assertNotIn(config["user"], serialized_calls)
        self.assertNotIn(config["password"], serialized_calls)

    def test_schema_acquisition_failure_closes_without_running_schema(self):
        class Result:
            def __init__(self, value):
                self.value = value

            def fetchone(self):
                return self.value

        class Connection:
            dialect = "mysql"

            def __init__(self, acquire_mode):
                self.acquire_mode = acquire_mode
                self.closed = False

            def execute(self, _statement, _params=None):
                if self.acquire_mode == "raise":
                    raise RuntimeError("acquisition failed")
                return Result(
                    {"acquired": 0}
                    if self.acquire_mode == "zero"
                    else {"acquired": None}
                )

            def close(self):
                self.closed = True

        class Store(MySQLStore):
            def __init__(self):
                self.ensure_count = 0

            def _ensure_schema(self, _connection):
                self.ensure_count += 1

        config = {
            "host": "127.0.0.1",
            "port": "43397",
            "database": "isolated-acquisition-test",
            "user": "isolated-test-user",
            "password": "not-in-cache-key",
            "unix_socket": "",
        }
        from memoryendpoints.storage import _MYSQL_SCHEMA_READY

        for acquire_mode in ("zero", "null", "raise"):
            with self.subTest(acquire_mode=acquire_mode):
                store = Store()
                schema_key = store._schema_cache_key(config)
                _MYSQL_SCHEMA_READY.discard(schema_key)
                connection = Connection(acquire_mode)
                with self.assertRaisesRegex(
                    RuntimeError,
                    "acquisition failed|could not be acquired",
                ):
                    store._ensure_schema_once(connection, config)
                self.assertEqual(0, store.ensure_count)
                self.assertNotIn(schema_key, _MYSQL_SCHEMA_READY)
                self.assertTrue(connection.closed)

    def test_schema_release_failure_never_masks_the_original_schema_error(self):
        class OriginalSchemaError(RuntimeError):
            pass

        class Result:
            def __init__(self, value):
                self.value = value

            def fetchone(self):
                return self.value

        class Connection:
            dialect = "mysql"

            def __init__(self, release_mode):
                self.release_mode = release_mode
                self.closed = False

            def execute(self, statement, _params=None):
                if "RELEASE_LOCK" in statement:
                    if self.release_mode == "raise":
                        raise RuntimeError("release failed")
                    return Result({"released": 0})
                return Result({"acquired": 1})

            def close(self):
                self.closed = True

        class Store(MySQLStore):
            def __init__(self):
                pass

            def _ensure_schema(self, _connection):
                raise OriginalSchemaError("original schema failure")

        store = Store()
        config = {
            "host": "127.0.0.1",
            "port": "43397",
            "database": "isolated-failure-test",
            "user": "isolated-test-user",
            "password": "not-in-cache-key",
            "unix_socket": "",
        }
        from memoryendpoints.storage import _MYSQL_SCHEMA_READY

        schema_key = store._schema_cache_key(config)
        for release_mode in ("zero", "raise"):
            with self.subTest(release_mode=release_mode):
                _MYSQL_SCHEMA_READY.discard(schema_key)
                connection = Connection(release_mode)
                with self.assertRaisesRegex(
                    OriginalSchemaError, "original schema failure"
                ):
                    store._ensure_schema_once(connection, config)
                self.assertNotIn(schema_key, _MYSQL_SCHEMA_READY)
                self.assertTrue(connection.closed)

    def test_schema_release_failure_discards_cache_and_closes_connection(self):
        class Result:
            def __init__(self, value):
                self.value = value

            def fetchone(self):
                return self.value

        class Connection:
            dialect = "mysql"

            def __init__(self, release_mode):
                self.release_mode = release_mode
                self.closed = False

            def execute(self, statement, _params=None):
                if "RELEASE_LOCK" not in statement:
                    return Result({"acquired": 1})
                if self.release_mode == "raise":
                    raise RuntimeError("release failed")
                return Result({"released": 0})

            def close(self):
                self.closed = True

        class Store(MySQLStore):
            def __init__(self):
                pass

            def _ensure_schema(self, _connection):
                pass

        config = {
            "host": "127.0.0.1",
            "port": "43397",
            "database": "isolated-release-test",
            "user": "isolated-test-user",
            "password": "not-in-cache-key",
            "unix_socket": "",
        }
        from memoryendpoints.storage import _MYSQL_SCHEMA_READY

        for release_mode in ("zero", "raise"):
            with self.subTest(release_mode=release_mode):
                store = Store()
                schema_key = store._schema_cache_key(config)
                _MYSQL_SCHEMA_READY.discard(schema_key)
                connection = Connection(release_mode)
                with self.assertRaisesRegex(
                    RuntimeError,
                    "release failed|could not be released",
                ):
                    store._ensure_schema_once(connection, config)
                self.assertNotIn(schema_key, _MYSQL_SCHEMA_READY)
                self.assertTrue(connection.closed)


def _candidate(label):
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()
    return "me_agent_v1.agenttoken-%s.%s" % (
        digest[:20],
        (digest + digest)[:43],
    )


def _browser_candidate(label):
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()
    return "me_commonsbrowser_v1.commonsbrowser-%s.%s" % (
        digest[:20],
        (digest + digest)[:43],
    )


def _key(label):
    return (label + "-" + ("k" * 64))[:64]


def _profile():
    return {
        "listed": True,
        "implementation": "real MySQL Commons contract test",
        "capabilities": ["commons"],
        "profileUrl": "",
        "capabilityUrl": "",
        "availability": "available",
    }


def _settings(workspace_id, project_id):
    return {
        "workspaceId": workspace_id,
        "projectId": project_id,
        "humanApprovalRequiredByDefault": False,
        "credentialTtlSeconds": 3600,
        "browserSessionTtlSeconds": 600,
        "enrollmentRequestTtlSeconds": 3600,
        "maximumActiveAgents": 100,
        "maximumPendingEnrollments": 20,
        "maximumRetainedAgents": 500,
        "maximumRetainedEnrollments": 500,
        "maximumCompanyRetainedAgents": 2000,
        "maximumCompanyRetainedEnrollments": 2000,
        "maximumAgentTombstones": 5000,
        "maximumCompanyAgentTombstones": 20000,
        "maximumEnrollmentTombstones": 5000,
        "maximumCompanyEnrollmentTombstones": 20000,
    }


def _enroll_worker(settings, agent_name, candidate, key, digest, gate, output):
    try:
        repository = CommonsRepository(MySQLStore(), settings)
        gate.wait(30)
        result, replay = repository.enroll(
            agent_name,
            "Concurrent MySQL Agent",
            _profile(),
            candidate,
            key,
            digest,
        )
        output.put(
            {
                "kind": "ok",
                "replay": bool(replay),
                "credentialId": result["principal"]["credentialId"],
            }
        )
    except BaseException as exc:
        output.put(
            {
                "kind": "error",
                "errorType": exc.__class__.__name__,
                "errorCode": getattr(exc, "code", None),
                "errorNumber": (
                    exc.args[0]
                    if getattr(exc, "args", ())
                    and type(exc.args[0]) is int
                    else None
                ),
            }
        )


@unittest.skipUnless(
    os.environ.get(_MYSQL_TEST_ENABLED) == "1",
    "real MySQL Commons contract requires explicit opt-in",
)
class CommonsMySQLContractTests(
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
        if database.lower() in ("", "mysql", "information_schema", "performance_schema", "sys"):
            raise AssertionError("The real MySQL Commons contract requires a non-system database.")
        expected = os.environ.get(_MYSQL_TEST_DATABASE_FINGERPRINT) or ""
        actual = hashlib.sha256(database.encode("utf-8")).hexdigest()
        if not expected or expected != actual:
            raise AssertionError(
                "%s must exactly match the selected isolated database"
                % _MYSQL_TEST_DATABASE_FINGERPRINT
            )

    def _context(self, label):
        store = MySQLStore()
        self.assertTrue(store.healthcheck())
        suffix = "%s-%s" % (label, uuid.uuid4().hex[:12])
        (
            workspace_id,
            _master_id,
            master_secret,
            _account_id,
            company_id,
            project_id,
            _human_secret,
        ) = store.create_free_account(
            "Commons MySQL " + suffix,
            "Commons MySQL " + suffix,
            "Commons MySQL " + suffix,
        )
        return (
            store,
            CommonsRepository(store, _settings(workspace_id, project_id)),
            workspace_id,
            project_id,
            company_id,
            master_secret,
            suffix,
        )

    def _enroll(self, repository, agent_name, label):
        candidate = _candidate(label)
        body = {
            "agentName": agent_name,
            "displayName": agent_name.replace("-", " ").title(),
            "publicProfile": _profile(),
            "candidateTokenSecret": candidate,
        }
        result, replay = repository.enroll(
            body["agentName"],
            body["displayName"],
            body["publicProfile"],
            candidate,
            _key("mysql-enroll-" + label),
            request_digest(body),
        )
        self.assertFalse(replay)
        self.assertEqual("active", result["status"])
        self.assertEqual("commons_only", result["principal"]["authority"])
        self.assertFalse(result["rawCredentialExposed"])
        return candidate, body, result

    def test_schema_and_two_agent_vertical_slice(self):
        store, repository, workspace_id, _project_id, _company_id, _master, suffix = self._context(
            "vertical"
        )
        required_tables = {
            "matm_commons_agent_profiles",
            "matm_commons_browser_sessions",
            "matm_commons_enrollment_requests",
            "matm_commons_memberships",
            "matm_commons_acknowledgements",
            "matm_commons_message_revisions",
            "matm_commons_messages",
            "matm_commons_policies",
            "matm_commons_rooms",
            "matm_commons_withdrawals",
        }
        with store._open_connection() as connection:
            rows = connection.execute(
                "SELECT table_name AS table_name FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name LIKE 'matm_commons_%'"
            ).fetchall()
        self.assertTrue(required_tables.issubset({row["table_name"] for row in rows}))

        name_a = "mysql-a-" + suffix[-12:]
        name_b = "mysql-b-" + suffix[-12:]
        token_a, body_a, enrolled_a = self._enroll(repository, name_a, suffix + "-a")
        token_b, _body_b, _enrolled_b = self._enroll(repository, name_b, suffix + "-b")
        replayed, replay = repository.enroll(
            body_a["agentName"],
            body_a["displayName"],
            body_a["publicProfile"],
            token_a,
            _key("mysql-enroll-" + suffix + "-a"),
            request_digest(body_a),
        )
        self.assertTrue(replay)
        self.assertEqual(
            enrolled_a["principal"]["credentialId"],
            replayed["principal"]["credentialId"],
        )
        auth_a = repository.authenticate_agent_credential(token_a)
        auth_b = repository.authenticate_agent_credential(token_b)
        self.assertIsNotNone(auth_a)
        self.assertIsNotNone(auth_b)
        room_id = repository.room_id
        repository.set_membership(
            room_id, auth_a, "joined", _key(suffix + "-join-a"), request_digest({"state": "joined"})
        )
        repository.set_membership(
            room_id, auth_b, "joined", _key(suffix + "-join-b"), request_digest({"state": "joined"})
        )
        posted, _ = repository.publish(
            room_id,
            auth_a,
            "MySQL public message",
            None,
            _key(suffix + "-post-a"),
            request_digest({"content": "MySQL public message"}),
        )
        reply, _ = repository.publish(
            room_id,
            auth_b,
            "MySQL public reply",
            posted["messageId"],
            _key(suffix + "-reply-b"),
            request_digest({"content": "MySQL public reply"}),
        )
        page = repository.list_messages(room_id, limit=10, viewer_agent_id=auth_b["agentId"])
        self.assertEqual(
            [posted["messageId"], reply["messageId"]],
            [item["messageId"] for item in page["items"]],
        )
        corrected, _ = repository.correct(
            posted["messageId"],
            auth_a,
            "MySQL corrected public message",
            1,
            _key(suffix + "-correct-a"),
            request_digest({"content": "MySQL corrected public message", "expectedRevision": 1}),
        )
        binding = corrected["acknowledgementBinding"]
        acknowledged, _ = repository.acknowledge(
            posted["messageId"],
            auth_b,
            binding["expectedRevision"],
            binding["expectedRevisionId"],
            binding["expectedState"],
            binding["expectedWithdrawalId"],
            _key(suffix + "-ack-corrected"),
            request_digest(binding),
        )
        self.assertTrue(acknowledged["acknowledgedByViewer"])
        withdrawn, _ = repository.withdraw(
            posted["messageId"],
            auth_a,
            2,
            _key(suffix + "-withdraw-a"),
            request_digest({"expectedRevision": 2}),
        )
        self.assertEqual("withdrawn", withdrawn["state"])
        withdrawn = repository.message(
            posted["messageId"], viewer_agent_id=auth_b["agentId"]
        )
        self.assertEqual("withdrawn", withdrawn["state"])
        self.assertTrue(withdrawn["tombstone"]["withdrawn"])
        tombstone_binding = withdrawn["acknowledgementBinding"]
        tombstone_ack, _ = repository.acknowledge(
            posted["messageId"],
            auth_b,
            tombstone_binding["expectedRevision"],
            tombstone_binding["expectedRevisionId"],
            tombstone_binding["expectedState"],
            tombstone_binding["expectedWithdrawalId"],
            _key(suffix + "-ack-tombstone"),
            request_digest(tombstone_binding),
        )
        self.assertTrue(tombstone_ack["acknowledgedByViewer"])

        browser_secret = _browser_candidate(suffix + "-browser")
        session, replay = repository.create_browser_session(
            auth_a,
            browser_secret,
            _key(suffix + "-browser"),
            request_digest({"candidateBrowserSessionSecret": browser_secret}),
        )
        self.assertFalse(replay)
        session_auth = repository.authenticate_browser_session(browser_secret)
        self.assertIsNotNone(session_auth)
        self.assertEqual(
            session["browserSession"]["browserSessionId"],
            repository.current_browser_session(session_auth)["browserSessionId"],
        )
        successor = _candidate(suffix + "-successor")
        rotated, replay = repository.rotate_credential(
            auth_a,
            successor,
            _key(suffix + "-rotate"),
            request_digest({"candidateTokenSecret": successor}),
        )
        self.assertFalse(replay)
        self.assertEqual("active", rotated["status"])
        self.assertIsNone(repository.authenticate_agent_credential(token_a))
        self.assertIsNone(repository.authenticate_browser_session(browser_secret))
        successor_auth = repository.authenticate_agent_credential(successor)
        self.assertIsNotNone(successor_auth)
        revoked, replay = repository.revoke_credential(
            successor_auth,
            _key(suffix + "-revoke"),
            request_digest({"revoke": True}),
        )
        self.assertFalse(replay)
        self.assertEqual("revoked", revoked["status"])
        self.assertIsNone(repository.authenticate_agent_credential(successor))

    def test_project_approval_queue_and_decision(self):
        store, repository, workspace_id, _project_id, _company_id, master, suffix = self._context(
            "approval"
        )
        master_auth = store.authenticate(master, workspace_id)
        policy, replay = repository.set_policy(
            master_auth,
            True,
            0,
            _key(suffix + "-policy"),
            request_digest({"humanApprovalRequired": True, "expectedRevision": 0}),
        )
        self.assertFalse(replay)
        self.assertTrue(policy["humanApprovalRequired"])
        candidate = _candidate(suffix + "-pending")
        pending, replay = repository.enroll(
            "mysql-pending-" + suffix[-12:],
            "MySQL Pending Agent",
            _profile(),
            candidate,
            _key(suffix + "-pending"),
            request_digest({"agentName": "mysql-pending-" + suffix[-12:]}),
        )
        self.assertFalse(replay)
        self.assertEqual("pending", pending["status"])
        self.assertIsNone(repository.authenticate_agent_credential(candidate))
        queue = repository.enrollment_requests(master_auth, limit=10)
        self.assertIn(
            pending["enrollmentRequestId"],
            [item["enrollmentRequestId"] for item in queue["items"]],
        )
        approved, replay = repository.decide_enrollment(
            master_auth,
            pending["enrollmentRequestId"],
            "approved",
            pending["revision"],
            _key(suffix + "-approve"),
            request_digest(
                {
                    "requestId": pending["enrollmentRequestId"],
                    "expectedRevision": pending["revision"],
                    "decision": "approved",
                }
            ),
        )
        self.assertFalse(replay)
        self.assertEqual("approved", approved["status"])
        self.assertIsNotNone(repository.authenticate_agent_credential(candidate))

    def test_outbound_mcp_initial_project_policy_insert(self):
        store, _repository, workspace_id, project_id, _company_id, _master, _suffix = (
            self._context("outbound-policy")
        )
        policy, error = store.set_outbound_mcp_project_policy(
            workspace_id,
            project_id,
            "human_required",
            0,
            forced_by_human=False,
            actor_id="mysql-contract-agent",
        )
        self.assertIsNone(error)
        self.assertEqual(1, policy["revision"])
        self.assertEqual("human_required", policy["mode"])
        self.assertEqual(
            policy,
            store.outbound_mcp_project_policy(workspace_id, project_id),
        )

    def test_two_process_exact_enrollment_idempotency(self):
        _store, repository, _workspace_id, _project_id, _company_id, _master, suffix = self._context(
            "multiprocess"
        )
        candidate = _candidate(suffix + "-concurrent")
        agent_name = "mysql-concurrent-" + suffix[-12:]
        digest = request_digest({"agentName": agent_name, "candidateTokenSecret": candidate})
        key = _key(suffix + "-concurrent")
        context = multiprocessing.get_context("spawn")
        gate = context.Barrier(2)
        output = context.Queue()
        processes = [
            context.Process(
                target=_enroll_worker,
                args=(
                    dict(repository.settings),
                    agent_name,
                    candidate,
                    key,
                    digest,
                    gate,
                    output,
                ),
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
            self.assertEqual(
                ["ok", "ok"],
                sorted(item["kind"] for item in results),
                results,
            )
            self.assertEqual([False, True], sorted(item["replay"] for item in results))
            self.assertEqual(1, len({item["credentialId"] for item in results}))
            self.assertIsNotNone(repository.authenticate_agent_credential(candidate))
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(5)


if __name__ == "__main__":
    unittest.main()
