import json
import tempfile
import unittest
from pathlib import Path

from memoryendpoints.storage import FileStore, SQLiteStore


class FileStoreSyncTests(unittest.TestCase):
    def make_store(self, tmp):
        return FileStore(Path(tmp) / "matm.json")

    def test_sync_mutation_records_head_changes_and_redacted_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(tmp)
            workspace_id, _key_id, _token, _account_id, _company_id, _project_id, _recovery_secret = store.create_free_account(
                "Sync Workspace",
                "Sync Company",
                "Sync Project",
            )
            device = store.register_sync_device(workspace_id, "sync-agent", "device-a", "Agent workstation")

            applied, http_status = store.submit_sync_mutation(
                workspace_id,
                "sync-agent",
                {
                    "logicalMemoryId": "logical-1",
                    "deviceId": "device-a",
                    "deviceEpoch": device["authorityEpoch"],
                    "operation": "upsert",
                    "title": "First sync memory",
                    "summary": "Public-safe sync mutation.",
                    "source": "memoryendpoints://tests/sync",
                },
                idempotency_key="secret-idempotency-key",
            )

            receipt = store.sync_receipt(workspace_id, idempotency_key="secret-idempotency-key")
            changes = store.sync_changes(workspace_id, after_sequence=0)
            heads = store.sync_heads(workspace_id, "logical-1")
            serialized_receipt = json.dumps(receipt, sort_keys=True)

        self.assertEqual("202 Accepted", http_status)
        self.assertTrue(applied["ok"])
        self.assertEqual("applied", applied["status"])
        self.assertEqual(1, applied["serverSequence"])
        self.assertEqual(1, changes["count"])
        self.assertEqual(1, changes["indexedThroughSequence"])
        self.assertEqual("logical-1", changes["items"][0]["logicalMemoryId"])
        self.assertEqual(1, len(heads))
        self.assertEqual(applied["revision"]["syncRevisionId"], heads[0]["headRevisionId"])
        self.assertEqual(receipt["receiptId"], applied["receipt"]["receiptId"])
        self.assertFalse(receipt["idempotencyKeyExposed"])
        self.assertNotIn("secret-idempotency-key", serialized_receipt)
        self.assertTrue(receipt["valuesRedacted"])

    def test_sync_conflict_preserves_existing_head_and_records_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(tmp)
            workspace_id, _key_id, _token, _account_id, _company_id, _project_id, _recovery_secret = store.create_free_account(
                "Sync Conflict Workspace",
                "Sync Conflict Company",
                "Sync Conflict Project",
            )
            device = store.register_sync_device(workspace_id, "sync-agent", "device-a", "Agent workstation")
            applied, _http_status = store.submit_sync_mutation(
                workspace_id,
                "sync-agent",
                {
                    "logicalMemoryId": "logical-1",
                    "deviceId": "device-a",
                    "deviceEpoch": device["authorityEpoch"],
                    "operation": "upsert",
                    "title": "Original sync memory",
                    "summary": "Original public-safe sync mutation.",
                },
            )
            original_head = store.sync_heads(workspace_id, "logical-1")[0]

            conflict, conflict_status = store.submit_sync_mutation(
                workspace_id,
                "sync-agent",
                {
                    "logicalMemoryId": "logical-1",
                    "parentRevisionId": "stale-parent",
                    "deviceId": "device-a",
                    "deviceEpoch": device["authorityEpoch"],
                    "operation": "upsert",
                    "title": "Conflicting sync memory",
                    "summary": "Conflicting public-safe sync mutation.",
                },
                idempotency_key="conflict-idempotency-key",
            )
            receipt = store.sync_receipt(workspace_id, idempotency_key="conflict-idempotency-key")
            heads = store.sync_heads(workspace_id, "logical-1")
            changes = store.sync_changes(workspace_id, after_sequence=0, logical_memory_id="logical-1")

        self.assertTrue(applied["ok"])
        self.assertEqual("409 Conflict", conflict_status)
        self.assertFalse(conflict["ok"])
        self.assertTrue(conflict["conflict"])
        self.assertEqual("conflict", conflict["status"])
        self.assertEqual("parent_revision_mismatch", conflict["receipt"]["conflictCode"])
        self.assertEqual("parent_revision_mismatch", receipt["conflictCode"])
        self.assertEqual(original_head["headRevisionId"], heads[0]["headRevisionId"])
        self.assertEqual(2, changes["count"])
        self.assertEqual("conflict", changes["items"][1]["status"])

    def test_revoked_sync_device_rejects_mutation_without_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(tmp)
            workspace_id, _key_id, _token, _account_id, _company_id, _project_id, _recovery_secret = store.create_free_account(
                "Sync Revoke Workspace",
                "Sync Revoke Company",
                "Sync Revoke Project",
            )
            device = store.register_sync_device(workspace_id, "sync-agent", "device-a", "Agent workstation")
            revoked, revoke_error = store.revoke_sync_device(workspace_id, "device-a", "sync-agent")

            rejected, http_status = store.submit_sync_mutation(
                workspace_id,
                "sync-agent",
                {
                    "logicalMemoryId": "logical-1",
                    "deviceId": "device-a",
                    "deviceEpoch": device["authorityEpoch"],
                    "operation": "upsert",
                    "title": "Rejected sync memory",
                    "summary": "Rejected public-safe sync mutation.",
                },
                idempotency_key="revoked-idempotency-key",
            )
            receipt = store.sync_receipt(workspace_id, idempotency_key="revoked-idempotency-key")
            changes = store.sync_changes(workspace_id, after_sequence=0)

        self.assertIsNone(revoke_error)
        self.assertEqual("revoked", revoked["status"])
        self.assertEqual("409 Conflict", http_status)
        self.assertFalse(rejected["ok"])
        self.assertEqual("rejected", rejected["status"])
        self.assertEqual("device_revoked", rejected["receipt"]["conflictCode"])
        self.assertEqual("device_revoked", receipt["conflictCode"])
        self.assertIsNone(rejected["revision"])
        self.assertEqual(0, changes["count"])


class SQLiteStoreSyncTests(FileStoreSyncTests):
    def make_store(self, tmp):
        return SQLiteStore(Path(tmp) / "matm.sqlite")


if __name__ == "__main__":
    unittest.main()
