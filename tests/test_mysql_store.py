import tempfile
import unittest
from pathlib import Path


class MySQLStoreTests(unittest.TestCase):
    def test_open_connection_uses_db_context_manager_directly(self):
        from memoryendpoints.storage import MySQLStore

        class FakeConnection(object):
            pass

        class FakeMySQLStore(MySQLStore):
            def __init__(self):
                pass

            def _connect(self):
                return self.fake_connection

        store = FakeMySQLStore()
        store.fake_connection = FakeConnection()

        self.assertIs(store.fake_connection, store._open_connection())

    def test_sql_workspace_status_does_not_export_whole_store(self):
        from memoryendpoints.storage import SQLiteStore

        class DirectWorkspaceStatusStore(SQLiteStore):
            def _load(self):
                raise AssertionError("workspace_status must use direct SQL queries")

        with tempfile.TemporaryDirectory() as tmp:
            store = DirectWorkspaceStatusStore(Path(tmp) / "matm.sqlite")
            workspace_id, _key_id, _token, account_id, company_id, project_id = store.create_free_account(
                "SQL Workspace",
                "SQL Company",
                "SQL Project",
            )

            status = store.workspace_status(workspace_id)

        self.assertEqual(workspace_id, status["workspaceId"])
        self.assertEqual(account_id, status["accountId"])
        self.assertEqual(company_id, status["companyId"])
        self.assertEqual(project_id, status["primaryProjectId"])
        self.assertEqual("SQL Company", status["company"]["label"])
        self.assertEqual(["company", "workspace", "project"], [room["scope"] for room in status["meetingRooms"]])
        self.assertTrue(all(room["alwaysAvailable"] for room in status["meetingRooms"]))
        self.assertEqual(3, len(status["meetingRooms"]))
        self.assertGreater(status["storageUsedBytes"], 0)
        self.assertFalse(status["rawKeyStoredByServer"])


if __name__ == "__main__":
    unittest.main()
