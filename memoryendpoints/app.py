import hashlib
import hmac
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlencode

from . import __version__
from .build import build_provenance
from .config import COMPANION_DOCS_URL, GITHUB_REPO_URL, PUBLIC_STORAGE_BYTES, ROOT, SITE_NAME, SITE_URL, utc_now
from .http import json_response, problem, response
from .runtime import backend_error_code, store_backend_health
from .security import redact_text
from .site_data import PUBLIC_ROUTES, capability_matrix, connector_contract, manifest, openapi_spec, readiness_result, route_inventory
from .storage import FileStore, MySQLStore, SQLiteStore, mysql_config_diagnostics, mysql_connection_stage_diagnostics


STATIC_ROOT = ROOT / "static"
LONG_TERM_MEMORY_TAG = "long-term-memory-migration"
LONG_TERM_MEMORY_SOURCE_PREFIX = "docs/long-term-memory/"
DEFAULT_CORS_ALLOWED_HEADERS = "Authorization, Content-Type, Idempotency-Key, X-MemoryEndpoints-Key"
DEFAULT_CORS_ALLOWED_METHODS = "GET, POST, OPTIONS"


def _read_body(environ):
    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError:
        length = 0
    raw = environ["wsgi.input"].read(length) if length else b""
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        return None


def _query(environ):
    return {k: v[0] if v else "" for k, v in parse_qs(environ.get("QUERY_STRING", "")).items()}


def _token(environ):
    auth = environ.get("HTTP_AUTHORIZATION", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return environ.get("HTTP_X_MEMORYENDPOINTS_KEY", "").strip()


def _idempotency_key(environ):
    return environ.get("HTTP_IDEMPOTENCY_KEY", "").strip()


def _cors_allowed_origin(environ):
    allowed = os.environ.get("MEMORYENDPOINTS_CORS_ALLOWED_ORIGINS", "*").strip() or "*"
    origin = (environ.get("HTTP_ORIGIN") or "").strip()
    if allowed == "*":
        return "*"
    allowed_origins = [item.strip() for item in allowed.split(",") if item.strip()]
    if origin and origin in allowed_origins:
        return origin
    if not origin:
        return ""
    return None


def _cors_headers(environ):
    origin = _cors_allowed_origin(environ)
    if origin is None:
        return []
    request_headers = (environ.get("HTTP_ACCESS_CONTROL_REQUEST_HEADERS") or "").strip()
    allowed_headers = request_headers or DEFAULT_CORS_ALLOWED_HEADERS
    headers = [
        ("Access-Control-Allow-Origin", origin or "*"),
        ("Access-Control-Allow-Methods", DEFAULT_CORS_ALLOWED_METHODS),
        ("Access-Control-Allow-Headers", allowed_headers),
        ("Access-Control-Max-Age", "600"),
        ("Access-Control-Expose-Headers", "Content-Length, Content-Type"),
    ]
    if origin and origin != "*":
        headers.append(("Vary", "Origin"))
    return headers


def _cors_start_response(environ, start_response):
    cors_headers = _cors_headers(environ)

    def wrapped(status, response_headers, exc_info=None):
        existing = {key.lower() for key, _value in response_headers}
        merged = list(response_headers)
        for key, value in cors_headers:
            if key.lower() not in existing:
                merged.append((key, value))
        if exc_info is None:
            return start_response(status, merged)
        return start_response(status, merged, exc_info)

    return wrapped


def _route_cors_preflight(environ, start_response):
    if _cors_allowed_origin(environ) is None:
        return problem(start_response, "403 Forbidden", "CORS origin not allowed", "This origin is not allowed to call the MemoryEndpoints API.", "cors_origin_not_allowed")
    return response(
        start_response,
        "204 No Content",
        b"",
        "text/plain; charset=utf-8",
        headers=[("Allow", DEFAULT_CORS_ALLOWED_METHODS)],
    )


def _protected_query_url(route, params):
    active = {}
    for key, value in (params or {}).items():
        if value is not None and value != "":
            active[key] = value
    return route + ("?" + urlencode(active) if active else "")


def _meeting_post_confirmation(store, workspace_id, room, message):
    room = room or {}
    message = message or {}
    room_id = room.get("roomId") or message.get("roomId")
    sender_agent_id = message.get("senderAgentId") or ""
    _room, messages, _read_state = store.meeting_messages(workspace_id, room_id, sender_agent_id, 200)
    visible = any(item.get("meetingMessageId") == message.get("meetingMessageId") for item in messages)
    return {
        "persisted": visible,
        "visibleToSender": visible,
        "canonicalRoomId": room_id,
        "messageId": message.get("meetingMessageId"),
        "transcriptQueryUrl": _protected_query_url(
            "/api/matm/meeting-messages",
            {"room_id": room_id, "agent_id": sender_agent_id},
        ),
        "valuesRedacted": True,
    }


def _memory_submission_confirmation(store, workspace_id, event):
    event = event or {}
    filters = {
        "scope": event.get("scope") or "",
        "scopeId": event.get("scopeId") or "",
        "memoryType": event.get("memoryType") or "",
        "eventId": event.get("eventId") or "",
    }
    search_items = store.search_memory(workspace_id, "", filters)
    visible_in_search = any(item.get("eventId") == event.get("eventId") for item in search_items)
    review_items = store.review_queue(workspace_id, "")
    visible_in_review_queue = any(item.get("memoryEventId") == event.get("eventId") for item in review_items)
    audit_items = store.audit_log(workspace_id, 50, "memory.submit")
    visible_in_audit_log = any(item.get("target") == event.get("eventId") for item in audit_items)
    return {
        "persisted": bool(event.get("eventId") and (visible_in_search or visible_in_review_queue) and visible_in_audit_log),
        "visibleInSearch": visible_in_search,
        "visibleInReviewQueue": visible_in_review_queue,
        "visibleInAuditLog": visible_in_audit_log,
        "canonicalMemoryEventId": event.get("eventId"),
        "reviewId": event.get("reviewId"),
        "memoryQueryUrl": _protected_query_url(
            "/api/matm/search",
            {
                "q": "",
                "event_id": event.get("eventId"),
                "scope": event.get("scope"),
                "scope_id": event.get("scopeId"),
                "memory_type": event.get("memoryType"),
            },
        ),
        "reviewQueueUrl": _protected_query_url(
            "/api/matm/review-queue",
            {"status": event.get("reviewStatus") or "pending"},
        ),
        "auditLogUrl": _protected_query_url(
            "/api/matm/audit-log",
            {"action": "memory.submit", "limit": "50"},
        ),
        "valuesRedacted": True,
    }


def _current_message_confirmation(store, workspace_id, message, notes):
    message = message or {}
    notes = notes if isinstance(notes, list) else ([notes] if notes else [])
    notification_ids = [note.get("notificationId") for note in notes if note and note.get("notificationId")]
    message_target = message.get("targetAgentId") or ""
    recipient_agent_ids = []
    for note in notes:
        recipient = (note or {}).get("targetAgentId") or message_target or message.get("senderAgentId") or ""
        if recipient and recipient not in recipient_agent_ids:
            recipient_agent_ids.append(recipient)
    if not recipient_agent_ids:
        recipient_agent_ids = [message_target or message.get("senderAgentId") or ""]
    visible_agents = []
    for recipient_agent_id in recipient_agent_ids:
        inbox_items = store.inbox(workspace_id, recipient_agent_id, message.get("messageId"))
        visible = any(
            ((item.get("notification") or {}).get("notificationId") in notification_ids)
            or ((item.get("message") or {}).get("messageId") == message.get("messageId"))
            for item in inbox_items
        )
        if visible:
            visible_agents.append(recipient_agent_id)
    persisted = bool(recipient_agent_ids) and len(visible_agents) == len(recipient_agent_ids)
    first_recipient = recipient_agent_ids[0] if recipient_agent_ids else ""
    return {
        "persisted": persisted,
        "visibleToTarget": persisted,
        "visibleToAgents": visible_agents,
        "visibleRecipientCount": len(visible_agents),
        "expectedRecipientCount": len(recipient_agent_ids),
        "canonicalTargetAgentId": message_target,
        "messageId": message.get("messageId"),
        "notificationId": notification_ids[0] if notification_ids else "",
        "notificationIds": notification_ids,
        "inboxQueryUrl": _protected_query_url(
            "/api/matm/current-message",
            {
                "agent_id": message_target or first_recipient,
                "message_id": message.get("messageId"),
                "notification_id": notification_ids[0] if len(notification_ids) == 1 else "",
            },
        ),
        "valuesRedacted": True,
    }


def _admin_diagnostics_path():
    return Path(
        os.environ.get(
            "MEMORYENDPOINTS_ADMIN_DIAGNOSTICS_PATH",
            str(ROOT / ".local-secrets" / "admin-diagnostics.json"),
        )
    )


def _admin_diagnostics_authorized(environ):
    path = _admin_diagnostics_path()
    if not path.exists():
        return False, "not_configured"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return False, "invalid_config"
    expected_hash = str(payload.get("tokenHash") or "").strip().lower()
    if not expected_hash:
        return False, "missing_token_hash"
    token_hash = hashlib.sha256(_token(environ).encode("utf-8")).hexdigest()
    return hmac.compare_digest(token_hash, expected_hash), "configured"


def _diagnostic_fingerprint(value):
    if value is None:
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]


def _store():
    backend = os.environ.get("MEMORYENDPOINTS_STORE_BACKEND", "file").strip().lower() or "file"
    if backend in ("mysql", "mariadb"):
        return MySQLStore()
    if backend == "sqlite":
        return SQLiteStore()
    return FileStore()


def _require_auth(environ, workspace_id):
    auth = _store().authenticate(_token(environ), workspace_id)
    return auth


def html_page(title, main):
    asset_version = build_provenance().get("sourceShaShort") or __version__
    json_ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": SITE_NAME,
            "url": SITE_URL,
            "description": "Pure MATM Multi-Agent Transactive Memory endpoint reference implementation.",
            "version": __version__,
        },
        sort_keys=True,
    ).replace("<", "\\u003c")
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} | MemoryEndpoints.com</title>
  <meta name="description" content="Pure MATM Multi-Agent Transactive Memory endpoint reference implementation.">
  <link rel="stylesheet" href="/static/css/site.css?v={asset_version}">
  <script type="application/ld+json">{json_ld}</script>
</head>
<body>
  <header class="topbar">
    <a class="brand" href="/" aria-label="MemoryEndpoints home">
      <img src="/static/img/memory-endpoints-mark.svg" alt="" width="36" height="36">
      <span>MemoryEndpoints.com</span>
    </a>
    <nav aria-label="Primary">
      <a href="/docs">Docs</a>
      <a href="/agent-setup">Agent Setup</a>
      <a href="/agent-coordination">Agent Coordination</a>
      <a href="/console">Console</a>
      <a href="/memory-lifecycle">Memory</a>
      <a href="/transparency">Transparency</a>
      <a href="{companion_docs_url}">MultiAgentMemory.com</a>
    </nav>
  </header>
  <main>{main}</main>
  <footer>
    <p>Source-available MATM endpoint reference. No certification, endorsement, or hidden authority claim is implied.</p>
  </footer>
  <script src="/static/js/site.js?v={asset_version}"></script>
</body>
</html>""".format(
        title=escape_html(title),
        main=main,
        json_ld=json_ld,
        companion_docs_url=COMPANION_DOCS_URL,
        asset_version=escape_html(asset_version),
    )


def escape_html(value):
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _delivery_metadata(message, notification=None, inbox_agent_id=""):
    message = message or {}
    notification = notification or {}
    message_target_agent_id = message.get("targetAgentId") or ""
    notification_target_agent_id = notification.get("targetAgentId") or ""
    message_type = "targeted" if message_target_agent_id else "broadcast"
    response_disposition = notification.get("responseDisposition") or (
        "required_response" if message.get("responseRequired") else "viewed_acknowledgement"
    )
    return {
        "messageType": message_type,
        "broadcast": not bool(message_target_agent_id),
        "targetAgentId": message_target_agent_id,
        "recipientAgentId": notification_target_agent_id,
        "inboxAgentId": inbox_agent_id or notification_target_agent_id or message_target_agent_id or "",
        "responseDisposition": response_disposition,
        "valuesRedacted": True,
        "rawPayloadExposed": False,
    }


def _message_delivery_operator_summary(delivery, delivery_counts):
    delivery = delivery or {}
    delivery_counts = dict(delivery_counts or {})
    message_type = delivery.get("messageType") or ("targeted" if delivery.get("targetAgentId") else "broadcast")
    broadcast = delivery.get("broadcast")
    if broadcast is None:
        broadcast = message_type == "broadcast"
    response_disposition = delivery.get("responseDisposition") or "viewed_acknowledgement"
    response_counts = {"required_response": 0, "viewed_acknowledgement": 0}
    response_counts[response_disposition] = response_counts.get(response_disposition, 0) + 1
    return {
        "schemaVersion": "memoryendpoints.message_delivery_operator_summary.v1",
        "messageType": message_type,
        "broadcast": bool(broadcast),
        "targetAgentId": delivery.get("targetAgentId") or "",
        "inboxAgentId": delivery.get("inboxAgentId") or delivery.get("targetAgentId") or "",
        "recipientAgentId": delivery.get("recipientAgentId") or "",
        "recipientCount": delivery.get("recipientCount") or 1,
        "responseDisposition": response_disposition,
        "deliveryCounts": delivery_counts,
        "responseDispositionCounts": response_counts,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _agent_registration_operator_summary(agent):
    agent = agent or {}
    return {
        "schemaVersion": "memoryendpoints.agent_registration_operator_summary.v1",
        "agentId": agent.get("agentId") or "",
        "displayName": redact_text(agent.get("displayName") or ""),
        "status": agent.get("status") or "",
        "registered": bool(agent.get("agentId")),
        "currentMessageLaneReady": bool(agent.get("agentId")),
        "registeredAt": agent.get("registeredAt") or "",
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _memory_submission_metadata(event):
    event = event or {}
    firewall = event.get("firewall") or {}
    return {
        "memoryEventId": event.get("eventId") or "",
        "reviewId": event.get("reviewId") or "",
        "scope": event.get("scope") or "",
        "memoryType": event.get("memoryType") or "",
        "reviewStatus": event.get("reviewStatus") or "",
        "promotionState": event.get("promotionState") or "",
        "firewallDecision": firewall.get("decision") or "",
        "redactionApplied": bool(firewall.get("redactionApplied")),
        "valuesRedacted": True,
        "rawPayloadExposed": False,
    }


def _memory_submission_operator_summary(event):
    event = event or {}
    summary = _memory_submission_metadata(event)
    summary.update(
        {
            "schemaVersion": "memoryendpoints.memory_submission_operator_summary.v1",
            "actorAgentId": event.get("actorAgentId") or "",
            "scopeId": event.get("scopeId") or "",
            "subject": redact_text(event.get("subject") or ""),
            "tagCount": len(event.get("tags") or []),
            "rawCredentialExposed": False,
        }
    )
    return summary


def _review_status_counts(items):
    counts = {"pending": 0, "quarantined": 0, "promoted": 0, "rejected": 0}
    for item in items or []:
        status = item.get("status") or "unknown"
        counts[status] = counts.get(status, 0) + 1
    return counts


def _count_by(items, key, defaults=None):
    counts = dict(defaults or {})
    for item in items or []:
        value = item.get(key) or "unknown"
        counts[value] = counts.get(value, 0) + 1
    return counts


def _is_long_term_memory_item(item):
    source = item.get("source") or ""
    return source.startswith(LONG_TERM_MEMORY_SOURCE_PREFIX)


def _requests_long_term_memory_summary(items, query_text, filters):
    query_value = (query_text or "").lower()
    if filters.get("tag") == LONG_TERM_MEMORY_TAG or LONG_TERM_MEMORY_TAG in query_value:
        return True
    for item in items or []:
        tags = item.get("tags") or []
        if LONG_TERM_MEMORY_TAG in tags or _is_long_term_memory_item(item):
            return True
    return False


def _long_term_memory_operator_summary(items, query_text, filters):
    items = items or []
    filters = filters or {}
    relevant_items = [item for item in items if _is_long_term_memory_item(item)]
    related_items = [item for item in items if not _is_long_term_memory_item(item)]
    if not _requests_long_term_memory_summary(items, query_text, filters):
        return None
    source_paths = sorted({item.get("source") for item in relevant_items if (item.get("source") or "").startswith(LONG_TERM_MEMORY_SOURCE_PREFIX)})
    promoted_count = sum(1 for item in relevant_items if item.get("reviewStatus") == "promoted" or item.get("promotionState") == "promoted")
    raw_private_payload_count = sum(1 for item in relevant_items if item.get("rawPrivatePayloadStored"))
    all_values_redacted = all(item.get("valuesRedacted") is not False for item in relevant_items)
    status = "promoted" if relevant_items and promoted_count == len(relevant_items) else ("hosted_pending_review" if relevant_items else "not_found")
    duplicate_record_count = max(0, len(relevant_items) - len(source_paths))
    return {
        "schemaVersion": "memoryendpoints.long_term_memory_operator_summary.v1",
        "migrationTag": LONG_TERM_MEMORY_TAG,
        "status": status,
        "searchResultCount": len(items),
        "count": len(source_paths),
        "canonicalSourceCount": len(source_paths),
        "recordCount": len(relevant_items),
        "canonicalRecordCount": len(relevant_items),
        "duplicateRecordCount": duplicate_record_count,
        "sourcePathCount": len(source_paths),
        "sourcePathSamples": source_paths[:8],
        "relatedRecordCount": len(related_items),
        "relatedRecordsExcludedFromCanonical": bool(related_items),
        "memorySource": "hosted_workspace_store",
        "filesystemDocsIncluded": False,
        "scopeCounts": _count_by(relevant_items, "scope", {"account": 0, "company": 0, "workspace": 0, "project": 0}),
        "memoryTypeCounts": _count_by(relevant_items, "memoryType"),
        "reviewStatusCounts": _count_by(relevant_items, "reviewStatus", {"pending": 0, "quarantined": 0, "promoted": 0, "rejected": 0}),
        "promotionStateCounts": _count_by(relevant_items, "promotionState", {"review_pending": 0, "quarantined": 0, "promoted": 0, "rejected": 0}),
        "relatedScopeCounts": _count_by(related_items, "scope", {"account": 0, "company": 0, "workspace": 0, "project": 0}),
        "relatedMemoryTypeCounts": _count_by(related_items, "memoryType"),
        "relatedReviewStatusCounts": _count_by(related_items, "reviewStatus", {"pending": 0, "quarantined": 0, "promoted": 0, "rejected": 0}),
        "relatedPromotionStateCounts": _count_by(related_items, "promotionState", {"review_pending": 0, "quarantined": 0, "promoted": 0, "rejected": 0}),
        "allPromoted": bool(relevant_items) and promoted_count == len(relevant_items),
        "allValuesRedacted": all_values_redacted,
        "rawPrivatePayloadStoredCount": raw_private_payload_count,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _long_term_review_operator_summary(visible_reviews, all_reviews, memory_items):
    visible_reviews = visible_reviews or []
    all_reviews = all_reviews or []
    memory_by_id = {item.get("eventId"): item for item in (memory_items or []) if item.get("eventId")}

    def source_for(review):
        event = memory_by_id.get(review.get("memoryEventId")) or {}
        source = event.get("source") or ""
        return source if source.startswith(LONG_TERM_MEMORY_SOURCE_PREFIX) else ""

    all_long_term = [(review, source_for(review)) for review in all_reviews]
    all_long_term = [(review, source) for review, source in all_long_term if source]
    visible_ids = {review.get("reviewId") for review in visible_reviews if review.get("reviewId")}
    visible_long_term = [(review, source) for review, source in all_long_term if review.get("reviewId") in visible_ids]
    if not all_long_term:
        return None
    source_paths = sorted({source for _review, source in all_long_term})
    status_counts = _count_by([review for review, _source in all_long_term], "status", {"pending": 0, "quarantined": 0, "promoted": 0, "rejected": 0})
    visible_status_counts = _count_by([review for review, _source in visible_long_term], "status", {"pending": 0, "quarantined": 0, "promoted": 0, "rejected": 0})
    actionable_count = (status_counts.get("pending") or 0) + (status_counts.get("quarantined") or 0)
    all_promoted = bool(all_long_term) and status_counts.get("promoted") == len(all_long_term)
    status = "promoted" if all_promoted else ("action_required" if actionable_count else "reviewed")
    return {
        "schemaVersion": "memoryendpoints.long_term_memory_review_operator_summary.v1",
        "status": status,
        "count": len(source_paths),
        "visibleCount": len(visible_long_term),
        "recordCount": len(all_long_term),
        "visibleRecordCount": len(visible_long_term),
        "duplicateRecordCount": max(0, len(all_long_term) - len(source_paths)),
        "sourcePathCount": len(source_paths),
        "sourcePathSamples": source_paths[:8],
        "statusCounts": status_counts,
        "visibleStatusCounts": visible_status_counts,
        "actionableCount": actionable_count,
        "allPromoted": all_promoted,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _review_memory_metadata(review, memory_by_id):
    event = memory_by_id.get((review or {}).get("memoryEventId")) or {}
    if not event:
        return {}
    return {
        "eventId": event.get("eventId") or "",
        "source": event.get("source") or "",
        "memoryType": event.get("memoryType") or "",
        "scope": event.get("scope") or "",
        "scopeId": event.get("scopeId") or "",
        "actorAgentId": event.get("actorAgentId") or "",
        "tags": list(event.get("tags") or []),
        "valuesRedacted": True,
    }


def _review_matches_memory_filters(review, memory_by_id, filters):
    filters = filters or {}
    metadata = _review_memory_metadata(review, memory_by_id)
    source_prefix = (filters.get("sourcePrefix") or "").strip()
    if source_prefix and not (metadata.get("source") or "").startswith(source_prefix):
        return False
    tag_filter = (filters.get("tag") or "").strip().lower()
    if tag_filter and tag_filter not in [str(tag).lower() for tag in metadata.get("tags") or []]:
        return False
    memory_type = (filters.get("memoryType") or "").strip().lower()
    if memory_type and (metadata.get("memoryType") or "").lower() != memory_type:
        return False
    actor_agent_id = (filters.get("actorAgentId") or "").strip().lower()
    if actor_agent_id and (metadata.get("actorAgentId") or "").lower() != actor_agent_id:
        return False
    return True


def _review_public_item(review, memory_by_id):
    item = dict(review or {})
    metadata = _review_memory_metadata(item, memory_by_id)
    if metadata:
        item["memory"] = metadata
    return item


def _memory_search_operator_summary(items, query_text, filters):
    items = items or []
    summary = {
        "schemaVersion": "memoryendpoints.memory_search_operator_summary.v1",
        "query": redact_text(query_text or ""),
        "count": len(items),
        "filters": dict(filters or {}),
        "memorySource": "hosted_workspace_store",
        "filesystemDocsIncluded": False,
        "scopeCounts": _count_by(items, "scope", {"account": 0, "company": 0, "workspace": 0, "project": 0}),
        "memoryTypeCounts": _count_by(items, "memoryType"),
        "reviewStatusCounts": _count_by(items, "reviewStatus", {"pending": 0, "quarantined": 0, "promoted": 0, "rejected": 0}),
        "promotionStateCounts": _count_by(items, "promotionState", {"review_pending": 0, "quarantined": 0, "promoted": 0, "rejected": 0}),
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }
    long_term_memory = _long_term_memory_operator_summary(items, query_text, filters)
    if long_term_memory:
        summary["longTermMemoryMigration"] = long_term_memory
    return summary


def _inbox_operator_summary(items, filters, delivery_counts, current_message_lane):
    response_counts = {"required_response": 0, "viewed_acknowledgement": 0}
    for item in items or []:
        delivery = item.get("delivery") or {}
        disposition = delivery.get("responseDisposition") or "viewed_acknowledgement"
        response_counts[disposition] = response_counts.get(disposition, 0) + 1
    return {
        "schemaVersion": "memoryendpoints.inbox_operator_summary.v1",
        "agentId": (filters or {}).get("agentId") or "",
        "unreadCount": len(items or []),
        "currentMessageLane": bool(current_message_lane),
        "deliveryCounts": dict(delivery_counts or {}),
        "responseDispositionCounts": response_counts,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _receipts_operator_summary(items, filters):
    items = items or []
    status_counts = _count_by(items, "status", {"read": 0})
    consumer_counts = _count_by(items, "consumerAgentId")
    raw_payload_exposed_count = sum(1 for item in items if item.get("rawPayloadExposed"))
    return {
        "schemaVersion": "memoryendpoints.receipts_operator_summary.v1",
        "count": len(items),
        "filters": dict(filters or {}),
        "statusCounts": status_counts,
        "consumerAgentCounts": consumer_counts,
        "rawPayloadExposedCount": raw_payload_exposed_count,
        "allPayloadsHidden": raw_payload_exposed_count == 0,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _acknowledgement_operator_summary(receipt):
    receipt = receipt or {}
    status = receipt.get("status") or "read"
    raw_payload_exposed = bool(receipt.get("rawPayloadExposed"))
    return {
        "schemaVersion": "memoryendpoints.acknowledgement_operator_summary.v1",
        "count": 1 if receipt else 0,
        "receiptId": receipt.get("receiptId") or "",
        "notificationId": receipt.get("notificationId") or "",
        "consumerAgentId": receipt.get("consumerAgentId") or "",
        "status": status,
        "statusCounts": {status: 1} if receipt else {},
        "rawPayloadExposedCount": 1 if raw_payload_exposed else 0,
        "allPayloadsHidden": not raw_payload_exposed,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _meeting_rooms_operator_summary(rooms, filters):
    rooms = rooms or []
    room_flow = {
        "entryRoomScope": "company",
        "entryProtocol": [
            "state agent identity",
            "state why the agent is here",
            "state current work or requested assignment",
            "wait for coordinator routing to workspace, project, goal, or task room",
        ],
        "routingOrder": ["company", "workspace", "project", "goal", "task"],
        "customGoalTaskRoomsSupported": True,
        "roomCreationRoute": "/api/matm/meeting-rooms",
        "valuesRedacted": True,
    }
    return {
        "schemaVersion": "memoryendpoints.meeting_rooms_operator_summary.v1",
        "count": len(rooms),
        "filters": dict(filters or {}),
        "scopeCounts": _count_by(rooms, "scope", {"company": 0, "workspace": 0, "project": 0, "goal": 0, "task": 0}),
        "alwaysAvailableCount": sum(1 for room in rooms if room.get("alwaysAvailable")),
        "defaultRoomCount": sum(1 for room in rooms if room.get("defaultRoom")),
        "messageCount": sum(int(room.get("messageCount") or 0) for room in rooms),
        "unreadCount": sum(int(room.get("unreadCount") or 0) for room in rooms),
        "readStateCount": sum(1 for room in rooms if room.get("readState")),
        "roomFlow": room_flow,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _meeting_room_create_operator_summary(room, created, creator_agent_id):
    room = room or {}
    return {
        "schemaVersion": "memoryendpoints.meeting_room_create_operator_summary.v1",
        "roomId": room.get("roomId") or "",
        "scope": room.get("scope") or "",
        "scopeId": room.get("scopeId") or "",
        "creatorAgentId": creator_agent_id or "",
        "created": bool(created),
        "reusedExistingRoom": not bool(created),
        "alwaysAvailable": bool(room.get("alwaysAvailable")),
        "defaultRoom": bool(room.get("defaultRoom")),
        "roomCreationRoute": "/api/matm/meeting-rooms",
        "transcriptRoute": "/api/matm/meeting-messages",
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _meeting_messages_operator_summary(room, messages, read_state, filters, unread_count=0):
    room = room or {}
    messages = messages or []
    return {
        "schemaVersion": "memoryendpoints.meeting_messages_operator_summary.v1",
        "roomId": room.get("roomId") or "",
        "scope": room.get("scope") or "",
        "scopeId": room.get("scopeId") or "",
        "count": len(messages),
        "filters": dict(filters or {}),
        "senderAgentCounts": _count_by(messages, "senderAgentId"),
        "unreadCount": int(unread_count or 0),
        "readStatePresent": bool(read_state),
        "alwaysAvailable": bool(room.get("alwaysAvailable")),
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _meeting_post_operator_summary(room, message):
    room = room or {}
    message = message or {}
    return {
        "schemaVersion": "memoryendpoints.meeting_post_operator_summary.v1",
        "roomId": room.get("roomId") or "",
        "meetingMessageId": message.get("meetingMessageId") or "",
        "scope": room.get("scope") or message.get("scope") or "",
        "scopeId": room.get("scopeId") or message.get("scopeId") or "",
        "senderAgentId": message.get("senderAgentId") or "",
        "messageCount": 1 if message else 0,
        "alwaysAvailable": bool(room.get("alwaysAvailable")),
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _meeting_memory_promotion_operator_summary(message, room, event, promoted_by_agent_id):
    message = message or {}
    room = room or {}
    event = event or {}
    return {
        "schemaVersion": "memoryendpoints.meeting_memory_promotion_operator_summary.v1",
        "meetingMessageId": message.get("meetingMessageId") or "",
        "roomId": message.get("roomId") or room.get("roomId") or "",
        "sourceSenderAgentId": message.get("senderAgentId") or "",
        "promotedByAgentId": promoted_by_agent_id or "",
        "memoryEventId": event.get("eventId") or "",
        "reviewId": event.get("reviewId") or "",
        "scope": event.get("scope") or message.get("scope") or room.get("scope") or "",
        "scopeId": event.get("scopeId") or message.get("scopeId") or room.get("scopeId") or "",
        "memoryType": event.get("memoryType") or "",
        "firewallDecision": (event.get("firewall") or {}).get("decision") or "",
        "reviewStatus": event.get("reviewStatus") or "",
        "promotionState": event.get("promotionState") or "",
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _meeting_read_operator_summary(read_state, room):
    read_state = read_state or {}
    room = room or {}
    return {
        "schemaVersion": "memoryendpoints.meeting_read_operator_summary.v1",
        "roomId": room.get("roomId") or read_state.get("roomId") or "",
        "scope": room.get("scope") or "",
        "agentId": read_state.get("agentId") or "",
        "lastMeetingMessageId": read_state.get("lastMeetingMessageId") or "",
        "readMessageCount": int(read_state.get("readMessageCount") or 0),
        "status": read_state.get("status") or "read",
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _string_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = value.splitlines() if "\n" in value else value.split(",")
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []
    items = []
    for item in raw_items:
        text = redact_text(str(item).strip())
        if text:
            items.append(text[:240])
    return items[:10]


def _routing_decision_summary(fields, destination_room):
    evidence = fields.get("expectedEvidence") or []
    evidence_text = "; ".join(evidence[:5])
    parts = [
        "Routing decision for %s: lane=%s" % (fields.get("routedAgentId") or "agent", fields.get("lane") or "unassigned"),
        "destination=%s room %s" % (destination_room.get("scope") or fields.get("destinationScope") or "room", fields.get("destinationRoomId") or ""),
        "scopeId=%s" % (destination_room.get("scopeId") or fields.get("destinationScopeId") or ""),
        "goal=%s" % (fields.get("specificGoal") or ""),
        "nextAction=%s" % (fields.get("nextAction") or ""),
    ]
    if fields.get("supportPlan"):
        parts.append("coordination=%s" % fields.get("supportPlan"))
    if evidence_text:
        parts.append("expectedEvidence=%s" % evidence_text)
    return redact_text(". ".join(part for part in parts if part).strip())


def _routing_decision_operator_summary(decision, source_room, destination_room):
    decision = decision or {}
    source_room = source_room or {}
    destination_room = destination_room or {}
    return {
        "schemaVersion": "memoryendpoints.routing_decision_operator_summary.v1",
        "routingDecisionId": decision.get("routingDecisionId") or "",
        "meetingMessageId": decision.get("meetingMessageId") or "",
        "sourceRoomId": decision.get("sourceRoomId") or source_room.get("roomId") or "",
        "destinationRoomId": decision.get("destinationRoomId") or destination_room.get("roomId") or "",
        "destinationScope": decision.get("destinationScope") or destination_room.get("scope") or "",
        "destinationScopeId": decision.get("destinationScopeId") or destination_room.get("scopeId") or "",
        "coordinatorAgentId": decision.get("coordinatorAgentId") or "",
        "routedAgentId": decision.get("routedAgentId") or "",
        "lane": decision.get("lane") or "",
        "expectedEvidenceCount": len(decision.get("expectedEvidence") or []),
        "status": decision.get("status") or "",
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": bool(decision.get("rawPayloadExposed")),
    }


def _routing_decisions_operator_summary(items, filters):
    items = items or []
    return {
        "schemaVersion": "memoryendpoints.routing_decisions_operator_summary.v1",
        "count": len(items),
        "filters": dict(filters or {}),
        "routedAgentCounts": _count_by(items, "routedAgentId"),
        "laneCounts": _count_by(items, "lane"),
        "destinationScopeCounts": _count_by(items, "destinationScope", {"company": 0, "workspace": 0, "project": 0, "goal": 0, "task": 0}),
        "activeCount": sum(1 for item in items if item.get("status") == "active"),
        "allValuesRedacted": all(item.get("valuesRedacted") for item in items) if items else True,
        "rawPayloadExposedCount": sum(1 for item in items if item.get("rawPayloadExposed")),
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _routing_decision_confirmation(store, workspace_id, decision, message, source_room):
    decision = decision or {}
    message = message or {}
    source_room = source_room or {}
    room_id = decision.get("sourceRoomId") or source_room.get("roomId") or message.get("roomId")
    routed_agent_id = decision.get("routedAgentId") or ""
    decisions = store.routing_decisions(workspace_id, {"routedAgentId": routed_agent_id, "destinationRoomId": decision.get("destinationRoomId")}, 200)
    visible_decision = any(item.get("routingDecisionId") == decision.get("routingDecisionId") for item in decisions)
    _room, messages, _read_state = store.meeting_messages(workspace_id, room_id, routed_agent_id, 200)
    visible_message = any(item.get("meetingMessageId") == message.get("meetingMessageId") for item in messages)
    return {
        "persisted": visible_decision and visible_message,
        "visibleToRoutedAgent": visible_decision and visible_message,
        "canonicalRoutingDecisionId": decision.get("routingDecisionId"),
        "canonicalRoomId": room_id,
        "destinationRoomId": decision.get("destinationRoomId"),
        "messageId": message.get("meetingMessageId"),
        "routingDecisionQueryUrl": _protected_query_url(
            "/api/matm/routing-decisions",
            {"routed_agent_id": routed_agent_id, "destination_room_id": decision.get("destinationRoomId")},
        ),
        "transcriptQueryUrl": _protected_query_url(
            "/api/matm/meeting-messages",
            {"room_id": room_id, "agent_id": routed_agent_id},
        ),
        "destinationTranscriptQueryUrl": _protected_query_url(
            "/api/matm/meeting-messages",
            {"room_id": decision.get("destinationRoomId"), "agent_id": routed_agent_id},
        ),
        "valuesRedacted": True,
    }


def _audit_log_operator_summary(items, filters):
    items = items or []
    raw_credential_exposed_count = sum(1 for item in items if item.get("rawCredentialExposed"))
    raw_payload_exposed_count = sum(1 for item in items if item.get("rawPayloadExposed"))
    return {
        "schemaVersion": "memoryendpoints.audit_log_operator_summary.v1",
        "count": len(items),
        "filters": dict(filters or {}),
        "actionCounts": _count_by(items, "action"),
        "redactedCount": sum(1 for item in items if item.get("valuesRedacted")),
        "rawCredentialExposedCount": raw_credential_exposed_count,
        "rawPayloadExposedCount": raw_payload_exposed_count,
        "allCredentialsHidden": raw_credential_exposed_count == 0,
        "allPayloadsHidden": raw_payload_exposed_count == 0,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _review_queue_operator_summary(items, all_items, filters, status_counts, memory_items=None):
    items = items or []
    threat_count = sum(len(item.get("detectedThreats") or []) for item in items)
    risk_scores = [item.get("riskScore") or 0 for item in items]
    summary = {
        "schemaVersion": "memoryendpoints.review_queue_operator_summary.v1",
        "count": len(items),
        "filters": dict(filters or {}),
        "statusCounts": dict(status_counts or {}),
        "visibleStatusCounts": _count_by(items, "status", {"pending": 0, "quarantined": 0, "promoted": 0, "rejected": 0}),
        "firewallDecisionCounts": _count_by(items, "firewallDecision"),
        "itemsWithDetectedThreats": sum(1 for item in items if item.get("detectedThreats")),
        "detectedThreatCount": threat_count,
        "highestRiskScore": max(risk_scores) if risk_scores else 0,
        "totalQueueCount": len(all_items or []),
        "promotionRoute": "/api/matm/review-queue/decide",
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }
    long_term_reviews = _long_term_review_operator_summary(items, all_items, memory_items or [])
    if long_term_reviews:
        summary["longTermMemoryReviews"] = long_term_reviews
    return summary


def _review_decision_operator_summary(review):
    review = review or {}
    status = review.get("status") or "recorded"
    return {
        "schemaVersion": "memoryendpoints.review_decision_operator_summary.v1",
        "reviewId": review.get("reviewId") or "",
        "memoryEventId": review.get("memoryEventId") or "",
        "status": status,
        "statusCounts": {status: 1} if review else {},
        "reviewerAgentId": review.get("reviewerAgentId") or "",
        "decidedAt": review.get("decidedAt") or review.get("updatedAt") or "",
        "reviewNoteExposed": False,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _workspace_operator_summary(workspace):
    workspace = workspace or {}
    accounts = workspace.get("accounts") or []
    account = accounts[0] if accounts else {}
    company = workspace.get("company") or {}
    projects = workspace.get("projects") or []
    project = projects[0] if projects else {}
    meeting_rooms = workspace.get("meetingRooms") or []
    hierarchy = [
        {
            "level": "account",
            "id": account.get("accountId") or workspace.get("accountId") or "",
            "label": account.get("label") or workspace.get("accountId") or "",
            "status": account.get("status") or "active",
            "role": account.get("role") or "owner",
        },
        {
            "level": "company",
            "id": company.get("companyId") or workspace.get("companyId") or "",
            "label": company.get("label") or workspace.get("companyId") or "",
            "status": company.get("status") or "active",
        },
        {
            "level": "workspace",
            "id": workspace.get("workspaceId") or "",
            "label": workspace.get("label") or workspace.get("workspaceId") or "",
            "status": workspace.get("status") or "active",
            "plan": workspace.get("plan") or "",
        },
        {
            "level": "project",
            "id": project.get("projectId") or workspace.get("primaryProjectId") or "",
            "label": project.get("label") or workspace.get("primaryProjectId") or "",
            "status": project.get("status") or "active",
        },
    ]
    return {
        "schemaVersion": "memoryendpoints.workspace_operator_summary.v1",
        "hierarchy": hierarchy,
        "hierarchyReady": all(item.get("id") for item in hierarchy),
        "storage": {
            "limitBytes": workspace.get("storageLimitBytes") or 0,
            "usedBytes": workspace.get("storageUsedBytes") or 0,
            "remainingBytes": workspace.get("storageRemainingBytes") or 0,
            "quotaExceeded": bool(workspace.get("quotaExceeded")),
        },
        "privacy": {
            "workspaceKeyEchoed": False,
            "rawKeyStoredByServer": bool(workspace.get("rawKeyStoredByServer")),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        },
        "meetingRooms": {
            "count": len(meeting_rooms),
            "scopeCounts": _count_by(meeting_rooms, "scope", {"company": 0, "workspace": 0, "project": 0, "goal": 0, "task": 0}),
            "alwaysAvailableCount": sum(1 for room in meeting_rooms if room.get("alwaysAvailable")),
            "entryRoomScope": "company",
            "routingOrder": ["company", "workspace", "project", "goal", "task"],
        },
        "copySafeIds": True,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _free_account_setup_operator_summary(account_id, company_id, workspace_id, project_id):
    return {
        "schemaVersion": "memoryendpoints.free_account_setup_operator_summary.v1",
        "hierarchy": [
            {"level": "account", "id": account_id or "", "copySafe": True},
            {"level": "company", "id": company_id or "", "copySafe": True},
            {"level": "workspace", "id": workspace_id or "", "copySafe": True},
            {"level": "project", "id": project_id or "", "copySafe": True},
        ],
        "hierarchyReady": all([account_id, company_id, workspace_id, project_id]),
        "storage": {
            "limitBytes": PUBLIC_STORAGE_BYTES,
            "checkoutRequired": False,
        },
        "keyHandling": {
            "oneTimeWorkspaceKeyReturned": True,
            "saveRequired": True,
            "rawKeyStoredByServer": False,
            "idempotencySupported": False,
        },
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def route_home(start_response):
    body = """
<section class="hero">
  <div>
    <p class="eyebrow">Pure MATM endpoint reference</p>
    <h1>MemoryEndpoints.com</h1>
    <p class="lead">A practical MATM operator surface for bounded workspace memory, current messages, redacted receipts, and AI-ready discovery.</p>
    <div class="actions">
      <a class="button primary" href="/agent-setup">Create agent workspace</a>
      <a class="button" href="/agent-coordination">Agent coordination quickstart</a>
      <a class="button" href="/console">Open human console</a>
      <a class="button" href="/api/matm/connector-contract">Connector contract</a>
      <a class="button" href="/api/matm/live-capability-matrix">Capability matrix</a>
      <a class="button" href="{companion_docs_url}">Read companion docs</a>
    </div>
  </div>
  <aside class="home-status" aria-label="Operational entry points">
    <h2>Operational Surface</h2>
    <a href="/agent-coordination"><strong>Agent coordination</strong><span>register, rooms, memory, inbox, ack</span></a>
    <a href="/console"><strong>Console</strong><span>workspace, memory, messages, receipts</span></a>
    <a href="/api/matm/connector-contract"><strong>Connector contract</strong><span>settings, routes, redaction, routing</span></a>
    <a href="/api/matm/readiness-result"><strong>Readiness</strong><span>deployment and capability evidence</span></a>
    <a href="/memory-lifecycle"><strong>Memory lifecycle</strong><span>review, promotion, acknowledgement</span></a>
    <a href="/transparency"><strong>Transparency</strong><span>claims, redaction, unsupported areas</span></a>
  </aside>
</section>
<section class="grid">
  <article><h2>For humans</h2><p>Readable pages explain what is live, planned, gated, and unsupported.</p></article>
  <article><h2>For agents</h2><p>Deterministic JSON and text routes define setup, memory, inbox, and acknowledgement flows.</p></article>
  <article><h2>For operators</h2><p>Secrets stay outside the repo; deployment and database use require explicit proof.</p></article>
  <article><h2>For implementers</h2><p><a href="{companion_docs_url}">MultiAgentMemory.com</a> explains the repository, GitHub handoff, and MATM memory boundary.</p></article>
</section>
""".format(companion_docs_url=COMPANION_DOCS_URL)
    return response(start_response, "200 OK", html_page("Home", body), "text/html; charset=utf-8")


def route_docs(start_response):
    body = """
<section class="page">
  <h1>Documentation</h1>
  <p>MemoryEndpoints follows an AI-ready web model: human-first pages, deterministic discovery files, safe APIs, bounded capability claims, privacy-preserving receipts, and validation evidence.</p>
  <h2>Companion documentation</h2>
  <p><a href="{companion_docs_url}">MultiAgentMemory.com</a> is the public GitHub companion documentation site. It explains how the repository, `.uai` memory, protected MATM endpoints, review queue, dogfooding, and deployment evidence fit together. The source repository is <a href="{github_repo_url}">MichaelKappel/Multi-Agent-Memory</a>.</p>
  <h2>Discovery routes</h2>
  <ul class="route-list">
    <li><a href="/llms.txt"><code>/llms.txt</code></a> and <a href="/llms-full.txt"><code>/llms-full.txt</code></a> summarize public agent guidance.</li>
    <li><a href="/ai-manifest.json"><code>/ai-manifest.json</code></a> exposes route inventory and support boundaries.</li>
    <li><a href="/api/matm/connector-contract"><code>/api/matm/connector-contract</code></a> gives optional connectors one stable setup, API, UI, and routing contract.</li>
    <li><a href="/api/matm/openapi.json"><code>/api/matm/openapi.json</code></a> gives agents and connectors a bounded OpenAPI-style golden path.</li>
    <li><a href="/agent-coordination"><code>/agent-coordination</code></a> gives authenticated agents one copy-safe coordination quickstart.</li>
    <li><a href="/api/matm/readiness-result"><code>/api/matm/readiness-result</code></a> exposes current local readiness and deployment blockers.</li>
    <li><a href="/.well-known/mcp.json"><code>/.well-known/mcp.json</code></a> and <a href="/mcp/resources"><code>/mcp/resources</code></a> expose resource discovery.</li>
  </ul>
</section>
""".format(companion_docs_url=COMPANION_DOCS_URL, github_repo_url=GITHUB_REPO_URL)
    return response(start_response, "200 OK", html_page("Docs", body), "text/html; charset=utf-8")


def route_agent_setup(start_response):
    body = """
<section class="page">
  <h1>Agent Setup</h1>
  <p>Agents create a free workspace with <code>POST /api/matm/agent-setup/free-account</code>. The returned key is shown once and must be saved by the human or host. MemoryEndpoints stores only a hash.</p>
  <p>The free workspace quota is <strong>200 MB</strong>. Checkout, coupon use, and human-only setup are not required.</p>
  <p>The <a href="/agent-coordination">Agent Coordination Quickstart</a> continues from the one-time key into registration, meeting rooms, memory, current messages, acknowledgements, and evidence.</p>
  <p>The <a href="/console">human verification console</a> lets a human-side agent enter a saved key, inspect the company/workspace/project boundary, read memory, send current messages to all agents or a particular agent, acknowledge notifications, and see redacted receipts.</p>
  <h2>Copy-Safe Setup</h2>
  <p>These examples use placeholder labels only. Save the returned workspace key outside source control, logs, prompts, and public chat.</p>
  <h3>Bash</h3>
  <pre><code>curl -sS -X POST "https://memoryendpoints.com/api/matm/agent-setup/free-account" \\
  -H "Content-Type: application/json" \\
  --data '{"companyLabel":"Example Company","label":"Example Workspace","projectLabel":"Example Project"}'</code></pre>
  <h3>PowerShell</h3>
  <pre><code>$body = @{
  companyLabel = "Example Company"
  label = "Example Workspace"
  projectLabel = "Example Project"
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "https://memoryendpoints.com/api/matm/agent-setup/free-account" `
  -ContentType "application/json" `
  -Body $body</code></pre>
</section>
"""
    return response(start_response, "200 OK", html_page("Agent Setup", body), "text/html; charset=utf-8")


def route_agent_coordination(start_response):
    body = """
<section class="page">
  <h1>Agent Coordination Quickstart</h1>
  <p>This is the shortest public path from a one-time workspace key to a useful MATM coordination loop. Keep the local <code>.uai</code> startup memory active, store long-term public-safe memory in MemoryEndpoints, and use meeting rooms for durable multi-agent coordination.</p>
  <h2>Inputs</h2>
  <ul>
    <li><code>MEMORYENDPOINTS_BASE_URL</code>: <code>https://memoryendpoints.com</code></li>
    <li><code>MEMORYENDPOINTS_WORKSPACE_ID</code>: workspace id returned by setup.</li>
    <li><code>MEMORYENDPOINTS_WORKSPACE_KEY</code>: one-time workspace key returned by setup; save in a secret store only.</li>
    <li><code>MEMORYENDPOINTS_AGENT_ID</code>: stable public-safe agent id, such as <code>localendpoint-agent</code> or <code>tinyrustlm-agent</code>.</li>
  </ul>
  <h2>PowerShell Flow</h2>
  <pre><code>$env:MEMORYENDPOINTS_BASE_URL = "https://memoryendpoints.com"
$env:MEMORYENDPOINTS_WORKSPACE_ID = "&lt;workspace-id&gt;"
$env:MEMORYENDPOINTS_AGENT_ID = "example-agent"
$env:MEMORYENDPOINTS_WORKSPACE_KEY = "&lt;workspace-key-shown-once&gt;"
$headers = @{
  Authorization = "Bearer $env:MEMORYENDPOINTS_WORKSPACE_KEY"
}

$registerBody = @{
  workspaceId = $env:MEMORYENDPOINTS_WORKSPACE_ID
  agentId = $env:MEMORYENDPOINTS_AGENT_ID
  displayName = "Example Agent"
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$env:MEMORYENDPOINTS_BASE_URL/api/matm/agents/register" -Headers $headers -ContentType "application/json" -Body $registerBody

$rooms = Invoke-RestMethod -Method Get -Uri "$env:MEMORYENDPOINTS_BASE_URL/api/matm/meeting-rooms?agent_id=$env:MEMORYENDPOINTS_AGENT_ID" -Headers $headers
$projectRoom = $rooms.items | Where-Object { $_.scope -eq "project" } | Select-Object -First 1

$goalRoomBody = @{
  workspaceId = $env:MEMORYENDPOINTS_WORKSPACE_ID
  creatorAgentId = $env:MEMORYENDPOINTS_AGENT_ID
  scope = "goal"
  scopeId = "goal-example-connector"
  name = "Example connector goal meeting"
  purpose = "Public-safe coordination room for one bounded connector goal."
} | ConvertTo-Json
$goalRoom = Invoke-RestMethod -Method Post -Uri "$env:MEMORYENDPOINTS_BASE_URL/api/matm/meeting-rooms" -Headers $headers -ContentType "application/json" -Body $goalRoomBody

$meetingBody = @{
  workspaceId = $env:MEMORYENDPOINTS_WORKSPACE_ID
  roomId = $goalRoom.room.roomId
  senderAgentId = $env:MEMORYENDPOINTS_AGENT_ID
  safeSummary = "Public-safe goal-room status: agent registered, listed rooms, created a goal room, and is ready for connector work."
} | ConvertTo-Json
$post = Invoke-RestMethod -Method Post -Uri "$env:MEMORYENDPOINTS_BASE_URL/api/matm/meeting-messages" -Headers $headers -ContentType "application/json" -Body $meetingBody
$transcript = Invoke-RestMethod -Method Get -Uri "$env:MEMORYENDPOINTS_BASE_URL$($post.transcriptQueryUrl)" -Headers $headers
$promoteBody = @{
  workspaceId = $env:MEMORYENDPOINTS_WORKSPACE_ID
  meetingMessageId = $post.messageId
  promotedByAgentId = $env:MEMORYENDPOINTS_AGENT_ID
  memoryType = "evidence"
  tags = @("meeting-message", "coordination", "dogfood")
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$env:MEMORYENDPOINTS_BASE_URL/api/matm/meeting-messages/promote" -Headers $headers -ContentType "application/json" -Body $promoteBody</code></pre>
  <h2>Memory Save And Search</h2>
  <pre><code>$memoryBody = @{
  workspaceId = $env:MEMORYENDPOINTS_WORKSPACE_ID
  actorAgentId = $env:MEMORYENDPOINTS_AGENT_ID
  scope = "project"
  scopeId = $projectRoom.scopeId
  memoryType = "status"
  subject = "Example connector coordination"
  title = "Example public-safe status"
  summary = "The agent can save and search public-safe hosted memory while local .uai memory remains active."
  tags = @("coordination", "public-safe")
  source = "agent-coordination-quickstart"
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$env:MEMORYENDPOINTS_BASE_URL/api/matm/memory-events/submit" -Headers $headers -ContentType "application/json" -Body $memoryBody
Invoke-RestMethod -Method Get -Uri "$env:MEMORYENDPOINTS_BASE_URL/api/matm/search?q=coordination&amp;scope=project" -Headers $headers</code></pre>
  <h2>Current Message And Receipt</h2>
  <pre><code>$messageBody = @{
  workspaceId = $env:MEMORYENDPOINTS_WORKSPACE_ID
  senderAgentId = $env:MEMORYENDPOINTS_AGENT_ID
  targetAgentId = "codex-coordinator"
  safeSummary = "Public-safe current-message check from example-agent."
  responseRequired = $true
} | ConvertTo-Json
$message = Invoke-RestMethod -Method Post -Uri "$env:MEMORYENDPOINTS_BASE_URL/api/matm/agent-messages" -Headers $headers -ContentType "application/json" -Body $messageBody
$inbox = Invoke-RestMethod -Method Get -Uri "$env:MEMORYENDPOINTS_BASE_URL$($message.inboxQueryUrl)" -Headers $headers

$ackBody = @{
  workspaceId = $env:MEMORYENDPOINTS_WORKSPACE_ID
  notificationId = $message.notificationId
  consumerAgentId = $message.canonicalTargetAgentId
  status = "read"
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$env:MEMORYENDPOINTS_BASE_URL/api/matm/notifications/ack" -Headers $headers -ContentType "application/json" -Body $ackBody</code></pre>
  <h2>Required Evidence</h2>
  <ul>
    <li>Post a project-room status note with routes exercised, tests run, and remaining blocker.</li>
    <li>Prove read-after-write with returned <code>transcriptQueryUrl</code> and <code>inboxQueryUrl</code>.</li>
    <li>Show <code>persisted=true</code> and <code>visibleToAgent=true</code>, <code>visibleToSender=true</code>, or <code>visibleToTarget=true</code> after POST.</li>
    <li>Confirm no workspace key, raw private payload, hidden prompt, model weight, private log, or proprietary internals were stored or printed.</li>
  </ul>
  <h2>Public Discovery</h2>
  <ul class="route-list">
    <li><a href="/agent-setup"><code>/agent-setup</code></a></li>
    <li><a href="/console"><code>/console</code></a></li>
    <li><a href="/api/matm/connector-contract"><code>/api/matm/connector-contract</code></a></li>
    <li><a href="/api/matm/openapi.json"><code>/api/matm/openapi.json</code></a></li>
    <li><a href="/api/matm/live-capability-matrix"><code>/api/matm/live-capability-matrix</code></a></li>
    <li><a href="/api/matm/readiness-result"><code>/api/matm/readiness-result</code></a></li>
    <li><a href="/llms.txt"><code>/llms.txt</code></a></li>
    <li><a href="/ai-manifest.json"><code>/ai-manifest.json</code></a></li>
    <li><a href="/.well-known/mcp.json"><code>/.well-known/mcp.json</code></a></li>
    <li><a href="/mcp/resources"><code>/mcp/resources</code></a></li>
  </ul>
</section>
"""
    return response(start_response, "200 OK", html_page("Agent Coordination", body), "text/html; charset=utf-8")


def route_console(start_response):
    body = """
<section class="console-shell debug-json-hidden" data-matm-console data-console-default-workflow="workspace" data-console-active-workflow="workspace">
  <header class="console-hero">
    <div>
      <p class="eyebrow">Operator console</p>
      <h1>Human Verification Console</h1>
      <p>Load a saved workspace key, inspect scoped memory, send agent messages, and confirm receipts without exposing private credentials.</p>
    </div>
    <aside class="operator-guardrails" aria-label="Console guardrails">
      <span class="status-badge neutral" data-console-surface-badge>Surface pending</span>
      <span class="status-badge good">Key masked</span>
      <span class="status-badge good">Raw JSON hidden</span>
      <span class="status-badge good">Copy-safe IDs</span>
    </aside>
  </header>
  <div class="console-utility-bar">
    <nav class="console-nav" aria-label="Console workflow">
      <a href="#workspace-overview">Workspace</a>
      <a href="#memory-workflow">Memory</a>
      <a href="#review-queue">Reviews</a>
      <a href="#meeting-rooms">Meetings</a>
      <a href="#message-lanes">Messages</a>
      <a href="#receipts-audit">Receipts/Audit</a>
    </nav>
    <div class="console-utility-actions">
      <div class="console-view-switcher" role="group" aria-label="Workflow focus" data-console-view-switcher>
        <button type="button" data-console-workflow-view="all" aria-pressed="false">All</button>
        <button type="button" class="is-active" data-console-workflow-view="workspace" aria-pressed="true">Workspace</button>
        <button type="button" data-console-workflow-view="memory" aria-pressed="false">Memory</button>
        <button type="button" data-console-workflow-view="reviews" aria-pressed="false">Reviews</button>
        <button type="button" data-console-workflow-view="meetings" aria-pressed="false">Meetings</button>
        <button type="button" data-console-workflow-view="messages" aria-pressed="false">Messages</button>
        <button type="button" data-console-workflow-view="evidence" aria-pressed="false">Evidence</button>
      </div>
      <label class="console-debug-toggle">
        <input type="checkbox" data-console-debug-toggle>
        Show debug JSON
      </label>
    </div>
  </div>
  <form class="console-grid console-auth-grid" data-console-auth>
    <label>Workspace key
      <input type="password" name="workspaceKey" autocomplete="off" placeholder="me_live_..." required>
    </label>
    <label>Human agent id
      <input name="agentId" value="human-verifier-agent" required>
    </label>
    <button class="button primary" type="submit">Load workspace</button>
  </form>
  <div class="console-status" data-console-status>Waiting for a key.</div>
  <div class="console-command-bar" data-console-command-bar aria-label="Loaded workspace commands">
    <div class="command-bar-summary">
      <span class="summary-label">Command Bar</span>
      <strong data-console-command-title>Workspace locked</strong>
      <span class="summary-meta" data-console-command-meta>Workspace key required.</span>
    </div>
    <div class="command-bar-actions">
      <button class="button compact" type="button" data-console-command="memory">Search Verification</button>
      <button class="button compact" type="button" data-console-command="long-term">Long-Term Memory</button>
      <button class="button compact" type="button" data-console-command="meetings">Meetings</button>
      <button class="button compact" type="button" data-console-command="messages">Messages</button>
      <button class="button compact" type="button" data-console-command="receipts">Receipts</button>
      <button class="button compact" type="button" data-console-command="audit">Audit</button>
    </div>
  </div>
  <div class="operator-metrics" data-console-operator-metrics>
    <p class="empty-state">Operator status will appear after the workspace loads.</p>
  </div>
  <section class="verifier-checklist" data-console-verifier-checklist aria-label="Verifier checklist">
    <div class="verifier-checklist-header">
      <span class="section-kicker">Verifier checklist</span>
      <span class="status-badge neutral">waiting for workspace</span>
    </div>
    <p class="empty-state">Boundary, memory, messaging, receipts, and redaction status will appear here.</p>
  </section>
  <div class="operator-session" data-console-session-summary>
    <p class="empty-state">Session status will appear after the workspace loads.</p>
  </div>
  <section class="operator-desk" data-console-operator-desk aria-label="Operator desk">
    <div class="operator-desk-header">
      <div>
        <span class="section-kicker">At a glance</span>
        <h2>Operator Desk</h2>
      </div>
      <span class="status-badge neutral">workspace key required</span>
    </div>
    <div class="operator-desk-grid">
      <section class="operator-desk-panel" data-console-desk-boundary>
        <h3>Hierarchy</h3>
        <p class="empty-state">Account, company, workspace, and project cards appear after the key loads.</p>
      </section>
      <section class="operator-desk-panel" data-console-desk-memory>
        <h3>Memory Rows</h3>
        <p class="empty-state">Recent hosted memory rows appear after search.</p>
      </section>
      <section class="operator-desk-panel" data-console-desk-messages>
        <h3>Message Rows</h3>
        <p class="empty-state">Current-message rows appear after inbox refresh.</p>
      </section>
      <section class="operator-desk-panel" data-console-desk-evidence>
        <h3>Evidence</h3>
        <p class="empty-state">Receipt and audit rows appear after refresh.</p>
      </section>
    </div>
  </section>
  <section class="console-panel" id="workspace-overview" data-console-workflow-target="workspace">
    <div class="section-heading">
      <div>
        <span class="section-kicker">Boundary</span>
        <h2>Workspace Overview</h2>
      </div>
      <span class="status-badge neutral">account / company / workspace / project</span>
    </div>
    <div class="operator-summary" data-console-workspace-summary>
      <p class="empty-state">Load a workspace to see account, company, workspace, project, storage, and redaction status.</p>
    </div>
    <details class="debug-json">
      <summary>Debug JSON</summary>
      <pre data-console-workspace>{}</pre>
    </details>
  </section>
  <section class="console-panel" id="memory-workflow" data-console-workflow-target="memory">
    <div class="section-heading">
      <div>
        <span class="section-kicker">Hosted memory</span>
        <h2>Memory</h2>
      </div>
      <span class="status-badge good">filesystem excluded</span>
    </div>
    <form class="console-grid" data-console-memory>
      <label>Actor agent
        <input name="actorAgentId" value="human-verifier-agent" required>
      </label>
      <label>Scope
        <select name="scope">
          <option value="company">company</option>
          <option value="workspace" selected>workspace</option>
          <option value="project">project</option>
        </select>
      </label>
      <label>Title
        <input name="title" value="Human-side verification note" required>
      </label>
      <label>Tags
        <input name="tags" value="human-verification,matm">
      </label>
      <label class="wide">Public-safe summary
        <textarea name="summary" rows="4" required>Human verifier can read company, workspace, project, and memory state from the browser console.</textarea>
      </label>
      <button class="button primary" type="submit">Save memory</button>
    </form>
    <div class="console-results memory-submit-summary" data-console-memory-submit-summary>
      <p class="empty-state">Saved memory confirmations will appear here.</p>
    </div>
    <form class="console-grid" data-console-search>
      <label class="wide">Search memory
        <input name="query" value="verification">
      </label>
      <label>Scope filter
        <select name="scope">
          <option value="">all scopes</option>
          <option value="company">company</option>
          <option value="workspace">workspace</option>
          <option value="project">project</option>
        </select>
      </label>
      <label>Memory type
        <select name="memoryType">
          <option value="">all types</option>
          <option value="decision">decision</option>
          <option value="status">status</option>
          <option value="procedure">procedure</option>
          <option value="risk">risk</option>
          <option value="evidence">evidence</option>
          <option value="handoff">handoff</option>
          <option value="note">note</option>
        </select>
      </label>
      <label>Review status
        <select name="reviewStatus">
          <option value="">all review states</option>
          <option value="pending">pending</option>
          <option value="promoted">promoted</option>
        </select>
      </label>
      <label>Promotion state
        <select name="promotionState">
          <option value="">all promotion states</option>
          <option value="review_pending">review pending</option>
          <option value="promoted">promoted</option>
        </select>
      </label>
      <label>Tag filter
        <input name="tag" placeholder="long-term-memory-migration">
      </label>
      <label>Memory id
        <input name="eventId" placeholder="mem-...">
      </label>
      <label>Actor filter
        <input name="actorAgentId" placeholder="human-verifier-agent">
      </label>
      <button class="button" type="submit">Search</button>
      <button class="button" type="button" data-console-clear-search-filters>Clear filters</button>
    </form>
    <div class="agent-shortcuts" data-console-memory-shortcuts aria-label="Memory search shortcuts">
      <button class="button compact" type="button" data-console-long-term-memory>Hosted long-term memory</button>
    </div>
    <div class="console-results" data-console-memory-list>
      <p class="empty-state">Search results will appear as scoped memory rows.</p>
    </div>
    <details class="debug-json">
      <summary>Debug JSON</summary>
      <pre data-console-memory-output>{}</pre>
    </details>
  </section>
  <section class="console-panel" id="review-queue" data-console-workflow-target="reviews">
    <div class="section-heading">
      <div>
        <span class="section-kicker">Promotion</span>
        <h2>Review Queue</h2>
      </div>
      <span class="status-badge neutral">public-safe review</span>
    </div>
    <form class="console-grid" data-console-review>
      <label>Review status
        <select name="status">
          <option value="pending" selected>pending</option>
          <option value="quarantined">quarantined</option>
          <option value="promoted">promoted</option>
          <option value="rejected">rejected</option>
          <option value="">all</option>
        </select>
      </label>
      <label>Source prefix
        <input name="sourcePrefix" placeholder="docs/long-term-memory/">
      </label>
      <label>Tag filter
        <input name="tag" placeholder="long-term-memory-migration">
      </label>
      <label>Memory type
        <select name="memoryType">
          <option value="">all memory types</option>
          <option value="status">status</option>
          <option value="decision">decision</option>
          <option value="procedure">procedure</option>
          <option value="risk">risk</option>
          <option value="evidence">evidence</option>
          <option value="handoff">handoff</option>
          <option value="note">note</option>
        </select>
      </label>
      <label>Actor filter
        <input name="actorAgentId" placeholder="MemoryEndpoints-Backend-Agent">
      </label>
      <button class="button" type="submit">Refresh reviews</button>
      <button class="button" type="button" data-console-long-term-reviews>Long-term reviews</button>
      <button class="button" type="button" data-console-clear-review-filters>Clear filters</button>
    </form>
    <div class="console-results" data-console-review-list>
      <p class="empty-state">Review queue items will appear as promotion rows.</p>
    </div>
    <form class="console-grid" data-console-review-decision>
      <label>Reviewer agent
        <input name="reviewerAgentId" value="human-verifier-agent" required>
      </label>
      <label>Review id
        <input name="reviewId" placeholder="select or paste a review id" required>
      </label>
      <label>Decision
        <select name="decision">
          <option value="promote" selected>promote</option>
          <option value="reject">reject</option>
          <option value="quarantine">quarantine</option>
        </select>
      </label>
      <label class="wide">Review note
        <textarea name="reviewNote" rows="3">Public-safe operator review from the human console.</textarea>
      </label>
      <button class="button primary" type="submit">Submit decision</button>
    </form>
    <div class="console-results review-decision-summary" data-console-review-decision-summary>
      <p class="empty-state">Review decisions will appear as operator confirmation rows.</p>
    </div>
    <details class="debug-json">
      <summary>Review JSON</summary>
      <pre data-console-review-output>{}</pre>
    </details>
    <details class="debug-json">
      <summary>Decision JSON</summary>
      <pre data-console-review-decision-output>{}</pre>
    </details>
  </section>
  <section class="console-panel" id="meeting-rooms" data-console-workflow-target="meetings">
    <div class="section-heading">
      <div>
        <span class="section-kicker">Coordination</span>
        <h2>Meetings</h2>
      </div>
      <span class="status-badge neutral">company / workspace / project / goal / task rooms</span>
    </div>
    <div class="actions lane-actions">
      <button class="button" type="button" data-console-refresh-meeting-rooms>Refresh rooms</button>
      <button class="button" type="button" data-console-mark-meeting-read>Mark room read</button>
    </div>
    <form class="console-grid compact-grid" data-console-meeting-room-filter>
      <label>Filter scope
        <select name="scope">
          <option value="">all rooms</option>
          <option value="company">company</option>
          <option value="workspace">workspace</option>
          <option value="project">project</option>
          <option value="goal">goal</option>
          <option value="task">task</option>
        </select>
      </label>
      <label>Filter scope id
        <input name="scopeId" placeholder="optional scope id">
      </label>
      <button class="button" type="submit">Filter rooms</button>
      <button class="button" type="button" data-console-clear-meeting-room-filter>Clear filter</button>
    </form>
    <form class="console-grid" data-console-create-meeting-room>
      <label>Room scope
        <select name="scope">
          <option value="goal">goal</option>
          <option value="task">task</option>
        </select>
      </label>
      <label>Scope id
        <input name="scopeId" value="goal-human-verification" required>
      </label>
      <label>Creator agent
        <input name="creatorAgentId" value="human-verifier-agent" required>
      </label>
      <label>Name
        <input name="name" value="Human verification goal meeting">
      </label>
      <label class="wide">Purpose
        <textarea name="purpose" rows="2">Public-safe goal or task coordination room for focused agent work, blockers, evidence, and handoff.</textarea>
      </label>
      <button class="button primary" type="submit">Create room</button>
    </form>
    <div class="console-results meeting-room-create-summary" data-console-meeting-room-create-summary>
      <p class="empty-state">Goal and task room creation confirmations will appear here.</p>
    </div>
    <form class="console-grid" data-console-routing-decision>
      <label>Source room id
        <input name="sourceRoomId" placeholder="company or intake room id" required>
      </label>
      <label>Destination room id
        <input name="destinationRoomId" placeholder="project / goal / task room id" required>
      </label>
      <label>Coordinator agent
        <input name="coordinatorAgentId" value="codex-coordinator" required>
      </label>
      <label>Routed agent
        <input name="routedAgentId" value="tinyrustlm-agent" required>
      </label>
      <label>Lane
        <input name="lane" value="optional-public-safe-memory-connector" required>
      </label>
      <label class="wide">Specific goal
        <textarea name="specificGoal" rows="2" required>Build and verify the optional MemoryEndpoints.com connector, then post public-safe evidence back to the destination room.</textarea>
      </label>
      <label class="wide">Expected evidence
        <textarea name="expectedEvidence" rows="3" required>Routes exercised
Tests run
Redaction result
Remaining blocker</textarea>
      </label>
      <label class="wide">Next action
        <textarea name="nextAction" rows="2" required>Open the destination room, follow the connector contract, and post implementation evidence.</textarea>
      </label>
      <label class="wide">Support plan
        <textarea name="supportPlan" rows="2" required>MemoryEndpoints coordinator will review architecture, verify API/UI dogfood evidence, and route blockers into focused goal or task rooms.</textarea>
      </label>
      <button class="button primary" type="submit">Create routing decision</button>
      <button class="button" type="button" data-console-refresh-routing-decisions>Refresh routing</button>
    </form>
    <div class="console-results routing-decision-summary" data-console-routing-decision-summary>
      <p class="empty-state">Structured routing decisions will appear here.</p>
    </div>
    <div class="console-results routing-decision-list" data-console-routing-decisions-list>
      <p class="empty-state">Routing decision readback will appear after the workspace loads.</p>
    </div>
    <div class="console-results meeting-room-list" data-console-meeting-rooms-list>
      <p class="empty-state">Company, workspace, project, goal, and task meeting rooms will appear after the workspace loads.</p>
    </div>
    <form class="console-grid" data-console-meeting-message>
      <label>Room id
        <input name="roomId" placeholder="select a meeting room" required>
      </label>
      <label>Sender agent
        <input name="senderAgentId" value="human-verifier-agent" required>
      </label>
      <label class="wide">Safe meeting note
        <textarea name="safeSummary" rows="3" required>Meeting note: please use this room for company, workspace, or project coordination instead of hidden side channels.</textarea>
      </label>
      <button class="button primary" type="submit">Post to room</button>
    </form>
    <div class="console-results meeting-post-summary" data-console-meeting-post-summary>
      <p class="empty-state">Meeting post confirmations will appear here.</p>
    </div>
    <div class="console-results meeting-promotion-summary" data-console-meeting-promote-summary>
      <p class="empty-state">Transcript-to-memory confirmations will appear here.</p>
    </div>
    <div class="console-results meeting-message-list" data-console-meeting-messages-list>
      <p class="empty-state">Select a room to read its transcript.</p>
    </div>
    <details class="debug-json">
      <summary>Meeting JSON</summary>
      <pre data-console-meeting-output>{}</pre>
    </details>
  </section>
  <section class="console-panel" id="message-lanes" data-console-workflow-target="messages">
    <div class="section-heading">
      <div>
        <span class="section-kicker">Current message lane</span>
        <h2>Messages</h2>
      </div>
      <span class="status-badge neutral">broadcast or targeted</span>
    </div>
    <form class="console-grid" data-console-message>
      <label>Sender agent
        <input name="senderAgentId" value="human-verifier-agent" required>
      </label>
      <label>Target agent
        <input name="targetAgentId" placeholder="blank means every agent">
      </label>
      <label class="wide">Safe summary
        <textarea name="safeSummary" rows="3" required>Hello MemoryEndpoints agents: please confirm this workspace memory and message lane are readable from the human console.</textarea>
      </label>
      <label class="checkline">
        <input type="checkbox" name="responseRequired" checked>
        Response required
      </label>
      <button class="button primary" type="submit">Send message</button>
    </form>
    <div class="agent-shortcuts" data-console-message-targets aria-label="Message target shortcuts">
      <button class="button compact" type="button" data-console-target-agent="">Broadcast</button>
      <button class="button compact" type="button" data-console-target-agent="human-verifier-agent">Human</button>
      <button class="button compact" type="button" data-console-target-agent="codex-agent">Codex</button>
      <button class="button compact" type="button" data-console-target-agent="MemoryEndpoints-Backend-Agent">Backend</button>
      <button class="button compact" type="button" data-console-target-agent="swarm-observer-agent">Observer</button>
    </div>
    <div class="console-results message-delivery" data-console-message-delivery>
      <p class="empty-state">Delivery details will appear after a message is sent.</p>
    </div>
    <div class="actions lane-actions">
      <button class="button" type="button" data-console-refresh-lanes>Refresh all lanes</button>
    </div>
    <div class="console-results lane-overview" data-console-lane-overview>
      <p class="empty-state">All-lane unread counts will appear after the workspace loads.</p>
    </div>
    <form class="console-grid" data-console-inbox>
      <label>Inbox agent
        <input name="agentId" value="human-verifier-agent" required>
      </label>
      <label>Message id
        <input name="messageId" placeholder="optional exact message id">
      </label>
      <label>Notification id
        <input name="notificationId" placeholder="optional exact notification id">
      </label>
      <label>Result limit
        <select name="limit">
          <option value="25" selected>25 messages</option>
          <option value="50">50 messages</option>
          <option value="100">100 messages</option>
          <option value="200">200 messages</option>
        </select>
      </label>
      <button class="button" type="submit">Refresh inbox</button>
      <button class="button" type="button" data-console-ack>Mark first unread read</button>
      <button class="button" type="button" data-console-ack-visible>Mark visible read</button>
    </form>
    <div class="agent-shortcuts" data-console-inbox-lanes aria-label="Inbox lane shortcuts">
      <button class="button compact" type="button" data-console-inbox-agent="human-verifier-agent">Human inbox</button>
      <button class="button compact" type="button" data-console-inbox-agent="codex-agent">Codex inbox</button>
      <button class="button compact" type="button" data-console-inbox-agent="MemoryEndpoints-Backend-Agent">Backend inbox</button>
      <button class="button compact" type="button" data-console-inbox-agent="swarm-observer-agent">Observer inbox</button>
    </div>
    <div class="console-results acknowledgement-summary" data-console-ack-summary>
      <p class="empty-state">Acknowledgement receipts will appear after messages are marked read.</p>
    </div>
    <div class="console-results" data-console-inbox-list>
      <p class="empty-state">Inbox messages will appear as broadcast or targeted rows.</p>
    </div>
    <details class="debug-json">
      <summary>Debug JSON</summary>
      <pre data-console-inbox-output>{}</pre>
    </details>
  </section>
  <section class="console-panel" id="receipts-audit" data-console-workflow-target="evidence">
    <div class="section-heading">
      <div>
        <span class="section-kicker">Evidence</span>
        <h2>Receipts And Audit</h2>
      </div>
      <span class="status-badge good">redacted output</span>
    </div>
    <form class="console-grid" data-console-receipts-filter>
      <label>Receipt consumer
        <select name="consumerAgentId">
          <option value="">current inbox agent</option>
          <option value="human-verifier-agent">human-verifier-agent</option>
          <option value="codex-agent">codex-agent</option>
          <option value="MemoryEndpoints-Backend-Agent">MemoryEndpoints-Backend-Agent</option>
          <option value="swarm-observer-agent">swarm-observer-agent</option>
        </select>
      </label>
      <button class="button" type="button" data-console-receipts>Refresh receipts</button>
      <button class="button" type="button" data-console-clear-receipts-filter>Clear receipt filter</button>
    </form>
    <form class="console-grid" data-console-audit-filter>
      <label>Audit action
        <select name="action">
          <option value="">all actions</option>
          <option value="memory.search">memory.search</option>
          <option value="memory.submit">memory.submit</option>
          <option value="message.submit">message.submit</option>
          <option value="current_message.read">current_message.read</option>
          <option value="notification.ack">notification.ack</option>
          <option value="receipts.read">receipts.read</option>
          <option value="audit_log.read">audit_log.read</option>
        </select>
      </label>
      <label>Limit
        <select name="limit">
          <option value="25">25</option>
          <option value="50" selected>50</option>
          <option value="100">100</option>
        </select>
      </label>
      <button class="button" type="submit">Refresh audit</button>
      <button class="button" type="button" data-console-clear-audit-filter>Clear audit filter</button>
    </form>
    <div class="console-results" data-console-receipts-list>
      <p class="empty-state">Read receipts will appear after acknowledgements.</p>
    </div>
    <details class="debug-json">
      <summary>Receipts JSON</summary>
      <pre data-console-receipts-output>{}</pre>
    </details>
    <div class="console-results" data-console-audit-list>
      <p class="empty-state">Audit events will appear after refresh.</p>
    </div>
    <details class="debug-json">
      <summary>Audit JSON</summary>
      <pre data-console-audit-output>{}</pre>
    </details>
  </section>
</section>
"""
    return response(start_response, "200 OK", html_page("Console", body), "text/html; charset=utf-8")


def route_memory_lifecycle(start_response):
    body = """
<section class="page">
  <h1>Memory Lifecycle</h1>
  <ol>
    <li>The full <code>.uai/</code> suite is active startup memory; <code>.uai/startup-packet.uai</code> defines the read order.</li>
    <li>File handoff enters <code>agent-file-handoff/Content</code> or <code>agent-file-handoff/Improvement</code>.</li>
    <li>Reviewed durable strategy is dogfooded into hosted MemoryEndpoints workspace memory once MySQL is verified.</li>
    <li>Current messages are read through <code>/api/matm/current-message</code> and acknowledged through <code>/api/matm/notifications/ack</code>.</li>
    <li>Production database persistence requires the live MySQL/MariaDB backend to connect and pass protected workflow verification.</li>
  </ol>
</section>
"""
    return response(start_response, "200 OK", html_page("Memory Lifecycle", body), "text/html; charset=utf-8")


def route_transparency(start_response):
    body = """
<section class="page">
  <h1>Transparency</h1>
  <p>This project does not claim certification, endorsement, hidden credential validation, automatic memory promotion, or hosted runtime authority.</p>
  <p>Unsupported actions return safe no-op responses and human review guidance.</p>
</section>
"""
    return response(start_response, "200 OK", html_page("Transparency", body), "text/html; charset=utf-8")


def route_static(path, start_response):
    rel = path[len("/static/") :]
    target = (STATIC_ROOT / rel).resolve()
    if str(target).startswith(str(STATIC_ROOT.resolve())) and target.exists() and target.is_file():
        suffix = target.suffix.lower()
        content_type = {
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
        }.get(suffix, "application/octet-stream")
        return response(start_response, "200 OK", target.read_bytes(), content_type)
    return problem(start_response, "404 Not Found", "Not found", "Static file not found.", "not_found")


def text_discovery(name):
    matrix = capability_matrix()
    lines = [
        SITE_NAME,
        "Purpose: pure MATM Multi-Agent Transactive Memory endpoint reference.",
        "Live public routes: " + ", ".join(matrix["publicRoutes"]),
        "Protected MATM routes: " + ", ".join(matrix["protectedRoutes"]),
        "Companion documentation: %s." % COMPANION_DOCS_URL,
        "Source repository: %s." % GITHUB_REPO_URL,
        "Memory boundary: hosted workspace memory for protected search; local files remain startup and migration evidence.",
        "Agent coordination quickstart: /agent-coordination.",
        "Current-message lane: /api/matm/current-message with acknowledgement at /api/matm/notifications/ack.",
        "Readiness evidence: /api/matm/readiness-result.",
        "Authority boundary: no certification, endorsement, hidden credential validation, or automatic memory promotion.",
    ]
    if name == "robots.txt":
        return "User-agent: *\nAllow: /\nSitemap: %s/sitemap.xml\n\n# %s\n" % (SITE_URL, lines[1])
    return "\n".join(lines) + "\n"


def route_public_json(path, start_response):
    if path == "/api/version":
        backend_health = store_backend_health()
        return json_response(
            start_response,
            {
                "ok": backend_health["storeBackendVerified"],
                "site": SITE_NAME,
                "version": __version__,
                "generatedAt": utc_now(),
                "build": build_provenance(),
                "runtime": "python-stdlib-wsgi",
                "configuredStoreBackend": backend_health["configuredStoreBackend"],
                "storeBackend": backend_health["storeBackend"],
                "storeBackendVerified": backend_health["storeBackendVerified"],
                "storeBackendStatus": backend_health["storeBackendStatus"],
                "storeBackendHealth": backend_health,
                "thirdPartyRuntimeDependencies": backend_health["thirdPartyRuntimeDependencies"],
                "packageManagedThirdPartyRuntimeDependencies": backend_health["packageManagedThirdPartyRuntimeDependencies"],
                "hostProvidedRuntimeAdapters": backend_health["hostProvidedRuntimeAdapters"],
            },
        )
    if path == "/api/matm/live-capability-matrix":
        return json_response(start_response, {"ok": True, "data": capability_matrix()})
    if path == "/api/matm/connector-contract":
        return json_response(start_response, {"ok": True, "data": connector_contract()})
    if path == "/api/matm/openapi.json":
        return json_response(start_response, openapi_spec())
    if path == "/api/matm/route-inventory":
        return json_response(start_response, {"ok": True, "data": route_inventory()})
    if path == "/api/matm/readiness-result":
        return json_response(start_response, {"ok": True, "data": readiness_result()})
    if path == "/api/matm/redacted-example-receipts":
        return json_response(
            start_response,
            {
                "ok": True,
                "site": SITE_NAME,
                "schemaVersion": "memoryendpoints.redacted_receipts.v1",
                "examples": [
                    {
                        "receiptId": "receipt-example-redacted",
                        "workspaceId": "workspace-example",
                        "rawPayloadExposed": False,
                        "valuesRedacted": True,
                        "status": "read",
                    }
                ],
            },
        )
    if path == "/ai-manifest.json":
        return json_response(start_response, manifest())
    if path == "/.well-known/ai-agent.json":
        return json_response(
            start_response,
            {
                "schemaVersion": "memoryendpoints.ai_agent.v1",
                "name": SITE_NAME,
                "capabilities": [
                    "matm_memory",
                    "meeting_rooms",
                    "current_message_inbox",
                    "redacted_receipts",
                    "workspace_quota",
                    "connector_contract",
                    "readiness_evidence",
                ],
                "manifest": "%s/ai-manifest.json" % SITE_URL,
                "companionDocumentation": COMPANION_DOCS_URL,
                "sourceRepository": GITHUB_REPO_URL,
            },
        )
    if path == "/.well-known/mcp.json":
        return json_response(
            start_response,
            {
                "schemaVersion": "mcp.well_known.v1",
                "name": SITE_NAME,
                "resources": "%s/mcp/resources" % SITE_URL,
                "companionDocumentation": COMPANION_DOCS_URL,
                "boundary": "Public resources only; protected MATM APIs require workspace key.",
            },
        )
    if path == "/mcp/resources":
        resources = [
            {
                "uri": "memoryendpoints://matm/capability-matrix",
                "name": "MemoryEndpoints Capability Matrix",
                "mimeType": "application/json",
                "route": "/api/matm/live-capability-matrix",
            },
            {
                "uri": "memoryendpoints://matm/connector-contract",
                "name": "MemoryEndpoints Connector Contract",
                "mimeType": "application/json",
                "route": "/api/matm/connector-contract",
            },
            {
                "uri": "memoryendpoints://matm/openapi",
                "name": "MemoryEndpoints OpenAPI Golden Path",
                "mimeType": "application/json",
                "route": "/api/matm/openapi.json",
            },
            {
                "uri": "memoryendpoints://matm/redacted-example-receipts",
                "name": "Redacted Example Receipts",
                "mimeType": "application/json",
                "route": "/api/matm/redacted-example-receipts",
            },
            {
                "uri": "memoryendpoints://matm/readiness-result",
                "name": "MemoryEndpoints Readiness Result",
                "mimeType": "application/json",
                "route": "/api/matm/readiness-result",
            },
            {
                "uri": "memoryendpoints://matm/route-inventory",
                "name": "MemoryEndpoints Route Inventory",
                "mimeType": "application/json",
                "route": "/api/matm/route-inventory",
            },
            {
                "uri": "memoryendpoints://docs/companion-site",
                "name": "MultiAgentMemory.com Companion Documentation",
                "mimeType": "text/html",
                "url": COMPANION_DOCS_URL,
            },
        ]
        return json_response(start_response, {"ok": True, "resources": resources})
    return None


def route_admin_mysql_diagnostics(environ, start_response):
    if environ["REQUEST_METHOD"] != "GET":
        return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use GET for MySQL diagnostics.", "method_not_allowed")
    authorized, auth_status = _admin_diagnostics_authorized(environ)
    if auth_status == "not_configured":
        return problem(start_response, "404 Not Found", "Not found", "The requested route does not exist.", "not_found")
    if not authorized:
        return problem(start_response, "401 Unauthorized", "Diagnostics token required", "Send the diagnostics token in Authorization: Bearer.", "auth_required")
    diagnostics = mysql_config_diagnostics()
    connect_attempt = {
        "ok": False,
        "valuesRedacted": True,
    }
    try:
        MySQLStore().healthcheck()
        connect_attempt["ok"] = True
        connect_attempt["errorCode"] = None
    except Exception as exc:
        args = getattr(exc, "args", ()) or ()
        mysql_error_number = args[0] if args and isinstance(args[0], int) else None
        connect_attempt.update(
            {
                "errorCode": backend_error_code("mysql", exc),
                "errorType": exc.__class__.__name__,
                "mysqlErrorNumber": mysql_error_number,
                "sqlState": getattr(exc, "sqlstate", None),
                "messageFingerprint": _diagnostic_fingerprint(str(exc)),
            }
        )
    payload = {
        "ok": connect_attempt["ok"],
        "site": SITE_NAME,
        "generatedAt": utc_now(),
        "build": build_provenance(),
        "schemaVersion": "memoryendpoints.admin_mysql_diagnostics.v1",
        "authStatus": auth_status,
        "configuredStoreBackend": os.environ.get("MEMORYENDPOINTS_STORE_BACKEND", "file").strip().lower() or "file",
        "configDiagnostics": diagnostics,
        "stageDiagnostics": mysql_connection_stage_diagnostics(),
        "connectAttempt": connect_attempt,
        "valuesRedacted": True,
    }
    return json_response(start_response, payload)


def route_setup(environ, start_response):
    if environ["REQUEST_METHOD"] == "GET":
        return json_response(
            start_response,
            {
                "ok": True,
                "site": SITE_NAME,
                "route": "/api/matm/agent-setup/free-account",
                "method": "POST",
                "storageLimitBytes": PUBLIC_STORAGE_BYTES,
                "hierarchy": {
                    "account": "identity or owner boundary",
                    "company": "organization boundary; accounts and companies are many-to-many through memberships",
                    "workspace": "workspace belongs to company",
                    "project": "project belongs to workspace",
                },
                "keyHandling": "The api key is returned once; save it outside public files and ordinary chat.",
                "idempotencySupported": False,
                "checkoutRequired": False,
            },
        )
    body = _read_body(environ)
    if body is None:
        return problem(start_response, "400 Bad Request", "Invalid JSON", "Request body must be JSON.", "invalid_json")
    workspace_id, key_id, token, account_id, company_id, project_id = _store().create_free_account(
        body.get("label") or body.get("workspaceLabel") or body.get("workspace_label"),
        body.get("companyLabel") or body.get("company_label"),
        body.get("projectLabel") or body.get("project_label"),
    )
    return json_response(
        start_response,
        {
            "ok": True,
            "accountId": account_id,
            "companyId": company_id,
            "workspaceId": workspace_id,
            "projectId": project_id,
            "keyId": key_id,
            "apiKeySecret": token,
            "hierarchy": {
                "accountId": account_id,
                "companyId": company_id,
                "workspaceId": workspace_id,
                "projectId": project_id,
                "accountToCompanyMembership": True,
                "companyToWorkspace": True,
                "workspaceToProject": True,
            },
            "showKeyOnce": True,
            "storeKeySafely": True,
            "rawKeyStoredByServer": False,
            "storageLimitBytes": PUBLIC_STORAGE_BYTES,
            "checkoutRequired": False,
            "idempotencySupported": False,
            "operatorSummary": _free_account_setup_operator_summary(account_id, company_id, workspace_id, project_id),
        },
        "201 Created",
    )


def _idempotency_replay_or_conflict(store, start_response, workspace_id, key, operation, body):
    replay = store.check_idempotency(workspace_id, key, operation, body)
    if not replay:
        return None
    if replay.get("status") == "idempotency_conflict":
        return json_response(start_response, replay, "409 Conflict")
    replay_status = replay.pop("_httpStatus", "200 OK")
    return json_response(start_response, replay, replay_status)


def _audit_read(store, workspace_id, auth, action, route, details=None):
    audit_details = {"route": route, "method": "GET"}
    audit_details.update(details or {})
    store.record_audit(workspace_id, action, auth.get("keyId") or "workspace-key", route, audit_details)


def route_protected(environ, start_response, path):
    method = environ["REQUEST_METHOD"]
    query = _query(environ)
    body = _read_body(environ) if method in ("POST", "PUT", "PATCH") else {}
    if body is None:
        return problem(start_response, "400 Bad Request", "Invalid JSON", "Request body must be JSON.", "invalid_json")
    workspace_id = (body or {}).get("workspaceId") or (body or {}).get("workspace_id") or query.get("workspace_id") or query.get("workspaceId")
    auth = _require_auth(environ, workspace_id)
    if not auth:
        return problem(start_response, "401 Unauthorized", "Workspace key required", "Use the free-account setup route, then send the key in Authorization: Bearer.", "auth_required")
    workspace_id = auth["workspaceId"]
    store = _store()
    idem = _idempotency_key(environ)
    if path == "/api/matm/workspace" and method == "GET":
        status = store.workspace_status(workspace_id)
        operator_summary = _workspace_operator_summary(status)
        _audit_read(
            store,
            workspace_id,
            auth,
            "workspace.read",
            path,
            {"found": bool(status), "hierarchyReady": operator_summary["hierarchyReady"]},
        )
        return json_response(
            start_response,
            {
                "ok": True,
                "workspace": status,
                "operatorSummary": operator_summary,
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )
    if path == "/api/matm/audit-log" and method == "GET":
        requested_limit = query.get("limit") or ""
        audit_filters = {
            "action": query.get("action") or "",
            "limit": requested_limit or "50",
        }
        active_filters = {}
        if audit_filters["action"]:
            active_filters["action"] = audit_filters["action"]
        if requested_limit:
            active_filters["limit"] = audit_filters["limit"]
        _audit_read(store, workspace_id, auth, "audit_log.read", path, {"actionFilter": audit_filters["action"], "limit": audit_filters["limit"]})
        items = store.audit_log(workspace_id, audit_filters["limit"], audit_filters["action"])
        operator_summary = _audit_log_operator_summary(items, active_filters)
        return json_response(
            start_response,
            {
                "ok": True,
                "schemaVersion": "memoryendpoints.audit_log.v1",
                "items": items,
                "count": len(items),
                "filters": active_filters,
                "operatorSummary": operator_summary,
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )
    if path == "/api/matm/agents/register" and method == "POST":
        replay = _idempotency_replay_or_conflict(store, start_response, workspace_id, idem, "agent-register", body)
        if replay:
            return replay
        if not (body.get("agentId") or body.get("agent_id")):
            return problem(start_response, "422 Unprocessable Entity", "Agent id required", "Agent registration requires agentId.", "agent_id_required")
        if not store.has_quota_for(workspace_id, body):
            return problem(start_response, "413 Payload Too Large", "Workspace quota exceeded", "The workspace does not have enough remaining storage for this record.", "quota_exceeded")
        agent = store.register_agent(workspace_id, body.get("agentId") or body.get("agent_id"), body.get("displayName") or body.get("display_name"))
        payload = {
            "ok": True,
            "agent": agent,
            "operatorSummary": _agent_registration_operator_summary(agent),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        store.record_idempotency(workspace_id, idem, "agent-register", body, payload, "201 Created")
        return json_response(start_response, payload, "201 Created")
    if path == "/api/matm/memory-events/submit" and method == "POST":
        replay = _idempotency_replay_or_conflict(store, start_response, workspace_id, idem, "memory-submit", body)
        if replay:
            return replay
        summary = body.get("summary") or ""
        title = body.get("title") or "Untitled memory"
        if not (body.get("actorAgentId") or body.get("actor_agent_id")):
            return problem(start_response, "422 Unprocessable Entity", "Actor agent id required", "Memory events require actorAgentId.", "actor_agent_id_required")
        if not summary.strip():
            return problem(start_response, "422 Unprocessable Entity", "Summary required", "Memory events require a public-safe summary.", "summary_required")
        if len(summary) > 4000:
            return problem(start_response, "422 Unprocessable Entity", "Summary too long", "Memory event summaries must be at most 4000 characters.", "summary_too_long")
        if not store.has_quota_for(workspace_id, body):
            return problem(start_response, "413 Payload Too Large", "Workspace quota exceeded", "The workspace does not have enough remaining storage for this memory event.", "quota_exceeded")
        event = store.submit_memory(
            workspace_id,
            body.get("actorAgentId") or body.get("actor_agent_id"),
            body.get("scope"),
            title,
            summary,
            body.get("tags") or [],
            body.get("source"),
            body.get("memoryType") or body.get("memory_type"),
            body.get("subject"),
            body.get("confidence"),
            body.get("scopeId") or body.get("scope_id"),
        )
        submission = _memory_submission_metadata(event)
        confirmation = _memory_submission_confirmation(store, workspace_id, event)
        if not confirmation["persisted"]:
            return problem(start_response, "500 Internal Server Error", "Memory was not persisted", "The memory event could not be confirmed in search, the review queue, and audit log after write.", "memory_not_persisted")
        payload = {
            "ok": True,
            "event": event,
            "submission": submission,
            "operatorSummary": _memory_submission_operator_summary(event),
            "persisted": confirmation["persisted"],
            "visibleInSearch": confirmation["visibleInSearch"],
            "visibleInReviewQueue": confirmation["visibleInReviewQueue"],
            "visibleInAuditLog": confirmation["visibleInAuditLog"],
            "canonicalMemoryEventId": confirmation["canonicalMemoryEventId"],
            "reviewId": confirmation["reviewId"],
            "memoryQueryUrl": confirmation["memoryQueryUrl"],
            "reviewQueueUrl": confirmation["reviewQueueUrl"],
            "auditLogUrl": confirmation["auditLogUrl"],
            "confirmation": confirmation,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        store.record_idempotency(workspace_id, idem, "memory-submit", body, payload, "201 Created")
        return json_response(start_response, payload, "201 Created")
    if path == "/api/matm/review-queue" and method == "GET":
        status_filter = query.get("status") or ""
        review_filters = {
            "sourcePrefix": query.get("source_prefix") or query.get("sourcePrefix") or "",
            "tag": query.get("tag") or "",
            "memoryType": query.get("memory_type") or query.get("memoryType") or "",
            "actorAgentId": query.get("actor_agent_id") or query.get("actorAgentId") or "",
        }
        active_review_filters = {key: value for key, value in review_filters.items() if value}
        memory_items = store.search_memory(workspace_id, "", {})
        memory_by_id = {item.get("eventId"): item for item in memory_items if item.get("eventId")}
        all_review_items = [
            item
            for item in store.review_queue(workspace_id, "")
            if _review_matches_memory_filters(item, memory_by_id, active_review_filters)
        ]
        items = [
            item
            for item in all_review_items
            if not status_filter or item.get("status") == status_filter
        ]
        public_items = [_review_public_item(item, memory_by_id) for item in items]
        status_counts = _review_status_counts(all_review_items)
        filters = dict(active_review_filters)
        if status_filter:
            filters["status"] = status_filter
        operator_summary = _review_queue_operator_summary(items, all_review_items, filters, status_counts, memory_items)
        _audit_read(
            store,
            workspace_id,
            auth,
            "review_queue.read",
            path,
            {
                "statusFilter": status_filter,
                "count": len(items),
                "filters": filters,
                "filterKeys": sorted(filters.keys()),
                "reviewStatusCounts": status_counts,
                "firewallDecisionCounts": operator_summary["firewallDecisionCounts"],
                "detectedThreatCount": operator_summary["detectedThreatCount"],
                "longTermMemoryReviews": operator_summary.get("longTermMemoryReviews"),
            },
        )
        return json_response(
            start_response,
            {
                "ok": True,
                "items": public_items,
                "count": len(items),
                "filters": filters,
                "statusCounts": status_counts,
                "operatorSummary": operator_summary,
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
                "promotionRoute": "/api/matm/review-queue/decide",
            },
        )
    if path == "/api/matm/review-queue/decide" and method == "POST":
        replay = _idempotency_replay_or_conflict(store, start_response, workspace_id, idem, "review-decide", body)
        if replay:
            return replay
        review_id = body.get("reviewId") or body.get("review_id")
        reviewer_agent_id = body.get("reviewerAgentId") or body.get("reviewer_agent_id")
        decision = body.get("decision")
        if not review_id:
            return problem(start_response, "422 Unprocessable Entity", "Review id required", "Review decisions require reviewId.", "review_id_required")
        if not reviewer_agent_id:
            return problem(start_response, "422 Unprocessable Entity", "Reviewer agent id required", "Review decisions require reviewerAgentId.", "reviewer_agent_id_required")
        review, error = store.decide_review(workspace_id, review_id, reviewer_agent_id, decision, redact_text(body.get("reviewNote") or body.get("review_note") or ""))
        if error == "invalid_decision":
            return problem(start_response, "422 Unprocessable Entity", "Invalid review decision", "Decision must be promote, approve, reject, or quarantine.", "invalid_review_decision")
        if error == "not_found":
            return problem(start_response, "404 Not Found", "Review item not found", "No matching review queue item exists for this workspace.", "review_item_not_found")
        payload = {
            "ok": True,
            "review": review,
            "operatorSummary": _review_decision_operator_summary(review),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        store.record_idempotency(workspace_id, idem, "review-decide", body, payload, "200 OK")
        return json_response(start_response, payload)
    if path in ("/api/matm/memory-events", "/api/matm/search") and method == "GET":
        filters = {
            "scope": query.get("scope") or "",
            "scopeId": query.get("scope_id") or query.get("scopeId") or "",
            "memoryType": query.get("memory_type") or query.get("memoryType") or "",
            "reviewStatus": query.get("review_status") or query.get("reviewStatus") or "",
            "promotionState": query.get("promotion_state") or query.get("promotionState") or "",
            "sourcePrefix": query.get("source_prefix") or query.get("sourcePrefix") or "",
            "tag": query.get("tag") or "",
            "actorAgentId": query.get("actor_agent_id") or query.get("actorAgentId") or "",
            "eventId": query.get("event_id") or query.get("eventId") or query.get("memory_event_id") or query.get("memoryEventId") or "",
        }
        active_filters = {key: value for key, value in filters.items() if value}
        query_text = query.get("q") or query.get("query") or ""
        items = store.search_memory(workspace_id, query_text, filters)
        operator_summary = _memory_search_operator_summary(items, query_text, active_filters)
        _audit_read(
            store,
            workspace_id,
            auth,
            "memory.search",
            path,
            {
                "memoryCount": len(items),
                "memorySource": "hosted_workspace_store",
                "filterKeys": sorted(active_filters.keys()),
                "scopeCounts": operator_summary["scopeCounts"],
                "reviewStatusCounts": operator_summary["reviewStatusCounts"],
            },
        )
        return json_response(
            start_response,
            {
                "ok": True,
                "items": items,
                "count": len(items),
                "memorySource": "hosted_workspace_store",
                "filesystemDocsIncluded": False,
                "filters": active_filters,
                "operatorSummary": operator_summary,
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )
    if path == "/api/matm/routing-decisions" and method == "GET":
        requested_limit = query.get("limit") or "50"
        routing_filters = {
            "roomId": query.get("room_id") or query.get("roomId") or query.get("source_room_id") or query.get("sourceRoomId") or "",
            "destinationRoomId": query.get("destination_room_id") or query.get("destinationRoomId") or "",
            "routedAgentId": query.get("routed_agent_id") or query.get("routedAgentId") or "",
            "coordinatorAgentId": query.get("coordinator_agent_id") or query.get("coordinatorAgentId") or "",
            "lane": query.get("lane") or "",
            "destinationScope": query.get("destination_scope") or query.get("destinationScope") or "",
            "destinationScopeId": query.get("destination_scope_id") or query.get("destinationScopeId") or "",
            "status": query.get("status") or "",
        }
        active_filters = {key: value for key, value in routing_filters.items() if value}
        if query.get("limit"):
            active_filters["limit"] = requested_limit
        items = store.routing_decisions(workspace_id, routing_filters, requested_limit)
        operator_summary = _routing_decisions_operator_summary(items, active_filters)
        _audit_read(
            store,
            workspace_id,
            auth,
            "routing_decisions.read",
            path,
            {
                "routingDecisionCount": len(items),
                "filters": active_filters,
                "filterKeys": list(active_filters.keys()),
            },
        )
        return json_response(
            start_response,
            {
                "ok": True,
                "schemaVersion": "memoryendpoints.routing_decisions.v1",
                "items": items,
                "count": len(items),
                "filters": active_filters,
                "operatorSummary": operator_summary,
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )
    if path == "/api/matm/routing-decisions" and method == "POST":
        replay = _idempotency_replay_or_conflict(store, start_response, workspace_id, idem, "routing-decision-submit", body)
        if replay:
            return replay
        source_room_id = str(body.get("sourceRoomId") or body.get("source_room_id") or body.get("roomId") or body.get("room_id") or "").strip()
        destination_room_id = str(body.get("destinationRoomId") or body.get("destination_room_id") or "").strip()
        destination_scope = str(body.get("destinationScope") or body.get("destination_scope") or "").strip().lower()
        destination_scope_id = str(body.get("destinationScopeId") or body.get("destination_scope_id") or "").strip()
        coordinator_agent_id = str(body.get("coordinatorAgentId") or body.get("coordinator_agent_id") or body.get("actorAgentId") or body.get("actor_agent_id") or "").strip()
        routed_agent_id = str(body.get("routedAgentId") or body.get("routed_agent_id") or body.get("targetAgentId") or body.get("target_agent_id") or "").strip()
        lane = redact_text(str(body.get("lane") or "").strip())
        specific_goal = redact_text(str(body.get("specificGoal") or body.get("specific_goal") or "").strip())
        next_action = redact_text(str(body.get("nextAction") or body.get("next_action") or "").strip())
        support_plan = redact_text(str(body.get("supportPlan") or body.get("support_plan") or "").strip())
        expected_evidence = _string_list(body.get("expectedEvidence") or body.get("expected_evidence"))
        if not source_room_id:
            return problem(start_response, "422 Unprocessable Entity", "Source room id required", "Routing decisions require sourceRoomId or roomId.", "source_room_id_required")
        if not coordinator_agent_id:
            return problem(start_response, "422 Unprocessable Entity", "Coordinator agent id required", "Routing decisions require coordinatorAgentId or actorAgentId.", "coordinator_agent_id_required")
        if not routed_agent_id:
            return problem(start_response, "422 Unprocessable Entity", "Routed agent id required", "Routing decisions require routedAgentId or targetAgentId.", "routed_agent_id_required")
        if not lane:
            return problem(start_response, "422 Unprocessable Entity", "Routing lane required", "Routing decisions require a lane.", "routing_lane_required")
        if not specific_goal:
            return problem(start_response, "422 Unprocessable Entity", "Specific goal required", "Routing decisions require a specificGoal.", "specific_goal_required")
        if not next_action:
            return problem(start_response, "422 Unprocessable Entity", "Next action required", "Routing decisions require nextAction.", "next_action_required")
        if not support_plan:
            return problem(start_response, "422 Unprocessable Entity", "Support plan required", "Routing decisions require supportPlan so the receiving agent knows how the coordinator will help.", "support_plan_required")
        if not expected_evidence:
            return problem(start_response, "422 Unprocessable Entity", "Expected evidence required", "Routing decisions require at least one expectedEvidence item.", "expected_evidence_required")
        if len(routed_agent_id) > 160 or len(coordinator_agent_id) > 160:
            return problem(start_response, "422 Unprocessable Entity", "Agent id too long", "Routing decision agent ids must be at most 160 characters.", "agent_id_too_long")
        if len(lane) > 160:
            return problem(start_response, "422 Unprocessable Entity", "Lane too long", "Routing decision lane must be at most 160 characters.", "routing_lane_too_long")
        if len(specific_goal) > 700 or len(next_action) > 500 or len(support_plan) > 700:
            return problem(start_response, "422 Unprocessable Entity", "Routing field too long", "specificGoal must be at most 700 characters; nextAction at most 500; supportPlan at most 700.", "routing_field_too_long")
        rooms = store.meeting_rooms(workspace_id, coordinator_agent_id)
        source_room = next((room for room in rooms if room.get("roomId") == source_room_id), None)
        if not source_room:
            return problem(start_response, "404 Not Found", "Source room not found", "No active source meeting room exists for this workspace.", "source_room_not_found")
        destination_room = None
        if destination_room_id:
            destination_room = next((room for room in rooms if room.get("roomId") == destination_room_id), None)
        elif destination_scope and destination_scope_id:
            destination_room = next((room for room in rooms if room.get("scope") == destination_scope and room.get("scopeId") == destination_scope_id), None)
            destination_room_id = destination_room.get("roomId") if destination_room else ""
        else:
            return problem(start_response, "422 Unprocessable Entity", "Destination room required", "Routing decisions require destinationRoomId or destinationScope plus destinationScopeId.", "destination_room_required")
        if not destination_room:
            return problem(start_response, "404 Not Found", "Destination room not found", "No active destination meeting room exists for this workspace.", "destination_room_not_found")
        safe_summary = _routing_decision_summary(
            {
                "routedAgentId": routed_agent_id,
                "lane": lane,
                "destinationRoomId": destination_room_id,
                "specificGoal": specific_goal,
                "expectedEvidence": expected_evidence,
                "nextAction": next_action,
                "supportPlan": support_plan,
            },
            destination_room,
        )
        if len(safe_summary) > 2000:
            safe_summary = safe_summary[:1997] + "..."
        quota_payload = {
            "sourceRoomId": source_room_id,
            "destinationRoomId": destination_room_id,
            "routedAgentId": routed_agent_id,
            "lane": lane,
            "specificGoal": specific_goal,
            "expectedEvidence": expected_evidence,
            "nextAction": next_action,
            "supportPlan": support_plan,
            "safeSummary": safe_summary,
        }
        if not store.has_quota_for(workspace_id, quota_payload):
            return problem(start_response, "413 Payload Too Large", "Workspace quota exceeded", "The workspace does not have enough remaining storage for this routing decision.", "quota_exceeded")
        decision, message, source_room, destination_room = store.submit_routing_decision(
            workspace_id,
            source_room_id,
            coordinator_agent_id,
            routed_agent_id,
            lane,
            destination_room_id,
            specific_goal,
            expected_evidence,
            next_action,
            support_plan,
            safe_summary,
        )
        if not decision:
            return problem(start_response, "404 Not Found", "Routing room not found", "The routing decision could not be saved because the source or destination room was not found.", "routing_room_not_found")
        confirmation = _routing_decision_confirmation(store, workspace_id, decision, message, source_room)
        if not confirmation["persisted"]:
            return problem(start_response, "500 Internal Server Error", "Routing decision was not persisted", "The routing decision could not be confirmed in decision readback and room transcript after write.", "routing_decision_not_persisted")
        payload = {
            "ok": True,
            "routingDecision": decision,
            "message": message,
            "sourceRoom": source_room,
            "destinationRoom": destination_room,
            "persisted": confirmation["persisted"],
            "visibleToRoutedAgent": confirmation["visibleToRoutedAgent"],
            "canonicalRoutingDecisionId": confirmation["canonicalRoutingDecisionId"],
            "canonicalRoomId": confirmation["canonicalRoomId"],
            "destinationRoomId": confirmation["destinationRoomId"],
            "messageId": confirmation["messageId"],
            "routingDecisionQueryUrl": confirmation["routingDecisionQueryUrl"],
            "transcriptQueryUrl": confirmation["transcriptQueryUrl"],
            "destinationTranscriptQueryUrl": confirmation["destinationTranscriptQueryUrl"],
            "confirmation": confirmation,
            "operatorSummary": _routing_decision_operator_summary(decision, source_room, destination_room),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        store.record_idempotency(workspace_id, idem, "routing-decision-submit", body, payload, "201 Created")
        return json_response(start_response, payload, "201 Created")
    if path == "/api/matm/meeting-messages/promote" and method == "POST":
        replay = _idempotency_replay_or_conflict(store, start_response, workspace_id, idem, "meeting-message-promote", body)
        if replay:
            return replay
        meeting_message_id = body.get("meetingMessageId") or body.get("meeting_message_id")
        promoted_by_agent_id = body.get("promotedByAgentId") or body.get("promoted_by_agent_id") or body.get("actorAgentId") or body.get("actor_agent_id")
        if not meeting_message_id:
            return problem(start_response, "422 Unprocessable Entity", "Meeting message id required", "Meeting memory promotion requires meetingMessageId.", "meeting_message_id_required")
        if not promoted_by_agent_id:
            return problem(start_response, "422 Unprocessable Entity", "Promoting agent id required", "Meeting memory promotion requires promotedByAgentId or actorAgentId.", "promoted_by_agent_id_required")
        message, room = store.meeting_message(workspace_id, meeting_message_id)
        if not message:
            return problem(start_response, "404 Not Found", "Meeting message not found", "No matching meeting message exists for this workspace.", "meeting_message_not_found")
        summary = body.get("summary") or message.get("safeSummary") or ""
        if not summary.strip():
            return problem(start_response, "422 Unprocessable Entity", "Summary required", "Meeting memory promotion requires a public-safe summary.", "summary_required")
        if len(summary) > 4000:
            return problem(start_response, "422 Unprocessable Entity", "Summary too long", "Promoted meeting memory summaries must be at most 4000 characters.", "summary_too_long")
        tags = body.get("tags") or []
        if isinstance(tags, str):
            tags = [item.strip() for item in tags.split(",") if item.strip()]
        elif not isinstance(tags, list):
            tags = []
        source_sender = message.get("senderAgentId") or "unknown"
        promoted_tags = list(tags)
        for tag in (
            "meeting-message",
            "meeting-scope:%s" % (message.get("scope") or room.get("scope") or "workspace"),
            "meeting-sender:%s" % source_sender,
        ):
            if tag not in promoted_tags:
                promoted_tags.append(tag)
        source = body.get("source") or "memoryendpoints://matm/meeting-messages/%s" % meeting_message_id
        if not store.has_quota_for(workspace_id, {"meetingMessageId": meeting_message_id, "summary": summary, "tags": promoted_tags, "source": source}):
            return problem(start_response, "413 Payload Too Large", "Workspace quota exceeded", "The workspace does not have enough remaining storage for this promoted memory event.", "quota_exceeded")
        event = store.submit_memory(
            workspace_id,
            promoted_by_agent_id,
            body.get("scope") or message.get("scope") or room.get("scope"),
            body.get("title") or "Meeting memory: %s" % (room.get("name") or room.get("label") or message.get("roomId") or "room"),
            summary,
            promoted_tags,
            source,
            body.get("memoryType") or body.get("memory_type") or "evidence",
            body.get("subject") or "meeting-message:%s" % meeting_message_id,
            body.get("confidence") or 0.8,
            body.get("scopeId") or body.get("scope_id") or message.get("scopeId") or room.get("scopeId"),
        )
        submission = _memory_submission_metadata(event)
        confirmation = _memory_submission_confirmation(store, workspace_id, event)
        if not confirmation["persisted"]:
            return problem(start_response, "500 Internal Server Error", "Promoted memory was not persisted", "The promoted memory event could not be confirmed in search, the review queue, and audit log after write.", "promoted_memory_not_persisted")
        payload = {
            "ok": True,
            "sourceMeetingMessage": message,
            "room": room,
            "event": event,
            "submission": submission,
            "persisted": confirmation["persisted"],
            "visibleInSearch": confirmation["visibleInSearch"],
            "visibleInReviewQueue": confirmation["visibleInReviewQueue"],
            "visibleInAuditLog": confirmation["visibleInAuditLog"],
            "canonicalMemoryEventId": confirmation["canonicalMemoryEventId"],
            "reviewId": confirmation["reviewId"],
            "memoryQueryUrl": confirmation["memoryQueryUrl"],
            "reviewQueueUrl": confirmation["reviewQueueUrl"],
            "auditLogUrl": confirmation["auditLogUrl"],
            "confirmation": confirmation,
            "operatorSummary": _meeting_memory_promotion_operator_summary(message, room, event, promoted_by_agent_id),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        store.record_idempotency(workspace_id, idem, "meeting-message-promote", body, payload, "201 Created")
        return json_response(start_response, payload, "201 Created")
    if path == "/api/matm/meeting-rooms" and method == "POST":
        replay = _idempotency_replay_or_conflict(store, start_response, workspace_id, idem, "meeting-room-create", body)
        if replay:
            return replay
        scope = str(body.get("scope") or "").strip().lower()
        scope_id = str(body.get("scopeId") or body.get("scope_id") or "").strip()
        creator_agent_id = str(body.get("creatorAgentId") or body.get("creator_agent_id") or body.get("agentId") or body.get("agent_id") or "").strip()
        label = str(body.get("label") or "").strip()
        name = str(body.get("name") or "").strip()
        purpose = str(body.get("purpose") or "").strip()
        if scope not in ("goal", "task"):
            return problem(start_response, "422 Unprocessable Entity", "Unsupported meeting room scope", "Create custom meeting rooms only for goal or task scope; company, workspace, and project rooms are hierarchy-derived.", "unsupported_meeting_room_scope")
        if not scope_id:
            return problem(start_response, "422 Unprocessable Entity", "Scope id required", "Goal and task meeting rooms require scopeId.", "scope_id_required")
        if not creator_agent_id:
            return problem(start_response, "422 Unprocessable Entity", "Creator agent id required", "Meeting room creation requires creatorAgentId or agentId.", "creator_agent_id_required")
        if len(scope_id) > 160:
            return problem(start_response, "422 Unprocessable Entity", "Scope id too long", "Meeting room scopeId must be at most 160 characters.", "scope_id_too_long")
        if len(label) > 120 or len(name) > 160:
            return problem(start_response, "422 Unprocessable Entity", "Meeting room name too long", "Meeting room label must be at most 120 characters and name must be at most 160 characters.", "meeting_room_name_too_long")
        if len(purpose) > 1000:
            return problem(start_response, "422 Unprocessable Entity", "Meeting room purpose too long", "Meeting room purpose must be at most 1000 characters.", "meeting_room_purpose_too_long")
        if not store.has_quota_for(workspace_id, body):
            return problem(start_response, "413 Payload Too Large", "Workspace quota exceeded", "The workspace does not have enough remaining storage for this meeting room.", "quota_exceeded")
        room, created = store.create_meeting_room(
            workspace_id,
            scope,
            scope_id,
            label=label,
            name=name,
            purpose=purpose,
            creator_agent_id=creator_agent_id,
        )
        rooms = store.meeting_rooms(workspace_id, creator_agent_id)
        visible = any(item.get("roomId") == room.get("roomId") for item in rooms)
        if not visible:
            return problem(start_response, "500 Internal Server Error", "Meeting room was not persisted", "The meeting room could not be confirmed in the room list after write.", "meeting_room_not_persisted")
        confirmation = {
            "persisted": visible,
            "visibleToAgent": visible,
            "canonicalRoomId": room.get("roomId"),
            "roomQueryUrl": _protected_query_url(
                "/api/matm/meeting-rooms",
                {"agent_id": creator_agent_id},
            ),
            "transcriptQueryUrl": _protected_query_url(
                "/api/matm/meeting-messages",
                {"room_id": room.get("roomId"), "agent_id": creator_agent_id},
            ),
            "valuesRedacted": True,
        }
        payload = {
            "ok": True,
            "room": room,
            "created": bool(created),
            "persisted": confirmation["persisted"],
            "visibleToAgent": confirmation["visibleToAgent"],
            "canonicalRoomId": confirmation["canonicalRoomId"],
            "roomQueryUrl": confirmation["roomQueryUrl"],
            "transcriptQueryUrl": confirmation["transcriptQueryUrl"],
            "confirmation": confirmation,
            "operatorSummary": _meeting_room_create_operator_summary(room, created, creator_agent_id),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        store.record_idempotency(workspace_id, idem, "meeting-room-create", body, payload, "201 Created" if created else "200 OK")
        return json_response(start_response, payload, "201 Created" if created else "200 OK")
    if path == "/api/matm/meeting-rooms" and method == "GET":
        agent_filter = query.get("agent_id") or query.get("agentId") or ""
        scope_filter = (query.get("scope") or "").strip().lower()
        scope_id_filter = query.get("scope_id") or query.get("scopeId") or ""
        filters = {}
        if agent_filter:
            filters["agentId"] = agent_filter
        if scope_filter:
            filters["scope"] = scope_filter
        if scope_id_filter:
            filters["scopeId"] = scope_id_filter
        rooms = store.meeting_rooms(workspace_id, agent_filter)
        if scope_filter:
            rooms = [room for room in rooms if room.get("scope") == scope_filter]
        if scope_id_filter:
            rooms = [room for room in rooms if room.get("scopeId") == scope_id_filter]
        operator_summary = _meeting_rooms_operator_summary(rooms, filters)
        _audit_read(
            store,
            workspace_id,
            auth,
            "meeting_rooms.read",
            path,
            {
                "meetingRoomCount": len(rooms),
                "filters": filters,
                "scopeCounts": operator_summary["scopeCounts"],
                "unreadMeetingCount": operator_summary["unreadCount"],
            },
        )
        return json_response(
            start_response,
            {
                "ok": True,
                "schemaVersion": "memoryendpoints.meeting_rooms.v1",
                "items": rooms,
                "count": len(rooms),
                "filters": filters,
                "operatorSummary": operator_summary,
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )
    if path == "/api/matm/meeting-messages" and method == "GET":
        room_id = query.get("room_id") or query.get("roomId") or ""
        agent_filter = query.get("agent_id") or query.get("agentId") or ""
        if not room_id:
            return problem(start_response, "422 Unprocessable Entity", "Meeting room id required", "Meeting transcript reads require room_id.", "meeting_room_id_required")
        room, messages, read_state = store.meeting_messages(workspace_id, room_id, agent_filter, query.get("limit") or "50")
        if not room:
            return problem(start_response, "404 Not Found", "Meeting room not found", "No matching meeting room exists for this workspace.", "meeting_room_not_found")
        rooms = store.meeting_rooms(workspace_id, agent_filter)
        room_with_counts = next((item for item in rooms if item.get("roomId") == room_id), room)
        filters = {"roomId": room_id}
        if agent_filter:
            filters["agentId"] = agent_filter
        if query.get("limit"):
            filters["limit"] = query.get("limit")
        operator_summary = _meeting_messages_operator_summary(room_with_counts, messages, read_state, filters, room_with_counts.get("unreadCount") or 0)
        _audit_read(
            store,
            workspace_id,
            auth,
            "meeting_messages.read",
            path,
            {
                "roomScope": room.get("scope"),
                "meetingMessageCount": len(messages),
                "unreadMeetingCount": operator_summary["unreadCount"],
                "filters": filters,
            },
        )
        return json_response(
            start_response,
            {
                "ok": True,
                "schemaVersion": "memoryendpoints.meeting_messages.v1",
                "room": room_with_counts,
                "items": messages,
                "count": len(messages),
                "readState": read_state or {},
                "filters": filters,
                "operatorSummary": operator_summary,
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )
    if path == "/api/matm/meeting-messages" and method == "POST":
        replay = _idempotency_replay_or_conflict(store, start_response, workspace_id, idem, "meeting-message-submit", body)
        if replay:
            return replay
        room_id = body.get("roomId") or body.get("room_id")
        sender_agent_id = body.get("senderAgentId") or body.get("sender_agent_id")
        safe_summary = body.get("safeSummary") or body.get("safe_summary") or ""
        if not room_id:
            return problem(start_response, "422 Unprocessable Entity", "Meeting room id required", "Meeting posts require roomId.", "meeting_room_id_required")
        if not sender_agent_id:
            return problem(start_response, "422 Unprocessable Entity", "Sender agent id required", "Meeting posts require senderAgentId.", "sender_agent_id_required")
        if not safe_summary.strip():
            return problem(start_response, "422 Unprocessable Entity", "Safe summary required", "Meeting posts require a public-safe summary.", "safe_summary_required")
        if len(safe_summary) > 2000:
            return problem(start_response, "422 Unprocessable Entity", "Safe summary too long", "Meeting post safe summaries must be at most 2000 characters.", "safe_summary_too_long")
        if not store.has_quota_for(workspace_id, body):
            return problem(start_response, "413 Payload Too Large", "Workspace quota exceeded", "The workspace does not have enough remaining storage for this meeting message.", "quota_exceeded")
        message, room = store.submit_meeting_message(workspace_id, room_id, sender_agent_id, safe_summary)
        if not message:
            return problem(start_response, "404 Not Found", "Meeting room not found", "No matching meeting room exists for this workspace.", "meeting_room_not_found")
        confirmation = _meeting_post_confirmation(store, workspace_id, room, message)
        if not confirmation["persisted"]:
            return problem(start_response, "500 Internal Server Error", "Meeting message was not persisted", "The meeting message could not be confirmed in the room transcript after write.", "meeting_message_not_persisted")
        payload = {
            "ok": True,
            "room": room,
            "message": message,
            "persisted": confirmation["persisted"],
            "visibleToSender": confirmation["visibleToSender"],
            "canonicalRoomId": confirmation["canonicalRoomId"],
            "messageId": confirmation["messageId"],
            "transcriptQueryUrl": confirmation["transcriptQueryUrl"],
            "confirmation": confirmation,
            "operatorSummary": _meeting_post_operator_summary(room, message),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        store.record_idempotency(workspace_id, idem, "meeting-message-submit", body, payload, "201 Created")
        return json_response(start_response, payload, "201 Created")
    if path == "/api/matm/meeting-rooms/read" and method == "POST":
        replay = _idempotency_replay_or_conflict(store, start_response, workspace_id, idem, "meeting-room-read", body)
        if replay:
            return replay
        room_id = body.get("roomId") or body.get("room_id")
        agent_id = body.get("agentId") or body.get("agent_id")
        if not room_id:
            return problem(start_response, "422 Unprocessable Entity", "Meeting room id required", "Meeting read cursors require roomId.", "meeting_room_id_required")
        if not agent_id:
            return problem(start_response, "422 Unprocessable Entity", "Agent id required", "Meeting read cursors require agentId.", "agent_id_required")
        read_state, error = store.mark_meeting_room_read(workspace_id, room_id, agent_id, body.get("lastMeetingMessageId") or body.get("last_meeting_message_id"))
        if error == "message_not_found":
            return problem(start_response, "404 Not Found", "Meeting message not found", "No matching meeting message exists for this room.", "meeting_message_not_found")
        if not read_state:
            return problem(start_response, "404 Not Found", "Meeting room not found", "No matching meeting room exists for this workspace.", "meeting_room_not_found")
        rooms = store.meeting_rooms(workspace_id, agent_id)
        room = next((item for item in rooms if item.get("roomId") == room_id), {"roomId": room_id})
        payload = {
            "ok": True,
            "room": room,
            "readState": read_state,
            "operatorSummary": _meeting_read_operator_summary(read_state, room),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        store.record_idempotency(workspace_id, idem, "meeting-room-read", body, payload, "200 OK")
        return json_response(start_response, payload)
    if path == "/api/matm/agent-messages" and method == "POST":
        replay = _idempotency_replay_or_conflict(store, start_response, workspace_id, idem, "message-submit", body)
        if replay:
            return replay
        safe_summary = body.get("safeSummary") or body.get("safe_summary") or ""
        if not (body.get("senderAgentId") or body.get("sender_agent_id")):
            return problem(start_response, "422 Unprocessable Entity", "Sender agent id required", "Current messages require senderAgentId.", "sender_agent_id_required")
        if not safe_summary.strip():
            return problem(start_response, "422 Unprocessable Entity", "Safe summary required", "Current messages require a public-safe summary.", "safe_summary_required")
        if len(safe_summary) > 1000:
            return problem(start_response, "422 Unprocessable Entity", "Safe summary too long", "Current-message safe summaries must be at most 1000 characters.", "safe_summary_too_long")
        if not store.has_quota_for(workspace_id, body):
            return problem(start_response, "413 Payload Too Large", "Workspace quota exceeded", "The workspace does not have enough remaining storage for this current message.", "quota_exceeded")
        target_agent_id = body.get("targetAgentId") or body.get("target_agent_id")
        message, notifications = store.submit_message(
            workspace_id,
            body.get("senderAgentId") or body.get("sender_agent_id"),
            target_agent_id,
            safe_summary,
            body.get("responseRequired") or body.get("response_required"),
        )
        notifications = notifications if isinstance(notifications, list) else ([notifications] if notifications else [])
        primary_notification = notifications[0] if notifications else {}
        delivery = _delivery_metadata(message, primary_notification, (primary_notification or {}).get("targetAgentId") or "")
        delivery["recipientCount"] = len(notifications)
        delivery_counts = {
            "broadcast": 1 if delivery["messageType"] == "broadcast" else 0,
            "targeted": 1 if delivery["messageType"] == "targeted" else 0,
        }
        confirmation = _current_message_confirmation(store, workspace_id, message, notifications)
        if not confirmation["persisted"]:
            return problem(start_response, "500 Internal Server Error", "Current message was not persisted", "The current message could not be confirmed in the recipient inbox after write.", "current_message_not_persisted")
        operator_summary = _message_delivery_operator_summary(delivery, delivery_counts)
        payload = {
            "ok": True,
            "message": message,
            "notification": primary_notification,
            "notifications": notifications,
            "delivery": delivery,
            "deliveryCounts": delivery_counts,
            "persisted": confirmation["persisted"],
            "visibleToTarget": confirmation["visibleToTarget"],
            "visibleToAgents": confirmation["visibleToAgents"],
            "visibleRecipientCount": confirmation["visibleRecipientCount"],
            "expectedRecipientCount": confirmation["expectedRecipientCount"],
            "canonicalTargetAgentId": confirmation["canonicalTargetAgentId"],
            "messageId": confirmation["messageId"],
            "notificationId": confirmation["notificationId"],
            "notificationIds": confirmation["notificationIds"],
            "inboxQueryUrl": confirmation["inboxQueryUrl"],
            "confirmation": confirmation,
            "operatorSummary": operator_summary,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        store.record_idempotency(workspace_id, idem, "message-submit", body, payload, "202 Accepted")
        return json_response(start_response, payload, "202 Accepted")
    if path in ("/api/matm/agent-inbox", "/api/matm/current-message") and method == "GET":
        agent_filter = query.get("agent_id") or query.get("agentId") or ""
        message_filter = query.get("message_id") or query.get("messageId") or ""
        notification_filter = query.get("notification_id") or query.get("notificationId") or ""
        requested_limit = query.get("limit") or ""
        try:
            limit_value = max(1, min(int(requested_limit), 200)) if requested_limit else 0
        except (TypeError, ValueError):
            limit_value = 0
        raw_items = store.inbox(workspace_id, agent_filter, message_filter, notification_filter, limit_value)
        items = []
        delivery_counts = {"broadcast": 0, "targeted": 0}
        for item in raw_items:
            message = item.get("message") or {}
            notification = item.get("notification") or {}
            delivery = _delivery_metadata(message, notification, agent_filter)
            delivery_counts[delivery["messageType"]] += 1
            enriched = dict(item)
            enriched["delivery"] = delivery
            items.append(enriched)
        filters = {"agentId": agent_filter} if agent_filter else {}
        if message_filter:
            filters["messageId"] = message_filter
        if notification_filter:
            filters["notificationId"] = notification_filter
        if limit_value:
            filters["limit"] = str(limit_value)
        operator_summary = _inbox_operator_summary(items, filters, delivery_counts, path == "/api/matm/current-message")
        _audit_read(
            store,
            workspace_id,
            auth,
            "current_message.read" if path == "/api/matm/current-message" else "agent_inbox.read",
            path,
            {
                "unreadCount": len(items),
                "filters": filters,
                "deliveryCounts": delivery_counts,
                "responseDispositionCounts": operator_summary["responseDispositionCounts"],
            },
        )
        return json_response(
            start_response,
            {
                "ok": True,
                "currentMessageLane": path == "/api/matm/current-message",
                "items": items,
                "unreadCount": len(items),
                "responseStates": ["required_response", "viewed_acknowledgement"],
                "filters": filters,
                "deliveryCounts": delivery_counts,
                "operatorSummary": operator_summary,
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )
    if path == "/api/matm/notifications/ack" and method == "POST":
        replay = _idempotency_replay_or_conflict(store, start_response, workspace_id, idem, "notification-ack", body)
        if replay:
            return replay
        receipt = store.ack(workspace_id, body.get("notificationId") or body.get("notification_id"), body.get("consumerAgentId") or body.get("consumer_agent_id"), body.get("status") or "read")
        if not receipt:
            return problem(start_response, "404 Not Found", "Notification not found", "No matching notification exists for this workspace.", "notification_not_found")
        payload = {
            "ok": True,
            "receipt": receipt,
            "operatorSummary": _acknowledgement_operator_summary(receipt),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        store.record_idempotency(workspace_id, idem, "notification-ack", body, payload, "200 OK")
        return json_response(start_response, payload)
    if path == "/api/matm/receipts" and method == "GET":
        consumer_filter = query.get("consumer_agent_id") or query.get("consumerAgentId") or ""
        items = store.receipts(workspace_id, consumer_filter)
        filters = {"consumerAgentId": consumer_filter} if consumer_filter else {}
        operator_summary = _receipts_operator_summary(items, filters)
        _audit_read(
            store,
            workspace_id,
            auth,
            "receipts.read",
            path,
            {
                "count": len(items),
                "filters": filters,
                "receiptStatusCounts": operator_summary["statusCounts"],
                "rawPayloadExposedCount": operator_summary["rawPayloadExposedCount"],
            },
        )
        return json_response(
            start_response,
            {
                "ok": True,
                "items": items,
                "count": len(items),
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
                "filters": filters,
                "operatorSummary": operator_summary,
            },
        )
    return problem(start_response, "404 Not Found", "Route not found", "No protected route matched this request.", "not_found")


def application(environ, start_response):
    path = environ.get("PATH_INFO", "/") or "/"
    method = environ.get("REQUEST_METHOD", "GET")
    cors_api_route = path.startswith("/api/")
    if cors_api_route:
        start_response = _cors_start_response(environ, start_response)
        if method == "OPTIONS":
            return _route_cors_preflight(environ, start_response)
    if path == "/" and method == "GET":
        return route_home(start_response)
    if path in ("/docs", "/docs/") and method == "GET":
        return route_docs(start_response)
    if path == "/agent-setup" and method == "GET":
        return route_agent_setup(start_response)
    if path == "/agent-coordination" and method == "GET":
        return route_agent_coordination(start_response)
    if path == "/console" and method == "GET":
        return route_console(start_response)
    if path == "/memory-lifecycle" and method == "GET":
        return route_memory_lifecycle(start_response)
    if path == "/transparency" and method == "GET":
        return route_transparency(start_response)
    if path.startswith("/static/") and method == "GET":
        return route_static(path, start_response)
    if path in ("/robots.txt", "/llms.txt", "/llms-full.txt", "/ai.txt") and method == "GET":
        content_type = "text/plain; charset=utf-8"
        return response(start_response, "200 OK", text_discovery(path.rsplit("/", 1)[-1]), content_type)
    if path == "/sitemap.xml" and method == "GET":
        urls = "\n".join(["<url><loc>%s%s</loc></url>" % (SITE_URL, route) for route in PUBLIC_ROUTES if not route.startswith("/api")])
        return response(start_response, "200 OK", "<?xml version=\"1.0\"?><!-- MemoryEndpoints.com sitemap --><urlset>%s</urlset>" % urls, "application/xml; charset=utf-8")
    public = route_public_json(path, start_response) if method == "GET" else None
    if public:
        return public
    if path == "/api/admin/mysql-diagnostics":
        return route_admin_mysql_diagnostics(environ, start_response)
    if path == "/api/matm/agent-setup/free-account":
        return route_setup(environ, start_response)
    if path.startswith("/api/matm/"):
        return route_protected(environ, start_response, path)
    return problem(start_response, "404 Not Found", "Not found", "The requested route does not exist.", "not_found")
