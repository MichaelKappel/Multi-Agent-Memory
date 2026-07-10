import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import application
from memoryendpoints.config import utc_now


REPORT_PATH = ROOT / "docs" / "reports" / "dogfood-memory-run.json"
PROGRESS_PATH = ROOT / ".uai" / "progress.uai"
DOGFOOD_STORE_DIR = ROOT / "var" / "dogfood-memory"
DOGFOOD_STORE = DOGFOOD_STORE_DIR / "store.json"
LIVE_READBACK_ATTEMPTS = 12


class WsgiTransport(object):
    mode = "local_wsgi"

    def call(self, path, method="GET", body=None, headers=None, query=""):
        raw = b""
        if body is not None:
            raw = json.dumps(body, sort_keys=True).encode("utf-8")
        captured = {}

        def start_response(status, response_headers):
            captured["status"] = status

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
        return captured.get("status", "500 Internal Server Error"), parse_payload(text)


class HttpTransport(object):
    mode = "live_http"

    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")

    def call(self, path, method="GET", body=None, headers=None, query=""):
        url = self.base_url + path
        if query:
            url += "?" + query
        request_headers = {"Accept": "application/json"}
        for key, value in (headers or {}).items():
            if key == "HTTP_AUTHORIZATION":
                request_headers["Authorization"] = value
            elif key == "HTTP_IDEMPOTENCY_KEY":
                request_headers["Idempotency-Key"] = value
            elif key.startswith("HTTP_"):
                request_headers[key[5:].replace("_", "-")] = value
            else:
                request_headers[key] = value
        data = None
        if body is not None:
            data = json.dumps(body, sort_keys=True).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=request_headers, method=method)
        try:
            with urlopen(request, timeout=30) as response:
                text = response.read().decode("utf-8", errors="replace")
                return "%s %s" % (response.status, getattr(response, "reason", "OK")), parse_payload(text)
        except HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            return "%s %s" % (exc.code, getattr(exc, "reason", "HTTP Error")), parse_payload(text)


def parse_payload(text):
    try:
        return json.loads(text)
    except ValueError:
        return {"rawText": text[:300]}


def ok_status(status):
    return str(status).startswith(("200", "201", "202"))


def step(report, name, status, payload=None, required=True, verified=None):
    http_ok = ok_status(status)
    ok = http_ok if verified is None else http_ok and bool(verified)
    item = {
        "name": name,
        "httpStatus": status,
        "ok": ok,
        "required": required,
        "payloadShape": sorted((payload or {}).keys()),
    }
    if verified is not None:
        item["contractVerified"] = bool(verified)
    report["steps"].append(
        item
    )


def canonical_path_query(url):
    parsed = urlparse(url or "")
    path = parsed.path or ""
    query = parsed.query or ""
    if not path and url:
        if "?" in url:
            path, query = url.split("?", 1)
        else:
            path = url
    if path and not path.startswith("/"):
        path = "/" + path
    return path, query


def call_canonical_url(transport, url, headers):
    path, query = canonical_path_query(url)
    if not path:
        return "500 Missing Canonical URL", {"ok": False, "error": "missing_canonical_url", "valuesRedacted": True}
    return transport.call(path, headers=headers, query=query)


def contains_memory_event(payload, event_id):
    if not event_id:
        return False
    return any(item.get("eventId") == event_id for item in payload.get("items") or [])


def read_memory_until(transport, headers, event_id, path=None, query="", url=None, attempts=1, delay_seconds=1.0):
    attempts = max(1, int(attempts or 1))
    if url:
        path, query = canonical_path_query(url)
    if not path:
        return "500 Missing Canonical URL", {"ok": False, "error": "missing_canonical_url", "valuesRedacted": True}
    last_status = "500 Missing Memory Read"
    last_payload = {"ok": False, "valuesRedacted": True}
    for attempt in range(attempts):
        last_status, last_payload = transport.call(path, headers=headers, query=query)
        if contains_memory_event(last_payload, event_id):
            return last_status, last_payload
        if attempt < attempts - 1:
            time.sleep(delay_seconds)
    return last_status, last_payload


def contains_meeting_message(payload, message_id):
    if not message_id:
        return False
    return any(item.get("meetingMessageId") == message_id for item in payload.get("items") or [])


def contains_current_message(payload, message_id, notification_id):
    if not message_id and not notification_id:
        return False
    for item in payload.get("items") or []:
        message = item.get("message") or {}
        notification = item.get("notification") or {}
        if message_id and message.get("messageId") == message_id:
            return True
        if notification_id and notification.get("notificationId") == notification_id:
            return True
    return False


def current_message_query(workspace_id, agent_id, message_id="", notification_id=""):
    query = {"workspace_id": workspace_id, "agent_id": agent_id}
    if message_id:
        query["message_id"] = message_id
    if notification_id:
        query["notification_id"] = notification_id
    return urlencode(query)


def read_current_message_until(transport, headers, workspace_id, agent_id, message_id, notification_id, expected_visible=True, attempts=1, delay_seconds=1.0):
    attempts = max(1, int(attempts or 1))
    last_status = "500 Missing Current Message Read"
    last_payload = {"ok": False, "valuesRedacted": True}
    for attempt in range(attempts):
        last_status, last_payload = transport.call(
            "/api/matm/current-message",
            headers=headers,
            query=current_message_query(workspace_id, agent_id, message_id, notification_id),
        )
        visible = contains_current_message(last_payload, message_id, notification_id)
        if visible == bool(expected_visible):
            return last_status, last_payload
        if attempt < attempts - 1:
            time.sleep(delay_seconds)
    return last_status, last_payload


def append_progress(report):
    if report.get("liveDogfoodVerified"):
        detail = "Live MATM dogfood run verified against `https://memoryendpoints.com`"
    elif report.get("liveCoreDogfoodVerified"):
        detail = "Live core MATM dogfood run verified against `https://memoryendpoints.com`; latest audit-log readback contract is not live yet"
    elif report.get("localDogfoodVerified"):
        detail = "Local MATM dogfood run verified through WSGI"
    else:
        detail = "MATM dogfood run attempted but not fully verified"
    line = (
        "- Dogfood status: %s; report `docs/reports/dogfood-memory-run.json`; "
        "local audit-log readback verified: %s; live audit-log readback verified: %s; "
        "MATM update URL `https://memoryendpoints.com/api/matm/memory-events/submit`; "
        "raw credential values stored in report: false."
        % (
            detail,
            str(bool(report.get("localAuditTrailReadbackVerified") or (report.get("localDogfoodVerified") and report.get("auditTrailReadbackVerified")))).lower(),
            str(bool(report.get("liveAuditTrailReadbackVerified") or (report.get("liveDogfoodVerified") and report.get("auditTrailReadbackVerified")))).lower(),
        )
    )
    existing = PROGRESS_PATH.read_text(encoding="utf-8").splitlines()
    cleaned = [
        item
        for item in existing
        if not (item.startswith("- 20") and "dogfood" in item.lower() and "docs/reports/dogfood-memory-run.json" in item)
    ]
    replaced = False
    for index, item in enumerate(cleaned):
        if item.startswith("- Local dogfood status:") or item.startswith("- Dogfood status:"):
            cleaned[index] = line
            replaced = True
            break
    if not replaced:
        insert_at = len(cleaned)
        for index, item in enumerate(cleaned):
            if item.startswith("- Completion must not be claimed"):
                insert_at = index
                break
        cleaned.insert(insert_at, line)
    PROGRESS_PATH.write_text("\n".join(cleaned).rstrip() + "\n", encoding="utf-8")
    report["uaiProgressUpdated"] = True


def run_sequence(transport, label, base_url=None):
    report = {
        "mode": transport.mode,
        "target": base_url or "local_wsgi_application",
        "generatedAt": utc_now(),
        "ok": False,
        "liveDogfoodVerified": False,
        "liveCoreDogfoodVerified": False,
        "latestDogfoodContractVerified": False,
        "localDogfoodVerified": False,
        "rawCredentialValuesStored": False,
        "rawPrivatePayloadsStored": False,
        "rawWorkspaceIdStoredInReport": False,
        "valuesRedacted": True,
        "steps": [],
    }
    token = ""
    workspace_id = ""
    try:
        status, setup = transport.call(
            "/api/matm/agent-setup/free-account",
            method="POST",
            body={"label": "MemoryEndpoints %s dogfood workspace" % label},
        )
        step(report, "create_free_workspace", status, setup)
        token = setup.get("apiKeySecret", "")
        workspace_id = setup.get("workspaceId", "")
        auth = {"HTTP_AUTHORIZATION": "Bearer " + token}
        run_tag = hashlib.sha256((workspace_id + label + utc_now()).encode("utf-8")).hexdigest()[:12]

        status, agent = transport.call(
            "/api/matm/agents/register",
            method="POST",
            headers=dict(auth, HTTP_IDEMPOTENCY_KEY="dogfood-register-" + run_tag),
            body={"workspaceId": workspace_id, "agentId": "memoryendpoints-dogfood-agent", "displayName": "MemoryEndpoints Dogfood Agent"},
        )
        step(report, "register_agent", status, agent)

        status, memory = transport.call(
            "/api/matm/memory-events/submit",
            method="POST",
            headers=dict(auth, HTTP_IDEMPOTENCY_KEY="dogfood-memory-" + run_tag),
            body={
                "workspaceId": workspace_id,
                "actorAgentId": "memoryendpoints-dogfood-agent",
                "memoryType": "status",
                "subject": "MemoryEndpoints enterprise MATM hardening",
                "title": "%s dogfood status" % label.title(),
                "summary": "%s dogfood verified workspace creation, agent registration, memory submit/search, meeting-room coordination, current-message readback, acknowledgement, receipt readback, and audit-log readback." % label.title(),
                "tags": ["dogfood", label, "matm"],
                "confidence": 0.86,
                "source": "scripts/dogfood_memoryendpoints.py",
            },
        )
        step(report, "submit_memory", status, memory)
        memory_event_id = (memory.get("event") or {}).get("eventId", "")

        status, search = transport.call(
            "/api/matm/search",
            headers=auth,
            query=urlencode({"workspace_id": workspace_id, "q": "dogfood"}),
        )
        memory_readback_verified = contains_memory_event(search, memory_event_id)
        step(report, "search_memory", status, search, verified=memory_readback_verified)

        status, queue = transport.call(
            "/api/matm/review-queue",
            headers=auth,
            query=urlencode({"workspace_id": workspace_id, "status": "pending"}),
        )
        step(report, "read_review_queue", status, queue, required=False)

        status, meeting_rooms = transport.call(
            "/api/matm/meeting-rooms",
            headers=auth,
            query=urlencode({"workspace_id": workspace_id, "agent_id": "memoryendpoints-followup-agent"}),
        )
        step(report, "read_meeting_rooms", status, meeting_rooms)
        meeting_room_items = meeting_rooms.get("items") or []
        project_rooms = [item for item in meeting_room_items if item.get("scope") == "project"]
        meeting_room_id = ((project_rooms or meeting_room_items or [{}])[0]).get("roomId", "")

        status, meeting_post = transport.call(
            "/api/matm/meeting-messages",
            method="POST",
            headers=dict(auth, HTTP_IDEMPOTENCY_KEY="dogfood-meeting-message-" + run_tag),
            body={
                "workspaceId": workspace_id,
                "roomId": meeting_room_id,
                "senderAgentId": "memoryendpoints-dogfood-agent",
                "safeSummary": "Project meeting dogfood: use first-class meeting rooms for project coordination and routing.",
            },
        )
        step(report, "post_meeting_message", status, meeting_post)
        meeting_message_id = meeting_post.get("messageId") or (meeting_post.get("message") or {}).get("meetingMessageId", "")
        canonical_room_id = meeting_post.get("canonicalRoomId") or meeting_room_id

        status, meeting_messages = call_canonical_url(transport, meeting_post.get("transcriptQueryUrl"), auth)
        meeting_readback_verified = contains_meeting_message(meeting_messages, meeting_message_id)
        step(report, "read_meeting_messages", status, meeting_messages, verified=meeting_readback_verified)

        status, meeting_promotion = transport.call(
            "/api/matm/meeting-messages/promote",
            method="POST",
            headers=dict(auth, HTTP_IDEMPOTENCY_KEY="dogfood-meeting-memory-promote-" + run_tag),
            body={
                "workspaceId": workspace_id,
                "meetingMessageId": meeting_message_id,
                "promotedByAgentId": "memoryendpoints-dogfood-agent",
                "memoryType": "evidence",
                "title": "%s meeting transcript evidence" % label.title(),
                "tags": ["dogfood", label, "meeting-message"],
            },
        )
        meeting_memory_event_id = (meeting_promotion.get("event") or {}).get("eventId", "")
        meeting_promotion_verified = bool(
            meeting_promotion.get("persisted")
            and meeting_promotion.get("visibleInReviewQueue")
            and meeting_promotion.get("canonicalMemoryEventId") == meeting_memory_event_id
        )
        step(report, "promote_meeting_message_to_memory", status, meeting_promotion, verified=meeting_promotion_verified)

        status, meeting_memory_search = read_memory_until(
            transport,
            auth,
            meeting_memory_event_id,
            url=meeting_promotion.get("memoryQueryUrl"),
            attempts=LIVE_READBACK_ATTEMPTS if transport.mode == "live_http" else 1,
            delay_seconds=1.0,
        )
        meeting_memory_readback_verified = contains_memory_event(meeting_memory_search, meeting_memory_event_id)
        step(report, "read_promoted_meeting_memory", status, meeting_memory_search, verified=meeting_memory_readback_verified)

        status, meeting_memory_source_search = read_memory_until(
            transport,
            auth,
            meeting_memory_event_id,
            path="/api/matm/search",
            query=urlencode(
                {
                    "workspace_id": workspace_id,
                    "q": meeting_message_id,
                    "scope": (meeting_promotion.get("event") or {}).get("scope") or "project",
                    "memory_type": (meeting_promotion.get("event") or {}).get("memoryType") or "evidence",
                }
            ),
            attempts=LIVE_READBACK_ATTEMPTS if transport.mode == "live_http" else 1,
            delay_seconds=1.0,
        )
        meeting_memory_source_readback_verified = contains_memory_event(meeting_memory_source_search, meeting_memory_event_id)
        step(report, "read_promoted_meeting_memory_by_source", status, meeting_memory_source_search, verified=meeting_memory_source_readback_verified)

        status, meeting_read = transport.call(
            "/api/matm/meeting-rooms/read",
            method="POST",
            headers=dict(auth, HTTP_IDEMPOTENCY_KEY="dogfood-meeting-read-" + run_tag),
            body={
                "workspaceId": workspace_id,
                "roomId": canonical_room_id,
                "agentId": "memoryendpoints-dogfood-agent",
                "lastMeetingMessageId": meeting_message_id,
            },
        )
        meeting_read_verified = bool(
            meeting_read.get("ok")
            and (meeting_read.get("readState") or {}).get("lastMeetingMessageId") == meeting_message_id
        )
        step(report, "mark_meeting_room_read", status, meeting_read, verified=meeting_read_verified)

        status, message = transport.call(
            "/api/matm/agent-messages",
            method="POST",
            headers=dict(auth, HTTP_IDEMPOTENCY_KEY="dogfood-message-" + run_tag),
            body={
                "workspaceId": workspace_id,
                "senderAgentId": "memoryendpoints-dogfood-agent",
                "targetAgentId": "memoryendpoints-followup-agent",
                "safeSummary": "Action required: review the dogfood memory report and continue hardening work.",
                "responseRequired": True,
            },
        )
        step(report, "create_current_message", status, message)
        message_id = message.get("messageId") or (message.get("message") or {}).get("messageId", "")
        notification_id = message.get("notificationId") or (message.get("notification") or {}).get("notificationId", "")

        status, current = read_current_message_until(
            transport,
            auth,
            workspace_id,
            "memoryendpoints-followup-agent",
            message_id,
            notification_id,
            expected_visible=True,
            attempts=LIVE_READBACK_ATTEMPTS if transport.mode == "live_http" else 1,
            delay_seconds=1.0,
        )
        current_readback_verified = contains_current_message(current, message_id, notification_id)
        step(report, "read_current_message", status, current, verified=current_readback_verified)

        status, ack = transport.call(
            "/api/matm/notifications/ack",
            method="POST",
            headers=dict(auth, HTTP_IDEMPOTENCY_KEY="dogfood-ack-" + run_tag),
            body={
                "workspaceId": workspace_id,
                "notificationId": notification_id,
                "consumerAgentId": "memoryendpoints-followup-agent",
                "status": "read",
            },
        )
        ack_verified = bool(
            ack.get("ok")
            and (ack.get("receipt") or {}).get("notificationId") == notification_id
            and (ack.get("receipt") or {}).get("consumerAgentId") == "memoryendpoints-followup-agent"
        )
        step(report, "acknowledge_notification", status, ack, verified=ack_verified)

        status, receipts = transport.call(
            "/api/matm/receipts",
            headers=auth,
            query=urlencode({"workspace_id": workspace_id, "consumer_agent_id": "memoryendpoints-followup-agent"}),
        )
        step(report, "read_redacted_receipts", status, receipts)

        status, audit_log = transport.call(
            "/api/matm/audit-log",
            headers=auth,
            query=urlencode({"workspace_id": workspace_id, "limit": "50"}),
        )
        step(report, "read_audit_log", status, audit_log)

        status, post_ack_current = read_current_message_until(
            transport,
            auth,
            workspace_id,
            "memoryendpoints-followup-agent",
            message_id,
            notification_id,
            expected_visible=False,
            attempts=LIVE_READBACK_ATTEMPTS if transport.mode == "live_http" else 1,
            delay_seconds=1.0,
        )
        post_ack_verified = not contains_current_message(post_ack_current, message_id, notification_id)
        step(report, "read_current_message_after_ack", status, post_ack_current, verified=post_ack_verified)

        required_ok = all(item["ok"] for item in report["steps"] if item["required"])
        core_required_ok = all(
            item["ok"]
            for item in report["steps"]
            if item["required"] and item["name"] != "read_audit_log"
        )
        report["ok"] = required_ok
        report["coreDogfoodWorkflowVerified"] = core_required_ok
        report["latestDogfoodContractVerified"] = required_ok
        report["localDogfoodVerified"] = transport.mode == "local_wsgi" and required_ok
        report["liveCoreDogfoodVerified"] = transport.mode == "live_http" and core_required_ok
        report["liveDogfoodVerified"] = transport.mode == "live_http" and required_ok
        report["workspaceIdHash"] = "sha256:" + hashlib.sha256(workspace_id.encode("utf-8")).hexdigest()
        report["oneTimeKeyReturned"] = bool(token)
        report["memoryReadbackVerified"] = memory_readback_verified
        report["searchReadbackCount"] = search.get("count", 0)
        report["meetingRoomCount"] = meeting_rooms.get("count", 0)
        report["meetingMessageCount"] = meeting_messages.get("count", 0)
        report["meetingMessageReadbackVerified"] = meeting_readback_verified
        report["meetingMemoryPromotionVerified"] = meeting_promotion_verified
        report["meetingMemoryReadbackVerified"] = meeting_memory_readback_verified
        report["meetingMemorySourceReadbackVerified"] = meeting_memory_source_readback_verified
        report["meetingReadVerified"] = meeting_read_verified
        report["currentMessageUnreadCount"] = current.get("unreadCount", 0)
        report["currentMessageReadbackVerified"] = current_readback_verified
        report["currentMessageAckVerified"] = ack_verified
        report["currentMessagePostAckVerified"] = post_ack_verified
        report["postAckUnreadCount"] = post_ack_current.get("unreadCount", 0)
        report["receiptCount"] = receipts.get("count", 0)
        report["auditLogCount"] = audit_log.get("count", 0)
        report["auditTrailReadbackVerified"] = bool(audit_log.get("ok") and audit_log.get("valuesRedacted") and audit_log.get("count", 0))
        report["requiredStepFailureCount"] = len([item for item in report["steps"] if item["required"] and not item["ok"]])
        report["optionalStepFailureCount"] = len([item for item in report["steps"] if not item["required"] and not item["ok"]])
    except Exception as exc:
        report["exceptionType"] = exc.__class__.__name__
        report["safeNoOp"] = True
    report["rawCredentialValuesStored"] = bool(token and token in json.dumps(report, sort_keys=True))
    return report


def combine_reports(runs):
    local_verified = any(item.get("localDogfoodVerified") for item in runs)
    live_verified = any(item.get("liveDogfoodVerified") for item in runs)
    live_core_verified = any(item.get("liveCoreDogfoodVerified") for item in runs)
    latest_contract_verified = all(item.get("latestDogfoodContractVerified") for item in runs)
    local_audit_verified = any(
        item.get("mode") == "local_wsgi" and item.get("auditTrailReadbackVerified")
        for item in runs
    )
    live_audit_verified = any(
        item.get("mode") == "live_http" and item.get("auditTrailReadbackVerified")
        for item in runs
    )
    report = {
        "schemaVersion": "memoryendpoints.dogfood_run.v3",
        "generatedAt": utc_now(),
        "mode": "combined" if len(runs) > 1 else runs[0]["mode"],
        "runs": runs,
        "ok": all(item.get("ok") for item in runs),
        "localDogfoodVerified": local_verified,
        "liveDogfoodVerified": live_verified,
        "liveCoreDogfoodVerified": live_core_verified,
        "latestDogfoodContractVerified": latest_contract_verified,
        "localAuditTrailReadbackVerified": local_audit_verified,
        "liveAuditTrailReadbackVerified": live_audit_verified,
        "rawCredentialValuesStored": any(item.get("rawCredentialValuesStored") for item in runs),
        "rawPrivatePayloadsStored": any(item.get("rawPrivatePayloadsStored") for item in runs),
        "rawWorkspaceIdStoredInReport": False,
        "requiredStepFailureCount": sum(item.get("requiredStepFailureCount", 0) for item in runs),
        "optionalStepFailureCount": sum(item.get("optionalStepFailureCount", 0) for item in runs),
        "valuesRedacted": True,
    }
    primary = next(
        (
            item
            for item in runs
            if item.get("liveDogfoodVerified") or item.get("liveCoreDogfoodVerified")
        ),
        runs[-1],
    )
    for key in (
        "steps",
        "memoryReadbackVerified",
        "searchReadbackCount",
        "meetingMessageReadbackVerified",
        "meetingMemoryPromotionVerified",
        "meetingMemoryReadbackVerified",
        "meetingMemorySourceReadbackVerified",
        "meetingReadVerified",
        "currentMessageUnreadCount",
        "currentMessageReadbackVerified",
        "currentMessageAckVerified",
        "currentMessagePostAckVerified",
        "postAckUnreadCount",
        "receiptCount",
        "auditLogCount",
        "auditTrailReadbackVerified",
    ):
        if key in primary:
            report[key] = primary[key]
    if "workspaceIdHash" in primary:
        report["workspaceIdHash"] = primary["workspaceIdHash"]
    report["oneTimeKeyReturned"] = any(item.get("oneTimeKeyReturned") for item in runs)
    return report


def restore_store_environment(previous_store_path, previous_backend):
    if previous_store_path is None:
        os.environ.pop("MEMORYENDPOINTS_STORE_PATH", None)
    else:
        os.environ["MEMORYENDPOINTS_STORE_PATH"] = previous_store_path
    if previous_backend is None:
        os.environ.pop("MEMORYENDPOINTS_STORE_BACKEND", None)
    else:
        os.environ["MEMORYENDPOINTS_STORE_BACKEND"] = previous_backend


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["local", "live", "both"], default="local")
    parser.add_argument("--base-url", default="https://memoryendpoints.com")
    parser.add_argument("--json-out", default=str(REPORT_PATH))
    parser.add_argument("--no-progress-update", action="store_true")
    args = parser.parse_args(argv)

    previous_store_path = os.environ.get("MEMORYENDPOINTS_STORE_PATH")
    previous_backend = os.environ.get("MEMORYENDPOINTS_STORE_BACKEND")
    runs = []
    try:
        if args.mode in ("local", "both"):
            shutil.rmtree(DOGFOOD_STORE_DIR, ignore_errors=True)
            DOGFOOD_STORE_DIR.mkdir(parents=True, exist_ok=True)
            os.environ["MEMORYENDPOINTS_STORE_PATH"] = str(DOGFOOD_STORE)
            os.environ.pop("MEMORYENDPOINTS_STORE_BACKEND", None)
            local = run_sequence(WsgiTransport(), "local-wsgi")
            store_text = DOGFOOD_STORE.read_text(encoding="utf-8") if DOGFOOD_STORE.exists() else ""
            local["rawCredentialValuesStored"] = local["rawCredentialValuesStored"] or ("me_live_" in store_text)
            runs.append(local)
        if args.mode in ("live", "both"):
            restore_store_environment(previous_store_path, previous_backend)
            runs.append(run_sequence(HttpTransport(args.base_url), "live-http", args.base_url))
    finally:
        restore_store_environment(previous_store_path, previous_backend)

    report = combine_reports(runs)
    if not args.no_progress_update:
        append_progress(report)
    out = Path(args.json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.mode == "local":
        ok = report["localDogfoodVerified"]
    elif args.mode == "live":
        ok = report["liveDogfoodVerified"]
    else:
        ok = report["localDogfoodVerified"] and report["liveDogfoodVerified"]
    ok = ok and not report["rawCredentialValuesStored"]
    print(json.dumps({"ok": ok, "localDogfoodVerified": report["localDogfoodVerified"], "liveDogfoodVerified": report["liveDogfoodVerified"], "report": str(out), "valuesRedacted": True}, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
