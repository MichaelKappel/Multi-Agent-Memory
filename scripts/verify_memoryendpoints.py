import argparse
import io
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


ROUTES = [
    "/",
    "/docs",
    "/docs/",
    "/agent-setup",
    "/memory-lifecycle",
    "/transparency",
    "/api/version",
    "/api/matm/live-capability-matrix",
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

SECRET_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{20,}"),
    re.compile(r"apiKeySecret\"\s*:\s*\"[^\"{][^\"]{12,}\""),
    re.compile(r"password\s*[:=]\s*[^,\s]{8,}", re.I),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----"),
]


def fetch(url):
    try:
        with urlopen(url, timeout=20) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, body
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body


def fetch_wsgi(route):
    from app import application

    captured = {}

    def start_response(status, headers):
        captured["status"] = int(status.split(" ", 1)[0])

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": route,
        "QUERY_STRING": "",
        "wsgi.input": io.BytesIO(b""),
        "CONTENT_LENGTH": "0",
    }
    body = b"".join(application(environ, start_response)).decode("utf-8", errors="replace")
    return captured["status"], body


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


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8088")
    parser.add_argument("--json-out")
    parser.add_argument("--wsgi", action="store_true")
    parser.add_argument("--expect-source-sha")
    parser.add_argument("--expect-git-head", action="store_true")
    args = parser.parse_args(argv)
    expected_source_sha = args.expect_source_sha
    if args.expect_git_head and not expected_source_sha:
        expected_source_sha = git_head_sha()

    items = []
    observed_source_sha = None
    for route in ROUTES:
        if args.wsgi:
            status, body = fetch_wsgi(route)
        else:
            url = args.base_url.rstrip("/") + route
            status, body = fetch(url)
        missing = []
        if "MemoryEndpoints" not in body and route not in ("/robots.txt",):
            missing.append("MemoryEndpoints")
        secret_hits = [pattern.pattern for pattern in SECRET_PATTERNS if pattern.search(body)]
        item = {"route": route, "status": status, "missing": missing, "secretHitCount": len(secret_hits)}
        if route == "/api/version":
            payload = parse_json(body) or {}
            build = payload.get("build") or {}
            observed_source_sha = build.get("sourceSha")
            item["sourceSha"] = observed_source_sha
            item["sourceShaShort"] = build.get("sourceShaShort")
            if expected_source_sha:
                item["expectedSourceSha"] = expected_source_sha
                item["sourceShaMatchesExpected"] = observed_source_sha == expected_source_sha
                if observed_source_sha != expected_source_sha:
                    missing.append("expected source sha %s" % expected_source_sha)
        items.append(item)

    failures = [item for item in items if item["status"] != 200 or item["missing"] or item["secretHitCount"]]
    report = {
        "schemaVersion": "memoryendpoints.verifier.v1",
        "ok": not failures,
        "routeCount": len(items),
        "failureCount": len(failures),
        "items": items,
        "failures": failures,
        "expectedSourceSha": expected_source_sha,
        "observedSourceSha": observed_source_sha,
        "sourceShaMatchesExpected": bool(expected_source_sha and observed_source_sha == expected_source_sha) if expected_source_sha else None,
    }
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
