import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = ROOT / "docs" / "long-term-memory"
DEFAULT_SECRET = ROOT / ".local-secrets" / "human-verifier-account.json"
DEFAULT_REPORT = ROOT / "docs" / "reports" / "long-term-memory-migration.json"
SUMMARY_LIMIT = 1800


MEMORY_TYPE_BY_STEM = {
    "api-contract-summary": "status",
    "architecture-notes": "decision",
    "enterprise-engineering-best-practices": "procedure",
    "matm-architecture-strategy": "procedure",
    "project-charter": "decision",
    "release-verification-summary": "status",
    "strategy-index": "procedure",
    "system-targets": "procedure",
}


def sha256_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def display_path(path):
    try:
        return str(Path(path).resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def first_heading(text, fallback):
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title
    return fallback


def compact_summary(text, limit=SUMMARY_LIMIT):
    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if line.startswith("#"):
            continue
        lines.append(re.sub(r"\s+", " ", line))
    summary = "\n".join(lines).strip()
    if len(summary) <= limit:
        return summary
    return summary[: limit - 3].rstrip() + "..."


def tag_slug(path):
    return Path(path).stem.lower().replace("_", "-")


def memory_type_for(path):
    return MEMORY_TYPE_BY_STEM.get(Path(path).stem, "note")


def idempotency_key(source_path, text):
    content_hash = sha256_text(text)
    digest = sha256_text(source_path + ":" + content_hash)
    return "ltm-migration-" + digest[:32]


def load_memory_items(source_dir):
    source_dir = Path(source_dir)
    items = []
    for path in sorted(source_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = display_path(path)
        title = first_heading(text, path.stem.replace("-", " ").title())
        items.append(
            {
                "sourcePath": rel,
                "contentHash": "sha256:" + sha256_text(text),
                "idempotencyKey": idempotency_key(rel, text),
                "title": title,
                "summary": compact_summary(text),
                "memoryType": memory_type_for(path),
                "tags": [
                    "long-term-memory-migration",
                    "hosted-memory",
                    "dogfood",
                    tag_slug(path),
                ],
            }
        )
    return items


def call_json(base_url, path, method="GET", body=None, token=None, idempotency_key_value=None, query=None):
    url = base_url.rstrip("/") + path
    if query:
        url += "?" + query
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if idempotency_key_value:
        headers["Idempotency-Key"] = idempotency_key_value
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


def workspace_context(base_url, token, configured_workspace_id=None):
    query = urlencode({"workspace_id": configured_workspace_id}) if configured_workspace_id else ""
    status, payload = call_json(base_url, "/api/matm/workspace", token=token, query=query)
    payload = require_ok(status, payload, "read workspace")
    workspace = payload.get("workspace") or {}
    return {
        "workspaceId": workspace.get("workspaceId") or configured_workspace_id,
        "companyId": workspace.get("companyId"),
        "projectId": workspace.get("primaryProjectId"),
        "storageRemainingBytes": workspace.get("storageRemainingBytes"),
        "rawKeyStoredByServer": bool(workspace.get("rawKeyStoredByServer")),
    }


def build_dry_run_report(base_url, source_dir, items):
    return {
        "schemaVersion": "memoryendpoints.long_term_memory_migration.v1",
        "mode": "dry_run",
        "baseUrl": base_url.rstrip("/"),
        "sourceDirectory": display_path(source_dir),
        "itemCount": len(items),
        "items": [
            {
                "sourcePath": item["sourcePath"],
                "title": item["title"],
                "contentHash": item["contentHash"],
                "idempotencyKeyHash": "sha256:" + sha256_text(item["idempotencyKey"]),
                "memoryType": item["memoryType"],
                "summaryLength": len(item["summary"]),
                "tags": item["tags"],
                "valuesRedacted": True,
            }
            for item in items
        ],
        "rawCredentialValuesStored": False,
        "rawWorkspaceIdStored": False,
        "valuesRedacted": True,
        "ok": True,
    }


def submit_item(base_url, token, context, actor_agent_id, item):
    scope_id = context.get("projectId") or context.get("workspaceId")
    body = {
        "workspaceId": context["workspaceId"],
        "actorAgentId": actor_agent_id,
        "scope": "project" if context.get("projectId") else "workspace",
        "scopeId": scope_id,
        "memoryType": item["memoryType"],
        "subject": item["title"],
        "title": item["title"],
        "summary": item["summary"],
        "tags": item["tags"],
        "source": item["sourcePath"],
        "confidence": 0.88,
    }
    status, payload = call_json(
        base_url,
        "/api/matm/memory-events/submit",
        method="POST",
        body=body,
        token=token,
        idempotency_key_value=item["idempotencyKey"],
    )
    payload = require_ok(status, payload, "submit %s" % item["sourcePath"])
    event = payload.get("event") or {}
    return {
        "sourcePath": item["sourcePath"],
        "title": item["title"],
        "status": status,
        "eventId": event.get("eventId"),
        "reviewStatus": event.get("reviewStatus"),
        "promotionState": event.get("promotionState"),
        "memoryType": event.get("memoryType"),
        "valuesRedacted": bool(event.get("valuesRedacted", True)),
        "rawPrivatePayloadStored": bool(event.get("rawPrivatePayloadStored")),
        "idempotentReplay": bool(payload.get("idempotentReplay")),
    }


def normalized_count(payload, items):
    count = payload.get("count")
    if isinstance(count, int):
        return count
    return len(items)


def hosted_migration_readback(payload, expected_items):
    items = payload.get("items") or []
    expected_sources = sorted(item["sourcePath"] for item in expected_items)
    expected_source_set = set(expected_sources)
    hosted_items = []
    for item in items:
        source = item.get("source") or ""
        tags = item.get("tags") or []
        if source in expected_source_set or (source.startswith("docs/long-term-memory/") and "long-term-memory-migration" in tags):
            hosted_items.append(item)
    hosted_sources = sorted(set(item.get("source") for item in hosted_items if item.get("source")))
    matched_sources = [source for source in expected_sources if source in hosted_sources]
    missing_sources = [source for source in expected_sources if source not in hosted_sources]
    unexpected_sources = [source for source in hosted_sources if source not in expected_source_set]
    raw_private_payload_count = sum(1 for item in hosted_items if item.get("rawPrivatePayloadStored"))
    review_status_counts = {}
    promotion_state_counts = {}
    for item in hosted_items:
        review_status = item.get("reviewStatus") or "unknown"
        promotion_state = item.get("promotionState") or "unknown"
        review_status_counts[review_status] = review_status_counts.get(review_status, 0) + 1
        promotion_state_counts[promotion_state] = promotion_state_counts.get(promotion_state, 0) + 1
    all_promoted = bool(hosted_items) and all(
        item.get("reviewStatus") == "promoted" and item.get("promotionState") == "promoted"
        for item in hosted_items
    )
    return {
        "status": payload.get("_httpStatus"),
        "count": normalized_count(payload, items),
        "expectedSourcePathCount": len(expected_sources),
        "matchedSourcePathCount": len(matched_sources),
        "allExpectedSourcesFound": not missing_sources,
        "missingSourcePaths": missing_sources,
        "unexpectedHostedSourcePaths": unexpected_sources,
        "hostedSourcePaths": hosted_sources,
        "hostedItemTitles": sorted(item.get("title") for item in hosted_items if item.get("title")),
        "currentReviewStatusCounts": dict(sorted(review_status_counts.items())),
        "currentPromotionStateCounts": dict(sorted(promotion_state_counts.items())),
        "currentAllPromoted": all_promoted,
        "allValuesRedacted": all(bool(item.get("valuesRedacted", True)) for item in hosted_items) if hosted_items else False,
        "rawPrivatePayloadStoredCount": raw_private_payload_count,
        "memorySource": payload.get("memorySource"),
        "filesystemDocsIncluded": payload.get("filesystemDocsIncluded"),
        "valuesRedacted": True,
    }


def verify_search(base_url, token, workspace_id, expected_items):
    status, payload = call_json(
        base_url,
        "/api/matm/search",
        token=token,
        query=urlencode({"workspace_id": workspace_id, "q": "long-term-memory-migration"}),
    )
    payload = require_ok(status, payload, "verify hosted long-term memory search")
    payload["_httpStatus"] = status
    return hosted_migration_readback(payload, expected_items)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://memoryendpoints.com")
    parser.add_argument("--secret", default=str(DEFAULT_SECRET))
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT))
    parser.add_argument("--agent-id", default="")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    source_dir = Path(args.source_dir)
    items = load_memory_items(source_dir)
    if not args.apply:
        report = build_dry_run_report(base_url, source_dir, items)
        write_json(args.report_out, report)
        print(json.dumps({"ok": True, "mode": "dry_run", "itemCount": len(items), "report": display_path(args.report_out), "valuesRedacted": True}, indent=2, sort_keys=True))
        return 0

    secret = read_json(args.secret)
    token = secret.get("apiKeySecret") or ""
    if not token:
        raise RuntimeError("secret file does not contain apiKeySecret")
    actor_agent_id = args.agent_id or secret.get("codexAgentId") or "codex-agent"
    context = workspace_context(base_url, token, secret.get("workspaceId"))

    status, register = call_json(
        base_url,
        "/api/matm/agents/register",
        method="POST",
        token=token,
        idempotency_key_value="ltm-migration-register-" + actor_agent_id,
        body={"workspaceId": context["workspaceId"], "agentId": actor_agent_id, "displayName": actor_agent_id},
    )
    require_ok(status, register, "register migration actor")

    submitted = [submit_item(base_url, token, context, actor_agent_id, item) for item in items]
    search = verify_search(base_url, token, context["workspaceId"], items)
    ok = (
        len(submitted) == len(items)
        and search["allExpectedSourcesFound"]
        and search["matchedSourcePathCount"] == len(items)
        and search["memorySource"] == "hosted_workspace_store"
        and search["filesystemDocsIncluded"] is False
        and not context["rawKeyStoredByServer"]
        and all(item["valuesRedacted"] and not item["rawPrivatePayloadStored"] for item in submitted)
        and search["allValuesRedacted"]
        and search["rawPrivatePayloadStoredCount"] == 0
    )
    report = {
        "schemaVersion": "memoryendpoints.long_term_memory_migration.v1",
        "mode": "live_apply",
        "baseUrl": base_url,
        "sourceDirectory": display_path(source_dir),
        "workspaceIdHash": "sha256:" + sha256_text(context["workspaceId"] or ""),
        "projectId": context.get("projectId"),
        "actorAgentId": actor_agent_id,
        "itemCount": len(items),
        "submittedCount": len(submitted),
        "searchReadbackCount": search["count"],
        "sourcePathReadbackVerified": search["allExpectedSourcesFound"],
        "matchedSourcePathCount": search["matchedSourcePathCount"],
        "missingSourcePaths": search["missingSourcePaths"],
        "searchReadback": search,
        "submitted": submitted,
        "rawCredentialValuesStored": False,
        "rawWorkspaceIdStored": False,
        "valuesRedacted": True,
        "ok": ok,
    }
    report_text = json.dumps(report, sort_keys=True)
    report["rawCredentialValuesStored"] = bool(token and token in report_text)
    report["rawWorkspaceIdStored"] = bool(context["workspaceId"] and context["workspaceId"] in report_text)
    write_json(args.report_out, report)
    print(json.dumps({"ok": ok, "mode": "live_apply", "itemCount": len(items), "submittedCount": len(submitted), "searchReadbackCount": search["count"], "report": display_path(args.report_out), "valuesRedacted": True}, indent=2, sort_keys=True))
    return 0 if ok and not report["rawCredentialValuesStored"] and not report["rawWorkspaceIdStored"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
