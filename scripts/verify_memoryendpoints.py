import argparse
import io
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


ROUTES = [
    "/",
    "/docs",
    "/docs/",
    "/agent-setup",
    "/agent-coordination",
    "/console",
    "/knowledge",
    "/tour",
    "/tour/knowledge",
    "/tour/human",
    "/memory-lifecycle",
    "/transparency",
    "/api/version",
    "/api/matm/live-capability-matrix",
    "/api/matm/agent-compatibility",
    "/api/matm/sync/capabilities",
    "/api/matm/connector-contract",
    "/.well-known/memoryendpoints-connector",
    "/connect/authorize/{publicRequestRef}",
    "/tour/connect/authorize/{demoState}",
    "/api/matm/connector-pairings/requests",
    "/api/matm/connector-pairings/authorization-code-claims",
    "/api/matm/connector-pairings/token",
    "/api/matm/uai-memory/contract",
    "/api/matm/openapi.json",
    "/api/matm/route-inventory",
    "/api/matm/readiness-result",
    "/api/matm/redacted-example-receipts",
    "/api/matm/agent-setup/free-account",
    "/mcp/resources",
    "/robots.txt",
    "/sitemap.xml",
    "/llms.txt",
    "/llms-full.txt",
    "/ai.txt",
    "/ai-manifest.json",
    "/.well-known/mcp.json",
    "/.well-known/ai-agent.json",
]

CONNECTOR_SCHEMA = "memoryendpoints.connector_pairing.v1"
CONNECTOR_PUBLIC_PROBES = {
    "/.well-known/memoryendpoints-connector": {
        "path": "/.well-known/memoryendpoints-connector",
        "method": "GET",
        "expectedStatuses": (200,),
        "contentType": "application/json",
        "kind": "discovery",
    },
    "/connect/authorize/{publicRequestRef}": {
        "path": "/connect/authorize/pairref_" + ("A" * 43),
        "method": "GET",
        "expectedStatuses": (200,),
        "contentType": "text/html",
        "kind": "authorization_shell",
    },
    "/tour/connect/authorize/{demoState}": {
        "path": "/tour/connect/authorize/signed_out",
        "method": "GET",
        "expectedStatuses": (200,),
        "contentType": "text/html",
        "kind": "demo_shell",
    },
    "/api/matm/connector-pairings/requests": {
        "path": "/api/matm/connector-pairings/requests",
        "method": "POST",
        "body": b"{}",
        "expectedStatuses": (405, 422),
        "contentType": "application/json",
        "kind": "safe_no_op",
    },
    "/api/matm/connector-pairings/authorization-code-claims": {
        "path": "/api/matm/connector-pairings/authorization-code-claims",
        "method": "POST",
        "body": b"{}",
        "expectedStatuses": (405, 422),
        "contentType": "application/json",
        "kind": "safe_no_op",
    },
    "/api/matm/connector-pairings/token": {
        "path": "/api/matm/connector-pairings/token",
        "method": "POST",
        "body": b"{}",
        "expectedStatuses": (405, 422),
        "contentType": "application/json",
        "kind": "safe_no_op",
    },
}

SECRET_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{20,}"),
    re.compile(r"apiKeySecret\"\s*:\s*\"[^\"{][^\"]{12,}\""),
    re.compile(r"password\s*[:=]\s*[^,\s]{8,}", re.I),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----"),
]

PUBLIC_LEAK_PATTERNS = [
    ("windows_local_path", re.compile(r"\b[A-Za-z]:[\\/][^\s<>'\")]+")),
    ("file_uri", re.compile(r"\bfile://[^\s<>'\")]+", re.I)),
    ("posix_home_path", re.compile(r"(?<!https:)(?<!http:)(?<![A-Za-z0-9._-])/(?:Users|home)/[^\s<>'\")]+")),
    ("private_runtime_path", re.compile(r"(?<!https:)(?<!http:)(?<![A-Za-z0-9._-])/(?:tmp|var/tmp|private/var)/[^\s<>'\")]+")),
    ("python_traceback", re.compile(r"Traceback \(most recent call last\):")),
    ("python_traceback_frame", re.compile(r"File \"[^\"]+\", line \d+, in ")),
]


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def fetch(url, method="GET", body=None):
    headers = {"Accept": "application/json, text/html;q=0.9"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=headers, method=method)
    opener = build_opener(NoRedirectHandler())
    try:
        with opener.open(request, timeout=20) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, body, dict(response.headers)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body, dict(exc.headers)


def fetch_wsgi(route, method="GET", body=None):
    from app import application

    captured = {}

    def start_response(status, headers):
        captured["status"] = int(status.split(" ", 1)[0])
        captured["headers"] = dict(headers)

    body = body or b""
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": route,
        "QUERY_STRING": "",
        "wsgi.input": io.BytesIO(body),
        "CONTENT_LENGTH": str(len(body)),
    }
    if body:
        environ["CONTENT_TYPE"] = "application/json"
    body = b"".join(application(environ, start_response)).decode("utf-8", errors="replace")
    return captured["status"], body, captured.get("headers") or {}


def git_head_sha():
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
    )
    if completed.returncode == 0:
        return completed.stdout.strip()
    return None


def parse_json(text):
    try:
        return json.loads(text)
    except ValueError:
        return None


def _header(headers, name):
    wanted = name.lower()
    for key, value in (headers or {}).items():
        if str(key).lower() == wanted:
            return str(value)
    return ""


def connector_public_probe_check(route, status, body, headers):
    probe = CONNECTOR_PUBLIC_PROBES[route]
    failures = []
    redirect_observed = 300 <= status < 400 or bool(_header(headers, "Location"))
    content_type = _header(headers, "Content-Type").split(";", 1)[0].strip().lower()
    if status not in probe["expectedStatuses"]:
        failures.append("expected status %s" % "/".join(str(item) for item in probe["expectedStatuses"]))
    if redirect_observed:
        failures.append("no redirects")
    if content_type != probe["contentType"]:
        failures.append("content type %s" % probe["contentType"])

    payload = parse_json(body) if content_type == "application/json" else None
    kind = probe["kind"]
    if kind == "discovery":
        endpoints = (payload or {}).get("endpoints") or {}
        required_endpoints = {
            "pairingRequest",
            "authorization",
            "authorizationCodeClaim",
            "token",
            "activation",
            "status",
            "rotation",
            "rotationActivation",
            "credentialList",
            "revocation",
            "disconnect",
            "cancellation",
        }
        if (payload or {}).get("schemaVersion") != CONNECTOR_SCHEMA:
            failures.append("connector pairing schema")
        if (payload or {}).get("issuer") != "https://memoryendpoints.com":
            failures.append("exact HTTPS issuer")
        if set(endpoints) != required_endpoints:
            failures.append("exact connector endpoint inventory")
        if any(not str(value).startswith("/") or "?" in str(value) or "#" in str(value) for value in endpoints.values()):
            failures.append("relative same-origin endpoint paths")
    elif kind in ("authorization_shell", "demo_shell"):
        if "Connector authorization" not in body:
            failures.append("connector authorization shell")
        if _header(headers, "Referrer-Policy").lower() != "no-referrer":
            failures.append("Referrer-Policy no-referrer")
        if kind == "demo_shell" and "demo" not in body.lower():
            failures.append("explicit Demo label")
    elif kind == "safe_no_op" and status != 405:
        error = (payload or {}).get("error") or {}
        exact_safe_no_op = bool(
            (payload or {}).get("ok") is False
            and (payload or {}).get("safeNoOp") is True
            and (payload or {}).get("valuesRedacted") is True
            and (payload or {}).get("rawCredentialExposed") is False
            and (payload or {}).get("rawPayloadExposed") is False
            and error.get("code") == "invalid_request"
            and error.get("safeNoOp") is True
            and error.get("valuesRedacted") is True
            and isinstance(error.get("title"), str)
            and isinstance(error.get("detail"), str)
            and "message" not in error
        )
        if not exact_safe_no_op:
            failures.append("exact redacted invalid_request safe no-op")
    return {
        "probePath": probe["path"],
        "probeMethod": probe["method"],
        "expectedStatuses": list(probe["expectedStatuses"]),
        "contentType": content_type,
        "noRedirectObserved": not redirect_observed,
        "verified": not failures,
        "failures": failures,
    }


def pattern_hits(patterns, text):
    return [name for name, pattern in patterns if pattern.search(text)]


def apply_build_expectations(item, build, expected_source_sha, require_clean_build=False, git_head_available=True):
    missing = item.setdefault("missing", [])
    observed_source_sha = build.get("sourceSha")
    dirty_present = "sourceWorktreeDirty" in build
    source_worktree_dirty = build.get("sourceWorktreeDirty") if dirty_present else None
    item["sourceSha"] = observed_source_sha
    item["sourceShaShort"] = build.get("sourceShaShort")
    item["sourceWorktreeDirty"] = source_worktree_dirty
    item["sourceWorktreeDirtyPresent"] = dirty_present
    item["cleanSourceRevision"] = source_worktree_dirty is False if dirty_present else None

    if require_clean_build and not git_head_available:
        missing.append("available local Git HEAD")
    if expected_source_sha:
        item["expectedSourceSha"] = expected_source_sha
        source_sha_value_matches = observed_source_sha == expected_source_sha
        clean_metadata_acceptable = (
            source_worktree_dirty is False if dirty_present else not require_clean_build
        )
        item["sourceShaValueMatchesExpected"] = source_sha_value_matches
        item["sourceShaMatchesExpected"] = source_sha_value_matches and clean_metadata_acceptable
        if not source_sha_value_matches:
            missing.append("expected source sha %s" % expected_source_sha)
        if dirty_present and source_worktree_dirty is not False:
            missing.append("clean source revision metadata")
    if require_clean_build and not dirty_present:
        missing.append("sourceWorktreeDirty false metadata")
    return observed_source_sha


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8088")
    parser.add_argument("--json-out")
    parser.add_argument("--wsgi", action="store_true")
    parser.add_argument("--expect-source-sha")
    parser.add_argument("--expect-git-head", action="store_true")
    args = parser.parse_args(argv)
    expected_source_sha = args.expect_source_sha
    expected_source_sha_source = "argument" if expected_source_sha else None
    git_head_at_verification = git_head_sha()
    if args.expect_git_head and not expected_source_sha:
        expected_source_sha = git_head_at_verification
        expected_source_sha_source = "git_head"

    items = []
    observed_source_sha = None
    for route in ROUTES:
        probe = CONNECTOR_PUBLIC_PROBES.get(route) or {
            "path": route,
            "method": "GET",
            "body": None,
            "expectedStatuses": (200,),
        }
        if args.wsgi:
            status, body, headers = fetch_wsgi(
                probe["path"], probe["method"], probe.get("body")
            )
        else:
            url = args.base_url.rstrip("/") + probe["path"]
            status, body, headers = fetch(
                url, probe["method"], probe.get("body")
            )
        missing = []
        if (
            route not in CONNECTOR_PUBLIC_PROBES
            and "MemoryEndpoints" not in body
            and route not in ("/robots.txt", "/api/matm/sync/capabilities")
        ):
            missing.append("MemoryEndpoints")
        secret_hits = [pattern.pattern for pattern in SECRET_PATTERNS if pattern.search(body)]
        leak_hits = pattern_hits(PUBLIC_LEAK_PATTERNS, body)
        item = {
            "route": route,
            "probePath": probe["path"],
            "probeMethod": probe["method"],
            "status": status,
            "missing": missing,
            "secretHitCount": len(secret_hits),
            "leakHitCount": len(leak_hits),
            "leakRules": leak_hits,
        }
        if route in CONNECTOR_PUBLIC_PROBES:
            connector_probe = connector_public_probe_check(route, status, body, headers)
            item["connectorProbe"] = connector_probe
            missing.extend(connector_probe["failures"])
        if route == "/api/version":
            payload = parse_json(body) or {}
            build = payload.get("build") or {}
            observed_source_sha = apply_build_expectations(
                item,
                build,
                expected_source_sha,
                require_clean_build=args.expect_git_head,
                git_head_available=bool(git_head_at_verification),
            )
        items.append(item)

    failures = [
        item
        for item in items
        if item["status"] not in (CONNECTOR_PUBLIC_PROBES.get(item["route"]) or {"expectedStatuses": (200,)})["expectedStatuses"]
        or item["missing"]
        or item["secretHitCount"]
        or item["leakHitCount"]
    ]
    version_item = next((item for item in items if item["route"] == "/api/version"), {})
    report = {
        "schemaVersion": "memoryendpoints.verifier.v1",
        "reportScope": "point_in_time_snapshot",
        "mode": "wsgi" if args.wsgi else "http",
        "ok": not failures,
        "routeCount": len(items),
        "failureCount": len(failures),
        "items": items,
        "failures": failures,
        "expectedSourceSha": expected_source_sha,
        "expectedSourceShaSource": expected_source_sha_source,
        "gitHeadAtVerification": git_head_at_verification,
        "observedSourceSha": observed_source_sha,
        "sourceShaValueMatchesExpected": version_item.get("sourceShaValueMatchesExpected") if expected_source_sha else None,
        "sourceShaMatchesExpected": version_item.get("sourceShaMatchesExpected") if expected_source_sha else None,
        "observedSourceWorktreeDirty": version_item.get("sourceWorktreeDirty"),
    }
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
