import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memoryendpoints.external_links import normalize_external_url
from scripts.ingest_one_knowledge_report import (
    DEFAULT_SECRET,
    call_json,
    read_json,
    require_ok,
    sha256_text,
    workspace_context,
    write_json,
)

DEFAULT_REPORT = ROOT / "var" / "reports" / "single-external-link-ingest.json"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Review and ingest exactly one external link into the database-backed curated web index."
    )
    parser.add_argument("--base-url", default="https://memoryendpoints.com")
    parser.add_argument("--secret", default=str(DEFAULT_SECRET))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT))
    parser.add_argument("--agent-id", default="")
    parser.add_argument("--url", required=True)
    parser.add_argument("--site-name", required=True)
    parser.add_argument("--page-title", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--keyword", action="append", default=[], required=True)
    parser.add_argument("--language", default="und")
    parser.add_argument("--content-type", default="text/html")
    parser.add_argument("--review-status", default="reviewed", choices=["unreviewed", "reviewed", "quarantined", "rejected"])
    parser.add_argument("--crawl-status", default="not_requested", choices=["not_requested", "queued", "fetched", "failed", "blocked"])
    parser.add_argument("--crawl-policy", default="metadata_only")
    parser.add_argument("--document-id", default="")
    parser.add_argument("--relationship-type", default="reference", choices=["citation", "evidence", "further_reading", "reference", "related", "source"])
    parser.add_argument("--anchor-text", default="")
    parser.add_argument("--context-description", default="")
    parser.add_argument("--citation-label", default="")
    parser.add_argument("--citation-order", type=int, default=0)
    parser.add_argument("--source-report-name", default="")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    if not args.keyword:
        raise RuntimeError("single external-link ingest requires at least one --keyword")
    if args.document_id and not args.context_description.strip():
        raise RuntimeError("a knowledge-document citation requires --context-description")
    if args.citation_order < 0:
        raise RuntimeError("--citation-order must be non-negative")

    normalized = normalize_external_url(args.url)
    secret = read_json(args.secret)
    token = secret.get("apiKeySecret") or ""
    if not token:
        raise RuntimeError("secret file does not contain apiKeySecret")
    actor_agent_id = args.agent_id or secret.get("backendAgentId") or "MemoryEndpoints-Backend-Agent"
    context = workspace_context(args.base_url, token, secret.get("workspaceId"))
    body = {
        "workspaceId": context["workspaceId"],
        "actorAgentId": actor_agent_id,
        "url": normalized["url"],
        "siteName": args.site_name,
        "pageTitle": args.page_title,
        "description": args.description,
        "keywords": args.keyword,
        "language": args.language,
        "contentType": args.content_type,
        "reviewStatus": args.review_status,
        "crawlStatus": args.crawl_status,
        "crawlPolicy": args.crawl_policy,
        "visibility": "workspace_private",
        "metadata": {
            "ingestMode": "single_external_link_reviewed",
            "sourceReportName": args.source_report_name,
            "automaticFetchRequested": False,
            "valuesRedacted": True,
        },
    }
    if args.document_id:
        body.update(
            {
                "knowledgeDocumentId": args.document_id,
                "relationshipType": args.relationship_type,
                "anchorText": args.anchor_text or args.page_title,
                "contextDescription": args.context_description,
                "citationLabel": args.citation_label,
                "citationOrder": args.citation_order,
            }
        )
    idempotency_material = "\n".join(
        [normalized["normalizedUrl"], args.document_id, args.relationship_type, args.citation_label, args.anchor_text or args.page_title]
    )
    idempotency_key = "single-external-link-" + sha256_text(idempotency_material)[:24]
    result = {
        "schemaVersion": "memoryendpoints.single_external_link_ingest.v1",
        "mode": "live_apply" if args.apply else "dry_run",
        "baseUrl": args.base_url.rstrip("/"),
        "url": normalized["url"],
        "pageUrl": normalized["pageUrl"],
        "host": normalized["host"],
        "siteName": args.site_name,
        "pageTitle": args.page_title,
        "description": args.description,
        "keywords": args.keyword,
        "knowledgeDocumentId": args.document_id or None,
        "relationshipType": args.relationship_type if args.document_id else None,
        "citationLabel": args.citation_label if args.document_id else None,
        "databaseSourceOfTruth": True,
        "firstClassExternalLink": True,
        "bulkImport": False,
        "automaticFetchRequested": False,
        "rawCredentialValuesStored": False,
        "rawWorkspaceKeyStoredByServer": context["rawKeyStoredByServer"],
        "valuesRedacted": True,
    }
    if args.apply:
        status, payload = call_json(
            args.base_url,
            "/api/matm/external-links/upsert",
            method="POST",
            body=body,
            token=token,
            idempotency_key=idempotency_key,
        )
        payload = require_ok(status, payload, "upsert external link")
        link = payload.get("link") or {}
        result.update(
            {
                "httpStatus": status,
                "externalLinkId": link.get("externalLinkId"),
                "mentionCount": link.get("mentionCount"),
                "persisted": bool(payload.get("persisted")),
                "visibleInInternetSearch": bool(payload.get("visibleInInternetSearch")),
                "visibleOnKnowledgeDocument": bool(payload.get("visibleOnKnowledgeDocument")),
                "visibleInAuditLog": bool(payload.get("visibleInAuditLog")),
                "linkQueryUrl": payload.get("linkQueryUrl"),
                "internetSearchQueryUrl": payload.get("internetSearchQueryUrl"),
                "knowledgeDocumentLinksQueryUrl": payload.get("knowledgeDocumentLinksQueryUrl"),
            }
        )
    else:
        result["idempotencyKeyHash"] = "sha256:" + sha256_text(idempotency_key)
        result["wouldWriteCanonicalExternalLink"] = True
        result["wouldWriteKnowledgeCitation"] = bool(args.document_id)
    result["ok"] = bool(result.get("persisted") or not args.apply) and not context["rawKeyStoredByServer"]
    write_json(args.report_out, result)
    print(
        json.dumps(
            {
                "ok": result["ok"],
                "mode": result["mode"],
                "host": result["host"],
                "report": str(args.report_out),
                "bulkImport": False,
                "valuesRedacted": True,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
