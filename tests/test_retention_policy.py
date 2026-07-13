import datetime
import json
import tempfile
import unittest
from pathlib import Path

from memoryendpoints.storage import (
    FileStore,
    SQLiteStore,
    _blank_store,
    _prune_coordination_data,
)


NOW = datetime.datetime(2026, 7, 13, 12, 0, tzinfo=datetime.timezone.utc)


class RetentionPolicyTests(unittest.TestCase):
    def test_file_audit_log_is_physically_pruned_after_seven_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "matm.json"
            data = _blank_store()
            data["auditLog"] = [
                {"auditId": "old", "workspaceId": "ws", "action": "old", "createdAt": "2000-01-01T00:00:00.000000Z"},
                {"auditId": "current", "workspaceId": "ws", "action": "current", "createdAt": "2099-01-01T00:00:00.000000Z"},
            ]
            path.write_text(json.dumps(data), encoding="utf-8")

            items = FileStore(path).audit_log("ws")

            self.assertEqual(["current"], [item["auditId"] for item in items])
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(["current"], [item["auditId"] for item in persisted["auditLog"]])

    def test_transient_coordination_is_pruned_without_deleting_durable_routing(self):
        data = _blank_store()
        data["messages"] = [
            {"messageId": "ack-old", "createdAt": "2026-06-01T00:00:00.000000Z"},
            {"messageId": "unread-old", "createdAt": "2026-05-01T00:00:00.000000Z"},
            {"messageId": "ack-current", "createdAt": "2026-07-10T00:00:00.000000Z"},
        ]
        data["notifications"] = [
            {"notificationId": "n1", "messageId": "ack-old", "status": "read", "readAt": "2026-07-01T00:00:00.000000Z"},
            {"notificationId": "n2", "messageId": "unread-old", "status": "unread", "createdAt": "2026-05-01T00:00:00.000000Z"},
            {"notificationId": "n3", "messageId": "ack-current", "status": "read", "readAt": "2026-07-10T00:00:00.000000Z"},
        ]
        data["receipts"] = [
            {"receiptId": "r1", "notificationId": "n1"},
            {"receiptId": "r3", "notificationId": "n3"},
        ]
        data["meetingMessages"] = [
            {"meetingMessageId": "ordinary-old", "createdAt": "2026-07-01T00:00:00.000000Z"},
            {"meetingMessageId": "routing-old", "createdAt": "2026-07-01T00:00:00.000000Z"},
            {"meetingMessageId": "ordinary-current", "createdAt": "2026-07-10T00:00:00.000000Z"},
        ]
        data["routingDecisions"] = [{"routingDecisionId": "route-1", "meetingMessageId": "routing-old"}]
        data["meetingReads"] = [{"meetingReadId": "read-1", "lastMeetingMessageId": "ordinary-old"}]

        removed = _prune_coordination_data(data, NOW)

        self.assertEqual({"directMessages": 2, "notifications": 2, "meetingMessages": 1}, removed)
        self.assertEqual(["ack-current"], [item["messageId"] for item in data["messages"]])
        self.assertEqual(["n3"], [item["notificationId"] for item in data["notifications"]])
        self.assertEqual(["r3"], [item["receiptId"] for item in data["receipts"]])
        self.assertEqual(
            {"routing-old", "ordinary-current"},
            {item["meetingMessageId"] for item in data["meetingMessages"]},
        )
        self.assertEqual("", data["meetingReads"][0]["lastMeetingMessageId"])

    def test_sqlite_audit_and_transient_messages_are_physically_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteStore(Path(tmp) / "matm.sqlite")
            workspace_id, _key_id, _token, _account_id, _company_id, _project_id, _recovery = store.create_free_account("Retention")
            with store._open_connection() as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO matm_audit_log (
                          audit_id, workspace_id, action, actor, target, details_json, created_at,
                          raw_credential_exposed, raw_payload_exposed, values_redacted
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        ("audit-old", workspace_id, "old", "system", workspace_id, "{}", "2000-01-01T00:00:00.000000Z", 0, 0, 1),
                    )
                    connection.execute(
                        """
                        INSERT INTO matm_messages (
                          message_id, workspace_id, sender_agent_id, target_agent_id, safe_summary,
                          response_required, raw_message_body_stored, values_redacted, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        ("message-old", workspace_id, "agent-a", "agent-b", "expired", 0, 0, 1, "2000-01-01T00:00:00.000000Z"),
                    )
                    connection.execute(
                        """
                        INSERT INTO matm_notifications (
                          notification_id, workspace_id, message_id, target_agent_id, status,
                          response_disposition, created_at, read_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        ("note-old", workspace_id, "message-old", "agent-b", "read", "viewed_acknowledgement", "2000-01-01T00:00:00.000000Z", "2000-01-02T00:00:00.000000Z"),
                    )

            store.audit_log(workspace_id)

            with store._open_connection() as connection:
                self.assertIsNone(connection.execute("SELECT audit_id FROM matm_audit_log WHERE audit_id = ?", ("audit-old",)).fetchone())
                self.assertIsNone(connection.execute("SELECT message_id FROM matm_messages WHERE message_id = ?", ("message-old",)).fetchone())
                self.assertIsNone(connection.execute("SELECT notification_id FROM matm_notifications WHERE notification_id = ?", ("note-old",)).fetchone())


if __name__ == "__main__":
    unittest.main()
