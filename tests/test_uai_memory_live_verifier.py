import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_uai_memory_live.py"
SPEC = importlib.util.spec_from_file_location("verify_uai_memory_live", SCRIPT)
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


class UaiMemoryLiveVerifierTests(unittest.TestCase):
    def test_protected_verifier_exercises_both_modes_without_leaking_auth(self):
        workspace_id = "workspace-private-verifier"
        workspace_key = "workspace-key-private-verifier-value"
        agent_id = "tinyrustlm-agent"
        project_id = "project-private-verifier"
        package_id = "uaipkg-private-verifier"
        claim_id = "uaiclaim-private-verifier"
        calls = []

        def fake_request(base_url, path, method="GET", token="", body=None, query=None, idempotency_key=""):
            calls.append({"path": path, "method": method, "token": token, "body": body, "query": query, "idempotencyKey": idempotency_key})
            if path == "/api/matm/uai-memory/contract":
                return 200, {
                    "ok": True,
                    "data": {
                        "profile": "uaix.accountless-browser-memory.v1",
                        "durableHomePath": "https://memoryendpoints.com",
                        "startupReadOrder": [".uai/startup-packet.uai", ".uai/progress.uai"],
                        "standardsPosture": {
                            "uaixHostedImportClaimed": False,
                            "uaixConformanceClaimed": False,
                        },
                        "exceptionBoundary": {"anonymousStorageAllowed": False},
                        "localCollaborationOverlay": {
                            "truthBoundary": {"localUaiContentsStored": False, "automaticMerge": False},
                            "confirmationFields": ["persisted", "visibleToSender"],
                        },
                    },
                }
            if path == "/api/matm/agents/register":
                return 201, {"ok": True}
            if path == "/api/matm/uai-memory/packages":
                return 201, {
                    "ok": True,
                    "persisted": True,
                    "visibleToSender": True,
                    "created": True,
                    "canonicalPackageId": package_id,
                    "package": {"packageId": package_id, "status": "setup_required", "readyForStartup": False},
                }
            if path == "/api/matm/workspace":
                return 200, {"ok": True, "workspace": {"primaryProjectId": project_id}}
            if path == "/api/matm/uai-memory/file-heads":
                return 200, {"ok": True, "items": [], "localContentStored": False}
            if path == "/api/matm/uai-memory/edit-claims":
                return 201, {
                    "ok": True,
                    "persisted": True,
                    "visibleToSender": True,
                    "claimAcquired": True,
                    "localContentStored": False,
                    "canonicalClaimId": claim_id,
                    "claim": {"claimId": claim_id},
                }
            if path == "/api/matm/uai-memory/edit-claims/release":
                return 200, {
                    "ok": True,
                    "persisted": True,
                    "visibleToSender": True,
                    "localContentStored": False,
                    "headRevision": 0,
                    "claim": {"status": "released"},
                }
            raise AssertionError(path)

        original_request = VERIFIER.request_json
        VERIFIER.request_json = fake_request
        try:
            with tempfile.TemporaryDirectory() as tmp:
                auth_path = Path(tmp) / "auth.json"
                report_path = Path(tmp) / "report.json"
                auth_path.write_text(
                    json.dumps(
                        {
                            "baseUrl": "https://memoryendpoints.example",
                            "workspaceId": workspace_id,
                            "workspaceKey": workspace_key,
                            "agentId": agent_id,
                        }
                    ),
                    encoding="utf-8",
                )

                exit_code = VERIFIER.main(["--auth-file", str(auth_path), "--json-out", str(report_path)])
                report_text = report_path.read_text(encoding="utf-8")
                report = json.loads(report_text)
        finally:
            VERIFIER.request_json = original_request

        self.assertEqual(0, exit_code)
        self.assertTrue(report["ok"])
        self.assertNotIn(workspace_id, report_text)
        self.assertNotIn(workspace_key, report_text)
        self.assertNotIn(agent_id, report_text)
        self.assertNotIn(project_id, report_text)
        self.assertNotIn(package_id, report_text)
        self.assertNotIn(claim_id, report_text)
        self.assertTrue(all(call["token"] in ("", workspace_key) for call in calls))
        self.assertEqual(
            {
                "/api/matm/uai-memory/contract",
                "/api/matm/agents/register",
                "/api/matm/uai-memory/packages",
                "/api/matm/workspace",
                "/api/matm/uai-memory/file-heads",
                "/api/matm/uai-memory/edit-claims",
                "/api/matm/uai-memory/edit-claims/release",
            },
            {call["path"] for call in calls},
        )


if __name__ == "__main__":
    unittest.main()
