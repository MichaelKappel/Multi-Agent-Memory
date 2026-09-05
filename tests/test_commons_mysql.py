import hashlib
import datetime
import multiprocessing
import os
import threading
import unittest
import uuid

from memoryendpoints.commons import request_digest
from memoryendpoints.commons_storage import CommonsRepository
from memoryendpoints.storage import (
    MySQLStore,
    _DbConnection,
    _MYSQL_SCHEMA_METADATA_TABLE,
    _MYSQL_SCHEMA_READY,
    _MYSQL_SCHEMA_VERSION,
    _mysql_config_from_env,
)
from tests.governed_test_support import DeterministicCredentialPepperMixin


_MYSQL_TEST_ENABLED = "MEMORYENDPOINTS_COMMONS_MYSQL_TEST"
_MYSQL_TEST_MUTATION_ACK = "MEMORYENDPOINTS_COMMONS_MYSQL_TEST_ALLOW_MUTATION"
_MYSQL_TEST_DATABASE_FINGERPRINT = (
    "MEMORYENDPOINTS_COMMONS_MYSQL_TEST_DATABASE_SHA256"
)
_EXPECTED_MUTATION_ACK = "isolated-disposable-database"


class _SchemaResult:
    def __init__(self, rows):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class _SharedSchemaState:
    def __init__(self, tables=None, metadata=None, views=None):
        self.tables = set(tables or ())
        self.views = set(views or ())
        self.metadata = dict(metadata) if metadata else None
        self.advisory_lock = threading.Lock()
        self.mutex = threading.Lock()


class _SchemaConnection:
    dialect = "mysql"

    def __init__(self, state, before_lock=None):
        self.state = state
        self.before_lock = before_lock
        self.calls = []
        self.closed = False
        self.commits = 0

    def execute(self, statement, params=None):
        normalized = " ".join(statement.split())
        self.calls.append((normalized, params))
        if "GET_LOCK" in normalized:
            if self.before_lock:
                self.before_lock.set()
            self.state.advisory_lock.acquire()
            return _SchemaResult(({"acquired": 1},))
        if "RELEASE_LOCK" in normalized:
            self.state.advisory_lock.release()
            return _SchemaResult(({"released": 1},))
        if "FROM information_schema.tables" in normalized:
            with self.state.mutex:
                rows = tuple(
                    {"object_name": table_name, "object_type": "BASE TABLE"}
                    for table_name in sorted(self.state.tables)
                ) + tuple(
                    {"object_name": view_name, "object_type": "VIEW"}
                    for view_name in sorted(self.state.views)
                )
            return _SchemaResult(rows)
        if normalized.startswith("SELECT schema_version AS schema_version"):
            with self.state.mutex:
                rows = (dict(self.state.metadata),) if self.state.metadata else ()
            return _SchemaResult(rows)
        if normalized.startswith("CREATE TABLE matm_schema_metadata"):
            with self.state.mutex:
                self.state.tables.add(_MYSQL_SCHEMA_METADATA_TABLE)
            return _SchemaResult(())
        if normalized.startswith("INSERT INTO matm_schema_metadata"):
            with self.state.mutex:
                self.state.metadata = {
                    "schema_version": params[1],
                    "schema_digest": params[2],
                }
            return _SchemaResult(())
        raise AssertionError("Unexpected schema test statement: %s" % normalized)

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


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

            def _ensure_mysql_schema_current(self, _connection):
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

    def test_schema_classifier_initializes_only_an_empty_database_and_reads_back_exactly(
        self,
    ):
        state = _SharedSchemaState()

        class Store(MySQLStore):
            def __init__(self):
                self.ensure_count = 0

            def _ensure_schema(self, connection):
                self.ensure_count += 1
                connection.calls.append(("SYNTHETIC CANONICAL DDL", None))
                expected_tables, _expected_digest = self._mysql_expected_schema()
                with connection.state.mutex:
                    connection.state.tables.update(
                        expected_tables - {_MYSQL_SCHEMA_METADATA_TABLE}
                    )

        store = Store()
        config = {
            "host": "127.0.0.1",
            "port": "43397",
            "database": "isolated-empty-schema-test",
            "user": "isolated-test-user",
            "password": "not-in-cache-key",
            "unix_socket": "",
        }
        schema_key = store._schema_cache_key(config)
        _MYSQL_SCHEMA_READY.discard(schema_key)
        connection = _SchemaConnection(state)

        store._ensure_schema_once(connection, config)

        expected_tables, expected_digest = store._mysql_expected_schema()
        self.assertEqual(1, store.ensure_count)
        self.assertEqual(expected_tables, frozenset(state.tables))
        self.assertEqual(
            {
                "schema_version": _MYSQL_SCHEMA_VERSION,
                "schema_digest": expected_digest,
            },
            state.metadata,
        )
        statements = [statement for statement, _params in connection.calls]
        first_classification = next(
            index
            for index, statement in enumerate(statements)
            if "FROM information_schema.tables" in statement
        )
        first_ddl = statements.index("SYNTHETIC CANONICAL DDL")
        metadata_ddl = next(
            index
            for index, statement in enumerate(statements)
            if statement.startswith("CREATE TABLE matm_schema_metadata")
        )
        readbacks = [
            index
            for index, statement in enumerate(statements)
            if "FROM information_schema.tables" in statement
        ]
        self.assertLess(first_classification, first_ddl)
        self.assertLess(first_ddl, metadata_ddl)
        self.assertEqual(2, len(readbacks))
        self.assertLess(metadata_ddl, readbacks[-1])
        self.assertEqual("SELECT RELEASE_LOCK(?) AS released", statements[-1])
        self.assertIn(schema_key, _MYSQL_SCHEMA_READY)
        _MYSQL_SCHEMA_READY.discard(schema_key)

    def test_schema_classifier_rejects_incompatible_schemas_without_ddl(self):
        store = MySQLStore()
        expected_tables, expected_digest = store._mysql_expected_schema()
        cases = (
            (
                "unversioned",
                _SharedSchemaState({"matm_workspaces"}),
                "non-empty and unversioned",
            ),
            (
                "unknown",
                _SharedSchemaState(
                    expected_tables,
                    {
                        "schema_version": _MYSQL_SCHEMA_VERSION,
                        "schema_digest": "0" * 64,
                    },
                ),
                "does not match the exact supported schema",
            ),
            (
                "view-only",
                _SharedSchemaState(views={"unexpected_view"}),
                "non-empty and unversioned",
            ),
            (
                "extra-view",
                _SharedSchemaState(
                    expected_tables,
                    {
                        "schema_version": _MYSQL_SCHEMA_VERSION,
                        "schema_digest": expected_digest,
                    },
                    views={"unexpected_view"},
                ),
                "does not match the exact supported schema",
            ),
            (
                "missing-metadata-row",
                _SharedSchemaState(expected_tables),
                "metadata is not recognized",
            ),
            (
                "malformed-version",
                _SharedSchemaState(
                    expected_tables,
                    {
                        "schema_version": "not-a-version",
                        "schema_digest": expected_digest,
                    },
                ),
                "metadata is not recognized",
            ),
            (
                "incomplete",
                _SharedSchemaState(
                    expected_tables - {"matm_audit_log"},
                    {
                        "schema_version": _MYSQL_SCHEMA_VERSION,
                        "schema_digest": expected_digest,
                    },
                ),
                "does not match the exact supported schema",
            ),
            (
                "newer",
                _SharedSchemaState(
                    expected_tables,
                    {
                        "schema_version": _MYSQL_SCHEMA_VERSION + 1,
                        "schema_digest": expected_digest,
                    },
                ),
                "newer than supported",
            ),
            (
                "older",
                _SharedSchemaState(
                    expected_tables,
                    {
                        "schema_version": _MYSQL_SCHEMA_VERSION - 1,
                        "schema_digest": expected_digest,
                    },
                ),
                "requires a governed migration",
            ),
        )
        for label, state, message in cases:
            with self.subTest(label=label):
                config = {
                    "host": "127.0.0.1",
                    "port": "43397",
                    "database": "isolated-%s-schema-test" % label,
                    "user": "isolated-test-user",
                    "password": "not-in-cache-key",
                    "unix_socket": "",
                }
                schema_key = store._schema_cache_key(config)
                _MYSQL_SCHEMA_READY.discard(schema_key)
                connection = _SchemaConnection(state)
                with self.assertRaisesRegex(RuntimeError, message):
                    store._ensure_schema_once(connection, config)
                statements = [statement for statement, _params in connection.calls]
                self.assertFalse(
                    any(
                        statement.startswith(("CREATE ", "ALTER ", "INSERT "))
                        for statement in statements
                    )
                )
                self.assertEqual(
                    "SELECT RELEASE_LOCK(?) AS released", statements[-1]
                )
                self.assertNotIn(schema_key, _MYSQL_SCHEMA_READY)

    def test_waiting_mysql_initializer_reclassifies_after_advisory_lock(self):
        state = _SharedSchemaState()
        first_schema_started = threading.Event()
        second_waiting = threading.Event()
        allow_first_schema = threading.Event()

        class Store(MySQLStore):
            def __init__(self):
                self.ensure_count = 0

            def _ensure_schema(self, connection):
                with connection.state.mutex:
                    self.ensure_count += 1
                first_schema_started.set()
                if not allow_first_schema.wait(timeout=5):
                    raise RuntimeError("timed out waiting for schema race")
                expected_tables, _expected_digest = self._mysql_expected_schema()
                with connection.state.mutex:
                    connection.state.tables.update(
                        expected_tables - {_MYSQL_SCHEMA_METADATA_TABLE}
                    )

        store = Store()
        first_config = {
            "host": "127.0.0.1",
            "port": "43397",
            "database": "isolated-schema-race-test",
            "user": "isolated-test-user",
            "password": "not-in-cache-key",
            "unix_socket": "",
        }
        second_config = dict(
            first_config,
            host="mysql.internal.example",
            user="alternate-isolated-user",
            unix_socket="/isolated/mysql.sock",
        )
        first_schema_key = store._schema_cache_key(first_config)
        second_schema_key = store._schema_cache_key(second_config)
        self.assertNotEqual(first_schema_key, second_schema_key)
        _MYSQL_SCHEMA_READY.discard(first_schema_key)
        _MYSQL_SCHEMA_READY.discard(second_schema_key)
        first_connection = _SchemaConnection(state)
        second_connection = _SchemaConnection(state, before_lock=second_waiting)
        errors = []

        def initialize(connection, config):
            try:
                store._ensure_schema_once(connection, config)
            except Exception as exc:
                errors.append(exc)

        first = threading.Thread(
            target=initialize, args=(first_connection, first_config)
        )
        second = threading.Thread(
            target=initialize, args=(second_connection, second_config)
        )
        first.start()
        self.assertTrue(first_schema_started.wait(timeout=5))
        second.start()
        self.assertTrue(second_waiting.wait(timeout=5))
        allow_first_schema.set()
        first.join(timeout=5)
        second.join(timeout=5)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual([], errors)
        self.assertEqual(1, store.ensure_count)
        first_lock_name = next(
            params[0]
            for statement, params in first_connection.calls
            if "GET_LOCK" in statement
        )
        second_lock_name = next(
            params[0]
            for statement, params in second_connection.calls
            if "GET_LOCK" in statement
        )
        self.assertEqual(first_lock_name, second_lock_name)
        self.assertEqual(
            1,
            sum(
                "FROM information_schema.tables" in statement
                for statement, _params in second_connection.calls
            ),
        )
        self.assertFalse(
            any(
                statement.startswith(("CREATE ", "ALTER ", "INSERT "))
                for statement, _params in second_connection.calls
            )
        )
        self.assertIn(first_schema_key, _MYSQL_SCHEMA_READY)
        self.assertIn(second_schema_key, _MYSQL_SCHEMA_READY)
        _MYSQL_SCHEMA_READY.discard(first_schema_key)
        _MYSQL_SCHEMA_READY.discard(second_schema_key)

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

            def _ensure_mysql_schema_current(self, _connection):
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

            def _ensure_mysql_schema_current(self, _connection):
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

            def _ensure_mysql_schema_current(self, _connection):
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
