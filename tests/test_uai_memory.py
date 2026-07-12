import io
import json
import os
import shutil
import sqlite3
import unittest
from pathlib import Path

from app import application
from memoryendpoints.uai_memory import VIRTUAL_UAI_STARTUP_ORDER


def call_app(path, method="GET", body=None, token="", query="", idempotency_key=""):
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "wsgi.input": io.BytesIO(raw),
        "CONTENT_LENGTH": str(len(raw)),
    }
    if token:
        environ["HTTP_AUTHORIZATION"] = "Bearer " + token
    if idempotency_key:
        environ["HTTP_IDEMPOTENCY_KEY"] = idempotency_key
    text = b"".join(application(environ, start_response)).decode("utf-8")
    return captured["status"], json.loads(text)


def uai_content(logical_path, suffix="", agent_id="browser-agent", agent_name="Browser Memory Agent"):
    label = logical_path.rsplit("/", 1)[-1]
    role_content = {
        ".uai/identity.uai": """Agent id: %s
Agent name: %s
Owner/steward: protected workspace owner
Declared profile: uaix.accountless-browser-memory.v1
Namespace: protected workspace and registered agent
Source authority: MemoryEndpoints protected package readback
Sensitivity boundary: public-safe operational memory only
Actor boundary: registered agent bound to the workspace bearer key""" % (agent_id, agent_name),
        ".uai/startup-packet.uai": """Required read order:
%s
First safe action: verify package readiness and stop if any required record is missing or invalid.""" % "\n".join(
            "- %s" % path for path in VIRTUAL_UAI_STARTUP_ORDER
        ),
        ".uai/progress.uai": """Completed work: accepted active-memory setup work only.
Remaining work: follow the current next action.
Verification evidence: protected package readback and connector test evidence.
Blockers: none recorded.""",
        ".uai/short-term-memory.uai": """Current working state: compact accepted context for the current browser-agent session.
Newest accepted decisions: use typed records and explicit review.
Active blockers: none recorded.
Next-read pointers: startup packet and protected durable-memory search.
Review status: current until superseded by a reviewed write.""",
        ".uai/long-term-memory.uai": """Stable id: memoryendpoints-protected-durable-memory
Path: https://memoryendpoints.com/
Label: MemoryEndpoints protected durable memory
Routing summary: Search reviewed company, workspace, and project memory through the authenticated connector.
Authority/source: protected MemoryEndpoints database records and source references
Review status: current until superseded by a reviewed pointer update
Review evidence: protected record readback and durable-memory verification""",
    }.get(logical_path, "")
    return """%s

Purpose:
- Preserve bounded active context for this logical role.
Verification status: active operational memory.
Memory scope: registered agent active context.
Public-safe status: safe for protected workspace storage.
Update route: protected virtual UAIX record route.
Source of truth: registered agent and protected package readback.
Next action for agents: load this record in startup order.
Must not expose: credentials, private keys, private prompts, or customer data.
%s
%s
""" % (label, role_content, suffix)


class UaiMemoryIntegrationTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / "var" / "test-store" / ("uai-%s-%s" % (os.getpid(), self._testMethodName))
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        os.environ["MEMORYENDPOINTS_STORE_PATH"] = str(root / "store.json")
        os.environ["MEMORYENDPOINTS_SQLITE_PATH"] = str(root / "store.sqlite3")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        os.environ.pop("MEMORYENDPOINTS_STORE_BACKEND", None)
        os.environ.pop("MEMORYENDPOINTS_STORE_PATH", None)
        os.environ.pop("MEMORYENDPOINTS_SQLITE_PATH", None)

    def setup_workspace(self, label):
        status, payload = call_app(
            "/api/matm/agent-setup/free-account",
            "POST",
            {"label": label, "companyLabel": label + " Company", "projectLabel": label + " Project"},
        )
        self.assertEqual("201 Created", status)
        return payload

    def register_agent(self, setup, agent_id, display_name=None):
        status, payload = call_app(
            "/api/matm/agents/register",
            "POST",
            {
                "workspaceId": setup["workspaceId"],
                "agentId": agent_id,
                "displayName": display_name or agent_id,
            },
            setup["apiKeySecret"],
            idempotency_key="register-%s" % agent_id,
        )
        self.assertEqual("201 Created", status)
        return payload

    def create_package(self, setup, agent_id):
        status, payload = call_app(
            "/api/matm/uai-memory/packages",
            "POST",
            {
                "workspaceId": setup["workspaceId"],
                "agentId": agent_id,
                "clientClass": "accountless_browser_ai",
                "localFilesystemAvailable": False,
            },
            setup["apiKeySecret"],
            idempotency_key="package-%s" % agent_id,
        )
        self.assertEqual("201 Created", status)
        return payload

    def test_public_contract_separates_virtual_exception_from_local_overlay(self):
        status, payload = call_app("/api/matm/uai-memory/contract")

        self.assertEqual("200 OK", status)
        contract = payload["data"]
        self.assertFalse(contract["exceptionBoundary"]["anonymousStorageAllowed"])
        self.assertTrue(contract["exceptionBoundary"]["registeredStableAgentRequired"])
        self.assertFalse(contract["exceptionBoundary"]["virtualLogicalPathsCreateLocalFiles"])
        self.assertFalse(contract["standardsPosture"]["uaixHostedImportClaimed"])
        self.assertFalse(contract["standardsPosture"]["uaixConformanceClaimed"])
        self.assertEqual(".uai/startup-packet.uai", contract["startupReadOrder"][0])
        self.assertIn(".uai/progress.uai", contract["startupReadOrder"])
        self.assertIn(".uai/short-term-memory.uai", contract["startupReadOrder"])
        overlay = contract["localCollaborationOverlay"]
        self.assertFalse(overlay["truthBoundary"]["localUaiContentsStored"])
        self.assertFalse(overlay["truthBoundary"]["automaticMerge"])
        self.assertEqual("best_effort_claim_plus_compare_and_swap", overlay["truthBoundary"]["conflictPrevention"])
        self.assertIn("short-term-memory.uai", overlay["forbiddenLocalFilenames"])

    def test_virtual_package_full_startup_revision_and_tenant_isolation_on_all_backends(self):
        for backend in ("file", "sqlite"):
            with self.subTest(backend=backend):
                os.environ["MEMORYENDPOINTS_STORE_BACKEND"] = backend
                backend_root = self.root / backend
                backend_root.mkdir(parents=True, exist_ok=True)
                os.environ["MEMORYENDPOINTS_STORE_PATH"] = str(backend_root / "store.json")
                os.environ["MEMORYENDPOINTS_SQLITE_PATH"] = str(backend_root / "store.sqlite3")
                owner = self.setup_workspace("Owner " + backend)
                outsider = self.setup_workspace("Outsider " + backend)
                self.register_agent(owner, "browser-agent", "Browser Memory Agent")

                status, rejected = call_app(
                    "/api/matm/uai-memory/packages",
                    "POST",
                    {
                        "workspaceId": owner["workspaceId"],
                        "agentId": "browser-agent",
                        "clientClass": "accountless_browser_ai",
                        "localFilesystemAvailable": True,
                    },
                    owner["apiKeySecret"],
                    idempotency_key="local-client-rejected-%s" % backend,
                )
                self.assertEqual("422 Unprocessable Entity", status)
                self.assertEqual("uai_exception_not_applicable", rejected["error"]["code"])

                package_payload = self.create_package(owner, "browser-agent")
                package_id = package_payload["canonicalPackageId"]
                self.assertEqual("setup_required", package_payload["package"]["status"])
                self.assertEqual("Browser Memory Agent", package_payload["package"]["agentName"])

                status, cross_tenant = call_app(
                    "/api/matm/uai-memory/packages",
                    token=outsider["apiKeySecret"],
                    query="workspace_id=%s&package_id=%s" % (outsider["workspaceId"], package_id),
                )
                self.assertEqual("200 OK", status)
                self.assertEqual([], cross_tenant["items"])

                invalid_date = uai_content(".uai/identity.uai", "Observed on 2026-07-11.")
                status, date_error = call_app(
                    "/api/matm/uai-memory/records",
                    "POST",
                    {
                        "workspaceId": owner["workspaceId"],
                        "agentId": "browser-agent",
                        "packageId": package_id,
                        "logicalPath": ".uai/identity.uai",
                        "content": invalid_date,
                    },
                    owner["apiKeySecret"],
                    idempotency_key="date-rejected-%s" % backend,
                )
                self.assertEqual("422 Unprocessable Entity", status)
                self.assertEqual("uai_content_must_be_date_free", date_error["error"]["code"])

                synthetic_secret_marker = "api_" + "key=" + "not-a-real-key-value"
                secret_content = uai_content(".uai/identity.uai", synthetic_secret_marker)
                status, secret_error = call_app(
                    "/api/matm/uai-memory/records",
                    "POST",
                    {
                        "workspaceId": owner["workspaceId"],
                        "agentId": "browser-agent",
                        "packageId": package_id,
                        "logicalPath": ".uai/identity.uai",
                        "content": secret_content,
                    },
                    owner["apiKeySecret"],
                    idempotency_key="secret-rejected-%s" % backend,
                )
                self.assertEqual("422 Unprocessable Entity", status)
                self.assertEqual("uai_content_rejected_by_memory_firewall", secret_error["error"]["code"])

                status, identity_error = call_app(
                    "/api/matm/uai-memory/records",
                    "POST",
                    {
                        "workspaceId": owner["workspaceId"],
                        "agentId": "browser-agent",
                        "packageId": package_id,
                        "logicalPath": ".uai/identity.uai",
                        "content": uai_content(".uai/identity.uai", agent_id="another-agent"),
                    },
                    owner["apiKeySecret"],
                    idempotency_key="identity-binding-rejected-%s" % backend,
                )
                self.assertEqual("422 Unprocessable Entity", status)
                self.assertEqual("uai_content_role_invalid", identity_error["error"]["code"])
                self.assertEqual(
                    ["Agent id:"],
                    identity_error["error"]["details"]["identityBindingMismatches"],
                )

                status, pointer_error = call_app(
                    "/api/matm/uai-memory/records",
                    "POST",
                    {
                        "workspaceId": owner["workspaceId"],
                        "agentId": "browser-agent",
                        "packageId": package_id,
                        "logicalPath": ".uai/long-term-memory.uai",
                        "content": uai_content(".uai/long-term-memory.uai").replace(
                            "Path: https://memoryendpoints.com/",
                            "Path: https://memoryendpoints.com/api/matm/search",
                        ),
                    },
                    owner["apiKeySecret"],
                    idempotency_key="pointer-path-rejected-%s" % backend,
                )
                self.assertEqual("422 Unprocessable Entity", status)
                self.assertEqual("uai_content_role_invalid", pointer_error["error"]["code"])
                self.assertTrue(pointer_error["error"]["details"]["durableHomePathRequired"])

                first_record = None
                for index, logical_path in enumerate(VIRTUAL_UAI_STARTUP_ORDER):
                    status, record_payload = call_app(
                        "/api/matm/uai-memory/records",
                        "POST",
                        {
                            "workspaceId": owner["workspaceId"],
                            "agentId": "browser-agent",
                            "packageId": package_id,
                            "logicalPath": logical_path,
                            "title": logical_path.rsplit("/", 1)[-1],
                            "content": uai_content(logical_path),
                        },
                        owner["apiKeySecret"],
                        idempotency_key="record-%s-%s" % (backend, index),
                    )
                    self.assertEqual("201 Created", status, logical_path)
                    self.assertTrue(record_payload["persisted"])
                    self.assertTrue(record_payload["visibleToSender"])
                    if logical_path == ".uai/identity.uai":
                        first_record = record_payload["record"]

                status, startup_payload = call_app(
                    "/api/matm/uai-memory/startup",
                    token=owner["apiKeySecret"],
                    query="workspace_id=%s&agent_id=browser-agent&package_id=%s" % (owner["workspaceId"], package_id),
                )
                self.assertEqual("200 OK", status)
                startup = startup_payload["startup"]
                self.assertTrue(startup["readyForStartup"])
                self.assertEqual([], startup["missingRequiredPaths"])
                self.assertEqual(list(VIRTUAL_UAI_STARTUP_ORDER), [item["logicalPath"] for item in startup["records"]])

                status, missing_expected = call_app(
                    "/api/matm/uai-memory/records",
                    "POST",
                    {
                        "workspaceId": owner["workspaceId"],
                        "agentId": "browser-agent",
                        "packageId": package_id,
                        "logicalPath": ".uai/identity.uai",
                        "title": "identity.uai",
                        "content": uai_content(".uai/identity.uai", "Refined identity guidance."),
                    },
                    owner["apiKeySecret"],
                    idempotency_key="missing-revision-%s" % backend,
                )
                self.assertEqual("422 Unprocessable Entity", status)
                self.assertEqual("expected_revision_required", missing_expected["error"]["code"])

                status, updated = call_app(
                    "/api/matm/uai-memory/records",
                    "POST",
                    {
                        "workspaceId": owner["workspaceId"],
                        "agentId": "browser-agent",
                        "packageId": package_id,
                        "logicalPath": ".uai/identity.uai",
                        "title": "identity.uai",
                        "content": uai_content(".uai/identity.uai", "Refined identity guidance."),
                        "expectedRevision": first_record["revision"],
                    },
                    owner["apiKeySecret"],
                    idempotency_key="update-revision-%s" % backend,
                )
                self.assertEqual("200 OK", status)
                self.assertEqual(2, updated["revision"])

                status, history = call_app(
                    "/api/matm/uai-memory/records",
                    token=owner["apiKeySecret"],
                    query=(
                        "workspace_id=%s&agent_id=browser-agent&package_id=%s&record_id=%s&include_history=true"
                        % (owner["workspaceId"], package_id, first_record["recordId"])
                    ),
                )
                self.assertEqual("200 OK", status)
                self.assertEqual([1, 2], [item["revision"] for item in history["revisions"]])

                status, _ = call_app(
                    "/api/matm/agents/register",
                    "POST",
                    {
                        "workspaceId": owner["workspaceId"],
                        "agentId": "browser-agent",
                        "displayName": "Renamed Browser Memory Agent",
                    },
                    owner["apiKeySecret"],
                    idempotency_key="rename-browser-agent-%s" % backend,
                )
                self.assertEqual("201 Created", status)
                status, renamed_startup = call_app(
                    "/api/matm/uai-memory/startup",
                    token=owner["apiKeySecret"],
                    query="workspace_id=%s&agent_id=browser-agent&package_id=%s" % (owner["workspaceId"], package_id),
                )
                self.assertEqual("200 OK", status)
                self.assertFalse(renamed_startup["startup"]["readyForStartup"])
                self.assertEqual(
                    [".uai/identity.uai"],
                    renamed_startup["startup"]["invalidRequiredPaths"],
                )

                store_path = Path(os.environ["MEMORYENDPOINTS_STORE_PATH"] if backend == "file" else os.environ["MEMORYENDPOINTS_SQLITE_PATH"])
                self.assertNotIn(owner["apiKeySecret"].encode("utf-8"), store_path.read_bytes())

    def test_hash_only_edit_claims_prevent_overlap_and_stale_completion(self):
        os.environ["MEMORYENDPOINTS_STORE_BACKEND"] = "sqlite"
        setup = self.setup_workspace("Collaboration")
        self.register_agent(setup, "agent-a", "Agent A")
        self.register_agent(setup, "agent-b", "Agent B")
        token = setup["apiKeySecret"]
        base_hash = "a" * 64
        next_hash = "b" * 64

        status, acquired = call_app(
            "/api/matm/uai-memory/edit-claims",
            "POST",
            {
                "workspaceId": setup["workspaceId"],
                "projectId": setup["projectId"],
                "agentId": "agent-a",
                "logicalPath": ".uai/context.uai",
                "baseContentHash": "sha256:" + base_hash,
                "intentSummary": "Update local routing context before the next handoff.",
                "leaseSeconds": 600,
            },
            token,
            idempotency_key="claim-a",
        )
        self.assertEqual("201 Created", status)
        self.assertTrue(acquired["claimAcquired"])
        self.assertTrue(acquired["persisted"])
        self.assertTrue(acquired["visibleToSender"])
        self.assertFalse(acquired["localContentStored"])
        self.assertIn("scope=project", acquired["projectMeetingRoomQueryUrl"])

        status, conflict = call_app(
            "/api/matm/uai-memory/edit-claims",
            "POST",
            {
                "workspaceId": setup["workspaceId"],
                "projectId": setup["projectId"],
                "agentId": "agent-b",
                "logicalPath": ".uai/context.uai",
                "baseContentHash": base_hash,
                "intentSummary": "Edit the same local context file for another change.",
            },
            token,
            idempotency_key="claim-b-conflict",
        )
        self.assertEqual("409 Conflict", status)
        self.assertEqual("uai_edit_claim_conflict", conflict["error"]["code"])
        self.assertEqual("agent-a", conflict["error"]["details"]["activeClaim"]["agentId"])
        self.assertNotIn("content", conflict["error"]["details"]["activeClaim"])
        self.assertNotIn("content", conflict["error"]["details"]["head"])

        status, forbidden = call_app(
            "/api/matm/uai-memory/edit-claims",
            "POST",
            {
                "workspaceId": setup["workspaceId"],
                "projectId": setup["projectId"],
                "agentId": "agent-b",
                "logicalPath": ".uai/short-term-memory.uai",
                "baseContentHash": base_hash,
                "intentSummary": "Try a locally forbidden aggregate file.",
            },
            token,
            idempotency_key="claim-forbidden",
        )
        self.assertEqual("422 Unprocessable Entity", status)
        self.assertEqual("unsupported_local_uai_path", forbidden["error"]["code"])

        status, completed = call_app(
            "/api/matm/uai-memory/edit-claims/complete",
            "POST",
            {
                "workspaceId": setup["workspaceId"],
                "agentId": "agent-a",
                "claimId": acquired["canonicalClaimId"],
                "newContentHash": next_hash,
                "completionSummary": "Completed the local context edit and verified the resulting hash.",
            },
            token,
            idempotency_key="claim-a-complete",
        )
        self.assertEqual("200 OK", status)
        self.assertTrue(completed["persisted"])
        self.assertTrue(completed["visibleToSender"])
        self.assertEqual(1, completed["headRevision"])
        self.assertEqual("sha256:" + next_hash, completed["head"]["observedContentHash"])
        self.assertFalse(completed["head"]["localContentStored"])

        status, stale = call_app(
            "/api/matm/uai-memory/edit-claims",
            "POST",
            {
                "workspaceId": setup["workspaceId"],
                "projectId": setup["projectId"],
                "agentId": "agent-b",
                "logicalPath": ".uai/context.uai",
                "baseContentHash": base_hash,
                "intentSummary": "Attempt an edit from a stale local copy.",
            },
            token,
            idempotency_key="claim-b-stale",
        )
        self.assertEqual("409 Conflict", status)
        self.assertEqual("uai_base_hash_mismatch", stale["error"]["code"])
        self.assertEqual("sha256:" + next_hash, stale["error"]["details"]["currentContentHash"])

        status, heads = call_app(
            "/api/matm/uai-memory/file-heads",
            token=token,
            query="workspace_id=%s&project_id=%s&logical_path=.uai/context.uai" % (setup["workspaceId"], setup["projectId"]),
        )
        self.assertEqual("200 OK", status)
        self.assertEqual(1, heads["count"])
        self.assertFalse(heads["items"][0]["localContentStored"])

    def test_sqlite_schema_has_virtual_package_and_collaboration_tables(self):
        os.environ["MEMORYENDPOINTS_STORE_BACKEND"] = "sqlite"
        setup = self.setup_workspace("Schema")
        self.register_agent(setup, "schema-agent")
        self.create_package(setup, "schema-agent")

        with sqlite3.connect(os.environ["MEMORYENDPOINTS_SQLITE_PATH"]) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

        self.assertTrue(
            {
                "matm_uai_packages",
                "matm_uai_records",
                "matm_uai_record_revisions",
                "matm_uai_collaboration_heads",
                "matm_uai_edit_claims",
            }.issubset(tables)
        )


if __name__ == "__main__":
    unittest.main()
