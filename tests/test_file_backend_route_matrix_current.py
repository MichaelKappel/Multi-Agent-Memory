"""Current protected-route parity checks against the hermetic FileStore backend."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from app import application
from memoryendpoints.storage import FileStore, SQLiteStore
from memoryendpoints.uai_memory import VIRTUAL_UAI_STARTUP_ORDER
from tests.test_uai_memory import uai_content


class FileBackendRouteMatrixCurrentTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="matm-file-routes-")
        root = Path(self.tempdir.name)
        self.previous = {
            key: os.environ.get(key)
            for key in (
                "MEMORYENDPOINTS_STORE_BACKEND",
                "MEMORYENDPOINTS_STORE_PATH",
                "MEMORYENDPOINTS_SQLITE_PATH",
                "MEMORYENDPOINTS_CREDENTIAL_PEPPER",
                "MEMORYENDPOINTS_MYSQL_CONFIG_PATH",
            )
        }
        os.environ["MEMORYENDPOINTS_STORE_BACKEND"] = "file"
        os.environ["MEMORYENDPOINTS_STORE_PATH"] = str(root / "store.json")
        os.environ["MEMORYENDPOINTS_SQLITE_PATH"] = str(root / "unused.sqlite3")
        os.environ["MEMORYENDPOINTS_MYSQL_CONFIG_PATH"] = str(root / "missing-mysql.json")
        os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = "synthetic-file-route-pepper-" + ("x" * 48)
        self.store = FileStore(root / "store.json")
        setup = self.store.create_free_account(
            "File Route Workspace", "File Route Company", "File Route Project"
        )
        self.workspace_id = setup[0]
        self.company_id = setup[4]
        self.project_id = setup[5]
        self.master_secret = setup[2]
        self.agent_id = "file-route-agent"
        self.store.register_agent(self.workspace_id, self.agent_id, "File Route Agent")
        request = self.store.request_agent_access(
            self.company_id, self.agent_id, "workspace", self.workspace_id
        )
        self.store.decide_agent_access_request(
            self.master_secret, request["request"]["requestId"], "approved"
        )
        invite = self.store.issue_agent_invite(
            self.master_secret, request["request"]["requestId"]
        )
        self.agent_secret = (
            "me_agent_v1.agenttoken-" + ("a" * 20) + "." + ("b" * 43)
        )
        redeemed = self.store.redeem_agent_invite(
            {
                "schemaVersion": "memoryendpoints.agent_invite_redemption.v1",
                "inviteSecret": invite["inviteSecret"],
                "candidateAgentTokenSecret": self.agent_secret,
            },
            "route-agent-redeem",
        )
        if not redeemed.get("ok"):
            raise AssertionError(redeemed)

    def tearDown(self):
        self.tempdir.cleanup()
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def call(
        self,
        path,
        method="GET",
        body=None,
        query="",
        suffix="x",
        token=None,
        raw_body=None,
        idempotency_key=None,
    ):
        raw = (
            raw_body
            if raw_body is not None
            else b"" if body is None else json.dumps(body).encode("utf-8")
        )
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": query or "workspace_id=" + self.workspace_id,
            "CONTENT_LENGTH": str(len(raw)),
            "CONTENT_TYPE": "application/json" if body is not None or raw_body is not None else "",
            "HTTP_AUTHORIZATION": "Bearer " + (token or self.master_secret),
            "REMOTE_ADDR": "127.0.0.1",
            "wsgi.input": io.BytesIO(raw),
        }
        if idempotency_key is not False:
            environ["HTTP_IDEMPOTENCY_KEY"] = idempotency_key or "file-route-" + suffix
        payload = b"".join(application(environ, start_response)).decode("utf-8")
        self.assertIn("status", captured)
        decoded = json.loads(payload) if payload else {}
        self.assertIsInstance(decoded, dict)
        self.assertIn("valuesRedacted", decoded)
        return captured["status"], decoded

    def test_file_backend_request_parser_and_scope_edges_remain_safe(self):
        status, payload = self.call(
            "/api/matm/projects",
            method="POST",
            raw_body=b"{not-json",
            suffix="invalid-json",
        )
        self.assertTrue(status.startswith("400"), (status, payload))
        self.assertEqual("invalid_json", payload["error"]["code"])

        status, payload = self.call(
            "/api/matm/projects",
            method="POST",
            body={"workspaceId": 7, "label": "invalid workspace type"},
            suffix="invalid-workspace-type-current",
        )
        self.assertTrue(status.startswith("4"), (status, payload))
        self.assertEqual("insufficient_scope", payload["error"]["code"])

        status, payload = self.call(
            "/api/matm/projects",
            method="POST",
            body={"workspaceId": self.workspace_id, "label": "missing key"},
            suffix="missing-idempotency-current",
            idempotency_key=False,
        )
        self.assertTrue(status.startswith("4"), (status, payload))
        self.assertEqual("idempotency_key_required", payload["error"]["code"])

        status, payload = self.call(
            "/api/matm/workspace",
            token="me_agent_v1.invalid.invalid",
            query="workspace_id=" + self.workspace_id,
            suffix="invalid-token-current",
        )
        self.assertTrue(status.startswith("401"), (status, payload))
        self.assertEqual("auth_required", payload["error"]["code"])

        status, payload = self.call(
            "/api/matm/workspace",
            query="workspace_id=other-workspace-current",
            suffix="wrong-workspace-current",
        )
        self.assertTrue(status.startswith("403"), (status, payload))
        self.assertEqual("insufficient_scope", payload["error"]["code"])

    def test_file_backend_protected_reads_share_the_current_route_contract(self):
        routes = (
            "/api/matm/workspace",
            "/api/matm/projects",
            "/api/matm/external-links",
            "/api/matm/internet-search",
            "/api/matm/knowledge-tree",
            "/api/matm/knowledge-documents",
            "/api/matm/sync/retention",
            "/api/matm/sync/receipts",
            "/api/matm/sync/changes",
            "/api/matm/sync/heads",
            "/api/matm/uai-memory/packages",
            "/api/matm/uai-memory/records",
            "/api/matm/uai-memory/startup",
            "/api/matm/uai-memory/file-heads",
            "/api/matm/uai-memory/edit-claims",
            "/api/matm/review-queue",
            "/api/matm/memory-events",
            "/api/matm/search",
            "/api/matm/routing-decisions",
            "/api/matm/meeting-rooms",
            "/api/matm/meeting-messages",
            "/api/matm/agent-inbox",
            "/api/matm/current-message",
            "/api/matm/receipts",
            "/api/matm/audit-log",
        )
        for index, route in enumerate(routes):
            with self.subTest(route=route):
                status, payload = self.call(route, query="workspace_id=" + self.workspace_id, suffix="read-%d" % index)
                self.assertNotEqual("500 Internal Server Error", status, payload)
                self.assertFalse(payload.get("rawCredentialExposed", True))
                self.assertFalse(payload.get("rawPayloadExposed", True))

    def test_file_backend_invalid_writes_reach_each_current_validation_boundary(self):
        routes = (
            "/api/matm/projects",
            "/api/matm/external-links",
            "/api/matm/knowledge-documents",
            "/api/matm/agents/register",
            "/api/matm/sync/mutations",
            "/api/matm/uai-memory/packages",
            "/api/matm/uai-memory/records",
            "/api/matm/uai-memory/edit-claims",
            "/api/matm/uai-memory/edit-claims/heartbeat",
            "/api/matm/uai-memory/edit-claims/complete",
            "/api/matm/uai-memory/edit-claims/release",
            "/api/matm/memory-events/submit",
            "/api/matm/review-queue/decide",
            "/api/matm/routing-decisions",
            "/api/matm/meeting-rooms",
            "/api/matm/meeting-messages",
            "/api/matm/meeting-rooms/read",
            "/api/matm/agent-messages",
            "/api/matm/notifications/ack",
        )
        for index, route in enumerate(routes):
            with self.subTest(route=route):
                status, payload = self.call(route, method="POST", body={}, suffix="write-%d" % index)
                self.assertNotEqual("500 Internal Server Error", status, payload)
                self.assertFalse(payload.get("rawCredentialExposed", True))
        status, payload = self.call(
            "/api/matm/projects",
            method="POST",
            body={"workspaceId": 7},
            suffix="invalid-workspace-type",
        )
        self.assertTrue(status.startswith("4"), (status, payload))
        self.assertFalse(payload.get("rawCredentialExposed", True))

    def test_same_protected_read_matrix_runs_against_sqlite_backend(self):
        root = Path(self.tempdir.name)
        os.environ["MEMORYENDPOINTS_STORE_BACKEND"] = "sqlite"
        setup = SQLiteStore(root / "sqlite-store.sqlite3").create_free_account(
            "SQLite Route Workspace", "SQLite Route Company", "SQLite Route Project"
        )
        self.workspace_id = setup[0]
        self.master_secret = setup[2]
        for index, route in enumerate(
            (
                "/api/matm/workspace",
                "/api/matm/projects",
                "/api/matm/external-links",
                "/api/matm/knowledge-tree",
                "/api/matm/knowledge-documents",
                "/api/matm/sync/retention",
                "/api/matm/sync/changes",
                "/api/matm/sync/heads",
                "/api/matm/uai-memory/packages",
                "/api/matm/uai-memory/records",
                "/api/matm/uai-memory/startup",
                "/api/matm/uai-memory/file-heads",
                "/api/matm/uai-memory/edit-claims",
                "/api/matm/review-queue",
                "/api/matm/memory-events",
                "/api/matm/search",
                "/api/matm/routing-decisions",
                "/api/matm/meeting-rooms",
                "/api/matm/meeting-messages",
                "/api/matm/agent-inbox",
                "/api/matm/current-message",
                "/api/matm/receipts",
                "/api/matm/audit-log",
            )
        ):
            with self.subTest(route=route):
                status, payload = self.call(route, query="workspace_id=" + self.workspace_id, suffix="sqlite-%d" % index)
                self.assertNotEqual("500 Internal Server Error", status, payload)
                self.assertFalse(payload.get("rawCredentialExposed", True))

    def test_file_backend_current_mutations_persist_and_replay_safely(self):
        status, project_payload = self.call(
            "/api/matm/projects",
            method="POST",
            body={"workspaceId": self.workspace_id, "label": "Route Matrix Project"},
            suffix="project-upsert",
        )
        self.assertEqual("201 Created", status, project_payload)
        self.assertTrue(project_payload["persisted"])
        replay_status, replay_payload = self.call(
            "/api/matm/projects",
            method="POST",
            body={"workspaceId": self.workspace_id, "label": "Route Matrix Project"},
            suffix="project-upsert",
        )
        self.assertEqual("201 Created", replay_status, replay_payload)
        self.assertTrue(replay_payload.get("idempotentReplay"))
        status, document_payload = self.call(
            "/api/matm/knowledge-documents",
            method="POST",
            body={
                "workspaceId": self.workspace_id,
                "scope": "project",
                "scopeId": self.project_id,
                "projectId": self.project_id,
                "title": "Route Matrix Knowledge",
                "content": "A current route matrix knowledge record.",
                "description": "A current route matrix knowledge record.",
                "category": "operations",
                "keywords": ["route", "matrix"],
                "taxonomyPaths": [["Operations", "Routes"]],
            },
            suffix="knowledge-upsert",
        )
        self.assertEqual("201 Created", status, document_payload)
        document = document_payload["document"]
        status, link_payload = self.call(
            "/api/matm/external-links",
            method="POST",
            body={
                "workspaceId": self.workspace_id,
                "url": "https://example.com/route-matrix",
                "siteName": "Example Matrix",
                "pageTitle": "Route Matrix Reference",
                "description": "A reviewed route matrix reference.",
                "keywords": ["route", "matrix"],
                "knowledgeDocumentId": document["searchDocumentId"],
                "contextDescription": "This page supports the current route matrix.",
                "relationshipType": "reference",
                "reviewStatus": "reviewed",
            },
            suffix="link-upsert",
        )
        self.assertEqual("201 Created", status, link_payload)
        self.assertTrue(link_payload["confirmation"]["persisted"])
        status, device_payload = self.call(
            "/api/matm/sync/devices",
            method="POST",
            body={"workspaceId": self.workspace_id, "deviceId": "route-device", "label": "Route Device"},
            suffix="device-register",
        )
        self.assertEqual("201 Created", status, device_payload)
        self.assertEqual(1, device_payload["device"]["authorityEpoch"])
        status, rotated = self.call(
            "/api/matm/sync/devices/rotate",
            method="POST",
            body={"workspaceId": self.workspace_id, "deviceId": "route-device"},
            suffix="device-rotate",
        )
        self.assertEqual("200 OK", status, rotated)
        self.assertEqual(2, rotated["device"]["authorityEpoch"])
        status, revoked = self.call(
            "/api/matm/sync/devices/revoke",
            method="POST",
            body={"workspaceId": self.workspace_id, "deviceId": "route-device"},
            suffix="device-revoke",
        )
        self.assertEqual("200 OK", status, revoked)
        self.assertEqual("revoked", revoked["device"]["status"])
        status, mutation = self.call(
            "/api/matm/sync/mutations",
            method="POST",
            body={
                "workspaceId": self.workspace_id,
                "scope": "workspace",
                "operation": "upsert",
                "summary": "Route matrix sync mutation",
            },
            suffix="sync-mutation",
        )
        self.assertIn(status, ("200 OK", "201 Created", "202 Accepted"), mutation)
        self.assertTrue(mutation.get("confirmation", {}).get("persisted"))

    def test_file_backend_uai_routes_cover_package_record_and_edit_claim_lifecycle(self):
        status, package_payload = self.call(
            "/api/matm/uai-memory/packages",
            method="POST",
            body={
                "workspaceId": self.workspace_id,
                "agentId": self.agent_id,
                "clientClass": "accountless_browser_ai",
                "localFilesystemAvailable": False,
            },
            suffix="uai-package",
            token=self.agent_secret,
        )
        self.assertEqual("201 Created", status, package_payload)
        package_id = package_payload["package"]["packageId"]
        package_agent_name = package_payload["package"].get("agentName") or "File Route Agent"
        status, record_payload = self.call(
            "/api/matm/uai-memory/records",
            method="POST",
            body={
                "workspaceId": self.workspace_id,
                "agentId": self.agent_id,
                "packageId": package_id,
                "logicalPath": ".uai/identity.uai",
                "title": "Route identity",
                "content": uai_content(
                    ".uai/identity.uai",
                    agent_id=self.agent_id,
                    agent_name=package_agent_name,
                ),
            },
            suffix="uai-record",
            token=self.agent_secret,
        )
        self.assertEqual("201 Created", status, record_payload)
        for index, logical_path in enumerate(
            (path for path in VIRTUAL_UAI_STARTUP_ORDER if path != ".uai/identity.uai"),
            start=1,
        ):
            status, startup_record = self.call(
                "/api/matm/uai-memory/records",
                method="POST",
                body={
                    "workspaceId": self.workspace_id,
                    "agentId": self.agent_id,
                    "packageId": package_id,
                    "logicalPath": logical_path,
                    "title": logical_path.rsplit("/", 1)[-1],
                    "content": uai_content(
                        logical_path,
                        agent_id=self.agent_id,
                        agent_name=package_agent_name,
                    ),
                },
                suffix="uai-record-%d" % index,
                token=self.agent_secret,
            )
            self.assertEqual("201 Created", status, startup_record)
        status, records = self.call(
            "/api/matm/uai-memory/records",
            query="workspace_id=%s&agent_id=%s&package_id=%s&include_history=1"
            % (self.workspace_id, self.agent_id, package_id),
            suffix="uai-record-read",
            token=self.agent_secret,
        )
        self.assertEqual("200 OK", status, records)
        self.assertEqual(len(VIRTUAL_UAI_STARTUP_ORDER), records["count"])
        status, startup = self.call(
            "/api/matm/uai-memory/startup",
            query="workspace_id=%s&agent_id=%s&package_id=%s"
            % (self.workspace_id, self.agent_id, package_id),
            suffix="uai-startup",
            token=self.agent_secret,
        )
        self.assertEqual("200 OK", status, startup)
        self.assertTrue(startup["startup"]["readyForStartup"])
        status, claim_payload = self.call(
            "/api/matm/uai-memory/edit-claims",
            method="POST",
            body={
                "workspaceId": self.workspace_id,
                "projectId": self.project_id,
                "agentId": self.agent_id,
                "logicalPath": ".uai/identity.uai",
                "baseContentHash": "a" * 64,
                "intentSummary": "Route edit claim",
                "leaseSeconds": 60,
            },
            suffix="uai-claim",
            token=self.agent_secret,
        )
        self.assertEqual("201 Created", status, claim_payload)
        claim_id = claim_payload["claim"]["claimId"]
        for operation, body in (
            ("heartbeat", {"leaseSeconds": 120}),
            ("complete", {"newContentHash": "b" * 64, "completionSummary": "Done"}),
        ):
            status, changed = self.call(
                "/api/matm/uai-memory/edit-claims/" + operation,
                method="POST",
                body=dict(body, workspaceId=self.workspace_id, agentId=self.agent_id, claimId=claim_id),
                suffix="uai-claim-" + operation,
                token=self.agent_secret,
            )
            self.assertEqual("200 OK", status, changed)
            self.assertEqual(operation, changed["operation"])


if __name__ == "__main__":
    unittest.main()
