import argparse
import json
from pathlib import Path

try:
    from scripts.promote_long_term_memory_reviews import (
        DEFAULT_SECRET,
        ROOT,
        SOURCE_PREFIX,
        call_json,
        display_path,
        fetch_reviews,
        read_json,
        require_ok,
        sha256_text,
        write_json,
    )
except ImportError:
    from promote_long_term_memory_reviews import (
        DEFAULT_SECRET,
        ROOT,
        SOURCE_PREFIX,
        call_json,
        display_path,
        fetch_reviews,
        read_json,
        require_ok,
        sha256_text,
        write_json,
    )


DEFAULT_REPORT = ROOT / "docs" / "reports" / "long-term-memory-duplicate-cleanup.json"
DUPLICATE_TAGS = ("docs-seed", "dogfood-migration")
DUPLICATE_SUMMARY_PREFIX = "Deep link: docs/long-term-memory/"


def fetch_search(base_url, token, workspace_id, query):
    from urllib.parse import urlencode

    status, payload = call_json(
        base_url,
        "/api/matm/search",
        token=token,
        query=urlencode({"workspace_id": workspace_id, "q": query}),
    )
    return require_ok(status, payload, "search duplicate long-term memory")


def is_duplicate_item(item):
    source = item.get("source") or ""
    tags = item.get("tags") or []
    summary = item.get("summary") or ""
    return (
        source.startswith(SOURCE_PREFIX)
        and any(tag in tags for tag in DUPLICATE_TAGS)
        and summary.startswith(DUPLICATE_SUMMARY_PREFIX)
        and item.get("reviewStatus") != "promoted"
        and item.get("promotionState") != "promoted"
    )


def duplicate_items(search_payloads):
    by_id = {}
    for payload in search_payloads:
        for item in payload.get("items") or []:
            if is_duplicate_item(item):
                by_id[item["eventId"]] = item
    return sorted(by_id.values(), key=lambda item: item.get("source") or item.get("eventId") or "")


def source_from_review_summary(summary):
    first_line = (summary or "").splitlines()[0] if summary else ""
    if first_line.startswith("Deep link: "):
        return first_line.replace("Deep link: ", "", 1).strip()
    return ""


def duplicate_items_from_reviews(review_items):
    items = []
    for review in review_items:
        source = source_from_review_summary(review.get("publicSafeSummary") or "")
        if not source.startswith(SOURCE_PREFIX):
            continue
        items.append(
            {
                "eventId": review.get("memoryEventId"),
                "title": source.rsplit("/", 1)[-1].replace(".md", "").replace("-", " ").title(),
                "source": source,
                "summary": review.get("publicSafeSummary") or "",
                "tags": list(DUPLICATE_TAGS),
                "reviewStatus": review.get("status"),
                "promotionState": review.get("status"),
            }
        )
    return sorted(items, key=lambda item: item.get("source") or item.get("eventId") or "")


def merge_duplicate_items(*groups):
    by_id = {}
    for group in groups:
        for item in group:
            event_id = item.get("eventId")
            if event_id:
                by_id[event_id] = item
    return sorted(by_id.values(), key=lambda item: item.get("source") or item.get("eventId") or "")


def build_plan(duplicates, review_items):
    reviews_by_memory = {item.get("memoryEventId"): item for item in review_items if item.get("memoryEventId")}
    plan = []
    for item in duplicates:
        review = reviews_by_memory.get(item.get("eventId"))
        if not review:
            action = "missing_review"
        elif review.get("status") == "rejected":
            action = "already_rejected"
        elif review.get("status") in ("pending", "quarantined"):
            action = "reject"
        else:
            action = "skip"
        plan.append(
            {
                "action": action,
                "eventId": item.get("eventId"),
                "reviewId": review.get("reviewId") if review else None,
                "title": item.get("title"),
                "source": item.get("source"),
                "reviewStatusBefore": item.get("reviewStatus"),
                "promotionStateBefore": item.get("promotionState"),
                "reviewQueueStatusBefore": review.get("status") if review else None,
                "tags": item.get("tags") or [],
                "valuesRedacted": True,
            }
        )
    return plan


def reject_item(base_url, token, workspace_id, reviewer_agent_id, planned):
    if planned["action"] != "reject":
        return dict(planned, httpStatus=None, rejected=planned["action"] == "already_rejected")
    body = {
        "workspaceId": workspace_id,
        "reviewId": planned["reviewId"],
        "reviewerAgentId": reviewer_agent_id,
        "decision": "reject",
        "reviewNote": "Duplicate earlier long-term memory migration copy; canonical hosted memory record is already promoted.",
    }
    status, payload = call_json(
        base_url,
        "/api/matm/review-queue/decide",
        method="POST",
        token=token,
        idempotency_key="ltm-duplicate-reject-" + planned["reviewId"],
        body=body,
    )
    require_ok(status, payload, "reject %s" % planned["reviewId"])
    review = payload.get("review") or {}
    return dict(planned, httpStatus=status, rejected=review.get("status") == "rejected", reviewStatusAfter=review.get("status"))


def verification_summary(search_payloads):
    remaining = duplicate_items(search_payloads)
    return {
        "remainingDuplicateCount": len(remaining),
        "remainingDuplicates": [
            {
                "eventId": item.get("eventId"),
                "title": item.get("title"),
                "source": item.get("source"),
                "reviewStatus": item.get("reviewStatus"),
                "promotionState": item.get("promotionState"),
                "valuesRedacted": True,
            }
            for item in remaining
        ],
        "valuesRedacted": True,
    }


def build_report(base_url, workspace_id, token, reviewer_agent_id, mode, plan, results, verification):
    if mode == "live_apply":
        ok = verification["remainingDuplicateCount"] == 0
    else:
        ok = len(plan) > 0 and sum(1 for item in plan if item.get("action") == "reject") > 0
    report = {
        "schemaVersion": "memoryendpoints.long_term_memory_duplicate_cleanup.v1",
        "mode": mode,
        "baseUrl": base_url,
        "workspaceIdHash": "sha256:" + sha256_text(workspace_id),
        "reviewerAgentId": reviewer_agent_id,
        "targetTags": list(DUPLICATE_TAGS),
        "targetSummaryPrefix": DUPLICATE_SUMMARY_PREFIX,
        "targetCount": len(plan),
        "wouldRejectCount": sum(1 for item in plan if item.get("action") == "reject"),
        "rejectedCount": sum(1 for item in results if item.get("rejected")),
        "alreadyRejectedCount": sum(1 for item in results if item.get("action") == "already_rejected"),
        "skippedCount": sum(1 for item in results if item.get("action") not in ("reject", "already_rejected")),
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


def search_payloads(base_url, token, workspace_id):
    return [
        fetch_search(base_url, token, workspace_id, "docs-seed"),
        fetch_search(base_url, token, workspace_id, "dogfood-migration"),
        fetch_search(base_url, token, workspace_id, DUPLICATE_SUMMARY_PREFIX),
    ]


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

    reviews = fetch_reviews(base_url, token, workspace_id)
    duplicates = merge_duplicate_items(
        duplicate_items(search_payloads(base_url, token, workspace_id)),
        duplicate_items_from_reviews(reviews.get("items") or []),
    )
    plan = build_plan(duplicates, reviews.get("items") or [])
    mode = "live_apply" if args.apply else "dry_run"
    if args.apply:
        results = [reject_item(base_url, token, workspace_id, reviewer_agent_id, item) for item in plan]
    else:
        results = [dict(item, httpStatus=None, rejected=item.get("action") == "already_rejected") for item in plan]
    verification = verification_summary(search_payloads(base_url, token, workspace_id))
    report = build_report(base_url, workspace_id, token, reviewer_agent_id, mode, plan, results, verification)
    write_json(args.report_out, report)
    print(json.dumps({"ok": report["ok"], "mode": mode, "targetCount": report["targetCount"], "wouldRejectCount": report["wouldRejectCount"], "rejectedCount": report["rejectedCount"], "report": display_path(args.report_out), "valuesRedacted": True}, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
