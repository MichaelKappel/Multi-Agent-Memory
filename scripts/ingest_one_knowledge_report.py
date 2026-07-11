import argparse
import hashlib
import json
import re
import string
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SECRET = ROOT / ".local-secrets" / "human-verifier-account.json"
DEFAULT_REPORT = ROOT / "var" / "reports" / "single-knowledge-report-ingest.json"


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


def clean_heading(value):
    text = re.sub(r"\s+#+\s*$", "", str(value or "").strip())
    text = re.sub(r"^[*_`~]+|[*_`~]+$", "", text).strip()
    text = re.sub(r"\\([" + re.escape(string.punctuation) + r"])", r"\1", text)
    return text


def markdown_sections(text):
    lines = text.splitlines()
    headings = []
    fence_character = ""
    fence_length = 0
    for index, line in enumerate(lines):
        if fence_character:
            closing_fence = r"^[ ]{0,3}%s{%d,}[ \t]*$" % (re.escape(fence_character), fence_length)
            if re.match(closing_fence, line):
                fence_character = ""
                fence_length = 0
            continue
        opening_fence = re.match(r"^[ ]{0,3}(`{3,}|~{3,})(?:[^\r\n]*)$", line)
        if opening_fence:
            marker = opening_fence.group(1)
            fence_character = marker[0]
            fence_length = len(marker)
            continue
        match = re.match(r"^[ ]{0,3}(#{1,6})[ \t]+(.+?)[ \t]*$", line)
        if not match:
            continue
        headings.append(
            {
                "lineIndex": index,
                "lineStart": index + 1,
                "level": len(match.group(1)),
                "title": clean_heading(match.group(2)),
            }
        )
    for position, heading in enumerate(headings):
        end_index = len(lines)
        for candidate in headings[position + 1 :]:
            if candidate["level"] <= heading["level"]:
                end_index = candidate["lineIndex"]
                break
        section_lines = lines[heading["lineIndex"] : end_index]
        while section_lines and not section_lines[-1].strip():
            section_lines.pop()
        heading["lineEnd"] = heading["lineIndex"] + len(section_lines)
        heading["text"] = "\n".join(section_lines).strip() + "\n"
        heading["ordinal"] = position + 1
    return headings


def select_knowledge_unit(text, source_path, section_heading="", stop_heading=""):
    report_title = first_heading(text, source_path.stem.replace("-", " ").replace("_", " ").title())
    requested = clean_heading(section_heading)
    if not requested:
        knowledge_text = text
        unit = {
            "kind": "whole_report",
            "reportTitle": clean_heading(report_title),
            "sectionHeading": "",
            "sectionLevel": None,
            "sectionOrdinal": None,
            "lineStart": 1,
            "lineEnd": len(text.splitlines()),
        }
    else:
        matches = [item for item in markdown_sections(text) if item["title"].casefold() == requested.casefold()]
        if not matches:
            raise RuntimeError("section heading not found in source report: %s" % section_heading)
        if len(matches) > 1:
            raise RuntimeError("section heading is ambiguous in source report: %s" % section_heading)
        section = matches[0]
        knowledge_text = section["text"]
        unit = {
            "kind": "report_section",
            "reportTitle": clean_heading(report_title),
            "sectionHeading": section["title"],
            "sectionLevel": section["level"],
            "sectionOrdinal": section["ordinal"],
            "lineStart": section["lineStart"],
            "lineEnd": section["lineEnd"],
        }
    requested_stop = clean_heading(stop_heading)
    if requested_stop:
        boundaries = [
            item
            for item in markdown_sections(text)
            if item["title"].casefold() == requested_stop.casefold()
            and item["lineStart"] > unit["lineStart"]
            and item["lineStart"] <= unit["lineEnd"]
        ]
        if not boundaries:
            raise RuntimeError("stop heading not found inside selected knowledge unit: %s" % stop_heading)
        if len(boundaries) > 1:
            raise RuntimeError("stop heading is ambiguous inside selected knowledge unit: %s" % stop_heading)
        boundary = boundaries[0]
        selected_lines = text.splitlines()[unit["lineStart"] - 1 : boundary["lineStart"] - 1]
        while selected_lines and not selected_lines[-1].strip():
            selected_lines.pop()
        knowledge_text = "\n".join(selected_lines).strip() + "\n"
        unit["lineEnd"] = unit["lineStart"] + len(selected_lines) - 1
        unit["stopHeading"] = boundary["title"]
    else:
        unit["stopHeading"] = ""
    return knowledge_text, unit


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


def build_body(args, context, actor_agent_id, source_path, source_text, knowledge_text, knowledge_unit):
    title = clean_heading(args.title or knowledge_unit.get("sectionHeading") or first_heading(source_text, source_path.stem.replace("-", " ").replace("_", " ").title()))
    source_content_hash = sha256_text(source_text)
    knowledge_content_hash = sha256_text(knowledge_text)
    source_uri = args.source_uri or "report://%s-%s" % (slug(source_path.stem), source_content_hash[:12])
    route_or_path = args.route_or_path or "/knowledge/%s/%s/%s" % (args.scope, args.category, slug(title))
    document_type = args.document_type or ("reviewed-report-section" if knowledge_unit.get("kind") == "report_section" else "reviewed-report")
    body = {
        "workspaceId": context["workspaceId"],
        "actorAgentId": actor_agent_id,
        "scope": args.scope,
        "title": title,
        "description": args.description,
        "keywords": args.keyword,
        "taxonomyPaths": args.taxonomy_path,
        "searchableText": knowledge_text,
        "category": args.category,
        "documentType": document_type,
        "knowledgeStatus": args.knowledge_status,
        "authorityLevel": args.authority_level,
        "statusReason": args.status_reason,
        "supersededByDocumentId": args.superseded_by_document_id or None,
        "sourceUri": source_uri,
        "sourceType": args.source_type,
        "routeOrPath": route_or_path,
        "visibility": "workspace_private",
        "crawlPolicy": "workspace_private",
        "tags": [tag for tag in args.tag if tag],
        "metadata": {
            "sourceFileName": source_path.name,
            "sourceContentHash": "sha256:" + source_content_hash,
            "knowledgeUnitContentHash": "sha256:" + knowledge_content_hash,
            "ingestMode": "single_report_reviewed_section" if knowledge_unit.get("kind") == "report_section" else "single_report_reviewed",
            "knowledgeUnitKind": knowledge_unit.get("kind"),
            "sourceReportTitle": knowledge_unit.get("reportTitle"),
            "sourceReportRoute": args.source_report_route or "",
            "sourceSectionHeading": knowledge_unit.get("sectionHeading") or "",
            "sourceSectionLevel": knowledge_unit.get("sectionLevel"),
            "sourceSectionOrdinal": knowledge_unit.get("sectionOrdinal"),
            "sourceStopHeading": knowledge_unit.get("stopHeading") or "",
            "sourceLineStart": knowledge_unit.get("lineStart"),
            "sourceLineEnd": knowledge_unit.get("lineEnd"),
            "absoluteSourcePathStored": False,
            "classificationNote": args.classification_note or "",
            "knowledgeStatus": args.knowledge_status,
            "authorityLevel": args.authority_level,
            "statusReason": args.status_reason,
            "supersededByDocumentId": args.superseded_by_document_id or None,
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
    parser.add_argument("--document-type", default="")
    parser.add_argument("--knowledge-status", default="current", choices=["current", "proposed", "historical", "superseded", "archived"])
    parser.add_argument("--authority-level", default="reviewed", choices=["canonical", "reviewed", "reference", "community", "unverified"])
    parser.add_argument("--status-reason", default="")
    parser.add_argument("--superseded-by-document-id", default="")
    parser.add_argument("--source-type", default="reviewed_markdown_report")
    parser.add_argument("--source-uri", default="")
    parser.add_argument("--source-report-route", default="")
    parser.add_argument("--section-heading", default="", help="Exact Markdown heading to ingest as one reviewed knowledge page. Nested subsections are included.")
    parser.add_argument("--stop-heading", default="", help="Optional exact nested heading that ends the selected knowledge page before that heading.")
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
    if args.knowledge_status != "current" and not args.status_reason.strip():
        raise RuntimeError("non-current knowledge requires --status-reason")
    if args.knowledge_status == "superseded" and not args.superseded_by_document_id.strip():
        raise RuntimeError("superseded knowledge requires --superseded-by-document-id")

    source_path = Path(args.source_file)
    source_text = source_path.read_text(encoding="utf-8", errors="replace")
    knowledge_text, knowledge_unit = select_knowledge_unit(source_text, source_path, args.section_heading, args.stop_heading)
    secret = read_json(args.secret)
    token = secret.get("apiKeySecret") or ""
    if not token:
        raise RuntimeError("secret file does not contain apiKeySecret")
    actor_agent_id = args.agent_id or secret.get("backendAgentId") or "MemoryEndpoints-Backend-Agent"
    context = workspace_context(args.base_url, token, secret.get("workspaceId"))
    body = build_body(args, context, actor_agent_id, source_path, source_text, knowledge_text, knowledge_unit)
    idempotency_material = body["sourceUri"] + body["scope"] + body.get("scopeId", "") + body["routeOrPath"]
    idempotency_key = "single-knowledge-page-" + sha256_text(idempotency_material)[:24]

    result = {
        "schemaVersion": "memoryendpoints.single_knowledge_report_ingest.v3",
        "mode": "live_apply" if args.apply else "dry_run",
        "baseUrl": args.base_url.rstrip("/"),
        "sourceFileName": source_path.name,
        "sourceContentHash": body["metadata"]["sourceContentHash"],
        "scope": body["scope"],
        "scopeId": body.get("scopeId"),
        "projectId": body.get("projectId"),
        "category": body["category"],
        "knowledgeStatus": body["knowledgeStatus"],
        "authorityLevel": body["authorityLevel"],
        "statusReason": body["statusReason"],
        "supersededByDocumentId": body.get("supersededByDocumentId"),
        "title": body["title"],
        "description": body["description"],
        "keywords": body["keywords"],
        "taxonomyPaths": body["taxonomyPaths"],
        "sourceUri": body["sourceUri"],
        "routeOrPath": body["routeOrPath"],
        "knowledgeUnitKind": knowledge_unit.get("kind"),
        "sourceReportTitle": knowledge_unit.get("reportTitle"),
        "sourceSectionHeading": knowledge_unit.get("sectionHeading"),
        "sourceLineStart": knowledge_unit.get("lineStart"),
        "sourceLineEnd": knowledge_unit.get("lineEnd"),
        "knowledgeUnitContentHash": body["metadata"]["knowledgeUnitContentHash"],
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
            "tags": sorted(
                set(
                    body["tags"]
                    + body["keywords"]
                    + [
                        "single-report-ingest",
                        "wiki-backed-memory",
                        body["category"],
                        "knowledge-status:" + body["knowledgeStatus"],
                        "authority:" + body["authorityLevel"],
                    ]
                )
            ),
            "source": document.get("routeOrPath") or body["sourceUri"],
            "confidence": 0.9,
        }
        status, memory_payload = call_json(
            args.base_url,
            "/api/matm/memory-events/submit",
            method="POST",
            body=memory_body,
            token=token,
            idempotency_key="single-knowledge-memory-" + sha256_text(idempotency_material)[:24],
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
