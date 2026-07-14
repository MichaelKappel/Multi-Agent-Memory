import os
import unittest
from urllib.parse import parse_qs

from scripts import dogfood_memoryendpoints


class FakeTransport(object):
    mode = "live_http"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def call(self, path, method="GET", body=None, headers=None, query=""):
        self.calls.append({"path": path, "query": query, "method": method, "headers": headers or {}})
        if self.responses:
            return self.responses.pop(0)
        return "200 OK", {"ok": True, "items": [], "valuesRedacted": True}


class DogfoodReportTests(unittest.TestCase):
    def test_agent_audit_denial_uses_stable_human_owner_error(self):
        self.assertTrue(
            dogfood_memoryendpoints.agent_audit_denial_verified(
                "403 Forbidden",
                {"error": {"code": "human_owner_required"}},
            )
        )
        self.assertFalse(
            dogfood_memoryendpoints.agent_audit_denial_verified(
                "403 Forbidden",
                {"error": {"code": "insufficient_scope"}},
            )
        )

    def test_setup_authority_uses_current_company_master_field_only(self):
        current = "me_master_v1.master-current.secret-current"
        self.assertEqual(
            current,
            dogfood_memoryendpoints.setup_authority_token(
                {
                    "companyMasterTokenSecret": current,
                    "apiKeySecret": "obsolete-must-not-be-used",
                }
            ),
        )
        self.assertEqual(
            "",
            dogfood_memoryendpoints.setup_authority_token(
                {"apiKeySecret": "obsolete-must-not-be-used"}
            ),
        )

        transport = FakeTransport(
            [
                (
                    "201 Created",
                    {
                        "ok": True,
                        "companyMasterTokenSecret": current,
                        "workspaceId": "ws-current",
                    },
                ),
                ("200 OK", {"ok": True, "workspaceId": "ws-current"}),
            ]
        )
        setup_status, _setup, ready_status, _ready = (
            dogfood_memoryendpoints.create_ready_workspace(transport, "current")
        )
        self.assertEqual("201 Created", setup_status)
        self.assertEqual("200 OK", ready_status)
        self.assertEqual(
            "Bearer " + current,
            transport.calls[1]["headers"]["HTTP_AUTHORIZATION"],
        )

    def test_workspace_agent_provisioning_uses_governed_invite_flow(self):
        master = "me_master_v1.master-current.secret-current"
        agent = "me_agent_v1.agent-current.secret-current"
        transport = FakeTransport(
            [
                ("201 Created", {"ok": True, "request": {"requestId": "request-1"}}),
                ("200 OK", {"ok": True, "request": {"status": "approved"}}),
                (
                    "201 Created",
                    {
                        "ok": True,
                        "inviteUrl": "https://memoryendpoints.com/agent-setup#invite=me_invite_v1.invite-current.secret-current",
                    },
                ),
                (
                    "201 Created",
                    {
                        "ok": True,
                        "agentTokenSecret": agent,
                        "principal": {
                            "credentialType": "agent_token",
                            "agentId": "dogfood-primary-current",
                            "grant": {"scopeType": "workspace", "scopeId": "ws-current"},
                        },
                    },
                ),
            ]
        )

        status, payload = dogfood_memoryendpoints.provision_workspace_agent(
            transport,
            master,
            "ws-current",
            "project-current",
            "dogfood-primary-current",
            "Dogfood Primary Current",
        )

        self.assertEqual("201 Created", status)
        self.assertEqual(agent, payload["agentTokenSecret"])
        self.assertEqual(
            [
                "/api/matm/access/agent-name-requests",
                "/api/matm/access/agent-name-requests/request-1/decision",
                "/api/matm/access/invites",
                "/api/matm/access/invites/redeem",
            ],
            [item["path"] for item in transport.calls],
        )
        self.assertTrue(
            all(
                item["headers"].get("HTTP_AUTHORIZATION") == "Bearer " + master
                for item in transport.calls[:3]
            )
        )
        self.assertNotIn("HTTP_AUTHORIZATION", transport.calls[3]["headers"])

    def test_canonical_url_helpers_parse_relative_and_absolute_urls(self):
        self.assertEqual(
            ("/api/matm/current-message", "agent_id=agent-b"),
            dogfood_memoryendpoints.canonical_path_query("/api/matm/current-message?agent_id=agent-b"),
        )
        self.assertEqual(
            ("/api/matm/meeting-messages", "room_id=room-1"),
            dogfood_memoryendpoints.canonical_path_query("https://memoryendpoints.com/api/matm/meeting-messages?room_id=room-1"),
        )

    def test_contract_verified_step_requires_http_and_readback_evidence(self):
        report = {"steps": []}
        dogfood_memoryendpoints.step(report, "read_current_message", "200 OK", {"items": []}, verified=False)

        self.assertFalse(report["steps"][0]["ok"])
        self.assertFalse(report["steps"][0]["contractVerified"])

    def test_call_with_retries_retries_live_transient_status(self):
        transport = FakeTransport(
            [
                ("413 Request Entity Too Large", {"ok": False, "valuesRedacted": True}),
                ("201 Created", {"ok": True, "agent": {"agentId": "agent-b"}, "valuesRedacted": True}),
            ]
        )

        status, payload = dogfood_memoryendpoints.call_with_retries(
            transport,
            "/api/matm/agents/register",
            method="POST",
            body={"workspaceId": "ws-1", "agentId": "agent-b"},
            retry_statuses=("413",),
            attempts=2,
            delay_seconds=0,
        )

        self.assertEqual("201 Created", status)
        self.assertTrue(payload["ok"])
        self.assertEqual(2, len(transport.calls))

    def test_readback_helpers_match_returned_ids(self):
        self.assertTrue(
            dogfood_memoryendpoints.contains_memory_event(
                {"items": [{"eventId": "mem-1"}]},
                "mem-1",
            )
        )
        self.assertTrue(
            dogfood_memoryendpoints.contains_meeting_message(
                {"items": [{"meetingMessageId": "meetmsg-1"}]},
                "meetmsg-1",
            )
        )
        self.assertTrue(
            dogfood_memoryendpoints.contains_current_message(
                {"items": [{"message": {"messageId": "msg-1"}, "notification": {"notificationId": "note-1"}}]},
                "msg-1",
                "note-1",
            )
        )

    def test_current_message_query_includes_exact_readback_filters(self):
        query = dogfood_memoryendpoints.current_message_query("ws-1", "agent-b", "msg-1", "note-1")
        parsed = parse_qs(query)

        self.assertEqual(["ws-1"], parsed["workspace_id"])
        self.assertEqual(["agent-b"], parsed["agent_id"])
        self.assertEqual(["msg-1"], parsed["message_id"])
        self.assertEqual(["note-1"], parsed["notification_id"])

    def test_read_current_message_until_polls_until_exact_notification_visible(self):
        transport = FakeTransport(
            [
                ("200 OK", {"ok": True, "items": [], "valuesRedacted": True}),
                (
                    "200 OK",
                    {
                        "ok": True,
                        "items": [
                            {
                                "message": {"messageId": "msg-1"},
                                "notification": {"notificationId": "note-1"},
                            }
                        ],
                        "valuesRedacted": True,
                    },
                ),
            ]
        )

        status, payload = dogfood_memoryendpoints.read_current_message_until(
            transport,
            {"HTTP_AUTHORIZATION": "Bearer hidden"},
            "ws-1",
            "agent-b",
            "msg-1",
            "note-1",
            expected_visible=True,
            attempts=3,
            delay_seconds=0,
        )

        self.assertEqual("200 OK", status)
        self.assertTrue(dogfood_memoryendpoints.contains_current_message(payload, "msg-1", "note-1"))
        self.assertEqual(2, len(transport.calls))
        self.assertEqual("/api/matm/current-message", transport.calls[0]["path"])
        self.assertEqual(["note-1"], parse_qs(transport.calls[0]["query"])["notification_id"])

    def test_read_memory_until_polls_until_memory_event_visible(self):
        transport = FakeTransport(
            [
                ("200 OK", {"ok": True, "items": [], "valuesRedacted": True}),
                ("200 OK", {"ok": True, "items": [{"eventId": "mem-1"}], "valuesRedacted": True}),
            ]
        )

        status, payload = dogfood_memoryendpoints.read_memory_until(
            transport,
            {"HTTP_AUTHORIZATION": "Bearer hidden"},
            "mem-1",
            url="https://memoryendpoints.com/api/matm/search?q=Meeting",
            attempts=3,
            delay_seconds=0,
        )

        self.assertEqual("200 OK", status)
        self.assertTrue(dogfood_memoryendpoints.contains_memory_event(payload, "mem-1"))
        self.assertEqual(2, len(transport.calls))
        self.assertEqual("/api/matm/search", transport.calls[0]["path"])
        self.assertEqual(["Meeting"], parse_qs(transport.calls[0]["query"])["q"])

    def test_read_meeting_message_until_polls_until_message_visible(self):
        transport = FakeTransport(
            [
                ("200 OK", {"ok": True, "items": [], "valuesRedacted": True}),
                (
                    "200 OK",
                    {
                        "ok": True,
                        "items": [{"meetingMessageId": "meetmsg-1"}],
                        "valuesRedacted": True,
                    },
                ),
            ]
        )

        status, payload = dogfood_memoryendpoints.read_meeting_message_until(
            transport,
            {"HTTP_AUTHORIZATION": "Bearer hidden"},
            "meetmsg-1",
            url="https://memoryendpoints.com/api/matm/meeting-messages?room_id=room-1",
            attempts=3,
            delay_seconds=0,
        )

        self.assertEqual("200 OK", status)
        self.assertTrue(dogfood_memoryendpoints.contains_meeting_message(payload, "meetmsg-1"))
        self.assertEqual(2, len(transport.calls))
        self.assertEqual("/api/matm/meeting-messages", transport.calls[0]["path"])
        self.assertEqual(["room-1"], parse_qs(transport.calls[0]["query"])["room_id"])

    def test_combined_report_preserves_agent_audit_denial_evidence(self):
        report = dogfood_memoryendpoints.combine_reports(
            [
                {
                    "mode": "local_wsgi",
                    "ok": True,
                    "coreDogfoodWorkflowVerified": True,
                    "latestDogfoodContractVerified": True,
                    "localDogfoodVerified": True,
                    "liveDogfoodVerified": False,
                    "liveCoreDogfoodVerified": False,
                    "rawCredentialValuesStored": False,
                    "rawPrivatePayloadsStored": False,
                    "requiredStepFailureCount": 0,
                    "optionalStepFailureCount": 0,
                    "agentAuditAccessDenied": True,
                    "meetingMemoryPromotionVerified": True,
                    "meetingMemoryReadbackVerified": True,
                    "meetingMemorySourceReadbackVerified": True,
                }
            ]
        )

        self.assertTrue(report["ok"])
        self.assertTrue(report["localDogfoodVerified"])
        self.assertFalse(report["liveCoreDogfoodVerified"])
        self.assertTrue(report["latestDogfoodContractVerified"])
        self.assertTrue(report["localAgentAuditAccessDenied"])
        self.assertTrue(report["agentAuditAccessDenied"])
        self.assertTrue(report["meetingMemoryPromotionVerified"])
        self.assertTrue(report["meetingMemoryReadbackVerified"])
        self.assertTrue(report["meetingMemorySourceReadbackVerified"])
        self.assertFalse(report["rawCredentialValuesStored"])

    def test_combined_report_records_missing_live_agent_audit_denial(self):
        report = dogfood_memoryendpoints.combine_reports(
            [
                {
                    "mode": "live_http",
                    "ok": False,
                    "coreDogfoodWorkflowVerified": True,
                    "latestDogfoodContractVerified": False,
                    "localDogfoodVerified": False,
                    "liveDogfoodVerified": False,
                    "liveCoreDogfoodVerified": True,
                    "rawCredentialValuesStored": False,
                    "rawPrivatePayloadsStored": False,
                    "requiredStepFailureCount": 1,
                    "optionalStepFailureCount": 1,
                    "agentAuditAccessDenied": False,
                }
            ]
        )

        self.assertFalse(report["ok"])
        self.assertFalse(report["liveDogfoodVerified"])
        self.assertTrue(report["liveCoreDogfoodVerified"])
        self.assertFalse(report["latestDogfoodContractVerified"])
        self.assertFalse(report["liveAgentAuditAccessDenied"])
        self.assertFalse(report["agentAuditAccessDenied"])

    def test_restore_store_environment_removes_local_store_before_live(self):
        previous_path = os.environ.get("MEMORYENDPOINTS_STORE_PATH")
        previous_sqlite_path = os.environ.get("MEMORYENDPOINTS_SQLITE_PATH")
        previous_backend = os.environ.get("MEMORYENDPOINTS_STORE_BACKEND")
        try:
            os.environ["MEMORYENDPOINTS_STORE_PATH"] = "local-dogfood-store.json"
            os.environ["MEMORYENDPOINTS_SQLITE_PATH"] = "local-dogfood-store.sqlite3"
            os.environ["MEMORYENDPOINTS_STORE_BACKEND"] = "file"

            dogfood_memoryendpoints.restore_store_environment(None, None, None)

            self.assertNotIn("MEMORYENDPOINTS_STORE_PATH", os.environ)
            self.assertNotIn("MEMORYENDPOINTS_SQLITE_PATH", os.environ)
            self.assertNotIn("MEMORYENDPOINTS_STORE_BACKEND", os.environ)

            dogfood_memoryendpoints.restore_store_environment(
                "existing-store.json",
                "existing-store.sqlite3",
                "sqlite",
            )

            self.assertEqual("existing-store.json", os.environ["MEMORYENDPOINTS_STORE_PATH"])
            self.assertEqual("existing-store.sqlite3", os.environ["MEMORYENDPOINTS_SQLITE_PATH"])
            self.assertEqual("sqlite", os.environ["MEMORYENDPOINTS_STORE_BACKEND"])
        finally:
            dogfood_memoryendpoints.restore_store_environment(previous_path, previous_sqlite_path, previous_backend)

    def test_local_dogfood_forces_isolated_sqlite_backend(self):
        previous_path = os.environ.get("MEMORYENDPOINTS_STORE_PATH")
        previous_sqlite_path = os.environ.get("MEMORYENDPOINTS_SQLITE_PATH")
        previous_backend = os.environ.get("MEMORYENDPOINTS_STORE_BACKEND")
        try:
            os.environ["MEMORYENDPOINTS_STORE_PATH"] = "inherited-store.json"
            os.environ["MEMORYENDPOINTS_SQLITE_PATH"] = "inherited-store.sqlite3"
            os.environ["MEMORYENDPOINTS_STORE_BACKEND"] = "mysql"

            dogfood_memoryendpoints.configure_local_store_environment()

            self.assertNotIn("MEMORYENDPOINTS_STORE_PATH", os.environ)
            self.assertEqual(str(dogfood_memoryendpoints.DOGFOOD_SQLITE), os.environ["MEMORYENDPOINTS_SQLITE_PATH"])
            self.assertEqual("sqlite", os.environ["MEMORYENDPOINTS_STORE_BACKEND"])
        finally:
            dogfood_memoryendpoints.restore_store_environment(previous_path, previous_sqlite_path, previous_backend)


if __name__ == "__main__":
    unittest.main()
