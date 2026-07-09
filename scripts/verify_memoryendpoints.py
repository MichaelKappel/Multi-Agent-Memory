import argparse
import io
import json
import re
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


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8088")
    parser.add_argument("--json-out")
    parser.add_argument("--wsgi", action="store_true")
    args = parser.parse_args(argv)

    items = []
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
        items.append({"route": route, "status": status, "missing": missing, "secretHitCount": len(secret_hits)})

    failures = [item for item in items if item["status"] != 200 or item["missing"] or item["secretHitCount"]]
    report = {
        "schemaVersion": "memoryendpoints.verifier.v1",
        "ok": not failures,
        "routeCount": len(items),
        "failureCount": len(failures),
        "items": items,
        "failures": failures,
    }
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
