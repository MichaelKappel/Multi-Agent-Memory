import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path

from memoryendpoints.storage import SQLiteStore, _SQLITE_SCHEMA_VERSION


class CountingSQLiteStore(SQLiteStore):
    def __init__(self, path):
        super().__init__(path)
        self.schema_runs = 0

    def _ensure_schema(self, connection):
        self.schema_runs += 1
        return super()._ensure_schema(connection)


class SQLiteSchemaInitializationTests(unittest.TestCase):
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
