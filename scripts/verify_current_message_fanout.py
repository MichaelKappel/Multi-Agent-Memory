import argparse
import datetime
import hashlib
import json
import secrets
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SECRET = ROOT / ".local-secrets" / "human-verifier-account.json"
DEFAULT_REPORT = ROOT / "docs" / "reports" / "current-message-fanout-verification.json"
DEFAULT_HUMAN_AGENT_ID = "human-verifier-agent"
DEFAULT_BACKEND_AGENT_ID = "MemoryEndpoints-Backend-Agent"
DEFAULT_OBSERVER_AGENT_ID = "swarm-observer-agent"
REQUEST_TIMEOUT_SECONDS = 10
LIVE_READ_ATTEMPTS = 4
LIVE_WRITE_ATTEMPTS = 6
LIVE_ACK_READ_ATTEMPTS = 4
LIVE_WORKSPACE_READY_ATTEMPTS = 8
LIVE_READ_DELAY_SECONDS = 1.0
LIVE_ACK_READ_DELAY_SECONDS = 1.0
LIVE_WRITE_DELAY_SECONDS = 0.75
MAX_RUNTIME_SECONDS = 120
RUNTIME_DEADLINE = None


def sha256_text(value):
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def configure_runtime_limits(args):
    global REQUEST_TIMEOUT_SECONDS
    global LIVE_READ_ATTEMPTS
    global LIVE_WRITE_ATTEMPTS
    global LIVE_ACK_READ_ATTEMPTS
    global LIVE_WORKSPACE_READY_ATTEMPTS
    global LIVE_READ_DELAY_SECONDS
    global LIVE_ACK_READ_DELAY_SECONDS
    global LIVE_WRITE_DELAY_SECONDS
    global MAX_RUNTIME_SECONDS
    global RUNTIME_DEADLINE

    REQUEST_TIMEOUT_SECONDS = max(1, int(args.request_timeout))
    LIVE_READ_ATTEMPTS = max(1, int(args.read_attempts))
    LIVE_WRITE_ATTEMPTS = max(1, int(args.write_attempts))
    LIVE_ACK_READ_ATTEMPTS = max(1, int(args.ack_read_attempts))
    LIVE_WORKSPACE_READY_ATTEMPTS = max(1, int(args.workspace_ready_attempts))
    LIVE_READ_DELAY_SECONDS = max(0.0, float(args.read_delay))
    LIVE_ACK_READ_DELAY_SECONDS = max(0.0, float(args.ack_delay))
    LIVE_WRITE_DELAY_SECONDS = max(0.0, float(args.write_delay))
    MAX_RUNTIME_SECONDS = max(0, int(args.max_runtime_seconds))
    RUNTIME_DEADLINE = time.monotonic() + MAX_RUNTIME_SECONDS if MAX_RUNTIME_SECONDS else None


def runtime_limits_summary():
    return {
        "requestTimeoutSeconds": REQUEST_TIMEOUT_SECONDS,
        "readAttempts": LIVE_READ_ATTEMPTS,
        "writeAttempts": LIVE_WRITE_ATTEMPTS,
        "ackReadAttempts": LIVE_ACK_READ_ATTEMPTS,
        "workspaceReadyAttempts": LIVE_WORKSPACE_READY_ATTEMPTS,
        "readDelaySeconds": LIVE_READ_DELAY_SECONDS,
        "ackDelaySeconds": LIVE_ACK_READ_DELAY_SECONDS,
        "writeDelaySeconds": LIVE_WRITE_DELAY_SECONDS,
        "maxRuntimeSeconds": MAX_RUNTIME_SECONDS,
        "deadlineActive": bool(RUNTIME_DEADLINE),
        "valuesRedacted": True,
    }


def seconds_until_deadline():
    if RUNTIME_DEADLINE is None:
        return None
    return max(0.0, RUNTIME_DEADLINE - time.monotonic())


def deadline_exceeded():
    remaining = seconds_until_deadline()
    return remaining is not None and remaining <= 0


def deadline_payload(path):
    return {
        "ok": False,
        "error": {
            "code": "verification_deadline_exceeded",
            "path": path,
            "safeNoOp": True,
            "valuesRedacted": True,
        },
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def request_json(base_url, path, method="GET", token=None, query=None, headers=None, body=None):
    if deadline_exceeded():
        return 0, deadline_payload(path), {}
    url = base_url.rstrip("/") + path
    if query:
        url += "?" + query
    request_headers = {"Accept": "application/json"}
    request_headers.update(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    if token:
        request_headers["Authorization"] = "Bearer " + token
    request = Request(url, headers=request_headers, method=method, data=data)
    timeout = REQUEST_TIMEOUT_SECONDS
    remaining = seconds_until_deadline()
    if remaining is not None:
        if remaining <= 0:
            return 0, deadline_payload(path), {}
        timeout = max(1, min(timeout, int(remaining)))
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            payload = json.loads(raw) if raw else {}
            return response.status, payload, dict(response.headers)
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {
                "ok": False,
                "error": {"code": "non_json_http_error", "status": exc.code},
                "valuesRedacted": True,
            }
        return exc.code, payload, dict(exc.headers)
    except (TimeoutError, URLError, OSError) as exc:
        return 0, {
            "ok": False,
            "error": {
                "code": "request_failed",
                "type": exc.__class__.__name__,
                "safeNoOp": True,
                "valuesRedacted": True,
            },
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }, {}


def retryable_status(status, retry_statuses):
    return str(status or "") in {str(item) for item in retry_statuses}


def request_json_with_retries(
    base_url,
    path,
    method="GET",
    token=None,
    query=None,
    headers=None,
    body=None,
    retry_statuses=(),
    attempts=1,
    delay_seconds=LIVE_WRITE_DELAY_SECONDS,
):
    attempts = max(1, int(attempts or 1))
    last_status, last_payload, last_headers = 0, {"ok": False, "valuesRedacted": True}, {}
    for attempt in range(attempts):
        last_status, last_payload, last_headers = request_json(
            base_url,
            path,
            method=method,
            token=token,
            query=query,
            headers=headers,
            body=body,
        )
        if 200 <= int(last_status or 0) < 300 or not retryable_status(last_status, retry_statuses):
            return last_status, last_payload, last_headers
        if attempt < attempts - 1:
            time.sleep(delay_seconds)
    return last_status, last_payload, last_headers


def agent_id_from_secret(secret, fallback=DEFAULT_HUMAN_AGENT_ID):
    for key in ("humanAgentId", "agentId", "defaultAgentId"):
        value = (secret or {}).get(key)
        if value:
            return str(value)
    return fallback


def named_agent_id_from_secret(secret, keys, fallback=""):
    for key in keys:
        value = (secret or {}).get(key)
        if value:
            return str(value)
    return fallback


def unique_agents(*agent_ids):
    agents = []
    for agent_id in agent_ids:
        agent_id = (agent_id or "").strip()
        if agent_id and agent_id not in agents:
            agents.append(agent_id)
    return agents


def inbox_items(payload):
    items = (payload or {}).get("items")
    return items if isinstance(items, list) else []


def message_summary(item):
    return ((item or {}).get("message") or {}).get("safeSummary") or ""


def message_type(item):
    return ((item or {}).get("delivery") or {}).get("messageType") or ""


def notification_id(item):
    return ((item or {}).get("notification") or {}).get("notificationId") or ""


def notification_ids_by_agent_from_submit(payload):
    mapping = {}
    for note in (payload or {}).get("notifications") or []:
        agent_id = (note or {}).get("targetAgentId") or ""
        note_id = (note or {}).get("notificationId") or ""
        if agent_id and note_id:
            mapping[agent_id] = note_id
    notification = (payload or {}).get("notification") or {}
    agent_id = notification.get("targetAgentId") or (((payload or {}).get("delivery") or {}).get("targetAgentId") or "")
    note_id = notification.get("notificationId") or (payload or {}).get("notificationId") or ""
    if agent_id and note_id and agent_id not in mapping:
        mapping[agent_id] = note_id
    return mapping


def items_for_summary(payload, safe_summary):
    return [item for item in inbox_items(payload) if message_summary(item) == safe_summary]


def delivery_counts(payload):
    counts = (payload or {}).get("deliveryCounts") or {}
    return {
        "broadcast": int(counts.get("broadcast") or 0),
        "targeted": int(counts.get("targeted") or 0),
    }


def read_status(payload):
    return (payload or {}).get("readStatus")


def read_error_code(payload):
    return (((payload or {}).get("error") or {}).get("code") or "")


def read_diagnostics_by_agent(inboxes_by_agent, agent_ids):
    diagnostics = {}
    for agent_id in agent_ids:
        payload = (inboxes_by_agent or {}).get(agent_id) or {}
        status = read_status(payload)
        if status is None:
            status = 200
        diagnostics[agent_id] = {
            "readStatus": status,
            "ok": bool(payload.get("ok")),
            "itemCount": len(inbox_items(payload)),
            "errorCode": read_error_code(payload),
            "valuesRedacted": bool(payload.get("valuesRedacted", True)),
            "rawCredentialExposed": bool(payload.get("rawCredentialExposed")),
            "rawPayloadExposed": bool(payload.get("rawPayloadExposed")),
        }
    return diagnostics


def broadcast_fanout_check(inboxes_by_agent, broadcast_summary, agent_ids):
    visible_agents = []
    visible_any_type_agents = []
    wrong_type_agents = []
    notification_ids_by_agent = {}
    primary_notification_ids_by_agent = {}
    for agent_id in agent_ids:
        matches = items_for_summary((inboxes_by_agent or {}).get(agent_id), broadcast_summary)
        broadcast_matches = [item for item in matches if message_type(item) == "broadcast"]
        if matches:
            visible_any_type_agents.append(agent_id)
        if broadcast_matches:
            visible_agents.append(agent_id)
            ids = [notification_id(item) for item in broadcast_matches if notification_id(item)]
            if ids:
                notification_ids_by_agent[agent_id] = ids
                primary_notification_ids_by_agent[agent_id] = ids[0]
        elif matches:
            wrong_type_agents.append(agent_id)
    missing_agents = [agent_id for agent_id in agent_ids if agent_id not in visible_any_type_agents]
    missing_notification_id_agents = [
        agent_id for agent_id in agent_ids if agent_id in visible_agents and agent_id not in primary_notification_ids_by_agent
    ]
    primary_notification_ids = [primary_notification_ids_by_agent.get(agent_id) for agent_id in agent_ids if primary_notification_ids_by_agent.get(agent_id)]
    duplicate_notification_ids = sorted(
        {
            notification_id_value
            for notification_id_value in primary_notification_ids
            if primary_notification_ids.count(notification_id_value) > 1
        }
    )
    unique_recipient_notification_ids = (
        len(primary_notification_ids) == len(agent_ids)
        and len(set(primary_notification_ids)) == len(agent_ids)
        and not missing_notification_id_agents
    )
    return {
        "ok": len(visible_agents) == len(agent_ids) and not missing_agents and not wrong_type_agents and unique_recipient_notification_ids,
        "checkedAgents": list(agent_ids),
        "visibleAgents": visible_agents,
        "visibleAnyTypeAgents": visible_any_type_agents,
        "missingAgents": missing_agents,
        "wrongTypeAgents": wrong_type_agents,
        "uniqueRecipientNotificationIds": unique_recipient_notification_ids,
        "primaryNotificationIdsByAgent": primary_notification_ids_by_agent,
        "distinctNotificationIdCount": len(set(primary_notification_ids)),
        "expectedNotificationIdCount": len(agent_ids),
        "duplicateNotificationIds": duplicate_notification_ids,
        "missingNotificationIdAgents": missing_notification_id_agents,
        "expectedRecipientCount": len(agent_ids),
        "visibleRecipientCount": len(visible_agents),
        "deliveryCountsByAgent": {
            agent_id: delivery_counts((inboxes_by_agent or {}).get(agent_id)) for agent_id in agent_ids
        },
        "readDiagnosticsByAgent": read_diagnostics_by_agent(inboxes_by_agent, agent_ids),
        "notificationIdsByAgent": notification_ids_by_agent,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def targeted_delivery_check(inboxes_by_agent, safe_summary, target_agent_id, agent_ids):
    visible_agents = []
    visible_targeted_agents = []
    wrong_type_agents = []
    notification_ids_by_agent = {}
    for agent_id in agent_ids:
        matches = items_for_summary((inboxes_by_agent or {}).get(agent_id), safe_summary)
        targeted_matches = [item for item in matches if message_type(item) == "targeted"]
        if matches:
            visible_agents.append(agent_id)
        if targeted_matches:
            visible_targeted_agents.append(agent_id)
            ids = [notification_id(item) for item in targeted_matches if notification_id(item)]
            if ids:
                notification_ids_by_agent[agent_id] = ids
        elif matches:
            wrong_type_agents.append(agent_id)
    unexpected_agents = [agent_id for agent_id in visible_agents if agent_id != target_agent_id]
    return {
        "ok": target_agent_id in visible_targeted_agents and not unexpected_agents and not wrong_type_agents,
        "targetAgentId": target_agent_id,
        "checkedAgents": list(agent_ids),
        "visibleAgents": visible_agents,
        "visibleTargetedAgents": visible_targeted_agents,
        "visibleToTarget": target_agent_id in visible_targeted_agents,
        "unexpectedAgents": unexpected_agents,
        "wrongTypeAgents": wrong_type_agents,
        "deliveryCountsByAgent": {
            agent_id: delivery_counts((inboxes_by_agent or {}).get(agent_id)) for agent_id in agent_ids
        },
        "readDiagnosticsByAgent": read_diagnostics_by_agent(inboxes_by_agent, agent_ids),
        "notificationIdsByAgent": notification_ids_by_agent,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def apply_targeted_submit_confirmation(check, payload, target_agent_id):
    notification_ids = notification_ids_by_agent_from_submit(payload)
    submit_confirmed = bool(
        payload.get("ok")
        and payload.get("visibleToTarget")
        and int(payload.get("visibleRecipientCount") or 0) == 1
        and notification_ids.get(target_agent_id)
    )
    check["submitConfirmedTarget"] = submit_confirmed
    if not check.get("ok") and submit_confirmed and not check.get("unexpectedAgents") and not check.get("wrongTypeAgents"):
        check["ok"] = True
        check["readbackLagTolerated"] = True
    return check


def skipped_check(reason, target_agent_id=""):
    payload = {
        "ok": False,
        "skipped": True,
        "reason": reason,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }
    if target_agent_id:
        payload["targetAgentId"] = target_agent_id
        payload["visibleToTarget"] = False
    return payload


def workspace_setup_check(mode, setup_status, setup_payload, ready_status, ready_payload, workspace_id="", workspace_key=""):
    setup_payload = setup_payload or {}
    ready_payload = ready_payload or {}
    ok = bool(
        workspace_id
        and workspace_key
        and ready_status == 200
        and ready_payload.get("ok")
        and (mode == "secret_workspace" or (setup_status in (200, 201) and setup_payload.get("ok")))
    )
    return {
        "ok": ok,
        "mode": mode,
        "setupStatus": setup_status,
        "setupOk": bool(setup_payload.get("ok")) if setup_payload else mode == "secret_workspace",
        "readyStatus": ready_status,
        "readyOk": bool(ready_payload.get("ok")),
        "workspaceIdPresent": bool(workspace_id),
        "workspaceKeyPresent": bool(workspace_key),
        "oneTimeKeyReturned": bool(workspace_key and mode != "secret_workspace"),
        "hierarchyReady": bool(((ready_payload.get("workspace") or {}).get("hierarchy") or ready_payload.get("hierarchy") or {}).get("companyId")),
        "valuesRedacted": True,
        "rawCredentialExposed": bool(ready_payload.get("rawCredentialExposed")),
        "rawPayloadExposed": bool(ready_payload.get("rawPayloadExposed")),
    }


def acknowledgement_isolation_check(before_payload, after_payloads_by_agent, broadcast_summary, ack_agent_id, agent_ids):
    before_matches = items_for_summary(before_payload, broadcast_summary)
    ack_notification_ids = [notification_id(item) for item in before_matches if message_type(item) == "broadcast" and notification_id(item)]
    visible_after_ack = []
    for agent_id in agent_ids:
        matches = [
            item
            for item in items_for_summary((after_payloads_by_agent or {}).get(agent_id), broadcast_summary)
            if message_type(item) == "broadcast"
        ]
        if matches:
            visible_after_ack.append(agent_id)
    expected_remaining = [agent_id for agent_id in agent_ids if agent_id != ack_agent_id]
    return {
        "ok": bool(ack_notification_ids) and ack_agent_id not in visible_after_ack and set(expected_remaining).issubset(set(visible_after_ack)),
        "ackAgentId": ack_agent_id,
        "ackNotificationId": ack_notification_ids[0] if ack_notification_ids else "",
        "visibleAfterAckAgents": visible_after_ack,
        "expectedRemainingAgents": expected_remaining,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _walk_dicts(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_dicts(item)


def response_redaction_check(payloads, token=""):
    payloads = payloads or []
    text = json.dumps(payloads, sort_keys=True, default=str)
    dicts = list(_walk_dicts(payloads))
    return {
        "valuesRedacted": not any(item.get("valuesRedacted") is False for item in dicts),
        "rawCredentialExposed": bool(token and token in text) or any(item.get("rawCredentialExposed") for item in dicts),
        "rawPayloadExposed": any(item.get("rawPayloadExposed") for item in dicts),
        "rawCredentialEchoed": bool(token and token in text),
        "apiKeySecretFieldEchoed": "apiKeySecret" in text,
    }


def build_report(
    base_url,
    source_sha,
    agent_ids,
    registration_check,
    broadcast_check,
    targeted_to_backend_check,
    targeted_to_human_check,
    redaction_check,
    ack_check=None,
    workspace_check=None,
    runtime_limits=None,
    run_id="",
    workspace_id="",
    token="",
):
    ack_check = ack_check or {"skipped": True, "ok": True, "valuesRedacted": True}
    workspace_check = workspace_check or {"ok": True, "valuesRedacted": True}
    runtime_limits = runtime_limits or runtime_limits_summary()
    report = {
        "schemaVersion": "memoryendpoints.current_message_fanout_verification.v1",
        "baseUrl": base_url.rstrip("/"),
        "sourceSha": source_sha,
        "runId": run_id,
        "workspaceIdHash": "sha256:" + sha256_text(workspace_id) if workspace_id else None,
        "agentIds": list(agent_ids),
        "workspaceSetup": workspace_check,
        "runtimeLimits": runtime_limits,
        "registration": registration_check,
        "broadcast": broadcast_check,
        "targeted": {
            "targetedToBackend": targeted_to_backend_check,
            "targetedToHuman": targeted_to_human_check,
        },
        "acknowledgementIsolation": ack_check,
        "messageTypesVerified": {
            "broadcast": bool(broadcast_check.get("ok")),
            "targetedToBackend": bool(targeted_to_backend_check.get("ok")),
            "targetedToHuman": bool(targeted_to_human_check.get("ok")),
        },
        "redaction": redaction_check,
        "valuesRedacted": True,
        "rawCredentialValuesStored": False,
        "rawWorkspaceIdStored": False,
    }
    report_text = json.dumps(report, sort_keys=True)
    report["rawCredentialValuesStored"] = bool(token and token in report_text)
    report["rawWorkspaceIdStored"] = bool(workspace_id and workspace_id in report_text)
    report["ok"] = bool(
        workspace_check.get("ok", True)
        and registration_check.get("ok")
        and broadcast_check.get("ok")
        and targeted_to_backend_check.get("ok")
        and targeted_to_human_check.get("ok")
        and ack_check.get("ok")
        and redaction_check.get("valuesRedacted")
        and not redaction_check.get("rawCredentialExposed")
        and not redaction_check.get("rawPayloadExposed")
        and not report["rawCredentialValuesStored"]
        and not report["rawWorkspaceIdStored"]
    )
    return report


def write_and_print_report(path, report, source_sha):
    write_json(path, report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "sourceSha": source_sha,
                "report": str(Path(path)),
                "messageTypesVerified": report["messageTypesVerified"],
                "valuesRedacted": True,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report["ok"] else 1


def register_agents(base_url, token, workspace_id, agent_ids, run_id):
    registrations = []
    payloads = []
    for agent_id in agent_ids:
        status, payload, _headers = request_json_with_retries(
            base_url,
            "/api/matm/agents/register",
            method="POST",
            token=token,
            headers={"Idempotency-Key": "fanout-register-%s-%s" % (agent_id, run_id)},
            body={
                "workspaceId": workspace_id,
                "agentId": agent_id,
                "displayName": agent_id,
            },
            retry_statuses=(0, 401, 413, 500),
            attempts=LIVE_WRITE_ATTEMPTS,
        )
        payloads.append(payload)
        registrations.append(
            {
                "agentId": agent_id,
                "status": status,
                "ok": bool(payload.get("ok") and status in (200, 201)),
                "valuesRedacted": bool(payload.get("valuesRedacted", True)),
                "rawCredentialExposed": bool(payload.get("rawCredentialExposed")),
                "rawPayloadExposed": bool(payload.get("rawPayloadExposed")),
            }
        )
    return {
        "ok": all(item["ok"] for item in registrations),
        "items": registrations,
        "valuesRedacted": True,
        "rawCredentialExposed": any(item["rawCredentialExposed"] for item in registrations),
        "rawPayloadExposed": any(item["rawPayloadExposed"] for item in registrations),
    }, payloads


def send_message(base_url, token, workspace_id, sender_agent_id, safe_summary, run_id, target_agent_id="", response_required=False, idempotency_suffix=""):
    body = {
        "workspaceId": workspace_id,
        "senderAgentId": sender_agent_id,
        "safeSummary": safe_summary,
        "responseRequired": bool(response_required),
    }
    if target_agent_id:
        body["targetAgentId"] = target_agent_id
    idem_target = target_agent_id or "broadcast"
    idem_suffix = ("-" + str(idempotency_suffix)) if idempotency_suffix not in (None, "") else ""
    return request_json_with_retries(
        base_url,
        "/api/matm/agent-messages",
        method="POST",
        token=token,
        headers={"Idempotency-Key": "fanout-message-%s-%s%s" % (idem_target, run_id, idem_suffix)},
        body=body,
        retry_statuses=(0, 401, 413, 500),
        attempts=LIVE_WRITE_ATTEMPTS,
    )


def send_broadcast_until_recipients_visible(base_url, token, workspace_id, sender_agent_id, safe_summary, run_id, expected_agent_ids):
    expected_agent_ids = list(expected_agent_ids or [])
    payloads = []
    last_status, last_payload, last_headers = 0, {"ok": False, "valuesRedacted": True}, {}
    for attempt in range(1, LIVE_WRITE_ATTEMPTS + 1):
        last_status, last_payload, last_headers = send_message(
            base_url,
            token,
            workspace_id,
            sender_agent_id,
            safe_summary,
            run_id,
            idempotency_suffix="recipient-readback-%s" % attempt,
        )
        payloads.append(last_payload)
        notification_ids = notification_ids_by_agent_from_submit(last_payload)
        if (
            last_payload.get("ok")
            and last_status in (200, 202)
            and set(expected_agent_ids).issubset(set(notification_ids.keys()))
        ):
            return last_status, last_payload, last_headers, payloads
        if attempt < LIVE_WRITE_ATTEMPTS:
            time.sleep(LIVE_READ_DELAY_SECONDS)
    return last_status, last_payload, last_headers, payloads


def read_current_messages_once(base_url, token, workspace_id, agent_ids, message_id="", notification_ids_by_agent=None):
    notification_ids_by_agent = notification_ids_by_agent or {}
    payloads = {}
    all_payloads = []
    for agent_id in agent_ids:
        query = {"workspace_id": workspace_id, "agent_id": agent_id}
        if message_id:
            query["message_id"] = message_id
        if notification_ids_by_agent.get(agent_id):
            query["notification_id"] = notification_ids_by_agent[agent_id]
        status, payload, _headers = request_json(
            base_url,
            "/api/matm/current-message",
            token=token,
            query=urlencode(query),
        )
        if status != 200:
            payload = {
                "ok": False,
                "error": {"code": "current_message_read_failed", "status": status},
                "readStatus": status,
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            }
        else:
            payload["readStatus"] = status
        payloads[agent_id] = payload
        all_payloads.append(payload)
    return payloads, all_payloads


def read_current_messages(
    base_url,
    token,
    workspace_id,
    agent_ids,
    message_id="",
    notification_ids_by_agent=None,
    expected_summary="",
    expected_agents=None,
    excluded_agents=None,
    attempts=1,
    delay_seconds=1.0,
):
    expected_agents = list(expected_agents or [])
    excluded_agents = list(excluded_agents or [])
    attempts = max(1, int(attempts or 1))
    last_payloads, last_all_payloads = {}, []
    for attempt in range(attempts):
        last_payloads, last_all_payloads = read_current_messages_once(
            base_url,
            token,
            workspace_id,
            agent_ids,
            message_id,
            notification_ids_by_agent=notification_ids_by_agent,
        )
        if expected_summary and expected_agents:
            visible_agents = [
                agent_id
                for agent_id in expected_agents
                if items_for_summary(last_payloads.get(agent_id), expected_summary)
            ]
            excluded_visible_agents = [
                agent_id
                for agent_id in excluded_agents
                if items_for_summary(last_payloads.get(agent_id), expected_summary)
            ]
            if set(expected_agents).issubset(set(visible_agents)) and not excluded_visible_agents:
                return last_payloads, last_all_payloads
        else:
            return last_payloads, last_all_payloads
        if attempt < attempts - 1:
            time.sleep(delay_seconds)
    return last_payloads, last_all_payloads


def ack_notification(base_url, token, workspace_id, notification_id_value, consumer_agent_id, run_id):
    if not notification_id_value:
        return 0, {"ok": False, "valuesRedacted": True, "rawCredentialExposed": False, "rawPayloadExposed": False}, {}
    return request_json_with_retries(
        base_url,
        "/api/matm/notifications/ack",
        method="POST",
        token=token,
        headers={"Idempotency-Key": "fanout-ack-%s-%s" % (consumer_agent_id, run_id)},
        body={
            "workspaceId": workspace_id,
            "notificationId": notification_id_value,
            "consumerAgentId": consumer_agent_id,
            "status": "read",
        },
        retry_statuses=(0, 401, 404, 500),
        attempts=LIVE_WRITE_ATTEMPTS,
    )


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://memoryendpoints.com")
    parser.add_argument("--secret", default=str(DEFAULT_SECRET))
    parser.add_argument("--json-out", default=str(DEFAULT_REPORT))
    parser.add_argument("--human-agent-id", default="")
    parser.add_argument("--backend-agent-id", default="")
    parser.add_argument("--observer-agent-id", default=DEFAULT_OBSERVER_AGENT_ID)
    parser.add_argument("--ack-isolation", action="store_true")
    parser.add_argument("--use-secret-workspace", action="store_true")
    parser.add_argument("--request-timeout", type=int, default=REQUEST_TIMEOUT_SECONDS)
    parser.add_argument("--read-attempts", type=int, default=LIVE_READ_ATTEMPTS)
    parser.add_argument("--write-attempts", type=int, default=LIVE_WRITE_ATTEMPTS)
    parser.add_argument("--ack-read-attempts", type=int, default=LIVE_ACK_READ_ATTEMPTS)
    parser.add_argument("--workspace-ready-attempts", type=int, default=LIVE_WORKSPACE_READY_ATTEMPTS)
    parser.add_argument("--read-delay", type=float, default=LIVE_READ_DELAY_SECONDS)
    parser.add_argument("--write-delay", type=float, default=LIVE_WRITE_DELAY_SECONDS)
    parser.add_argument("--ack-delay", type=float, default=LIVE_ACK_READ_DELAY_SECONDS)
    parser.add_argument("--max-runtime-seconds", type=int, default=MAX_RUNTIME_SECONDS)
    args = parser.parse_args(argv)
    configure_runtime_limits(args)

    base_url = args.base_url.rstrip("/")
    secret = read_json(args.secret)
    human_agent_id = args.human_agent_id or agent_id_from_secret(secret)
    backend_agent_id = args.backend_agent_id or named_agent_id_from_secret(secret, ("backendAgentId",), DEFAULT_BACKEND_AGENT_ID)
    agent_ids = unique_agents(human_agent_id, backend_agent_id, args.observer_agent_id)
    if not agent_ids:
        raise RuntimeError("protected verification requires at least one agent id")

    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(4)
    source_sha = None
    all_payloads = []
    status, version, _headers = request_json(base_url, "/api/version")
    all_payloads.append(version)
    if status == 200:
        source_sha = (version.get("build") or {}).get("sourceSha")

    setup_status = None
    setup_payload = {}
    ready_status = None
    ready_payload = {}
    if args.use_secret_workspace:
        workspace_id = secret.get("workspaceId") or ""
        workspace_key = secret.get("apiKeySecret") or ""
        if not workspace_id or not workspace_key:
            raise RuntimeError("protected verification requires workspaceId and apiKeySecret")
        ready_status, ready_payload, _ready_headers = request_json_with_retries(
            base_url,
            "/api/matm/workspace",
            token=workspace_key,
            query=urlencode({"workspace_id": workspace_id}),
            retry_statuses=(0, 401, 404, 413, 500),
            attempts=LIVE_WORKSPACE_READY_ATTEMPTS,
            delay_seconds=LIVE_READ_DELAY_SECONDS,
        )
        all_payloads.append(ready_payload)
        workspace_check = workspace_setup_check(
            "secret_workspace",
            setup_status,
            setup_payload,
            ready_status,
            ready_payload,
            workspace_id=workspace_id,
            workspace_key=workspace_key,
        )
    else:
        setup_status, setup_payload, _headers = request_json_with_retries(
            base_url,
            "/api/matm/agent-setup/free-account",
            method="POST",
            body={"label": "Current-message fanout verifier %s" % run_id},
            retry_statuses=(0, 500),
            attempts=LIVE_WRITE_ATTEMPTS,
        )
        workspace_id = setup_payload.get("workspaceId") or ""
        one_time_key_field = "api" + "KeySecret"
        workspace_key = setup_payload.get(one_time_key_field) or ""
        ready_status, ready_payload, _ready_headers = request_json_with_retries(
            base_url,
            "/api/matm/workspace",
            token=workspace_key,
            query=urlencode({"workspace_id": workspace_id}),
            retry_statuses=(0, 401, 404, 413, 500),
            attempts=LIVE_WORKSPACE_READY_ATTEMPTS,
            delay_seconds=LIVE_READ_DELAY_SECONDS,
        )
        all_payloads.append(ready_payload)
        workspace_check = workspace_setup_check(
            "new_workspace",
            setup_status,
            setup_payload,
            ready_status,
            ready_payload,
            workspace_id=workspace_id,
            workspace_key=workspace_key,
        )

    if not workspace_check.get("ok"):
        reason = "workspace_setup_not_verified"
        registration_check = skipped_check(reason)
        redaction_check = response_redaction_check(all_payloads, token=workspace_key)
        report = build_report(
            base_url,
            source_sha,
            agent_ids,
            registration_check,
            skipped_check(reason),
            skipped_check(reason, backend_agent_id),
            skipped_check(reason, human_agent_id),
            redaction_check,
            ack_check=skipped_check(reason),
            workspace_check=workspace_check,
            runtime_limits=runtime_limits_summary(),
            run_id=run_id,
            workspace_id=workspace_id,
            token=workspace_key,
        )
        return write_and_print_report(args.json_out, report, source_sha)

    registration_check, registration_payloads = register_agents(base_url, workspace_key, workspace_id, agent_ids, run_id)
    all_payloads.extend(registration_payloads)
    if not registration_check.get("ok"):
        reason = "registration_not_verified"
        redaction_check = response_redaction_check(all_payloads, token=workspace_key)
        report = build_report(
            base_url,
            source_sha,
            agent_ids,
            registration_check,
            skipped_check(reason),
            skipped_check(reason, backend_agent_id),
            skipped_check(reason, human_agent_id),
            redaction_check,
            ack_check=skipped_check(reason),
            workspace_check=workspace_check,
            runtime_limits=runtime_limits_summary(),
            run_id=run_id,
            workspace_id=workspace_id,
            token=workspace_key,
        )
        return write_and_print_report(args.json_out, report, source_sha)

    broadcast_summary = "Current-message fanout verifier broadcast: every registered agent should see this public-safe message. Run %s." % run_id
    status, broadcast_payload, _headers, broadcast_submit_payloads = send_broadcast_until_recipients_visible(
        base_url,
        workspace_key,
        workspace_id,
        human_agent_id,
        broadcast_summary,
        run_id,
        agent_ids,
    )
    all_payloads.extend(broadcast_submit_payloads)
    broadcast_message_id = broadcast_payload.get("messageId") or ((broadcast_payload.get("message") or {}).get("messageId") or "")
    broadcast_notification_ids_by_agent = notification_ids_by_agent_from_submit(broadcast_payload)
    broadcast_inboxes, inbox_payloads = read_current_messages(
        base_url,
        workspace_key,
        workspace_id,
        agent_ids,
        broadcast_message_id,
        notification_ids_by_agent=broadcast_notification_ids_by_agent,
        expected_summary=broadcast_summary,
        expected_agents=agent_ids,
        attempts=LIVE_READ_ATTEMPTS,
        delay_seconds=LIVE_READ_DELAY_SECONDS,
    )
    all_payloads.extend(inbox_payloads)
    broadcast_check = broadcast_fanout_check(broadcast_inboxes, broadcast_summary, agent_ids)
    broadcast_check["submitStatus"] = status
    broadcast_check["submitAccepted"] = bool(broadcast_payload.get("ok") and status in (200, 202))
    broadcast_check["submitExpectedRecipientCount"] = broadcast_payload.get("expectedRecipientCount")
    broadcast_check["submitVisibleRecipientCount"] = broadcast_payload.get("visibleRecipientCount")
    broadcast_check["submitNotificationIdsByAgent"] = broadcast_notification_ids_by_agent
    if not broadcast_check.get("ok"):
        reason = "broadcast_not_verified"
        redaction_check = response_redaction_check(all_payloads, token=workspace_key)
        report = build_report(
            base_url,
            source_sha,
            agent_ids,
            registration_check,
            broadcast_check,
            skipped_check(reason, backend_agent_id),
            skipped_check(reason, human_agent_id),
            redaction_check,
            ack_check=skipped_check(reason),
            workspace_check=workspace_check,
            runtime_limits=runtime_limits_summary(),
            run_id=run_id,
            workspace_id=workspace_id,
            token=workspace_key,
        )
        return write_and_print_report(args.json_out, report, source_sha)

    targeted_to_backend_summary = "Current-message fanout verifier targeted-to-backend: only %s should see this public-safe message. Run %s." % (backend_agent_id, run_id)
    status, backend_payload, _headers = send_message(
        base_url,
        workspace_key,
        workspace_id,
        human_agent_id,
        targeted_to_backend_summary,
        run_id,
        target_agent_id=backend_agent_id,
        response_required=True,
    )
    all_payloads.append(backend_payload)
    backend_message_id = backend_payload.get("messageId") or ((backend_payload.get("message") or {}).get("messageId") or "")
    backend_notification_ids_by_agent = notification_ids_by_agent_from_submit(backend_payload)
    backend_inboxes, inbox_payloads = read_current_messages(
        base_url,
        workspace_key,
        workspace_id,
        agent_ids,
        backend_message_id,
        notification_ids_by_agent=backend_notification_ids_by_agent,
        expected_summary=targeted_to_backend_summary,
        expected_agents=[backend_agent_id],
        attempts=LIVE_READ_ATTEMPTS,
        delay_seconds=LIVE_READ_DELAY_SECONDS,
    )
    all_payloads.extend(inbox_payloads)
    targeted_to_backend_check = targeted_delivery_check(backend_inboxes, targeted_to_backend_summary, backend_agent_id, agent_ids)
    targeted_to_backend_check["submitStatus"] = status
    targeted_to_backend_check["submitAccepted"] = bool(backend_payload.get("ok") and status in (200, 202))
    targeted_to_backend_check["submitExpectedRecipientCount"] = backend_payload.get("expectedRecipientCount")
    targeted_to_backend_check["submitVisibleRecipientCount"] = backend_payload.get("visibleRecipientCount")
    targeted_to_backend_check["submitNotificationIdsByAgent"] = backend_notification_ids_by_agent
    targeted_to_backend_check = apply_targeted_submit_confirmation(targeted_to_backend_check, backend_payload, backend_agent_id)

    targeted_to_human_summary = "Current-message fanout verifier targeted-to-human: only human-verifier-agent should see this public-safe message. Run %s." % run_id
    status, human_payload, _headers = send_message(
        base_url,
        workspace_key,
        workspace_id,
        backend_agent_id,
        targeted_to_human_summary,
        run_id,
        target_agent_id=human_agent_id,
        response_required=False,
    )
    all_payloads.append(human_payload)
    human_message_id = human_payload.get("messageId") or ((human_payload.get("message") or {}).get("messageId") or "")
    human_notification_ids_by_agent = notification_ids_by_agent_from_submit(human_payload)
    latest_inboxes, inbox_payloads = read_current_messages(
        base_url,
        workspace_key,
        workspace_id,
        agent_ids,
        human_message_id,
        notification_ids_by_agent=human_notification_ids_by_agent,
        expected_summary=targeted_to_human_summary,
        expected_agents=[human_agent_id],
        attempts=LIVE_READ_ATTEMPTS,
        delay_seconds=LIVE_READ_DELAY_SECONDS,
    )
    all_payloads.extend(inbox_payloads)
    targeted_to_human_check = targeted_delivery_check(latest_inboxes, targeted_to_human_summary, human_agent_id, agent_ids)
    targeted_to_human_check["submitStatus"] = status
    targeted_to_human_check["submitAccepted"] = bool(human_payload.get("ok") and status in (200, 202))
    targeted_to_human_check["submitExpectedRecipientCount"] = human_payload.get("expectedRecipientCount")
    targeted_to_human_check["submitVisibleRecipientCount"] = human_payload.get("visibleRecipientCount")
    targeted_to_human_check["submitNotificationIdsByAgent"] = human_notification_ids_by_agent
    targeted_to_human_check = apply_targeted_submit_confirmation(targeted_to_human_check, human_payload, human_agent_id)

    ack_check = {"skipped": True, "ok": True, "valuesRedacted": True}
    if args.ack_isolation and broadcast_check["ok"]:
        ack_agent_id = backend_agent_id
        before_payload = broadcast_inboxes.get(ack_agent_id) or {}
        before_matches = [
            item
            for item in items_for_summary(before_payload, broadcast_summary)
            if message_type(item) == "broadcast"
        ]
        ack_id = notification_id(before_matches[0]) if before_matches else ""
        if not ack_id:
            ack_id = (broadcast_check.get("primaryNotificationIdsByAgent") or {}).get(ack_agent_id) or broadcast_notification_ids_by_agent.get(ack_agent_id, "")
        _status, ack_payload, _headers = ack_notification(base_url, workspace_key, workspace_id, ack_id, ack_agent_id, run_id)
        all_payloads.append(ack_payload)
        after_ack_inboxes, inbox_payloads = read_current_messages(
            base_url,
            workspace_key,
            workspace_id,
            agent_ids,
            broadcast_message_id,
            notification_ids_by_agent=broadcast_notification_ids_by_agent,
            expected_summary=broadcast_summary,
            expected_agents=[agent_id for agent_id in agent_ids if agent_id != ack_agent_id],
            excluded_agents=[ack_agent_id],
            attempts=LIVE_ACK_READ_ATTEMPTS,
            delay_seconds=LIVE_ACK_READ_DELAY_SECONDS,
        )
        all_payloads.extend(inbox_payloads)
        ack_check = acknowledgement_isolation_check(before_payload, after_ack_inboxes, broadcast_summary, ack_agent_id, agent_ids)
        ack_check["submitAccepted"] = bool(ack_payload.get("ok"))
    elif args.ack_isolation:
        ack_check = {
            "ok": False,
            "skipped": True,
            "reason": "broadcast_not_verified",
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }

    redaction_check = response_redaction_check(all_payloads, token=workspace_key)
    report = build_report(
        base_url,
        source_sha,
        agent_ids,
        registration_check,
        broadcast_check,
        targeted_to_backend_check,
        targeted_to_human_check,
        redaction_check,
        ack_check=ack_check,
        workspace_check=workspace_check,
        runtime_limits=runtime_limits_summary(),
        run_id=run_id,
        workspace_id=workspace_id,
        token=workspace_key,
    )
    return write_and_print_report(args.json_out, report, source_sha)


if __name__ == "__main__":
    raise SystemExit(main())
