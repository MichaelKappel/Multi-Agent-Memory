import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path

from memoryendpoints.storage import (
    MySQLStore,
    SQLiteStore,
    _SQLITE_SCHEMA_VERSION,
    _is_sql_duplicate_key_conflict,
)
from memoryendpoints.outbound_mcp import SERVER_SCHEMA, config_digest
from tests.governed_test_support import DeterministicCredentialPepperMixin


class CountingSQLiteStore(SQLiteStore):
    def __init__(self, path):
        super().__init__(path)
        self.schema_runs = 0

    def _ensure_schema(self, connection):
        self.schema_runs += 1
        return super()._ensure_schema(connection)


class SQLiteSchemaInitializationTests(
    DeterministicCredentialPepperMixin, unittest.TestCase
):
    def _user_version(self, path):
        with closing(sqlite3.connect(str(path))) as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    def test_current_schema_version_skips_repeated_schema_convergence(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "store.sqlite3"
            store = CountingSQLiteStore(path)

            self.assertTrue(store.healthcheck())
            self.assertTrue(store.healthcheck())

            self.assertEqual(1, store.schema_runs)
            self.assertEqual(_SQLITE_SCHEMA_VERSION, self._user_version(path))

    def test_older_schema_version_reruns_schema_convergence(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "store.sqlite3"
            store = CountingSQLiteStore(path)
            self.assertTrue(store.healthcheck())

            with closing(sqlite3.connect(str(path))) as connection:
                connection.execute("PRAGMA user_version = 0")
                connection.commit()

            self.assertTrue(store.healthcheck())
            self.assertEqual(2, store.schema_runs)
            self.assertEqual(_SQLITE_SCHEMA_VERSION, self._user_version(path))

    def test_populated_v1_database_migrates_without_losing_core_rows(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "store.sqlite3"
            store = CountingSQLiteStore(path)
            (
                workspace_id,
                _key_id,
                _token,
                _account_id,
                _company_id,
                project_id,
                _recovery_secret,
            ) = store.create_free_account(
                "Migration Workspace", "Migration Company", "Migration Project"
            )
            with closing(sqlite3.connect(str(path))) as connection:
                connection.execute("PRAGMA foreign_keys=OFF")
                connection.execute("DROP TABLE matm_outbound_mcp_servers")
                connection.execute("DROP TABLE matm_outbound_mcp_project_policies")
                connection.execute("PRAGMA user_version = 1")
                connection.commit()

            migrated = CountingSQLiteStore(path)
            self.assertTrue(migrated.healthcheck())
            self.assertEqual(_SQLITE_SCHEMA_VERSION, self._user_version(path))
            with closing(sqlite3.connect(str(path))) as connection:
                self.assertEqual(
                    (workspace_id,),
                    connection.execute(
                        "SELECT workspace_id FROM matm_workspaces WHERE workspace_id = ?",
                        (workspace_id,),
                    ).fetchone(),
                )
                self.assertEqual(
                    (project_id,),
                    connection.execute(
                        "SELECT project_id FROM matm_projects WHERE project_id = ?",
                        (project_id,),
                    ).fetchone(),
                )
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                self.assertTrue(
                    {
                        "matm_outbound_mcp_project_policies",
                        "matm_outbound_mcp_servers",
                    }.issubset(tables)
                )
                indexes = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'index'"
                    )
                }
                self.assertIn(
                    "ux_sqlite_projects_project_workspace", indexes
                )

    def test_v2_outbound_table_gains_approval_revision_column(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "store.sqlite3"
            with closing(sqlite3.connect(str(path))) as connection:
                connection.execute(
                    """
                    CREATE TABLE matm_outbound_mcp_servers (
                      server_id TEXT PRIMARY KEY,
                      workspace_id TEXT NOT NULL,
                      project_id TEXT NOT NULL,
                      owner_agent_id TEXT NOT NULL,
                      config_json TEXT NOT NULL,
                      config_digest TEXT NOT NULL,
                      approval_binding_json TEXT,
                      revision INTEGER NOT NULL,
                      status TEXT NOT NULL,
                      created_at TEXT NOT NULL,
                      updated_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute("PRAGMA user_version = 2")
                connection.commit()

            self.assertTrue(SQLiteStore(path).healthcheck())
            self.assertEqual(_SQLITE_SCHEMA_VERSION, self._user_version(path))
            with closing(sqlite3.connect(str(path))) as connection:
                columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(matm_outbound_mcp_servers)"
                    )
                }
            self.assertIn("approval_revision", columns)

    def test_v5_database_converges_hidden_bootstrap_claim_schema(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "store.sqlite3"
            store = SQLiteStore(path)
            account = store.create_free_account(
                "Bootstrap Upgrade", "Bootstrap Upgrade", "Bootstrap Upgrade"
            )
            workspace_id = account[0]
            with closing(sqlite3.connect(str(path))) as connection:
                connection.execute("DROP TABLE matm_bootstrap_account_setups")
                connection.execute("PRAGMA user_version = 5")
                connection.commit()

            self.assertTrue(SQLiteStore(path).healthcheck())
            self.assertEqual(_SQLITE_SCHEMA_VERSION, self._user_version(path))
            with closing(sqlite3.connect(str(path))) as connection:
                columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(matm_bootstrap_account_setups)"
                    )
                }
                indexes = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA index_list(matm_bootstrap_account_setups)"
                    )
                }
                readback = connection.execute(
                    "SELECT workspace_id FROM matm_workspaces WHERE workspace_id = ?",
                    (workspace_id,),
                ).fetchone()
            self.assertEqual(
                {
                    "capability_digest_sha256",
                    "idempotency_digest_sha256",
                    "request_digest_sha256",
                    "status",
                    "account_id",
                    "company_id",
                    "workspace_id",
                    "project_id",
                    "company_master_credential_id",
                    "human_owner_credential_id",
                    "created_at",
                },
                columns,
            )
            self.assertTrue(indexes)
            self.assertEqual((workspace_id,), readback)
            canonical = (
                Path(__file__).resolve().parents[1]
                / "docs"
                / "database-schema-canonical.sql"
            ).read_text(encoding="utf-8")
            self.assertIn(
                "CREATE TABLE IF NOT EXISTS matm_bootstrap_account_setups",
                canonical,
            )
            self.assertIn(
                "UNIQUE KEY ux_matm_bootstrap_account_setups_idempotency",
                canonical,
            )

    def test_commons_schema_has_canonical_tables_indexes_and_foreign_keys(self):
        expected_tables = {
            "matm_commons_policies",
            "matm_commons_enrollment_requests",
            "matm_commons_agent_profiles",
            "matm_commons_rooms",
            "matm_commons_memberships",
            "matm_commons_messages",
            "matm_commons_message_revisions",
            "matm_commons_withdrawals",
            "matm_commons_acknowledgements",
            "matm_commons_browser_sessions",
            "matm_commons_idempotency",
        }
        expected_indexes = {
            "ux_sqlite_workspaces_workspace_company",
            "ix_sqlite_commons_enrollment_queue",
            "ix_sqlite_commons_enrollment_name",
            "ix_sqlite_commons_profiles_public",
            "ix_sqlite_commons_rooms_discovery",
            "ix_sqlite_commons_memberships_scope_state",
            "ix_sqlite_commons_messages_cursor",
            "ix_sqlite_commons_revisions_scope",
            "ix_sqlite_commons_withdrawals_scope",
            "ix_sqlite_commons_ack_scope_agent",
            "ix_sqlite_commons_browser_sessions_scope",
            "ix_sqlite_commons_idempotency_scope",
        }
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "store.sqlite3"
            self.assertTrue(SQLiteStore(path).healthcheck())
            with closing(sqlite3.connect(str(path))) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                indexes = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'index'"
                    )
                }
                self.assertTrue(expected_tables.issubset(tables))
                self.assertTrue(expected_indexes.issubset(indexes))
                grant_columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(matm_agent_access_grants)"
                    )
                }
                self.assertIn("commons_only", grant_columns)
                request_columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(matm_commons_enrollment_requests)"
                    )
                }
                self.assertTrue(
                    {
                        "candidate_token_id",
                        "candidate_token_hash",
                        "revision",
                        "expires_at",
                        "activated_profile_id",
                    }.issubset(request_columns)
                )
                membership_parents = {
                    row[2]
                    for row in connection.execute(
                        "PRAGMA foreign_key_list(matm_commons_memberships)"
                    )
                }
                self.assertTrue(
                    {"matm_commons_rooms", "matm_commons_agent_profiles"}.issubset(
                        membership_parents
                    )
                )
                enrollment_foreign_keys = list(
                    connection.execute(
                        "PRAGMA foreign_key_list(matm_commons_enrollment_requests)"
                    )
                )
                grouped_foreign_keys = {}
                for row in enrollment_foreign_keys:
                    grouped_foreign_keys.setdefault((row[0], row[2]), []).append(
                        (row[3], row[4])
                    )
                self.assertIn(
                    [("company_id", "company_id"), ("workspace_id", "workspace_id")],
                    [
                        sorted(columns)
                        for (_key, table), columns in grouped_foreign_keys.items()
                        if table == "matm_workspaces"
                    ],
                )
                self.assertIn(
                    [("project_id", "project_id"), ("workspace_id", "workspace_id")],
                    [
                        sorted(columns)
                        for (_key, table), columns in grouped_foreign_keys.items()
                        if table == "matm_projects"
                    ],
                )
                self.assertEqual(
                    [], list(connection.execute("PRAGMA foreign_key_check"))
                )

        canonical = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "database-schema-canonical.sql"
        ).read_text(encoding="utf-8")
        for table in sorted(expected_tables):
            self.assertIn("CREATE TABLE IF NOT EXISTS %s" % table, canonical)
        self.assertIn("commons_only TINYINT(1) NOT NULL DEFAULT 0", canonical)
        self.assertIn(
            "UNIQUE KEY ux_matm_workspaces_workspace_company (workspace_id, company_id)",
            canonical,
        )
        self.assertIn(
            "FOREIGN KEY (workspace_id, company_id) REFERENCES matm_workspaces (workspace_id, company_id)",
            canonical,
        )
        self.assertIn(
            "FOREIGN KEY (project_id, workspace_id) REFERENCES matm_projects (project_id, workspace_id)",
            canonical,
        )

    def test_v4_database_converges_missing_commons_schema_without_core_loss(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "store.sqlite3"
            store = SQLiteStore(path)
            account = store.create_free_account(
                "Commons Upgrade", "Commons Upgrade", "Commons Upgrade"
            )
            workspace_id, project_id = account[0], account[5]
            commons_tables = [
                name
                for name in SQLiteStore.DELETE_ORDER
                if name.startswith("matm_commons_")
            ]
            with closing(sqlite3.connect(str(path))) as connection:
                connection.execute("PRAGMA foreign_keys=OFF")
                for table in commons_tables:
                    connection.execute("DROP TABLE %s" % table)
                connection.execute("PRAGMA user_version = 4")
                connection.commit()

            self.assertTrue(SQLiteStore(path).healthcheck())
            self.assertEqual(_SQLITE_SCHEMA_VERSION, self._user_version(path))
            with closing(sqlite3.connect(str(path))) as connection:
                self.assertEqual(
                    (workspace_id, project_id),
                    connection.execute(
                        "SELECT w.workspace_id, p.project_id FROM matm_workspaces w "
                        "JOIN matm_projects p ON p.workspace_id = w.workspace_id "
                        "WHERE w.workspace_id = ? AND p.project_id = ?",
                        (workspace_id, project_id),
                    ).fetchone(),
                )
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                self.assertTrue(set(commons_tables).issubset(tables))

    def test_mysql_upgrade_helper_converges_required_project_index(self):
        class FakeMySQLConnection:
            dialect = "mysql"

            def __init__(self):
                self.statements = []

            def execute(self, statement, _params=None):
                self.statements.append(" ".join(statement.split()))

        connection = FakeMySQLConnection()
        store = object.__new__(MySQLStore)
        store._ensure_outbound_mcp_project_index(connection)
        self.assertEqual(
            [
                "CREATE UNIQUE INDEX ux_matm_projects_project_workspace "
                "ON matm_projects (project_id, workspace_id)"
            ],
            connection.statements,
        )

        connection = FakeMySQLConnection()
        store._ensure_commons_scope_indexes(connection)
        self.assertEqual(
            [
                "CREATE UNIQUE INDEX ux_matm_workspaces_workspace_company "
                "ON matm_workspaces (workspace_id, company_id)"
            ],
            connection.statements,
        )

    def test_duplicate_key_classifier_is_backend_and_error_specific(self):
        self.assertTrue(
            _is_sql_duplicate_key_conflict(
                sqlite3.IntegrityError(
                    "UNIQUE constraint failed: matm_outbound_mcp_project_policies.project_id"
                )
            )
        )
        for error in (
            sqlite3.IntegrityError("FOREIGN KEY constraint failed"),
            sqlite3.IntegrityError(
                "NOT NULL constraint failed: matm_outbound_mcp_project_policies.mode"
            ),
            sqlite3.IntegrityError("CHECK constraint failed: valid_mode"),
            sqlite3.IntegrityError("arbitrary integrity failure"),
            sqlite3.OperationalError("database is locked"),
        ):
            with self.subTest(error=str(error)):
                self.assertFalse(_is_sql_duplicate_key_conflict(error))

        PyMySQLIntegrityError = type(
            "IntegrityError", (Exception,), {"__module__": "pymysql.err"}
        )
        self.assertTrue(
            _is_sql_duplicate_key_conflict(
                PyMySQLIntegrityError(1062, "Duplicate entry")
            )
        )
        self.assertFalse(
            _is_sql_duplicate_key_conflict(
                PyMySQLIntegrityError(1452, "Foreign key constraint fails")
            )
        )

    def test_initial_policy_insert_race_has_one_success_and_one_typed_conflict(self):
        class Result:
            def __init__(self, row=None, rowcount=-1):
                self.row = row
                self.rowcount = rowcount

            def fetchone(self):
                return self.row

        class PolicyInsertConnection:
            def __init__(self, insert_error=None):
                self.insert_error = insert_error

            def __enter__(self):
                return self

            def __exit__(self, _kind, _value, _traceback):
                return False

            def execute(self, statement, _params=None):
                normalized = " ".join(statement.split())
                if normalized.startswith("SELECT p.project_id FROM matm_projects p"):
                    return Result({"project_id": "project-race"})
                if normalized.startswith(
                    "SELECT * FROM matm_outbound_mcp_project_policies"
                ):
                    return Result(None)
                if normalized.startswith(
                    "INSERT INTO matm_outbound_mcp_project_policies"
                ):
                    if self.insert_error is not None:
                        raise self.insert_error
                    return Result(rowcount=1)
                raise AssertionError("Unexpected SQL in race test: " + normalized)

        class DeterministicRaceStore(SQLiteStore):
            def __init__(self, insert_outcomes):
                self.insert_outcomes = iter(insert_outcomes)
                self.audits = []

            def _open_connection(self):
                return PolicyInsertConnection(next(self.insert_outcomes))

            def _record_audit_sql(
                self, _connection, workspace_id, action, actor, target, details
            ):
                self.audits.append(
                    {
                        "workspaceId": workspace_id,
                        "action": action,
                        "actor": actor,
                        "target": target,
                        "details": details,
                    }
                )

        duplicate = sqlite3.IntegrityError(
            "UNIQUE constraint failed: matm_outbound_mcp_project_policies.project_id"
        )
        store = DeterministicRaceStore((None, duplicate))
        success = store.set_outbound_mcp_project_policy(
            "workspace-race", "project-race", "human_required", 0
        )
        conflict = store.set_outbound_mcp_project_policy(
            "workspace-race", "project-race", "blocked", 0
        )

        self.assertIsNotNone(success[0])
        self.assertIsNone(success[1])
        self.assertIsNone(conflict[0])
        self.assertEqual("outbound_mcp_revision_conflict", conflict[1])
        self.assertEqual(1, len(store.audits))
        self.assertEqual("outbound_mcp.policy.update", store.audits[0]["action"])
        self.assertEqual("human_required", store.audits[0]["details"]["mode"])

        for non_unique_error in (
            sqlite3.IntegrityError("FOREIGN KEY constraint failed"),
            sqlite3.IntegrityError(
                "NOT NULL constraint failed: matm_outbound_mcp_project_policies.mode"
            ),
            sqlite3.IntegrityError("CHECK constraint failed: valid_mode"),
            sqlite3.OperationalError("database is locked"),
            RuntimeError("synthetic connection failure"),
        ):
            with self.subTest(error=str(non_unique_error)):
                failing = DeterministicRaceStore((non_unique_error,))
                with self.assertRaises(type(non_unique_error)):
                    failing.set_outbound_mcp_project_policy(
                        "workspace-race", "project-race", "human_required", 0
                    )
                self.assertEqual([], failing.audits)

    def test_sql_policy_revision_is_compare_and_swap(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "store.sqlite3"
            store = SQLiteStore(path)
            workspace_id, _key, _token, _account, _company, project_id, _recovery = (
                store.create_free_account("CAS", "CAS", "CAS")
            )
            first, error = store.set_outbound_mcp_project_policy(
                workspace_id, project_id, "human_required", 0
            )
            self.assertIsNone(error)
            self.assertEqual(1, first["revision"])

            barrier = threading.Barrier(2)
            results = []

            def update(mode):
                contender = SQLiteStore(path)
                barrier.wait(timeout=5)
                results.append(
                    contender.set_outbound_mcp_project_policy(
                        workspace_id, project_id, mode, 1
                    )
                )

            workers = [
                threading.Thread(target=update, args=("blocked",)),
                threading.Thread(target=update, args=("human_required",)),
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=10)

            self.assertTrue(all(not worker.is_alive() for worker in workers))
            self.assertEqual(1, sum(1 for value, error in results if value and not error))
            self.assertEqual(
                1,
                sum(
                    1
                    for value, error in results
                    if value is None and error == "outbound_mcp_revision_conflict"
                ),
            )

    def test_outbound_project_workspace_pair_is_enforced_by_schema(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "store.sqlite3"
            store = SQLiteStore(path)
            first = store.create_free_account("First", "First", "First")
            second = store.create_free_account("Second", "Second", "Second")
            first_project_id = first[5]
            second_workspace_id = second[0]
            with closing(sqlite3.connect(str(path))) as connection:
                connection.execute("PRAGMA foreign_keys=ON")
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        "INSERT INTO matm_outbound_mcp_project_policies "
                        "(project_id, workspace_id, mode, forced_by_human, revision) "
                        "VALUES (?, ?, 'autonomous', 0, 0)",
                        (first_project_id, second_workspace_id),
                    )
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        "INSERT INTO matm_outbound_mcp_servers "
                        "(server_id, workspace_id, project_id, owner_agent_id, "
                        "config_json, config_digest, revision, status, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, '{}', ?, 1, 'active', 'now', 'now')",
                        (
                            "omcp-" + ("1" * 32),
                            second_workspace_id,
                            first_project_id,
                            "schema-test-agent",
                            "0" * 64,
                        ),
                    )

    def test_relational_full_save_round_trip_preserves_outbound_state(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "store.sqlite3"
            store = SQLiteStore(path)
            workspace_id, _key, _token, _account, _company, project_id, _recovery = (
                store.create_free_account("Round Trip", "Round Trip", "Round Trip")
            )
            configured = {
                "schemaVersion": SERVER_SCHEMA,
                "label": "Round trip server",
                "endpoint": "https://tools.example.test/mcp",
                "transport": "streamable_http",
                "authMode": "none",
                "requestedMode": "human_required",
                "toolAllowlist": ["memory.search", "tools.list"],
            }
            created, error = store.create_outbound_mcp_server(
                workspace_id, project_id, "round-trip-agent", configured
            )
            self.assertIsNone(error)
            policy, error = store.set_outbound_mcp_project_policy(
                workspace_id, project_id, "human_required", 0
            )
            self.assertIsNone(error)
            approved, error = store.set_outbound_mcp_server_approval(
                workspace_id,
                project_id,
                created["serverId"],
                created["revision"],
                created["configDigest"],
                policy["revision"],
                0,
                "human-schema-reviewer",
                decision_reason="Reviewed for schema round trip",
            )
            self.assertIsNone(error)
            self.assertEqual(1, approved["approvalRevision"])
            self.assertEqual(1, approved["approvalBinding"]["approvalRevision"])
            self.assertNotIn("humanActorId", approved["approvalBinding"])

            stale, error = store.set_outbound_mcp_server_approval(
                workspace_id,
                project_id,
                created["serverId"],
                created["revision"],
                created["configDigest"],
                policy["revision"],
                0,
                "human-stale-reviewer",
                status="denied",
            )
            self.assertIsNone(stale)
            self.assertEqual("outbound_mcp_revision_conflict", error)

            data = store._load()
            store._save(data)

            readback = store.outbound_mcp_server(
                workspace_id, project_id, "round-trip-agent", created["serverId"]
            )
            self.assertEqual(created["configDigest"], readback["configDigest"])
            self.assertEqual(config_digest(configured), readback["configDigest"])
            self.assertEqual(approved["approvalBinding"], readback["approvalBinding"])
            self.assertEqual(
                "human_required",
                store.outbound_mcp_project_policy(workspace_id, project_id)["mode"],
            )

    def test_replaced_database_at_same_path_is_initialized(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "store.sqlite3"
            store = CountingSQLiteStore(path)
            self.assertTrue(store.healthcheck())

            path.unlink()
            for suffix in ("-journal", "-shm", "-wal"):
                Path(str(path) + suffix).unlink(missing_ok=True)

            self.assertTrue(store.healthcheck())
            self.assertEqual(2, store.schema_runs)
            self.assertEqual(_SQLITE_SCHEMA_VERSION, self._user_version(path))

    def test_newer_schema_version_fails_closed_without_running_ddl(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "store.sqlite3"
            with closing(sqlite3.connect(str(path))) as connection:
                connection.execute(
                    "PRAGMA user_version = %d" % (_SQLITE_SCHEMA_VERSION + 1)
                )
                connection.commit()
            store = CountingSQLiteStore(path)

            with self.assertRaisesRegex(RuntimeError, "newer than supported"):
                store.healthcheck()

            self.assertEqual(0, store.schema_runs)
            with closing(sqlite3.connect(str(path))) as connection:
                table_count = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
                ).fetchone()[0]
            self.assertEqual(0, table_count)

    def test_schema_failure_rolls_back_ddl_and_version_marker(self):
        class FailingSQLiteStore(SQLiteStore):
            def _ensure_knowledge_schema_columns(self, connection):
                raise RuntimeError("synthetic schema failure")

        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "store.sqlite3"

            with self.assertRaisesRegex(RuntimeError, "synthetic schema failure"):
                FailingSQLiteStore(path).healthcheck()

            with closing(sqlite3.connect(str(path))) as connection:
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                table_count = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
                ).fetchone()[0]
            self.assertEqual(0, version)
            self.assertEqual(0, table_count)
            self.assertTrue(SQLiteStore(path).healthcheck())

    def test_waiting_initializer_rechecks_version_after_write_lock(self):
        first_version_read = threading.Event()

        class RecheckingSQLiteStore(SQLiteStore):
            def __init__(self, path):
                super().__init__(path)
                self.schema_runs = 0

            def _sqlite_user_version(self, connection):
                version = super()._sqlite_user_version(connection)
                first_version_read.set()
                return version

            def _ensure_schema(self, connection):
                self.schema_runs += 1

        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "store.sqlite3"
            store = RecheckingSQLiteStore(path)
            errors = []

            with closing(sqlite3.connect(str(path), timeout=20)) as writer:
                writer.execute("PRAGMA busy_timeout=20000")
                writer.execute("BEGIN IMMEDIATE")

                def initialize():
                    try:
                        with closing(sqlite3.connect(str(path), timeout=20)) as connection:
                            connection.execute("PRAGMA busy_timeout=20000")
                            store._ensure_sqlite_schema_current(connection)
                    except Exception as exc:
                        errors.append(exc)

                worker = threading.Thread(target=initialize)
                worker.start()
                self.assertTrue(first_version_read.wait(timeout=5))
                writer.execute(
                    "PRAGMA user_version = %d" % _SQLITE_SCHEMA_VERSION
                )
                writer.commit()
                worker.join(timeout=5)

            self.assertFalse(worker.is_alive())
            self.assertEqual([], errors)
            self.assertEqual(0, store.schema_runs)


if __name__ == "__main__":
    unittest.main()
