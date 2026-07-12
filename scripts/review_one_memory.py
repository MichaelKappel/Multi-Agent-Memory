import argparse
import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SECRET = ROOT / ".local-secrets" / "human-verifier-account.json"
DEFAULT_REPORT = ROOT / "var" / "reports" / "single-memory-review.json"


def sha256_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def call_json(base_url, path, method="GET", body=None, token=None, idempotency_key=None, query=None):
    url = base_url.rstrip("/") + path
    if query:
        url += "?" + query
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    data = None
    if body is not None:
        data = json.dumps(body, sort_keys=True).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {"ok": False, "error": {"code": "non_json_http_error", "status": exc.code}, "valuesRedacted": True}
        return exc.code, payload


def require_ok(status, payload, step):
    if not (200 <= int(status) < 300) or not payload.get("ok"):
        code = (payload.get("error") or {}).get("code") or "unknown"
        raise RuntimeError("%s failed with status %s and code %s" % (step, status, code))
    return payload


def memory_event_id(args):
    direct = str(args.memory_event_id or "").strip()
    from_report = ""
    if args.ingest_report:
        from_report = str(read_json(args.ingest_report).get("memoryEventId") or "").strip()
        if not from_report:
            raise RuntimeError("ingestion report does not contain memoryEventId")
    if direct and from_report and direct != from_report:
        raise RuntimeError("--memory-event-id does not match --ingest-report")
    value = direct or from_report
    if not value:
        raise RuntimeError("provide --memory-event-id or --ingest-report")
    return value


def fetch_reviews(base_url, token, workspace_id):
    status, payload = call_json(
        base_url,
        "/api/matm/review-queue",
        token=token,
        query=urlencode({"workspace_id": workspace_id}),
    )
    return require_ok(status, payload, "read review queue")


def find_review(payload, event_id):
    matches = [item for item in payload.get("items") or [] if item.get("memoryEventId") == event_id]
    if not matches:
        raise RuntimeError("no review queue item matches the memory event")
    if len(matches) > 1:
        raise RuntimeError("multiple review queue items match the memory event")
    return matches[0]


def expected_status(decision):
    return {"promote": "promoted", "reject": "rejected", "quarantine": "quarantined"}[decision]


def build_plan(review, decision):
    target_status = expected_status(decision)
    current_status = review.get("status") or ""
    if current_status == target_status:
        action = "already_decided"
    elif decision == "promote" and current_status == "pending" and review.get("firewallDecision") == "accepted":
        action = "decide"
    elif decision in ("reject", "quarantine") and current_status in ("pending", "quarantined"):
        action = "decide"
    else:
        raise RuntimeError(
            "review cannot transition from %s with firewall decision %s to %s"
            % (current_status or "unknown", review.get("firewallDecision") or "unknown", target_status)
        )
    return {
        "action": action,
        "memoryEventId": review.get("memoryEventId"),
        "reviewId": review.get("reviewId"),
        "statusBefore": current_status,
        "firewallDecision": review.get("firewallDecision"),
        "decision": decision,
        "expectedStatus": target_status,
        "valuesRedacted": True,
    }


def decide(base_url, token, workspace_id, reviewer_agent_id, review_note, plan):
    if plan["action"] == "already_decided":
        return {"httpStatus": None, "idempotentReplay": True, "status": plan["expectedStatus"], "valuesRedacted": True}
    body = {
        "workspaceId": workspace_id,
        "reviewId": plan["reviewId"],
        "reviewerAgentId": reviewer_agent_id,
        "decision": plan["decision"],
        "reviewNote": review_note,
    }
    status, payload = call_json(
        base_url,
        "/api/matm/review-queue/decide",
        method="POST",
        body=body,
        token=token,
        idempotency_key="single-memory-review-" + sha256_text(plan["reviewId"] + plan["decision"])[:24],
    )
    payload = require_ok(status, payload, "decide review")
    review = payload.get("review") or {}
    return {
        "httpStatus": status,
        "idempotentReplay": bool(payload.get("idempotentReplay")),
        "status": review.get("status"),
        "reviewerAgentId": review.get("reviewerAgentId"),
        "reviewNoteExposed": review_note in json.dumps(payload, sort_keys=True),
        "rawCredentialExposed": bool(payload.get("rawCredentialExposed")),
        "rawPayloadExposed": bool(payload.get("rawPayloadExposed")),
        "valuesRedacted": True,
    }


def build_report(args, token, workspace_id, event_id, plan, result, readback, review_note):
    report = {
        "schemaVersion": "memoryendpoints.single_memory_review.v1",
        "mode": "live_apply" if args.apply else "dry_run",
        "baseUrl": args.base_url.rstrip("/"),
        "memoryEventId": event_id,
        "reviewId": plan["reviewId"],
        "decision": plan["decision"],
        "action": plan["action"],
        "statusBefore": plan["statusBefore"],
        "statusAfter": readback.get("status"),
        "firewallDecision": plan["firewallDecision"],
        "reviewNoteHash": "sha256:" + sha256_text(review_note),
        "reviewNoteStored": False,
        "result": result,
        "readbackMatched": readback.get("memoryEventId") == event_id and readback.get("reviewId") == plan["reviewId"],
        "workspaceIdHash": "sha256:" + sha256_text(workspace_id),
        "rawWorkspaceIdStored": False,
        "rawCredentialValuesStored": False,
        "valuesRedacted": True,
    }
    expected = plan["statusBefore"] if not args.apply else plan["expectedStatus"]
    report["ok"] = bool(
        report["readbackMatched"]
        and report["statusAfter"] == expected
        and not result.get("reviewNoteExposed")
        and not result.get("rawCredentialExposed")
        and not result.get("rawPayloadExposed")
    )
    serialized = json.dumps(report, sort_keys=True)
    report["rawWorkspaceIdStored"] = workspace_id in serialized
    report["rawCredentialValuesStored"] = token in serialized
    report["ok"] = bool(report["ok"] and not report["rawWorkspaceIdStored"] and not report["rawCredentialValuesStored"])
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Review exactly one protected memory event and verify its resulting state.")
    parser.add_argument("--base-url", default="https://memoryendpoints.com")
    parser.add_argument("--secret", default=str(DEFAULT_SECRET))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT))
    parser.add_argument("--ingest-report", default="")
    parser.add_argument("--memory-event-id", default="")
    parser.add_argument("--reviewer-agent-id", default="")
    parser.add_argument("--decision", choices=["promote", "reject", "quarantine"], default="promote")
    parser.add_argument("--review-note", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    secret = read_json(args.secret)
    token = str(secret.get("apiKeySecret") or "")
    workspace_id = str(secret.get("workspaceId") or "")
    reviewer_agent_id = args.reviewer_agent_id or secret.get("humanAgentId") or "human-verifier-agent"
    if not token or not workspace_id:
        raise RuntimeError("secret file must contain apiKeySecret and workspaceId")
    if not args.review_note.strip():
        raise RuntimeError("--review-note must not be empty")

    event_id = memory_event_id(args)
    before = find_review(fetch_reviews(args.base_url, token, workspace_id), event_id)
    plan = build_plan(before, args.decision)
    result = (
        decide(args.base_url, token, workspace_id, reviewer_agent_id, args.review_note, plan)
        if args.apply
        else {"httpStatus": None, "valuesRedacted": True}
    )
    after = find_review(fetch_reviews(args.base_url, token, workspace_id), event_id)
    report = build_report(args, token, workspace_id, event_id, plan, result, after, args.review_note)
    write_json(args.report_out, report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "mode": report["mode"],
                "decision": report["decision"],
                "statusAfter": report["statusAfter"],
                "report": str(args.report_out),
                "bulkReview": False,
                "valuesRedacted": True,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
