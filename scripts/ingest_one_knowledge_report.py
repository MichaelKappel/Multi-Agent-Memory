import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SECRET = ROOT / ".local-secrets" / "human-verifier-account.json"
DEFAULT_REPORT = ROOT / "docs" / "reports" / "single-knowledge-report-ingest.json"


def sha256_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def slug(value, fallback="item", limit=120):
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    if not text:
        text = fallback
    return text[:limit].strip("-") or fallback


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


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
                return title[:240]
    return fallback


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


def workspace_context(base_url, token, configured_workspace_id=None):
    query = urlencode({"workspace_id": configured_workspace_id}) if configured_workspace_id else ""
    status, payload = call_json(base_url, "/api/matm/workspace", token=token, query=query)
    payload = require_ok(status, payload, "read workspace")
    workspace = payload.get("workspace") or {}
    return {
        "workspaceId": workspace.get("workspaceId") or configured_workspace_id,
        "companyId": workspace.get("companyId"),
        "rawKeyStoredByServer": bool(workspace.get("rawKeyStoredByServer")),
    }


def build_body(args, context, actor_agent_id, source_path, text):
    title = args.title or first_heading(text, source_path.stem.replace("-", " ").replace("_", " ").title())
    content_hash = sha256_text(text)
    source_uri = args.source_uri or "report://%s-%s" % (slug(source_path.stem), content_hash[:12])
    route_or_path = args.route_or_path or "/knowledge/%s/%s/%s" % (args.scope, args.category, slug(title))
    body = {
        "workspaceId": context["workspaceId"],
        "actorAgentId": actor_agent_id,
        "scope": args.scope,
        "title": title,
        "description": args.description,
        "keywords": args.keyword,
        "taxonomyPaths": args.taxonomy_path,
        "searchableText": text,
        "category": args.category,
        "documentType": args.document_type,
        "sourceUri": source_uri,
        "sourceType": args.source_type,
        "routeOrPath": route_or_path,
        "visibility": "workspace_private",
        "crawlPolicy": "workspace_private",
        "tags": [tag for tag in args.tag if tag],
        "metadata": {
            "sourceFileName": source_path.name,
            "sourceContentHash": "sha256:" + content_hash,
            "ingestMode": "single_report_reviewed",
            "absoluteSourcePathStored": False,
            "classificationNote": args.classification_note or "",
            "description": args.description,
            "keywords": args.keyword,
            "taxonomyPaths": args.taxonomy_path,
            "valuesRedacted": True,
        },
    }
    if args.scope == "company":
        body["scopeId"] = context["companyId"]
    elif args.scope == "workspace":
        body["scopeId"] = context["workspaceId"]
    else:
        body["scopeId"] = args.project_id
        body["projectId"] = args.project_id
        body["projectLabel"] = args.project_label
    return body


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Ingest exactly one reviewed report into the database-backed knowledge wiki."
    )
    parser.add_argument("--base-url", default="https://memoryendpoints.com")
    parser.add_argument("--secret", default=str(DEFAULT_SECRET))
    parser.add_argument("--source-file", required=True)
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT))
    parser.add_argument("--agent-id", default="")
    parser.add_argument("--scope", required=True, choices=["company", "workspace", "project"])
    parser.add_argument("--category", required=True)
    parser.add_argument("--project-id", default="")
    parser.add_argument("--project-label", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--document-type", default="reviewed-report")
    parser.add_argument("--source-type", default="reviewed_markdown_report")
    parser.add_argument("--source-uri", default="")
    parser.add_argument("--route-or-path", default="")
    parser.add_argument("--classification-note", default="")
    parser.add_argument("--description", required=True)
    parser.add_argument("--keyword", action="append", default=[], required=True)
    parser.add_argument("--taxonomy-path", action="append", default=[], required=True, help="Repeatable contextual path, for example: AI infrastructure > tokenization > prompt optimization")
    parser.add_argument("--memory-summary", default="")
    parser.add_argument("--memory-type", default="procedure", choices=["fact", "decision", "status", "procedure", "risk", "evidence", "handoff", "note"])
    parser.add_argument("--memory-subject", default="")
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    if args.scope == "project" and (not args.project_id or not args.project_label):
        raise RuntimeError("project scope requires --project-id and --project-label")
    if not args.keyword:
        raise RuntimeError("single-report ingest requires at least one --keyword")
    if not args.taxonomy_path:
        raise RuntimeError("single-report ingest requires at least one --taxonomy-path")
    if args.apply and not args.memory_summary.strip():
        raise RuntimeError("applied single-report ingest requires --memory-summary so wiki content and durable MATM memory are both updated")

    source_path = Path(args.source_file)
    text = source_path.read_text(encoding="utf-8", errors="replace")
    secret = read_json(args.secret)
    token = secret.get("apiKeySecret") or ""
    if not token:
        raise RuntimeError("secret file does not contain apiKeySecret")
    actor_agent_id = args.agent_id or secret.get("backendAgentId") or "MemoryEndpoints-Backend-Agent"
    context = workspace_context(args.base_url, token, secret.get("workspaceId"))
    body = build_body(args, context, actor_agent_id, source_path, text)
    idempotency_key = "single-knowledge-report-" + sha256_text(body["sourceUri"] + body["scope"] + body.get("scopeId", ""))[:24]

    result = {
        "schemaVersion": "memoryendpoints.single_knowledge_report_ingest.v1",
        "mode": "live_apply" if args.apply else "dry_run",
        "baseUrl": args.base_url.rstrip("/"),
        "sourceFileName": source_path.name,
        "sourceContentHash": body["metadata"]["sourceContentHash"],
        "scope": body["scope"],
        "scopeId": body.get("scopeId"),
        "projectId": body.get("projectId"),
        "category": body["category"],
        "title": body["title"],
        "description": body["description"],
        "keywords": body["keywords"],
        "taxonomyPaths": body["taxonomyPaths"],
        "sourceUri": body["sourceUri"],
        "routeOrPath": body["routeOrPath"],
        "databaseSourceOfTruth": True,
        "filesystemKnowledgeTree": False,
        "bulkImport": False,
        "rawReportBodyWrittenToFilesystem": False,
        "rawCredentialValuesStored": False,
        "rawWorkspaceKeyStoredByServer": context["rawKeyStoredByServer"],
        "valuesRedacted": True,
    }
    if args.apply:
        if args.scope == "project":
            project_body = {
                "workspaceId": context["workspaceId"],
                "actorAgentId": actor_agent_id,
                "projectId": args.project_id,
                "label": args.project_label,
            }
            status, payload = call_json(
                args.base_url,
                "/api/matm/projects",
                method="POST",
                body=project_body,
                token=token,
                idempotency_key="single-knowledge-project-" + sha256_text(args.project_id)[:24],
            )
            require_ok(status, payload, "upsert project")
        status, payload = call_json(
            args.base_url,
            "/api/matm/knowledge-documents/upsert",
            method="POST",
            body=body,
            token=token,
            idempotency_key=idempotency_key,
        )
        payload = require_ok(status, payload, "upsert knowledge document")
        document = payload.get("document") or {}
        result.update(
            {
                "httpStatus": status,
                "searchDocumentId": document.get("searchDocumentId"),
                "sourceId": document.get("sourceId"),
                "persisted": bool(payload.get("persisted")),
                "visibleInSearch": bool(payload.get("visibleInSearch")),
                "visibleInWikiTree": bool(payload.get("visibleInWikiTree")),
                "visibleInAuditLog": bool(payload.get("visibleInAuditLog")),
                "documentQueryUrl": payload.get("documentQueryUrl"),
                "treeQueryUrl": payload.get("treeQueryUrl"),
            }
        )
        memory_body = {
            "workspaceId": context["workspaceId"],
            "actorAgentId": actor_agent_id,
            "scope": body["scope"],
            "scopeId": body.get("scopeId"),
            "memoryType": args.memory_type,
            "subject": args.memory_subject or body["title"],
            "title": body["title"],
            "summary": args.memory_summary,
            "tags": sorted(set(body["tags"] + body["keywords"] + ["single-report-ingest", "wiki-backed-memory", body["category"]])),
            "source": document.get("routeOrPath") or body["sourceUri"],
            "confidence": 0.9,
        }
        status, memory_payload = call_json(
            args.base_url,
            "/api/matm/memory-events/submit",
            method="POST",
            body=memory_body,
            token=token,
            idempotency_key="single-knowledge-memory-" + sha256_text(body["sourceUri"] + body["scope"] + body.get("scopeId", ""))[:24],
        )
        memory_payload = require_ok(status, memory_payload, "submit durable memory summary")
        event = memory_payload.get("event") or {}
        result.update(
            {
                "memoryHttpStatus": status,
                "memoryEventId": event.get("eventId"),
                "memoryReviewStatus": event.get("reviewStatus"),
                "memoryPromotionState": event.get("promotionState"),
                "memoryPersisted": bool(memory_payload.get("persisted")),
                "memoryVisibleInSearch": bool(memory_payload.get("visibleInSearch")),
                "memoryVisibleInReviewQueue": bool(memory_payload.get("visibleInReviewQueue")),
                "memoryQueryUrl": memory_payload.get("memoryQueryUrl"),
            }
        )
    else:
        result["idempotencyKeyHash"] = "sha256:" + sha256_text(idempotency_key)
        result["wouldWriteDatabaseDocument"] = True
        result["memorySummaryRequiredForApply"] = True
    result["ok"] = bool((result.get("persisted") and result.get("memoryPersisted")) or not args.apply) and not context["rawKeyStoredByServer"]
    write_json(args.report_out, result)
    print(json.dumps({"ok": result["ok"], "mode": result["mode"], "sourceFileName": source_path.name, "report": str(args.report_out), "bulkImport": False, "valuesRedacted": True}, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
