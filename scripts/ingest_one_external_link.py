import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlencode


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memoryendpoints.external_links import normalize_external_url, stable_external_link_id
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


def canonical_language(value):
    return str(value or "und").strip().lower() or "und"


def canonical_content_type(value):
    return str(value or "text/html").strip().lower() or "text/html"


def canonical_crawl_policy(value):
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "metadata_only").lower()).strip("_")
    return (text or "metadata_only")[:64].rstrip("_") or "metadata_only"


def review_status_readback_satisfies(actual_status, requested_status):
    actual = str(actual_status or "").strip().lower()
    requested = str(requested_status or "unreviewed").strip().lower()
    if actual == requested:
        return True
    return requested == "unreviewed" and actual in ("reviewed", "quarantined", "rejected")


def merge_external_link_keywords(existing_keywords, requested_keywords):
    merged = []
    seen = set()
    for value in list(existing_keywords or []) + list(requested_keywords or []):
        keyword = str(value or "").strip()
        key = keyword.casefold()
        if keyword and key not in seen:
            seen.add(key)
            merged.append(keyword[:96])
    return merged


def external_link_request_fingerprint(body):
    material = dict(body)
    metadata = dict(material.get("metadata") or {})
    metadata.pop("requestFingerprint", None)
    material["metadata"] = metadata
    canonical = json.dumps(material, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return sha256_text(canonical)


def _matching_citation(link, body):
    document_id = body.get("knowledgeDocumentId") or ""
    if not document_id:
        return None
    expected_anchor = body.get("anchorText") or body.get("pageTitle") or ""
    expected_relationship = body.get("relationshipType") or "reference"
    expected_label = body.get("citationLabel") or ""
    return next(
        (
            mention
            for mention in (link or {}).get("mentions") or []
            if mention.get("knowledgeDocumentId") == document_id
            and mention.get("relationshipType") == expected_relationship
            and mention.get("anchorText") == expected_anchor
            and (mention.get("citationLabel") or "") == expected_label
        ),
        None,
    )


def external_link_readback_matches(link, body):
    link = link or {}
    expected_keywords = sorted(set(body.get("keywords") or []))
    actual_keywords = sorted(set(link.get("keywords") or []))
    metadata_matches = bool(link) and all(
        (
            link.get("normalizedUrl") == body.get("url"),
            link.get("siteName") == body.get("siteName"),
            link.get("pageTitle") == body.get("pageTitle"),
            link.get("description") == body.get("description"),
            actual_keywords == expected_keywords,
            canonical_language(link.get("language")) == canonical_language(body.get("language")),
            canonical_content_type(link.get("contentType")) == canonical_content_type(body.get("contentType")),
            review_status_readback_satisfies(link.get("reviewStatus"), body.get("reviewStatus")),
            link.get("crawlStatus") == body.get("crawlStatus"),
            canonical_crawl_policy(link.get("crawlPolicy")) == canonical_crawl_policy(body.get("crawlPolicy")),
            link.get("visibility") == body.get("visibility"),
        )
    )
    citation = _matching_citation(link, body)
    citation_matches = not body.get("knowledgeDocumentId") or bool(
        citation
        and citation.get("contextDescription") == body.get("contextDescription")
        and int(citation.get("citationOrder") or 0) == int(body.get("citationOrder") or 0)
        and (citation.get("sourceReportName") or "") == (body.get("sourceReportName") or "")
    )
    return {
        "metadataMatches": metadata_matches,
        "citationMatches": citation_matches,
    }


def external_link_preflight(base_url, token, workspace_id, normalized_url, body):
    external_link_id = stable_external_link_id(workspace_id, normalized_url)
    status, payload = call_json(
        base_url,
        "/api/matm/external-links",
        token=token,
        query=urlencode(
            {
                "workspace_id": workspace_id,
                "external_link_id": external_link_id,
                "limit": "10",
            }
        ),
    )
    payload = require_ok(status, payload, "preflight external link")
    items = [item for item in payload.get("items") or [] if item.get("externalLinkId") == external_link_id]
    link = items[0] if items else None
    citation = _matching_citation(link, body)
    return {
        "link": link,
        "sourcePreviouslyIndexed": bool(link),
        "existingCanonicalLinkCount": len(items),
        "citationAlreadyExists": bool(citation),
        "existingMentionCount": int((link or {}).get("mentionCount") or 0),
        "existingReviewStatus": (link or {}).get("reviewStatus"),
        "existingCrawlStatus": (link or {}).get("crawlStatus"),
    }


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
        "language": canonical_language(args.language),
        "contentType": canonical_content_type(args.content_type),
        "reviewStatus": args.review_status,
        "crawlStatus": args.crawl_status,
        "crawlPolicy": canonical_crawl_policy(args.crawl_policy),
        "visibility": "workspace_private",
        "metadata": {
            "ingestMode": "single_external_link_reviewed",
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
                "sourceReportName": args.source_report_name,
            }
        )
    preflight = external_link_preflight(
        args.base_url,
        token,
        context["workspaceId"],
        normalized["normalizedUrl"],
        body,
    )
    requested_keywords = list(body["keywords"])
    existing_keywords = list((preflight.get("link") or {}).get("keywords") or [])
    body["keywords"] = merge_external_link_keywords(existing_keywords, requested_keywords)
    body["metadata"]["keywordsMergedFromExisting"] = bool(existing_keywords)
    request_fingerprint = external_link_request_fingerprint(body)
    body["metadata"]["requestFingerprint"] = "sha256:" + request_fingerprint
    idempotency_key = "single-external-link-" + sha256_text(
        normalized["normalizedUrl"] + "\n" + request_fingerprint
    )[:24]
    result = {
        "schemaVersion": "memoryendpoints.single_external_link_ingest.v2",
        "mode": "live_apply" if args.apply else "dry_run",
        "baseUrl": args.base_url.rstrip("/"),
        "url": normalized["url"],
        "pageUrl": normalized["pageUrl"],
        "host": normalized["host"],
        "siteName": args.site_name,
        "pageTitle": args.page_title,
        "description": args.description,
        "requestedKeywords": requested_keywords,
        "keywords": body["keywords"],
        "existingKeywordCount": len(existing_keywords),
        "keywordsMergedFromExisting": bool(existing_keywords),
        "knowledgeDocumentIdHash": "sha256:" + sha256_text(args.document_id) if args.document_id else None,
        "relationshipType": args.relationship_type if args.document_id else None,
        "citationLabel": args.citation_label if args.document_id else None,
        "sourceReportName": args.source_report_name or None,
        "canonicalUrlHash": "sha256:" + normalized["normalizedUrlHash"],
        "requestFingerprint": "sha256:" + request_fingerprint,
        "sourcePreviouslyIndexed": preflight["sourcePreviouslyIndexed"],
        "existingCanonicalLinkCount": preflight["existingCanonicalLinkCount"],
        "citationAlreadyExists": preflight["citationAlreadyExists"],
        "existingMentionCount": preflight["existingMentionCount"],
        "existingReviewStatus": preflight["existingReviewStatus"],
        "existingCrawlStatus": preflight["existingCrawlStatus"],
        "requestedReviewStatus": args.review_status,
        "expectedEffectiveReviewStatus": (
            preflight["existingReviewStatus"]
            if args.review_status == "unreviewed"
            and preflight["existingReviewStatus"] in ("reviewed", "quarantined", "rejected")
            else args.review_status
        ),
        "databaseSourceOfTruth": True,
        "firstClassExternalLink": True,
        "bulkImport": False,
        "automaticFetchRequested": False,
        "rawCredentialValuesStored": False,
        "rawWorkspaceKeyStoredByServer": context["rawKeyStoredByServer"],
        "rawWorkspaceIdWrittenToReport": False,
        "rawKnowledgeDocumentIdWrittenToReport": False,
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
        readback = external_link_preflight(
            args.base_url,
            token,
            context["workspaceId"],
            normalized["normalizedUrl"],
            body,
        )
        readback_matches = external_link_readback_matches(readback.get("link"), body)
        result.update(
            {
                "httpStatus": status,
                "externalLinkId": link.get("externalLinkId"),
                "mentionCount": link.get("mentionCount"),
                "persisted": bool(payload.get("persisted")),
                "visibleInInternetSearch": bool(payload.get("visibleInInternetSearch")),
                "visibleOnKnowledgeDocument": bool(payload.get("visibleOnKnowledgeDocument")),
                "linkQueryUrl": payload.get("linkQueryUrl"),
                "internetSearchQueryUrl": payload.get("internetSearchQueryUrl"),
                "knowledgeDocumentLinksQueryUrl": payload.get("knowledgeDocumentLinksQueryUrl"),
                "readbackCanonicalLinkCount": readback["existingCanonicalLinkCount"],
                "readbackMentionCount": readback["existingMentionCount"],
                "readbackMatchesReviewedMetadata": readback_matches["metadataMatches"],
                "readbackCitationMatches": readback_matches["citationMatches"],
                "effectiveReviewStatus": (readback.get("link") or {}).get("reviewStatus"),
                "reviewStatusPreservedFromExisting": bool(
                    preflight["existingReviewStatus"]
                    and preflight["existingReviewStatus"] != args.review_status
                    and (readback.get("link") or {}).get("reviewStatus") == preflight["existingReviewStatus"]
                ),
            }
        )
    else:
        result["idempotencyKeyHash"] = "sha256:" + sha256_text(idempotency_key)
        result["wouldWriteCanonicalExternalLink"] = True
        result["wouldWriteKnowledgeCitation"] = bool(args.document_id)
    result["ok"] = bool(
        (
            not args.apply
            or (
                result.get("persisted")
                and result.get("visibleInInternetSearch")
                and result.get("visibleOnKnowledgeDocument")
                and result.get("readbackCanonicalLinkCount") == 1
                and result.get("readbackMatchesReviewedMetadata")
                and result.get("readbackCitationMatches")
            )
        )
        and not context["rawKeyStoredByServer"]
    )
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
