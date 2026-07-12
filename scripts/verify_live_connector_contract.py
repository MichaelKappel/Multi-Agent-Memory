import argparse
import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SECRET = ROOT / ".local-secrets" / "human-verifier-account.json"
DEFAULT_REPORT = ROOT / "docs" / "reports" / "live-connector-contract-verification.json"
REVIEW_QUEUE_FILTERS = ["status", "source_prefix", "tag", "memory_type", "actor_agent_id"]
MEMORY_SEARCH_FILTERS = [
    "q",
    "scope",
    "scope_id",
    "source_prefix",
    "tag",
    "actor_agent_id",
    "memory_type",
    "review_status",
    "promotion_state",
    "event_id",
]
CORS_HEADERS = ["Authorization", "Content-Type", "Idempotency-Key", "X-MemoryEndpoints-Key"]
DISCONNECTED_POLL_FIELDS = ["workspace_id", "agent_id", "message_id", "notification_id", "limit", "cursor", "after_notification_id"]
DISCONNECTED_PAGINATION_FIELDS = ["visibleUnreadCount", "totalUnreadCount", "hasMore", "nextCursor", "cursor", "cursorAccepted"]
SOURCE_PREFIX = "docs/long-term-memory/"
MIGRATION_TAG = "long-term-memory-migration"


def sha256_text(value):
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def request_json(base_url, path, method="GET", token=None, query=None, headers=None):
    url = base_url.rstrip("/") + path
    if query:
        url += "?" + query
    request_headers = {"Accept": "application/json"}
    request_headers.update(headers or {})
    if token:
        request_headers["Authorization"] = "Bearer " + token
    request = Request(url, headers=request_headers, method=method)
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
            payload = {"ok": False, "error": {"code": "non_json_http_error", "status": exc.code}, "valuesRedacted": True}
        return exc.code, payload, dict(exc.headers)


def request_preflight(base_url, path):
    request = Request(
        base_url.rstrip("/") + path,
        headers={
            "Origin": "https://connector.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": ", ".join(CORS_HEADERS),
        },
        method="OPTIONS",
    )
    try:
        with urlopen(request, timeout=30) as response:
            response.read()
            return response.status, dict(response.headers)
    except HTTPError as exc:
        exc.read()
        return exc.code, dict(exc.headers)


def missing_values(actual, required):
    actual_set = {str(item).lower() for item in (actual or [])}
    return [item for item in required if item.lower() not in actual_set]


def disconnected_delivery_check(contract):
    contract = contract or {}
    routes = contract.get("routes") or {}
    polling = contract.get("polling") or {}
    attention = contract.get("attentionOrdering") or {}
    acknowledgement = contract.get("acknowledgement") or {}
    transports = contract.get("transports") or {}
    semantics = contract.get("deliverySemantics") or {}
    required_and_optional = list(polling.get("requiredQueryFields") or []) + list(polling.get("optionalQueryFields") or [])
    missing_poll_fields = missing_values(required_and_optional, DISCONNECTED_POLL_FIELDS)
    missing_pagination_fields = missing_values(polling.get("paginationResponseFields"), DISCONNECTED_PAGINATION_FIELDS)
    client_loop = " ".join(str(item) for item in (contract.get("recommendedClientLoop") or [])).lower()
    multi_device_rule = str(contract.get("multiDeviceRule") or "").lower()
    return {
        "disconnectedPollingBaselineAdvertised": contract.get("status") == "live_polling_baseline" and polling.get("status") == "live",
        "disconnectedDatabaseTruthVerified": contract.get("deliverySourceOfTruth") == "durable_recipient_notification_in_server_database",
        "disconnectedRoutesVerified": routes == {
            "send": "/api/matm/agent-messages",
            "read": "/api/matm/current-message",
            "acknowledge": "/api/matm/notifications/ack",
        },
        "disconnectedPollFieldsVerified": not missing_poll_fields,
        "missingDisconnectedPollFields": missing_poll_fields,
        "disconnectedPaginationVerified": not missing_pagination_fields and (polling.get("limitRange") or {}).get("maximum") == 200,
        "missingDisconnectedPaginationFields": missing_pagination_fields,
        "disconnectedAttentionOrderingVerified": attention.get("priority") == ["required_response", "viewed_acknowledgement"] and attention.get("causalOrderingClaimed") is False,
        "disconnectedAcknowledgementVerified": acknowledgement.get("scope") == "recipient_notification" and acknowledgement.get("requiredResponseCompletionIsSeparate") is True,
        "disconnectedClientLoopVerified": all(term in client_loop for term in ("startup", "reconnect", "bounded backoff", "hasmore", "nextcursor")),
        "disconnectedUnavailableTransportsExplicit": str(transports.get("serverSentEvents") or "").startswith("not_implemented") and transports.get("inboundCallbacks") == "not_implemented",
        "disconnectedDeliveryClaimsSafe": semantics.get("unreadUntilRecipientAcknowledgement") is True and semantics.get("exactlyOnceClaimed") is False and semantics.get("liveHintIsDeliveryProof") is False,
        "disconnectedMultiDeviceRuleVerified": "share notification state" in multi_device_rule and "no device lease" in multi_device_rule,
    }


def connector_contract_check(payload):
    data = (payload or {}).get("data") or {}
    memory_flow = data.get("memoryFlow") or {}
    coordination_flow = data.get("coordinationFlow") or {}
    response_contract = data.get("responseContract") or {}
    browser_cors = data.get("browserCors") or {}
    missing_filters = missing_values(memory_flow.get("reviewQueueFilters"), REVIEW_QUEUE_FILTERS)
    missing_search_filters = missing_values(memory_flow.get("searchQueryFilters"), MEMORY_SEARCH_FILTERS)
    missing_headers = missing_values(browser_cors.get("allowedHeaders"), CORS_HEADERS)
    post_confirmation_fields = response_contract.get("postConfirmationFields") or []
    result = {
        "schemaVersion": data.get("schemaVersion"),
        "reviewQueueFiltersVerified": not missing_filters,
        "missingReviewQueueFilters": missing_filters,
        "searchQueryFiltersVerified": not missing_search_filters,
        "missingSearchQueryFilters": missing_search_filters,
        "reviewQueueOperatorSummaryVerified": "longTermMemoryReviews" in (memory_flow.get("reviewQueueOperatorSummary") or ""),
        "broadcastFanoutAdvertised": coordination_flow.get("broadcastFanout") == "per_active_agent_notification",
        "ackIsolationAdvertised": coordination_flow.get("ackIsolation") == "per_recipient_notification",
        "visibleAgentsConfirmationAdvertised": "visibleToAgents" in post_confirmation_fields,
        "recipientCountConfirmationAdvertised": "expectedRecipientCount" in post_confirmation_fields and "visibleRecipientCount" in post_confirmation_fields,
        "browserCorsStatus": browser_cors.get("status"),
        "browserCorsPreflightWithoutWorkspaceKey": browser_cors.get("preflightRequiresWorkspaceKey") is False,
        "missingBrowserCorsHeaders": missing_headers,
        "browserCorsHeadersVerified": not missing_headers,
        "valuesRedacted": True,
    }
    result.update(disconnected_delivery_check(data.get("disconnectedDelivery")))
    return result


def capability_matrix_check(payload):
    data = (payload or {}).get("data") or {}
    review_queue = data.get("reviewPromotionQueue") or {}
    current_message = data.get("currentMessageLane") or {}
    browser_cors = ((data.get("connectorContract") or {}).get("browserCors") or {})
    missing_filters = missing_values(review_queue.get("queryFilters"), REVIEW_QUEUE_FILTERS)
    result = {
        "reviewQueueFiltersVerified": not missing_filters,
        "missingReviewQueueFilters": missing_filters,
        "longTermReviewHealthAdvertised": "docs/long-term-memory" in (review_queue.get("longTermMemoryReviewHealth") or ""),
        "operatorSummaryFieldsIncludeLongTerm": "longTermMemoryReviews" in (review_queue.get("operatorSummaryFields") or []),
        "broadcastFanoutAdvertised": current_message.get("broadcastFanout") == "per_active_agent_notification",
        "ackIsolationAdvertised": current_message.get("ackIsolation") == "per_recipient_notification",
        "visibleAgentsConfirmationAdvertised": "visibleToAgents" in (current_message.get("postConfirmationFields") or []),
        "browserCorsAdvertised": browser_cors.get("status") == "live" and browser_cors.get("preflightWithoutWorkspaceKey") is True,
        "valuesRedacted": True,
    }
    result.update(disconnected_delivery_check(data.get("disconnectedDelivery")))
    return result


def cors_preflight_check(status, headers):
    allow_methods = headers.get("Access-Control-Allow-Methods") or headers.get("access-control-allow-methods") or ""
    allow_headers = headers.get("Access-Control-Allow-Headers") or headers.get("access-control-allow-headers") or ""
    allow_origin = headers.get("Access-Control-Allow-Origin") or headers.get("access-control-allow-origin") or ""
    missing_methods = missing_values([item.strip() for item in allow_methods.split(",")], ["GET", "POST", "OPTIONS"])
    missing_headers = missing_values([item.strip() for item in allow_headers.split(",")], CORS_HEADERS)
    return {
        "status": status,
        "ok": status == 204,
        "allowOriginPresent": bool(allow_origin),
        "missingMethods": missing_methods,
        "missingHeaders": missing_headers,
        "verified": status == 204 and bool(allow_origin) and not missing_methods and not missing_headers,
        "valuesRedacted": True,
    }


def protected_review_filter_check(payload):
    payload = payload or {}
    summary = ((payload.get("operatorSummary") or {}).get("longTermMemoryReviews") or {})
    filters = payload.get("filters") or {}
    return {
        "ok": bool(payload.get("ok")),
        "count": payload.get("count"),
        "filters": {key: filters.get(key) for key in ("status", "sourcePrefix", "tag") if filters.get(key)},
        "longTermReviewSummaryPresent": bool(summary),
        "sourcePathCount": summary.get("sourcePathCount"),
        "visibleRecordCount": summary.get("visibleRecordCount"),
        "actionableCount": summary.get("actionableCount"),
        "allPromoted": summary.get("allPromoted"),
        "valuesRedacted": bool(payload.get("valuesRedacted")),
        "rawCredentialExposed": bool(payload.get("rawCredentialExposed")),
        "rawPayloadExposed": bool(payload.get("rawPayloadExposed")),
        "verified": bool(
            payload.get("ok")
            and summary
            and summary.get("sourcePathCount")
            and summary.get("visibleRecordCount")
            and payload.get("valuesRedacted")
            and not payload.get("rawCredentialExposed")
            and not payload.get("rawPayloadExposed")
        ),
    }


def protected_exact_memory_readback_check(seed_payload, exact_payload, event_id):
    seed_items = (seed_payload or {}).get("items") or []
    exact_items = (exact_payload or {}).get("items") or []
    exact_filters = (exact_payload or {}).get("filters") or {}
    return {
        "seedCount": len(seed_items),
        "eventIdHash": "sha256:" + sha256_text(event_id) if event_id else None,
        "exactCount": len(exact_items),
        "exactContainsEvent": bool(event_id and any(item.get("eventId") == event_id for item in exact_items)),
        "eventIdFilterEchoed": exact_filters.get("eventId") == event_id,
        "valuesRedacted": bool((seed_payload or {}).get("valuesRedacted") and (exact_payload or {}).get("valuesRedacted")),
        "rawCredentialExposed": bool((seed_payload or {}).get("rawCredentialExposed") or (exact_payload or {}).get("rawCredentialExposed")),
        "rawPayloadExposed": bool((seed_payload or {}).get("rawPayloadExposed") or (exact_payload or {}).get("rawPayloadExposed")),
        "verified": bool(
            event_id
            and seed_items
            and len(exact_items) == 1
            and any(item.get("eventId") == event_id for item in exact_items)
            and exact_filters.get("eventId") == event_id
            and (seed_payload or {}).get("valuesRedacted")
            and (exact_payload or {}).get("valuesRedacted")
            and not (seed_payload or {}).get("rawCredentialExposed")
            and not (seed_payload or {}).get("rawPayloadExposed")
            and not (exact_payload or {}).get("rawCredentialExposed")
            and not (exact_payload or {}).get("rawPayloadExposed")
        ),
    }


def build_report(base_url, source_sha, contract_check, capability_check, preflight_check, protected_check, exact_memory_check=None, workspace_id="", token=""):
    exact_memory_check = exact_memory_check or {}
    report = {
        "schemaVersion": "memoryendpoints.live_connector_contract_verification.v3",
        "baseUrl": base_url.rstrip("/"),
        "sourceSha": source_sha,
        "connectorContract": contract_check,
        "capabilityMatrix": capability_check,
        "browserCorsPreflight": preflight_check,
        "protectedReviewQueueFilter": protected_check,
        "protectedExactMemoryReadback": exact_memory_check,
        "workspaceIdHash": "sha256:" + sha256_text(workspace_id) if workspace_id else None,
        "valuesRedacted": True,
        "rawCredentialValuesStored": False,
        "rawWorkspaceIdStored": False,
    }
    report_text = json.dumps(report, sort_keys=True)
    report["rawCredentialValuesStored"] = bool(token and token in report_text)
    report["rawWorkspaceIdStored"] = bool(workspace_id and workspace_id in report_text)
    report["ok"] = bool(
        contract_check.get("reviewQueueFiltersVerified")
        and contract_check.get("searchQueryFiltersVerified")
        and contract_check.get("reviewQueueOperatorSummaryVerified")
        and contract_check.get("broadcastFanoutAdvertised")
        and contract_check.get("ackIsolationAdvertised")
        and contract_check.get("visibleAgentsConfirmationAdvertised")
        and contract_check.get("recipientCountConfirmationAdvertised")
        and contract_check.get("browserCorsHeadersVerified")
        and contract_check.get("disconnectedPollingBaselineAdvertised")
        and contract_check.get("disconnectedDatabaseTruthVerified")
        and contract_check.get("disconnectedRoutesVerified")
        and contract_check.get("disconnectedPollFieldsVerified")
        and contract_check.get("disconnectedPaginationVerified")
        and contract_check.get("disconnectedAttentionOrderingVerified")
        and contract_check.get("disconnectedAcknowledgementVerified")
        and contract_check.get("disconnectedClientLoopVerified")
        and contract_check.get("disconnectedUnavailableTransportsExplicit")
        and contract_check.get("disconnectedDeliveryClaimsSafe")
        and contract_check.get("disconnectedMultiDeviceRuleVerified")
        and capability_check.get("reviewQueueFiltersVerified")
        and capability_check.get("longTermReviewHealthAdvertised")
        and capability_check.get("operatorSummaryFieldsIncludeLongTerm")
        and capability_check.get("broadcastFanoutAdvertised")
        and capability_check.get("ackIsolationAdvertised")
        and capability_check.get("visibleAgentsConfirmationAdvertised")
        and capability_check.get("disconnectedPollingBaselineAdvertised")
        and capability_check.get("disconnectedDatabaseTruthVerified")
        and capability_check.get("disconnectedRoutesVerified")
        and capability_check.get("disconnectedPollFieldsVerified")
        and capability_check.get("disconnectedPaginationVerified")
        and capability_check.get("disconnectedAttentionOrderingVerified")
        and capability_check.get("disconnectedAcknowledgementVerified")
        and capability_check.get("disconnectedClientLoopVerified")
        and capability_check.get("disconnectedUnavailableTransportsExplicit")
        and capability_check.get("disconnectedDeliveryClaimsSafe")
        and capability_check.get("disconnectedMultiDeviceRuleVerified")
        and preflight_check.get("verified")
        and (protected_check.get("verified") if protected_check else True)
        and (exact_memory_check.get("verified") if exact_memory_check else True)
        and not report["rawCredentialValuesStored"]
        and not report["rawWorkspaceIdStored"]
    )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://memoryendpoints.com")
    parser.add_argument("--secret", default=str(DEFAULT_SECRET))
    parser.add_argument("--json-out", default=str(DEFAULT_REPORT))
    parser.add_argument("--skip-protected", action="store_true")
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    status, version, _headers = request_json(base_url, "/api/version")
    source_sha = ((version.get("build") or {}).get("sourceSha") if status == 200 else None)
    status, contract, _headers = request_json(base_url, "/api/matm/connector-contract")
    if status != 200 or not contract.get("ok"):
        raise RuntimeError("connector contract fetch failed")
    status, capability, _headers = request_json(base_url, "/api/matm/live-capability-matrix")
    if status != 200 or not capability.get("ok"):
        raise RuntimeError("capability matrix fetch failed")
    preflight_status, preflight_headers = request_preflight(base_url, "/api/matm/review-queue")

    protected_check = {}
    exact_memory_check = {}
    workspace_id = ""
    token = ""
    if not args.skip_protected:
        secret = read_json(args.secret)
        workspace_id = secret.get("workspaceId") or ""
        token = secret.get("apiKeySecret") or ""
        if not workspace_id or not token:
            raise RuntimeError("protected verification requires workspaceId and apiKeySecret")
        status, protected_payload, _headers = request_json(
            base_url,
            "/api/matm/review-queue",
            token=token,
            query=urlencode(
                {
                    "workspace_id": workspace_id,
                    "status": "promoted",
                    "source_prefix": SOURCE_PREFIX,
                    "tag": MIGRATION_TAG,
                }
            ),
        )
        if status != 200:
            raise RuntimeError("protected review queue fetch failed")
        protected_check = protected_review_filter_check(protected_payload)
        status, seed_payload, _headers = request_json(
            base_url,
            "/api/matm/search",
            token=token,
            query=urlencode(
                {
                    "workspace_id": workspace_id,
                    "q": MIGRATION_TAG,
                    "tag": MIGRATION_TAG,
                }
            ),
        )
        if status != 200:
            raise RuntimeError("protected memory search seed fetch failed")
        seed_items = seed_payload.get("items") or []
        event_id = (seed_items[0] or {}).get("eventId") if seed_items else ""
        status, exact_payload, _headers = request_json(
            base_url,
            "/api/matm/search",
            token=token,
            query=urlencode(
                {
                    "workspace_id": workspace_id,
                    "q": "",
                    "event_id": event_id,
                }
            ),
        )
        if status != 200:
            raise RuntimeError("protected exact memory readback fetch failed")
        exact_memory_check = protected_exact_memory_readback_check(seed_payload, exact_payload, event_id)

    report = build_report(
        base_url,
        source_sha,
        connector_contract_check(contract),
        capability_matrix_check(capability),
        cors_preflight_check(preflight_status, preflight_headers),
        protected_check,
        exact_memory_check,
        workspace_id=workspace_id,
        token=token,
    )
    write_json(args.json_out, report)
    print(json.dumps({"ok": report["ok"], "sourceSha": source_sha, "report": str(Path(args.json_out)), "valuesRedacted": True}, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
