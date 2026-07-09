import argparse
import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = ROOT / "docs" / "long-term-memory"
DEFAULT_SECRET = ROOT / ".local-secrets" / "human-verifier-account.json"
DEFAULT_REPORT = ROOT / "docs" / "reports" / "hosted-long-term-memory-migration.json"


MEMORY_TYPE_BY_STEM = {
    "api-contract-summary": "procedure",
    "architecture-notes": "decision",
    "enterprise-engineering-best-practices": "procedure",
    "matm-architecture-strategy": "decision",
    "project-charter": "fact",
    "release-verification-summary": "evidence",
    "strategy-index": "note",
    "system-targets": "decision",
}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
                "error": {
                    "code": "non_json_http_error",
                    "status": exc.code,
                    "valuesRedacted": True,
                },
                "valuesRedacted": True,
            }
        return exc.code, payload


def token_hash(token):
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def first_heading(text, fallback):
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or fallback
    return fallback


def public_safe_summary(relative_path, text):
    normalized = "\n".join(line.rstrip() for line in text.strip().splitlines()).strip()
    prefix = "Deep link: %s\n\n" % relative_path
    max_body = 4000 - len(prefix)
    if len(normalized) <= max_body:
        return prefix + normalized
    suffix = "\n\n[Truncated for hosted memory summary limit; source document remains the canonical migration seed.]"
    return prefix + normalized[: max_body - len(suffix)].rstrip() + suffix


def idempotency_key(relative_path, text):
    digest = hashlib.sha256((relative_path + "\n" + text).encode("utf-8")).hexdigest()
    return "ltm-doc-" + digest[:40]


def event_shape(payload):
    event = payload.get("event") or {}
    return {
        "eventId": event.get("eventId"),
        "reviewStatus": event.get("reviewStatus"),
        "promotionState": event.get("promotionState"),
        "memoryType": event.get("memoryType"),
        "source": event.get("source"),
        "valuesRedacted": bool(event.get("valuesRedacted")),
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://memoryendpoints.com")
    parser.add_argument("--secret", default=str(DEFAULT_SECRET))
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT))
    parser.add_argument("--agent-id", default="codex-agent")
    args = parser.parse_args(argv)

    secret = read_json(args.secret)
    base_url = args.base_url.rstrip("/")
    token = secret["apiKeySecret"]
    workspace_id = secret["workspaceId"]
    project_id = secret.get("projectId") or workspace_id
    source_dir = Path(args.source_dir)
    records = []

    for path in sorted(source_dir.glob("*.md")):
        relative_path = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        title = first_heading(text, path.stem.replace("-", " ").title())
        body = {
            "workspaceId": workspace_id,
            "actorAgentId": args.agent_id,
            "scope": "project",
            "scopeId": project_id,
            "memoryType": MEMORY_TYPE_BY_STEM.get(path.stem, "note"),
            "subject": title,
            "title": title,
            "summary": public_safe_summary(relative_path, text),
            "tags": [
                "long-term-memory",
                "dogfood-migration",
                "docs-seed",
                path.stem,
            ],
            "confidence": 0.91,
            "source": relative_path,
        }
        status, payload = call_json(
            base_url,
            "/api/matm/memory-events/submit",
            method="POST",
            body=body,
            token=token,
            idempotency_key=idempotency_key(relative_path, text),
        )
        records.append(
            {
                "source": relative_path,
                "title": title,
                "httpStatus": status,
                "ok": 200 <= int(status) < 300 and bool(payload.get("ok")),
                "idempotencyKeyHash": "sha256:" + hashlib.sha256(idempotency_key(relative_path, text).encode("utf-8")).hexdigest(),
                "event": event_shape(payload),
                "payloadShape": sorted(payload.keys()),
            }
        )

    searches = []
    for term in ("enterprise", "MATM", "hierarchical", "MemoryEndpoints"):
        status, payload = call_json(
            base_url,
            "/api/matm/search",
            token=token,
            query=urlencode({"workspace_id": workspace_id, "q": term}),
        )
        searches.append(
            {
                "term": term,
                "httpStatus": status,
                "ok": 200 <= int(status) < 300 and bool(payload.get("ok")),
                "count": payload.get("count"),
                "memorySource": payload.get("memorySource"),
                "filesystemDocsIncluded": payload.get("filesystemDocsIncluded"),
                "payloadShape": sorted(payload.keys()),
            }
        )

    report = {
        "schemaVersion": "memoryendpoints.hosted_long_term_memory_migration.v1",
        "baseUrl": base_url,
        "workspaceId": workspace_id,
        "projectId": project_id,
        "actorAgentId": args.agent_id,
        "apiKeyHash": token_hash(token),
        "sourceDirectory": source_dir.relative_to(ROOT).as_posix(),
        "submittedCount": len(records),
        "successfulCount": sum(1 for item in records if item["ok"]),
        "allSubmissionsOk": all(item["ok"] for item in records),
        "searches": searches,
        "records": records,
        "valuesRedacted": True,
        "rawCredentialsStored": False,
    }
    write_json(args.report_out, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["allSubmissionsOk"] and all(item["ok"] for item in searches) else 1


if __name__ == "__main__":
    raise SystemExit(main())
