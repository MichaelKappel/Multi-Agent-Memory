import argparse
import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SECRET = ROOT / ".local-secrets" / "human-verifier-account.json"
DEFAULT_REPORT = ROOT / "docs" / "reports" / "long-term-memory-promotion.json"
MIGRATION_QUERY = "long-term-memory-migration"
SOURCE_PREFIX = "docs/long-term-memory/"
REVIEW_NOTE = "Public-safe long-term memory migration review accepted for hosted dogfood memory."


def sha256_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def display_path(path):
    try:
        return str(Path(path).resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


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
        with urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {
                "ok": False,
                "valuesRedacted": True,
                "error": {"code": "non_json_http_error", "status": exc.code, "valuesRedacted": True},
            }
        return exc.code, payload


def require_ok(status, payload, step):
    if not (200 <= int(status) < 300) or not payload.get("ok"):
        code = (payload.get("error") or {}).get("code") or "unknown"
        raise RuntimeError("%s failed with status %s and code %s" % (step, status, code))
    return payload


def fetch_search(base_url, token, workspace_id):
    status, payload = call_json(
        base_url,
        "/api/matm/search",
        token=token,
        query=urlencode({"workspace_id": workspace_id, "q": MIGRATION_QUERY}),
    )
    return require_ok(status, payload, "search hosted migration memory")


def fetch_reviews(base_url, token, workspace_id):
    status, payload = call_json(
        base_url,
        "/api/matm/review-queue",
        token=token,
        query=urlencode({"workspace_id": workspace_id}),
    )
    return require_ok(status, payload, "read review queue")


def target_memory_items(search_payload):
    items = []
    for item in search_payload.get("items") or []:
        source = item.get("source") or ""
        tags = item.get("tags") or []
        if source.startswith(SOURCE_PREFIX) and MIGRATION_QUERY in tags:
            items.append(item)
    return sorted(items, key=lambda item: item.get("source") or item.get("eventId") or "")


def build_plan(memory_items, review_items):
    reviews_by_memory = {item.get("memoryEventId"): item for item in review_items if item.get("memoryEventId")}
    planned = []
    for memory in memory_items:
        review = reviews_by_memory.get(memory.get("eventId"))
        if memory.get("reviewStatus") == "promoted" and memory.get("promotionState") == "promoted":
            action = "already_promoted"
        elif not review:
            action = "missing_review"
        elif review.get("status") == "promoted":
            action = "already_promoted"
        elif review.get("status") == "pending" and review.get("firewallDecision") == "accepted":
            action = "promote"
        else:
            action = "skip"
        planned.append(
            {
                "action": action,
                "eventId": memory.get("eventId"),
                "reviewId": review.get("reviewId") if review else None,
                "title": memory.get("title"),
                "source": memory.get("source"),
                "memoryType": memory.get("memoryType"),
                "reviewStatusBefore": memory.get("reviewStatus"),
                "promotionStateBefore": memory.get("promotionState"),
                "reviewQueueStatusBefore": review.get("status") if review else None,
                "reviewerAgentIdBefore": review.get("reviewerAgentId") if review else None,
                "firewallDecision": review.get("firewallDecision") if review else None,
                "valuesRedacted": True,
            }
        )
    return planned


def promote_item(base_url, token, workspace_id, reviewer_agent_id, planned):
    if planned["action"] != "promote":
        return dict(planned, httpStatus=None, promoted=planned["action"] == "already_promoted")
    body = {
        "workspaceId": workspace_id,
        "reviewId": planned["reviewId"],
        "reviewerAgentId": reviewer_agent_id,
        "decision": "promote",
        "reviewNote": REVIEW_NOTE,
    }
    status, payload = call_json(
        base_url,
        "/api/matm/review-queue/decide",
        method="POST",
        token=token,
        idempotency_key="ltm-review-promote-" + planned["reviewId"],
        body=body,
    )
    require_ok(status, payload, "promote %s" % planned["reviewId"])
    review = payload.get("review") or {}
    payload_text = json.dumps(payload, sort_keys=True)
    return dict(
        planned,
        httpStatus=status,
        promoted=review.get("status") == "promoted",
        reviewStatusAfter=review.get("status"),
        reviewerAgentId=review.get("reviewerAgentId"),
        reviewNoteReturnedVerbatim=REVIEW_NOTE in payload_text,
    )


def verification_summary(search_payload):
    items = target_memory_items(search_payload)
    return {
        "count": len(items),
        "allPromoted": all(item.get("reviewStatus") == "promoted" and item.get("promotionState") == "promoted" for item in items),
        "items": [
            {
                "eventId": item.get("eventId"),
                "title": item.get("title"),
                "source": item.get("source"),
                "reviewStatus": item.get("reviewStatus"),
                "promotionState": item.get("promotionState"),
                "valuesRedacted": True,
            }
            for item in items
        ],
        "memorySource": search_payload.get("memorySource"),
        "filesystemDocsIncluded": search_payload.get("filesystemDocsIncluded"),
        "valuesRedacted": True,
    }


def build_report(base_url, workspace_id, token, reviewer_agent_id, mode, plan, results, verification):
    if mode == "live_apply":
        ok = (
            len(plan) > 0
            and verification["allPromoted"]
            and verification.get("memorySource") == "hosted_workspace_store"
            and verification.get("filesystemDocsIncluded") is False
            and not any(item.get("reviewNoteReturnedVerbatim") for item in results)
        )
    else:
        ok = len(plan) > 0 and verification.get("memorySource") == "hosted_workspace_store" and verification.get("filesystemDocsIncluded") is False
    report = {
        "schemaVersion": "memoryendpoints.long_term_memory_promotion.v1",
        "mode": mode,
        "baseUrl": base_url,
        "workspaceIdHash": "sha256:" + sha256_text(workspace_id),
        "reviewerAgentId": reviewer_agent_id,
        "targetQuery": MIGRATION_QUERY,
        "targetSourcePrefix": SOURCE_PREFIX,
        "targetCount": len(plan),
        "wouldPromoteCount": sum(1 for item in plan if item.get("action") == "promote"),
        "promotedCount": sum(1 for item in results if item.get("promoted")),
        "alreadyPromotedCount": sum(1 for item in results if item.get("action") == "already_promoted"),
        "skippedCount": sum(1 for item in results if item.get("action") not in ("promote", "already_promoted")),
        "results": results,
        "verification": verification,
        "ok": ok,
        "valuesRedacted": True,
        "rawCredentialValuesStored": False,
        "rawWorkspaceIdStored": False,
    }
    report_text = json.dumps(report, sort_keys=True)
    report["rawCredentialValuesStored"] = bool(token and token in report_text)
    report["rawWorkspaceIdStored"] = bool(workspace_id and workspace_id in report_text)
    report["ok"] = bool(report["ok"] and not report["rawCredentialValuesStored"] and not report["rawWorkspaceIdStored"])
    return report


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://memoryendpoints.com")
    parser.add_argument("--secret", default=str(DEFAULT_SECRET))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT))
    parser.add_argument("--reviewer-agent-id", default="")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    secret = read_json(args.secret)
    token = secret.get("apiKeySecret") or ""
    workspace_id = secret.get("workspaceId") or ""
    if not token:
        raise RuntimeError("secret file does not contain apiKeySecret")
    if not workspace_id:
        raise RuntimeError("secret file does not contain workspaceId")
    reviewer_agent_id = args.reviewer_agent_id or secret.get("humanAgentId") or "human-verifier-agent"

    search_before = fetch_search(base_url, token, workspace_id)
    reviews = fetch_reviews(base_url, token, workspace_id)
    plan = build_plan(target_memory_items(search_before), reviews.get("items") or [])
    if args.apply:
        results = [promote_item(base_url, token, workspace_id, reviewer_agent_id, item) for item in plan]
        mode = "live_apply"
    else:
        results = [dict(item, httpStatus=None, promoted=item.get("action") == "already_promoted") for item in plan]
        mode = "dry_run"
    search_after = fetch_search(base_url, token, workspace_id)
    verification = verification_summary(search_after)
    report = build_report(base_url, workspace_id, token, reviewer_agent_id, mode, plan, results, verification)
    write_json(args.report_out, report)
    print(json.dumps({"ok": report["ok"], "mode": mode, "targetCount": report["targetCount"], "wouldPromoteCount": report["wouldPromoteCount"], "promotedCount": report["promotedCount"], "alreadyPromotedCount": report["alreadyPromotedCount"], "report": display_path(args.report_out), "valuesRedacted": True}, indent=2, sort_keys=True))
    return 0 if report["ok"] and not report["rawCredentialValuesStored"] and not report["rawWorkspaceIdStored"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
