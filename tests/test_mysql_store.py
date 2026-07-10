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

    def test_sql_memory_confirmation_uses_direct_audit_log(self):
        from memoryendpoints.app import _memory_submission_confirmation
        from memoryendpoints.storage import SQLiteStore

        class DirectConfirmationStore(SQLiteStore):
            def _load(self):
                raise AssertionError("memory confirmation must use direct SQL queries")

        with tempfile.TemporaryDirectory() as tmp:
            store = DirectConfirmationStore(Path(tmp) / "matm.sqlite")
            workspace_id, _key_id, _token, _account_id, _company_id, _project_id = store.create_free_account(
                "SQL Confirmation Workspace",
                "SQL Confirmation Company",
                "SQL Confirmation Project",
            )
            event = store.submit_memory(
                workspace_id,
                "sql-confirmation-agent",
                "workspace",
                "SQL confirmation memory",
                "SQL confirmation memory must be visible in search, review queue, and audit log.",
                ["sql-confirmation"],
                "tests/test_mysql_store.py",
                "status",
                "SQL confirmation",
                0.9,
            )

            confirmation = _memory_submission_confirmation(store, workspace_id, event)
            audit_items = store.audit_log(workspace_id, 50, "memory.submit")

        self.assertTrue(confirmation["persisted"])
        self.assertTrue(confirmation["visibleInSearch"])
        self.assertTrue(confirmation["visibleInReviewQueue"])
        self.assertTrue(confirmation["visibleInAuditLog"])
        self.assertTrue(any(item["target"] == event["eventId"] for item in audit_items))

    def test_sql_record_audit_does_not_rebuild_store_or_drop_sync_rows(self):
        from memoryendpoints.storage import SQLiteStore

        class DirectAuditStore(SQLiteStore):
            def _save(self, data):
                raise AssertionError("record_audit must use direct SQL insert, not full-store rebuild")

        with tempfile.TemporaryDirectory() as tmp:
            store = DirectAuditStore(Path(tmp) / "matm.sqlite")
            workspace_id, _key_id, _token, _account_id, _company_id, _project_id = store.create_free_account(
                "SQL Sync Audit Workspace",
                "SQL Sync Audit Company",
                "SQL Sync Audit Project",
            )
            device = store.register_sync_device(workspace_id, "sync-audit-agent", "device-a", "Agent workstation")
            applied, _http_status = store.submit_sync_mutation(
                workspace_id,
                "sync-audit-agent",
                {
                    "logicalMemoryId": "logical-audit",
                    "deviceId": "device-a",
                    "deviceEpoch": device["authorityEpoch"],
                    "operation": "upsert",
                    "title": "Sync audit memory",
                    "summary": "Public-safe sync mutation must survive read-audit writes.",
                },
                idempotency_key="sync-audit-idempotency",
            )

            store.record_audit(
                workspace_id,
                "sync.changes.read",
                "workspace-key",
                "/api/matm/sync/changes",
                {"count": 1},
            )
            receipt = store.sync_receipt(workspace_id, idempotency_key="sync-audit-idempotency")
            changes = store.sync_changes(workspace_id, after_sequence=0, logical_memory_id="logical-audit")
            heads = store.sync_heads(workspace_id, "logical-audit")

        self.assertTrue(applied["persisted"])
        self.assertEqual(applied["receipt"]["receiptId"], receipt["receiptId"])
        self.assertEqual(1, changes["count"])
        self.assertEqual(applied["revision"]["syncRevisionId"], changes["items"][0]["syncRevisionId"])
        self.assertEqual(applied["revision"]["syncRevisionId"], heads[0]["headRevisionId"])


if __name__ == "__main__":
    unittest.main()
