import argparse
import datetime
import hashlib
import json
import secrets
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SECRET = ROOT / ".local-secrets" / "human-verifier-account.json"
DEFAULT_REPORT = ROOT / "docs" / "reports" / "live-memory-submit-consistency.json"
REQUEST_TIMEOUT_SECONDS = 12
READBACK_ATTEMPTS = 10


def configure_request_timeout(seconds):
    global REQUEST_TIMEOUT_SECONDS

    REQUEST_TIMEOUT_SECONDS = max(1, int(seconds))
    return REQUEST_TIMEOUT_SECONDS


def sha256_text(value):
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def request_json(base_url, path, method="GET", token=None, query=None, headers=None, body=None):
    url = base_url.rstrip("/") + path
    if query:
        url += "?" + query
    request_headers = {"Accept": "application/json"}
    request_headers.update(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    if token:
        request_headers["Authorization"] = "Bearer " + token
    request = Request(url, headers=request_headers, method=method, data=data)
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(raw) if raw else {}, dict(response.headers)
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {
                "ok": False,
                "error": {"code": "non_json_http_error", "status": exc.code},
                "valuesRedacted": True,
            }
        return exc.code, payload, dict(exc.headers)
    except (TimeoutError, URLError, OSError) as exc:
        return 0, {
            "ok": False,
            "error": {
                "code": "request_failed",
                "type": exc.__class__.__name__,
                "safeNoOp": True,
            },
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }, {}


def event_id_from_submit(payload):
    payload = payload or {}
    event = payload.get("event") or {}
    return payload.get("canonicalMemoryEventId") or event.get("eventId") or ""


def review_id_from_submit(payload):
    payload = payload or {}
    event = payload.get("event") or {}
    return payload.get("reviewId") or event.get("reviewId") or ""


def items(payload):
    value = (payload or {}).get("items")
    return value if isinstance(value, list) else []


def raw_exposure(*payloads):
    return {
        "rawCredentialExposed": any(bool((payload or {}).get("rawCredentialExposed")) for payload in payloads),
        "rawPayloadExposed": any(bool((payload or {}).get("rawPayloadExposed")) for payload in payloads),
        "valuesRedacted": all(bool((payload or {}).get("valuesRedacted", True)) for payload in payloads),
    }


def evaluate_probe(submit_status, submit_payload, search_payload, review_payload, audit_payload):
    event_id = event_id_from_submit(submit_payload)
    review_id = review_id_from_submit(submit_payload)
    search_items = items(search_payload)
    review_items = items(review_payload)
    audit_items = items(audit_payload)
    exact_search_matches = [item for item in search_items if item.get("eventId") == event_id]
    review_matches = [item for item in review_items if item.get("memoryEventId") == event_id]
    audit_matches = [item for item in audit_items if item.get("target") == event_id]
    exposure = raw_exposure(submit_payload, search_payload, review_payload, audit_payload)
    response_claims = {
        "persisted": bool((submit_payload or {}).get("persisted")),
        "visibleInSearch": bool((submit_payload or {}).get("visibleInSearch")),
        "visibleInReviewQueue": bool((submit_payload or {}).get("visibleInReviewQueue")),
        "visibleInAuditLog": bool((submit_payload or {}).get("visibleInAuditLog")),
    }
    durable = {
        "exactSearchCount": len(exact_search_matches),
        "reviewQueueMatchCount": len(review_matches),
        "auditMatchCount": len(audit_matches),
    }
    mismatches = []
    if response_claims["visibleInSearch"] and durable["exactSearchCount"] != 1:
        mismatches.append("response_visible_search_without_exact_readback")
    if response_claims["visibleInReviewQueue"] and durable["reviewQueueMatchCount"] < 1:
        mismatches.append("response_visible_review_without_review_readback")
    if response_claims["visibleInAuditLog"] and durable["auditMatchCount"] < 1:
        mismatches.append("response_visible_audit_without_audit_readback")
    if submit_status not in (200, 201):
        mismatches.append("submit_http_status_not_created")
    if not event_id:
        mismatches.append("missing_event_id")
    if exposure["rawCredentialExposed"] or exposure["rawPayloadExposed"]:
        mismatches.append("raw_value_exposure")
    ok = bool(
        submit_status in (200, 201)
        and event_id
        and response_claims["persisted"]
        and durable["exactSearchCount"] == 1
        and durable["reviewQueueMatchCount"] >= 1
        and durable["auditMatchCount"] >= 1
        and not mismatches
    )
    return {
        "ok": ok,
        "eventId": event_id,
        "reviewId": review_id,
        "submitStatus": submit_status,
        "responseClaims": response_claims,
        "durableReadback": durable,
        "mismatches": mismatches,
        "searchFilters": (search_payload or {}).get("filters") or {},
        "reviewStatusCounts": (review_payload or {}).get("statusCounts") or {},
        "valuesRedacted": exposure["valuesRedacted"],
        "rawCredentialExposed": exposure["rawCredentialExposed"],
        "rawPayloadExposed": exposure["rawPayloadExposed"],
    }


def protected_get(base_url, token, workspace_id, path, params):
    params = dict(params or {})
    params["workspace_id"] = workspace_id
    return request_json(base_url, path, token=token, query=urlencode(params))


def run_probe(
    base_url,
    token,
    workspace_id,
    actor_agent_id,
    scope_id,
    run_tag,
    probe_index,
    delay_seconds,
    readback_attempts,
):
    tag = "submit-consistency-" + run_tag
    body = {
        "workspaceId": workspace_id,
        "actorAgentId": actor_agent_id,
        "scope": "project" if scope_id else "workspace",
        "scopeId": scope_id or workspace_id,
        "memoryType": "evidence",
        "title": "Memory submit consistency probe %s.%s" % (run_tag, probe_index),
        "summary": "Public-safe diagnostic memory: submit response must match search, review queue, and audit readback.",
        "tags": ["dogfood-diagnostic", "submit-consistency", tag],
        "source": "memoryendpoints://diagnostic/memory-submit-consistency/%s/%s" % (run_tag, probe_index),
    }
    submit_status, submit_payload, _headers = request_json(
        base_url,
        "/api/matm/memory-events/submit",
        method="POST",
        token=token,
        headers={"Idempotency-Key": "memory-submit-consistency-%s-%s" % (run_tag, probe_index)},
        body=body,
    )
    event_id = event_id_from_submit(submit_payload)
    attempts = max(1, int(readback_attempts))
    search_status = review_status = audit_status = 0
    search_payload = review_payload = audit_payload = {}
    check = {}
    for attempt in range(attempts):
        time.sleep(max(0.0, delay_seconds))
        search_status, search_payload, _search_headers = protected_get(
            base_url,
            token,
            workspace_id,
            "/api/matm/search",
            {"q": "", "event_id": event_id},
        )
        review_status, review_payload, _review_headers = protected_get(
            base_url,
            token,
            workspace_id,
            "/api/matm/review-queue",
            {"status": "", "tag": tag},
        )
        audit_status, audit_payload, _audit_headers = protected_get(
            base_url,
            token,
            workspace_id,
            "/api/matm/audit-log",
            {"action": "memory.submit", "limit": "200"},
        )
        check = evaluate_probe(submit_status, submit_payload, search_payload, review_payload, audit_payload)
        check["readbackAttemptsUsed"] = attempt + 1
        if check["ok"]:
            break
    check["probeIndex"] = probe_index
    check["readbackAttemptCount"] = attempts
    check["readStatuses"] = {
        "search": search_status,
        "reviewQueue": review_status,
        "auditLog": audit_status,
    }
    check["runTag"] = run_tag
    return check


def build_report(base_url, source_sha, workspace_id, token, probes):
    report = {
        "schemaVersion": "memoryendpoints.live_memory_submit_consistency.v1",
        "baseUrl": base_url.rstrip("/"),
        "sourceSha": source_sha,
        "workspaceIdHash": "sha256:" + sha256_text(workspace_id) if workspace_id else None,
        "probeCount": len(probes),
        "passedCount": sum(1 for probe in probes if probe.get("ok")),
        "failedCount": sum(1 for probe in probes if not probe.get("ok")),
        "probes": probes,
        "valuesRedacted": True,
    }
    report["rawCredentialExposed"] = any(probe.get("rawCredentialExposed") for probe in probes)
    report["rawPayloadExposed"] = any(probe.get("rawPayloadExposed") for probe in probes)
    text = json.dumps(report, sort_keys=True)
    report["rawCredentialValuesStored"] = bool(token and token in text)
    report["rawWorkspaceIdStored"] = bool(workspace_id and workspace_id in text)
    report["ok"] = bool(
        probes
        and report["failedCount"] == 0
        and not report["rawCredentialExposed"]
        and not report["rawPayloadExposed"]
        and not report["rawCredentialValuesStored"]
        and not report["rawWorkspaceIdStored"]
    )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verify live memory submit response/readback consistency.")
    parser.add_argument("--base-url", default="https://memoryendpoints.com")
    parser.add_argument("--secret", default=str(DEFAULT_SECRET))
    parser.add_argument("--json-out", default=str(DEFAULT_REPORT))
    parser.add_argument("--probes", type=int, default=1)
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--readback-attempts", type=int, default=READBACK_ATTEMPTS)
    parser.add_argument("--request-timeout", type=int, default=REQUEST_TIMEOUT_SECONDS)
    parser.add_argument("--agent-id", default="")
    args = parser.parse_args(argv)
    configure_request_timeout(args.request_timeout)

    secret = read_json(args.secret)
    token = secret.get("apiKeySecret") or ""
    workspace_id = secret.get("workspaceId") or ""
    if not token or not workspace_id:
        raise RuntimeError("secret must contain workspaceId and apiKeySecret")
    actor_agent_id = args.agent_id or secret.get("backendAgentId") or "MemoryEndpoints-Backend-Agent"
    scope_id = secret.get("projectId") or ""
    base_url = args.base_url.rstrip("/")
    version_status, version_payload, _version_headers = request_json(base_url, "/api/version")
    source_sha = ""
    if version_status == 200:
        source_sha = (version_payload.get("build") or {}).get("sourceSha") or ""
    run_tag = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(4)
    probes = [
        run_probe(
            base_url,
            token,
            workspace_id,
            actor_agent_id,
            scope_id,
            run_tag,
            index + 1,
            args.delay,
            args.readback_attempts,
        )
        for index in range(max(1, args.probes))
    ]
    report = build_report(base_url, source_sha, workspace_id, token, probes)
    write_json(args.json_out, report)
    print(json.dumps({
        "ok": report["ok"],
        "probeCount": report["probeCount"],
        "passedCount": report["passedCount"],
        "failedCount": report["failedCount"],
        "report": str(Path(args.json_out)),
        "valuesRedacted": True,
    }, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
