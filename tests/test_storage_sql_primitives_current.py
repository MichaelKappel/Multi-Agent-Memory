"""Hermetic coverage for the current Multi-Agent-Memory database adapter contract."""

from __future__ import annotations

import datetime
import unittest

from memoryendpoints import storage


class _Cursor:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []
        self.rowcount = len(self.rows)
        self.closed = False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)

    def close(self):
        self.closed = True


class _Connection:
    def __init__(self):
        self.cursor_value = _Cursor()
        self.cursor_calls = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self, **options):
        self.cursor_calls.append(options)
        return self.cursor_value

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class StorageSqlPrimitivesCurrentTests(unittest.TestCase):
    def test_sql_scanners_ignore_quotes_comments_and_nested_commas(self):
        statement = "SELECT '?' /* ? */, col FROM t WHERE created_at = ? AND note = 'x?';"
        self.assertEqual([50], storage._sql_placeholder_positions(statement))
        self.assertEqual(
            "SELECT '?' /* ? */, col FROM t WHERE created_at = %s AND note = 'x?';",
            storage._mysql_qmark_sql(statement),
        )
        self.assertEqual("SELECT 1", storage._mysql_qmark_sql("SELECT 1"))
        self.assertEqual(("a, (b,c)", 11), storage._sql_parenthesized_segment("x(a, (b,c))", 1))
        self.assertEqual((None, 1), storage._sql_parenthesized_segment("x(a", 1))
        self.assertEqual(["a", "fn('b,c')", "d"], storage._sql_csv_items("a, fn('b,c'), d"))
        self.assertEqual(9, storage._sql_top_level_keyword("x (FROM) FROM y", 0, ("FROM",)))
        self.assertEqual(10, storage._sql_top_level_keyword("x FROMAGE FROM", 0, ("FROM",)))

    def test_mysql_datetime_parameter_indexes_cover_values_select_direct_and_between(self):
        insert = "INSERT INTO t (name, created_at, updated_at) VALUES (?, ?, ?)"
        self.assertEqual({1, 2}, storage._mysql_datetime_parameter_indexes(insert))
        select_insert = "INSERT INTO t (name, created_at) SELECT ?, ? FROM source WHERE id = ?"
        self.assertEqual({1}, storage._mysql_datetime_parameter_indexes(select_insert))
        direct = "SELECT * FROM t WHERE created_at >= ? AND updated_at BETWEEN ? AND ?"
        self.assertEqual({0, 1, 2}, storage._mysql_datetime_parameter_indexes(direct))
        self.assertEqual(set(), storage._mysql_datetime_parameter_indexes("SELECT '?'"))
        params = ["name", "2026-09-11T12:30:01Z", 5]
        converted = storage._mysql_datetime_params(insert, params)
        self.assertEqual(datetime.datetime(2026, 9, 11, 12, 30, 1), converted[1])
        self.assertEqual(5, converted[2])
        self.assertEqual("raw", storage._mysql_datetime_params(insert, "raw"))

    def test_connection_adapts_sql_and_honors_transaction_lifecycle(self):
        connection = _Connection()
        adapter = storage._DbConnection(connection, "mysql", {"dictionary": True})
        self.assertEqual(
            "REPLACE INTO t VALUES (%%, %s)",
            adapter._sql("INSERT OR REPLACE INTO t VALUES (%, ?)", parameterized=True),
        )
        adapter.execute("SELECT ?", ("value",))
        adapter.execute("SELECT 1")
        adapter.executescript("SELECT 1; ; SELECT 2;")
        self.assertEqual(4, len(connection.cursor_value.calls))
        self.assertEqual({"dictionary": True}, connection.cursor_calls[0])
        with adapter:
            with adapter:
                pass
        self.assertEqual(1, connection.commits)
        self.assertTrue(connection.closed)

        failed = _Connection()
        with self.assertRaisesRegex(RuntimeError, "boom"):
            with storage._DbConnection(failed, "sqlite"):
                raise RuntimeError("boom")
        self.assertEqual(1, failed.rollbacks)
        self.assertTrue(failed.closed)

    def test_cursor_normalization_and_datetime_safety_are_fail_closed(self):
        date = datetime.date(2026, 9, 11)
        naive = datetime.datetime(2026, 9, 11, 12, 30, 1)
        cursor = storage._DbCursor(_Cursor([{"When": date, "created": naive, "n": 3}]))
        row = cursor.fetchone()
        self.assertEqual("2026-09-11", row["When"])
        self.assertEqual("2026-09-11T12:30:01Z", row["created"])
        self.assertEqual([row], list(storage._DbCursor(_Cursor([row]))))
        ambiguous = storage._DbCursor(_Cursor([{"Name": "a", "name": "b"}])).fetchone()
        self.assertEqual({"Name": "a", "name": "b"}, ambiguous)
        self.assertEqual((None, 1), storage._sql_parenthesized_segment("x('unfinished", 1))


if __name__ == "__main__":
    unittest.main()
