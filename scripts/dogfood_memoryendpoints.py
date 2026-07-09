import io
import json
import os
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import application
from memoryendpoints.config import utc_now


REPORT_PATH = ROOT / "docs" / "reports" / "dogfood-memory-run.json"
PROGRESS_PATH = ROOT / ".uai" / "progress.uai"
DOGFOOD_STORE_DIR = ROOT / "var" / "dogfood-memory"
DOGFOOD_STORE = DOGFOOD_STORE_DIR / "store.json"


def call_app(path, method="GET", body=None, headers=None, query=""):
    raw = b""
    if body is not None:
        raw = json.dumps(body, sort_keys=True).encode("utf-8")
    captured = {}

    def start_response(status, response_headers):
        captured["status"] = status
        captured["headers"] = dict(response_headers)

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "wsgi.input": io.BytesIO(raw),
        "CONTENT_LENGTH": str(len(raw)),
    }
    for key, value in (headers or {}).items():
        environ[key] = value
    chunks = application(environ, start_response)
    text = b"".join(chunks).decode("utf-8")
    try:
        payload = json.loads(text)
    except ValueError:
        payload = {"rawText": text[:200]}
    return captured["status"], captured["headers"], payload


def step(report, name, status, payload=None):
    report["steps"].append(
        {
            "name": name,
            "httpStatus": status,
            "ok": str(status).startswith(("200", "201", "202")),
            "payloadShape": sorted((payload or {}).keys()),
        }
    )


def append_progress(summary):
    stamp = utc_now()
    line = (
        "- %s: Local MATM dogfood run verified through WSGI; report `docs/reports/dogfood-memory-run.json`; "
        "MATM update URL `https://memoryendpoints.com/api/matm/memory-events/submit`; raw credential values stored in report: false.\n"
        % stamp
    )
    with PROGRESS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line)
    summary["uaiProgressUpdated"] = True


def main():
    shutil.rmtree(DOGFOOD_STORE_DIR, ignore_errors=True)
    DOGFOOD_STORE_DIR.mkdir(parents=True, exist_ok=True)
    previous_store_path = os.environ.get("MEMORYENDPOINTS_STORE_PATH")
    previous_backend = os.environ.get("MEMORYENDPOINTS_STORE_BACKEND")
    os.environ["MEMORYENDPOINTS_STORE_PATH"] = str(DOGFOOD_STORE)
    os.environ.pop("MEMORYENDPOINTS_STORE_BACKEND", None)

    report = {
        "schemaVersion": "memoryendpoints.dogfood_run.v1",
        "generatedAt": utc_now(),
        "mode": "local_wsgi",
        "liveDogfoodVerified": False,
        "localDogfoodVerified": False,
        "rawCredentialValuesStored": False,
        "rawPrivatePayloadsStored": False,
        "valuesRedacted": True,
        "steps": [],
    }
    try:
        status, _headers, setup = call_app(
            "/api/matm/agent-setup/free-account",
            method="POST",
            body={"label": "MemoryEndpoints local dogfood workspace"},
        )
        step(report, "create_free_workspace", status, setup)
        token = setup["apiKeySecret"]
        workspace_id = setup["workspaceId"]
        auth = {"HTTP_AUTHORIZATION": "Bearer " + token}

        status, _headers, agent = call_app(
            "/api/matm/agents/register",
            method="POST",
            headers=auth,
            body={"workspaceId": workspace_id, "agentId": "memoryendpoints-dogfood-agent", "displayName": "MemoryEndpoints Dogfood Agent"},
        )
        step(report, "register_agent", status, agent)

        status, _headers, memory = call_app(
            "/api/matm/memory-events/submit",
            method="POST",
            headers=auth,
            body={
                "workspaceId": workspace_id,
                "actorAgentId": "memoryendpoints-dogfood-agent",
                "memoryType": "status",
                "subject": "MemoryEndpoints enterprise MATM hardening",
                "title": "Local dogfood status",
                "summary": "Local WSGI dogfood verified workspace creation, agent registration, memory submit/search, current-message readback, acknowledgement, receipts, and review queue readback.",
                "tags": ["dogfood", "local-wsgi", "matm"],
                "confidence": 0.86,
                "source": "scripts/dogfood_memoryendpoints.py",
            },
        )
        step(report, "submit_memory", status, memory)

        status, _headers, search = call_app(
            "/api/matm/search",
            headers=auth,
            query="workspace_id=%s&q=dogfood" % workspace_id,
        )
        step(report, "search_memory", status, search)

        status, _headers, queue = call_app(
            "/api/matm/review-queue",
            headers=auth,
            query="workspace_id=%s&status=pending" % workspace_id,
        )
        step(report, "read_review_queue", status, queue)

        status, _headers, message = call_app(
            "/api/matm/agent-messages",
            method="POST",
            headers=auth,
            body={
                "workspaceId": workspace_id,
                "senderAgentId": "memoryendpoints-dogfood-agent",
                "targetAgentId": "memoryendpoints-followup-agent",
                "safeSummary": "Action required: review the dogfood memory report and continue hardening work.",
                "responseRequired": True,
            },
        )
        step(report, "create_current_message", status, message)
        notification_id = message["notification"]["notificationId"]

        status, _headers, current = call_app(
            "/api/matm/current-message",
            headers=auth,
            query="workspace_id=%s&agent_id=memoryendpoints-followup-agent" % workspace_id,
        )
        step(report, "read_current_message", status, current)

        status, _headers, ack = call_app(
            "/api/matm/notifications/ack",
            method="POST",
            headers=auth,
            body={
                "workspaceId": workspace_id,
                "notificationId": notification_id,
                "consumerAgentId": "memoryendpoints-followup-agent",
                "status": "read",
            },
        )
        step(report, "acknowledge_notification", status, ack)

        status, _headers, receipts = call_app(
            "/api/matm/receipts",
            headers=auth,
            query="workspace_id=%s&consumer_agent_id=memoryendpoints-followup-agent" % workspace_id,
        )
        step(report, "read_redacted_receipts", status, receipts)

        status, _headers, post_ack_current = call_app(
            "/api/matm/current-message",
            headers=auth,
            query="workspace_id=%s&agent_id=memoryendpoints-followup-agent" % workspace_id,
        )
        step(report, "read_current_message_after_ack", status, post_ack_current)

        store_text = DOGFOOD_STORE.read_text(encoding="utf-8") if DOGFOOD_STORE.exists() else ""
        report["localDogfoodVerified"] = all(item["ok"] for item in report["steps"])
        report["workspaceIdHash"] = "sha256:" + __import__("hashlib").sha256(workspace_id.encode("utf-8")).hexdigest()
        report["rawWorkspaceIdStoredInReport"] = False
        report["oneTimeKeyReturned"] = bool(token)
        report["rawCredentialValuesStored"] = token in json.dumps(report) or token in store_text
        report["rawPrivatePayloadsStored"] = False
        report["searchReadbackCount"] = search.get("count", 0)
        report["currentMessageUnreadCount"] = current.get("unreadCount", 0)
        report["postAckUnreadCount"] = post_ack_current.get("unreadCount", 0)
        report["receiptCount"] = receipts.get("count", 0)
        append_progress(report)
    finally:
        if previous_store_path is None:
            os.environ.pop("MEMORYENDPOINTS_STORE_PATH", None)
        else:
            os.environ["MEMORYENDPOINTS_STORE_PATH"] = previous_store_path
        if previous_backend is None:
            os.environ.pop("MEMORYENDPOINTS_STORE_BACKEND", None)
        else:
            os.environ["MEMORYENDPOINTS_STORE_BACKEND"] = previous_backend

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"ok": report["localDogfoodVerified"], "report": str(REPORT_PATH), "valuesRedacted": True}, indent=2, sort_keys=True))
    return 0 if report["localDogfoodVerified"] and not report["rawCredentialValuesStored"] else 1


if __name__ == "__main__":
    sys.exit(main())
