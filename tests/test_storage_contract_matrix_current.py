"""Current FileStore/SQLiteStore parity for shared storage workflows."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from memoryendpoints.storage import FileStore, SQLiteStore


class StorageContractMatrixCurrentTests(unittest.TestCase):
    def test_common_project_knowledge_external_meeting_and_sync_workflows_match(self):
        previous = os.environ.get("MEMORYENDPOINTS_CREDENTIAL_PEPPER")
        os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = "synthetic-storage-matrix-pepper-" + ("x" * 48)
        self.addCleanup(
            lambda: os.environ.__setitem__("MEMORYENDPOINTS_CREDENTIAL_PEPPER", previous)
            if previous is not None
            else os.environ.pop("MEMORYENDPOINTS_CREDENTIAL_PEPPER", None)
        )
        for store_type in (FileStore, SQLiteStore):
            with self.subTest(backend=store_type.__name__), tempfile.TemporaryDirectory() as tmp:
                suffix = "store.json" if store_type is FileStore else "store.sqlite3"
                store = store_type(Path(tmp) / suffix)
                setup = store.create_free_account("Matrix Workspace", "Matrix Company", "Matrix Project")
                workspace_id, _master_id, master_secret, _account, _company, project_id, _recovery = setup
                agent_id = "matrix-agent"
                store.register_agent(workspace_id, agent_id, "Matrix Agent")
                self.assertEqual(workspace_id, store.workspace_status(workspace_id)["workspaceId"])
                self.assertEqual((None, "workspace_not_found"), store.upsert_project("missing", "p", "P"))
                project, error = store.upsert_project(workspace_id, "matrix-secondary", "Secondary")
                self.assertIsNone(error)
                self.assertEqual("project-matrix-secondary", project["projectId"])
                updated, error = store.upsert_project(workspace_id, "matrix-secondary", "Secondary Updated", agent_id)
                self.assertIsNone(error)
                self.assertEqual("Secondary Updated", updated["label"])

                document, error = store.upsert_knowledge_document(
                    workspace_id,
                    agent_id,
                    {
                        "scope": "project",
                        "scopeId": project_id,
                        "projectId": project_id,
                        "title": "Matrix operations",
                        "content": "Stored matrix documentation for a current project.",
                        "category": "operations",
                        "source": "memoryendpoints://matrix",
                        "tags": ["matrix", "operations"],
                    },
                )
                self.assertIsNone(error)
                self.assertEqual(project_id, document["scopeId"])
                self.assertEqual((None, "unsupported_scope"), store.upsert_knowledge_document(workspace_id, agent_id, {"scope": "company-ish"}))
                self.assertEqual((None, "content_required"), store.upsert_knowledge_document(workspace_id, agent_id, {"scope": "workspace", "content": " "}))
                self.assertEqual((None, "workspace_not_found"), store.upsert_knowledge_document("missing", agent_id, {"content": "x"}))
                link, error = store.upsert_external_link(
                    workspace_id,
                    agent_id,
                    {
                        "url": "https://example.com/matrix",
                        "siteName": "Example Matrix",
                        "pageTitle": "Matrix Reference",
                        "description": "A reviewed current reference.",
                        "reviewStatus": "reviewed",
                        "knowledgeDocumentId": document["searchDocumentId"],
                        "relationshipType": "reference",
                    },
                )
                self.assertIsNone(error)
                self.assertEqual(1, len(store.external_links(workspace_id, {"host": "example.com"})))
                self.assertEqual(1, len(store.external_links(workspace_id, {"q": "matrix"})))
                self.assertEqual([], store.external_links(workspace_id, {"reviewStatus": "missing"}))

                rooms = store.meeting_rooms(workspace_id)
                self.assertTrue(rooms)
                room_id = rooms[0]["roomId"]
                self.assertEqual((None, "message_not_found"), store.mark_meeting_room_read(workspace_id, room_id, agent_id, "missing-message"))
                message, room = store.submit_meeting_message(workspace_id, room_id, agent_id, "Matrix meeting summary")
                self.assertEqual(room_id, room["roomId"])
                read, error = store.mark_meeting_room_read(workspace_id, room_id, agent_id, message["meetingMessageId"])
                self.assertIsNone(error)
                self.assertEqual(message["meetingMessageId"], read["lastMeetingMessageId"])
                repeat, error = store.mark_meeting_room_read(workspace_id, room_id, agent_id)
                self.assertIsNone(error)
                self.assertEqual(repeat["lastMeetingMessageId"], read["lastMeetingMessageId"])

                device = store.register_sync_device(workspace_id, agent_id, "matrix-device", "Matrix Device")
                self.assertEqual(1, device["authorityEpoch"])
                rotated, error = store.rotate_sync_device(workspace_id, "matrix-device", agent_id)
                self.assertIsNone(error)
                self.assertEqual(2, rotated["authorityEpoch"])
                revoked, error = store.revoke_sync_device(workspace_id, "matrix-device", agent_id)
                self.assertIsNone(error)
                self.assertEqual("revoked", revoked["status"])
                self.assertEqual((None, "device_revoked"), store.rotate_sync_device(workspace_id, "matrix-device", agent_id))
                self.assertEqual((None, "device_not_found"), store.rotate_sync_device(workspace_id, "missing-device", agent_id))
                self.assertTrue(store.auth_allows_scope(store.authenticate(master_secret, workspace_id), "workspace", workspace_id))
                self.assertFalse(store.auth_allows_scope(store.authenticate(master_secret, workspace_id), "project", "other-project"))

    def test_sync_transition_matrix_rejects_invalid_devices_and_blocks_resurrection(self):
        """Exercise the shared sync state machine on both local backends."""
        previous = os.environ.get("MEMORYENDPOINTS_CREDENTIAL_PEPPER")
        os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = "synthetic-sync-matrix-pepper-" + ("x" * 48)
        self.addCleanup(
            lambda: os.environ.__setitem__("MEMORYENDPOINTS_CREDENTIAL_PEPPER", previous)
            if previous is not None
            else os.environ.pop("MEMORYENDPOINTS_CREDENTIAL_PEPPER", None)
        )
        for store_type in (FileStore, SQLiteStore):
            with self.subTest(backend=store_type.__name__), tempfile.TemporaryDirectory() as tmp:
                suffix = "store.json" if store_type is FileStore else "store.sqlite3"
                store = store_type(Path(tmp) / suffix)
                workspace_id, _master_id, _master_secret, _account, _company, _project, _recovery = store.create_free_account(
                    "Sync Matrix Workspace", "Sync Matrix Company", "Sync Matrix Project"
                )
                device = store.register_sync_device(workspace_id, "sync-agent", "sync-device", "Matrix Device")

                rejected, status = store.submit_sync_mutation(
                    workspace_id,
                    "sync-agent",
                    {"logicalMemoryId": "invalid-device", "deviceId": "missing-device", "operation": "upsert"},
                    idempotency_key="unknown-device-key",
                )
                self.assertEqual("409 Conflict", status)
                self.assertEqual("device_not_registered", rejected["receipt"]["conflictCode"])
                self.assertIsNone(rejected["revision"])

                epoch_mismatch, status = store.submit_sync_mutation(
                    workspace_id,
                    "sync-agent",
                    {
                        "logicalMemoryId": "epoch-mismatch",
                        "deviceId": "sync-device",
                        "deviceEpoch": device["authorityEpoch"] + 1,
                        "operation": "upsert",
                    },
                )
                self.assertEqual("409 Conflict", status)
                self.assertEqual("device_epoch_mismatch", epoch_mismatch["receipt"]["conflictCode"])

                first, status = store.submit_sync_mutation(
                    workspace_id,
                    "sync-agent",
                    {
                        "logicalMemoryId": "logical-tombstone",
                        "deviceId": "sync-device",
                        "deviceEpoch": device["authorityEpoch"],
                        "operation": "upsert",
                        "title": "Current sync record",
                        "summary": "safe summary",
                    },
                    idempotency_key="sync-first-key",
                )
                self.assertEqual("202 Accepted", status)
                self.assertTrue(first["ok"])
                parent = first["revision"]["syncRevisionId"]
                deleted, status = store.submit_sync_mutation(
                    workspace_id,
                    "sync-agent",
                    {
                        "logicalMemoryId": "logical-tombstone",
                        "parentRevisionId": parent,
                        "deviceId": "sync-device",
                        "deviceEpoch": device["authorityEpoch"],
                        "operation": "delete",
                    },
                    idempotency_key="sync-delete-key",
                )
                self.assertEqual("202 Accepted", status)
                self.assertEqual("delete", deleted["revision"]["operation"])
                tombstone_parent = deleted["revision"]["syncRevisionId"]
                resurrect, status = store.submit_sync_mutation(
                    workspace_id,
                    "sync-agent",
                    {
                        "logicalMemoryId": "logical-tombstone",
                        "parentRevisionId": tombstone_parent,
                        "deviceId": "sync-device",
                        "deviceEpoch": device["authorityEpoch"],
                        "operation": "upsert",
                    },
                    idempotency_key="sync-resurrect-key",
                )
                self.assertEqual("409 Conflict", status)
                self.assertEqual("tombstone_resurrection_blocked", resurrect["receipt"]["conflictCode"])

                unsupported, status = store.submit_sync_mutation(
                    workspace_id,
                    "sync-agent",
                    {"logicalMemoryId": "unsupported", "deviceId": "sync-device", "operation": "hard_forget"},
                    idempotency_key="sync-hard-forget-key",
                )
                self.assertEqual("409 Conflict", status)
                self.assertEqual("hard_forget_not_supported", unsupported["receipt"]["conflictCode"])

                revoked, error = store.revoke_sync_device(workspace_id, "sync-device", "sync-agent")
                self.assertIsNone(error)
                self.assertEqual("revoked", revoked["status"])
                after_revoke, status = store.submit_sync_mutation(
                    workspace_id,
                    "sync-agent",
                    {"logicalMemoryId": "after-revoke", "deviceId": "sync-device", "operation": "upsert"},
                    idempotency_key="sync-after-revoke-key",
                )
                self.assertEqual("409 Conflict", status)
                self.assertEqual("device_revoked", after_revoke["receipt"]["conflictCode"])

    def test_workspace_status_repairs_missing_rooms_and_project_ids_remain_tenant_bound(self):
        previous = os.environ.get("MEMORYENDPOINTS_CREDENTIAL_PEPPER")
        os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = "synthetic-status-matrix-pepper-" + ("x" * 48)
        self.addCleanup(
            lambda: os.environ.__setitem__("MEMORYENDPOINTS_CREDENTIAL_PEPPER", previous)
            if previous is not None
            else os.environ.pop("MEMORYENDPOINTS_CREDENTIAL_PEPPER", None)
        )
        for store_type in (FileStore, SQLiteStore):
            with self.subTest(backend=store_type.__name__), tempfile.TemporaryDirectory() as tmp:
                suffix = "store.json" if store_type is FileStore else "store.sqlite3"
                store = store_type(Path(tmp) / suffix)
                workspace_id, _master_id, _master_secret, _account, _company, _project, _recovery = store.create_free_account(
                    "Status Matrix Workspace", "Status Matrix Company", "Status Matrix Project"
                )
                data = store._load()
                data["meetingRooms"] = {}
                store._save(data)
                status = store.workspace_status(workspace_id)
                self.assertTrue(status["meetingRooms"])
                self.assertEqual(workspace_id, status["workspaceId"])

                other = store.create_free_account("Other Workspace", "Other Company", "Other Project")
                other_project, error = store.upsert_project(other[0], "tenant-bound", "Tenant Bound")
                self.assertIsNone(error)
                conflict, error = store.upsert_project(workspace_id, "tenant-bound", "Cross Tenant")
                self.assertIsNone(conflict)
                self.assertEqual("project_id_conflict", error)
                self.assertEqual("project-tenant-bound", other_project["projectId"])


if __name__ == "__main__":
    unittest.main()
