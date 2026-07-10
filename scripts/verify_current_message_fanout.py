import argparse
import datetime
import hashlib
import json
import secrets
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SECRET = ROOT / ".local-secrets" / "human-verifier-account.json"
DEFAULT_REPORT = ROOT / "docs" / "reports" / "current-message-fanout-verification.json"
DEFAULT_HUMAN_AGENT_ID = "human-verifier-agent"
DEFAULT_CODEX_AGENT_ID = "codex-agent"
DEFAULT_OBSERVER_AGENT_ID = "swarm-observer-agent"


def sha256_text(value):
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def request_json(base_url, path, method="GET", token=None, query=None, headers=None, body=None):
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
    try:
        with urlopen(request, timeout=30) as response:
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


def agent_id_from_secret(secret, fallback=DEFAULT_HUMAN_AGENT_ID):
    for key in ("humanAgentId", "agentId", "defaultAgentId"):
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


def items_for_summary(payload, safe_summary):
    return [item for item in inbox_items(payload) if message_summary(item) == safe_summary]


def delivery_counts(payload):
    counts = (payload or {}).get("deliveryCounts") or {}
    return {
        "broadcast": int(counts.get("broadcast") or 0),
        "targeted": int(counts.get("targeted") or 0),
    }


def broadcast_fanout_check(inboxes_by_agent, broadcast_summary, agent_ids):
    visible_agents = []
    visible_any_type_agents = []
    wrong_type_agents = []
    notification_ids_by_agent = {}
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
        elif matches:
            wrong_type_agents.append(agent_id)
    missing_agents = [agent_id for agent_id in agent_ids if agent_id not in visible_any_type_agents]
    return {
        "ok": len(visible_agents) == len(agent_ids) and not missing_agents and not wrong_type_agents,
        "checkedAgents": list(agent_ids),
        "visibleAgents": visible_agents,
        "visibleAnyTypeAgents": visible_any_type_agents,
        "missingAgents": missing_agents,
        "wrongTypeAgents": wrong_type_agents,
        "expectedRecipientCount": len(agent_ids),
        "visibleRecipientCount": len(visible_agents),
        "deliveryCountsByAgent": {
            agent_id: delivery_counts((inboxes_by_agent or {}).get(agent_id)) for agent_id in agent_ids
        },
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
        "notificationIdsByAgent": notification_ids_by_agent,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
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
    targeted_to_codex_check,
    targeted_to_human_check,
    redaction_check,
    ack_check=None,
    workspace_id="",
    token="",
):
    ack_check = ack_check or {"skipped": True, "ok": True, "valuesRedacted": True}
    report = {
        "schemaVersion": "memoryendpoints.current_message_fanout_verification.v1",
        "baseUrl": base_url.rstrip("/"),
        "sourceSha": source_sha,
        "workspaceIdHash": "sha256:" + sha256_text(workspace_id) if workspace_id else None,
        "agentIds": list(agent_ids),
        "registration": registration_check,
        "broadcast": broadcast_check,
        "targeted": {
            "targetedToCodex": targeted_to_codex_check,
            "targetedToHuman": targeted_to_human_check,
        },
        "acknowledgementIsolation": ack_check,
        "messageTypesVerified": {
            "broadcast": bool(broadcast_check.get("ok")),
            "targetedToCodex": bool(targeted_to_codex_check.get("ok")),
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
        registration_check.get("ok")
        and broadcast_check.get("ok")
        and targeted_to_codex_check.get("ok")
        and targeted_to_human_check.get("ok")
        and ack_check.get("ok")
        and redaction_check.get("valuesRedacted")
        and not redaction_check.get("rawCredentialExposed")
        and not redaction_check.get("rawPayloadExposed")
        and not report["rawCredentialValuesStored"]
        and not report["rawWorkspaceIdStored"]
    )
    return report


def register_agents(base_url, token, workspace_id, agent_ids, run_id):
    registrations = []
    payloads = []
    for agent_id in agent_ids:
        status, payload, _headers = request_json(
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


def send_message(base_url, token, workspace_id, sender_agent_id, safe_summary, run_id, target_agent_id="", response_required=False):
    body = {
        "workspaceId": workspace_id,
        "senderAgentId": sender_agent_id,
        "safeSummary": safe_summary,
        "responseRequired": bool(response_required),
    }
    if target_agent_id:
        body["targetAgentId"] = target_agent_id
    idem_target = target_agent_id or "broadcast"
    return request_json(
        base_url,
        "/api/matm/agent-messages",
        method="POST",
        token=token,
        headers={"Idempotency-Key": "fanout-message-%s-%s" % (idem_target, run_id)},
        body=body,
    )


def read_current_messages(base_url, token, workspace_id, agent_ids):
    payloads = {}
    all_payloads = []
    for agent_id in agent_ids:
        status, payload, _headers = request_json(
            base_url,
            "/api/matm/current-message",
            token=token,
            query=urlencode({"workspace_id": workspace_id, "agent_id": agent_id}),
        )
        if status != 200:
            payload = {
                "ok": False,
                "error": {"code": "current_message_read_failed", "status": status},
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            }
        payloads[agent_id] = payload
        all_payloads.append(payload)
    return payloads, all_payloads


def ack_notification(base_url, token, workspace_id, notification_id_value, consumer_agent_id, run_id):
    if not notification_id_value:
        return 0, {"ok": False, "valuesRedacted": True, "rawCredentialExposed": False, "rawPayloadExposed": False}, {}
    return request_json(
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
    )


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://memoryendpoints.com")
    parser.add_argument("--secret", default=str(DEFAULT_SECRET))
    parser.add_argument("--json-out", default=str(DEFAULT_REPORT))
    parser.add_argument("--human-agent-id", default="")
    parser.add_argument("--codex-agent-id", default=DEFAULT_CODEX_AGENT_ID)
    parser.add_argument("--observer-agent-id", default=DEFAULT_OBSERVER_AGENT_ID)
    parser.add_argument("--ack-isolation", action="store_true")
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    secret = read_json(args.secret)
    workspace_id = secret.get("workspaceId") or ""
    token = secret.get("apiKeySecret") or ""
    human_agent_id = args.human_agent_id or agent_id_from_secret(secret)
    agent_ids = unique_agents(human_agent_id, args.codex_agent_id, args.observer_agent_id)
    if not workspace_id or not token:
        raise RuntimeError("protected verification requires workspaceId and apiKeySecret")
    if not agent_ids:
        raise RuntimeError("protected verification requires at least one agent id")

    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(4)
    source_sha = None
    all_payloads = []
    status, version, _headers = request_json(base_url, "/api/version")
    all_payloads.append(version)
    if status == 200:
        source_sha = (version.get("build") or {}).get("sourceSha")

    registration_check, registration_payloads = register_agents(base_url, token, workspace_id, agent_ids, run_id)
    all_payloads.extend(registration_payloads)

    broadcast_summary = "Current-message fanout verifier broadcast: every registered agent should see this public-safe message. Run %s." % run_id
    status, broadcast_payload, _headers = send_message(
        base_url,
        token,
        workspace_id,
        human_agent_id,
        broadcast_summary,
        run_id,
    )
    all_payloads.append(broadcast_payload)
    broadcast_inboxes, inbox_payloads = read_current_messages(base_url, token, workspace_id, agent_ids)
    all_payloads.extend(inbox_payloads)
    broadcast_check = broadcast_fanout_check(broadcast_inboxes, broadcast_summary, agent_ids)
    broadcast_check["submitStatus"] = status
    broadcast_check["submitAccepted"] = bool(broadcast_payload.get("ok") and status in (200, 202))

    targeted_to_codex_summary = "Current-message fanout verifier targeted-to-Codex: only codex-agent should see this public-safe message. Run %s." % run_id
    status, codex_payload, _headers = send_message(
        base_url,
        token,
        workspace_id,
        human_agent_id,
        targeted_to_codex_summary,
        run_id,
        target_agent_id=args.codex_agent_id,
        response_required=True,
    )
    all_payloads.append(codex_payload)
    codex_inboxes, inbox_payloads = read_current_messages(base_url, token, workspace_id, agent_ids)
    all_payloads.extend(inbox_payloads)
    targeted_to_codex_check = targeted_delivery_check(codex_inboxes, targeted_to_codex_summary, args.codex_agent_id, agent_ids)
    targeted_to_codex_check["submitStatus"] = status
    targeted_to_codex_check["submitAccepted"] = bool(codex_payload.get("ok") and status in (200, 202))

    targeted_to_human_summary = "Current-message fanout verifier targeted-to-human: only human-verifier-agent should see this public-safe message. Run %s." % run_id
    status, human_payload, _headers = send_message(
        base_url,
        token,
        workspace_id,
        args.codex_agent_id,
        targeted_to_human_summary,
        run_id,
        target_agent_id=human_agent_id,
        response_required=False,
    )
    all_payloads.append(human_payload)
    latest_inboxes, inbox_payloads = read_current_messages(base_url, token, workspace_id, agent_ids)
    all_payloads.extend(inbox_payloads)
    targeted_to_human_check = targeted_delivery_check(latest_inboxes, targeted_to_human_summary, human_agent_id, agent_ids)
    targeted_to_human_check["submitStatus"] = status
    targeted_to_human_check["submitAccepted"] = bool(human_payload.get("ok") and status in (200, 202))

    ack_check = {"skipped": True, "ok": True, "valuesRedacted": True}
    if args.ack_isolation:
        ack_agent_id = args.codex_agent_id
        before_payload = latest_inboxes.get(ack_agent_id) or {}
        before_matches = [
            item
            for item in items_for_summary(before_payload, broadcast_summary)
            if message_type(item) == "broadcast"
        ]
        ack_id = notification_id(before_matches[0]) if before_matches else ""
        _status, ack_payload, _headers = ack_notification(base_url, token, workspace_id, ack_id, ack_agent_id, run_id)
        all_payloads.append(ack_payload)
        after_ack_inboxes, inbox_payloads = read_current_messages(base_url, token, workspace_id, agent_ids)
        all_payloads.extend(inbox_payloads)
        ack_check = acknowledgement_isolation_check(before_payload, after_ack_inboxes, broadcast_summary, ack_agent_id, agent_ids)
        ack_check["submitAccepted"] = bool(ack_payload.get("ok"))

    redaction_check = response_redaction_check(all_payloads, token=token)
    report = build_report(
        base_url,
        source_sha,
        agent_ids,
        registration_check,
        broadcast_check,
        targeted_to_codex_check,
        targeted_to_human_check,
        redaction_check,
        ack_check=ack_check,
        workspace_id=workspace_id,
        token=token,
    )
    write_json(args.json_out, report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "sourceSha": source_sha,
                "report": str(Path(args.json_out)),
                "messageTypesVerified": report["messageTypesVerified"],
                "valuesRedacted": True,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
