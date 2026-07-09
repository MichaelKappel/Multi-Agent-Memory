import argparse
import json
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SITE_ROOT = ROOT / "sites" / "multiagentmemory.com"

REQUIRED_FILES = [
    "index.html",
    "docs/how-it-works.html",
    "docs/memory-boundary.html",
    "llms.txt",
    "ai.txt",
    "ai-manifest.json",
    ".well-known/ai-agent.json",
    ".well-known/mcp.json",
    "sitemap.xml",
]

LIVE_FILES = list(REQUIRED_FILES)

REQUIRED_STRINGS = {
    "index.html": [
        "https://github.com/MichaelKappel/Multi-Agent-Memory",
        "https://memoryendpoints.com",
        "/docs/how-it-works.html",
    ],
    "docs/how-it-works.html": [
        "static companion documentation site",
        "https://github.com/MichaelKappel/Multi-Agent-Memory",
        "https://memoryendpoints.com",
        ".uai/",
        "/api/matm/memory-events/submit",
    ],
    "docs/memory-boundary.html": [
        "https://github.com/MichaelKappel/Multi-Agent-Memory",
        "https://uaix.org/en-us/tools/ai-memory-package-wizard/#setup-MATM-MemoryEndpoints",
    ],
    "llms.txt": [
        "Source repository: https://github.com/MichaelKappel/Multi-Agent-Memory",
        "Hosted endpoint: https://memoryendpoints.com",
    ],
    "ai-manifest.json": [
        '"sourceRepository": "https://github.com/MichaelKappel/Multi-Agent-Memory"',
        '"primaryEndpointSite": "https://memoryendpoints.com"',
    ],
    "sitemap.xml": ["https://multiagentmemory.com/docs/how-it-works.html"],
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


def read_text(path):
    return path.read_text(encoding="utf-8", errors="replace")


def live_route_for(rel):
    if rel == "index.html":
        return "/"
    return "/" + rel.replace("\\", "/")


def fetch_live(base_url, rel):
    route = live_route_for(rel)
    url = base_url.rstrip("/") + route
    try:
        with urlopen(url, timeout=20) as response:
            return response.status, response.read().decode("utf-8", errors="replace"), None
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace"), exc.__class__.__name__
    except URLError as exc:
        return None, "", exc.__class__.__name__


def pattern_hits(patterns, text):
    return [name for name, pattern in patterns if pattern.search(text)]


def apply_public_text_checks(item, text):
    item["secretHitCount"] = sum(1 for pattern in SECRET_PATTERNS if pattern.search(text))
    item["leakRules"] = pattern_hits(PUBLIC_LEAK_PATTERNS, text)
    item["leakHitCount"] = len(item["leakRules"])


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-root", default=str(DEFAULT_SITE_ROOT))
    parser.add_argument("--base-url")
    parser.add_argument("--json-out")
    args = parser.parse_args(argv)

    site_root = Path(args.site_root)
    items = []
    required = LIVE_FILES if args.base_url else REQUIRED_FILES
    for rel in required:
        path = site_root / rel
        item = {"file": rel, "missingStrings": [], "secretHitCount": 0, "leakHitCount": 0, "leakRules": []}
        if args.base_url:
            status, text, error_type = fetch_live(args.base_url, rel)
            item["route"] = live_route_for(rel)
            item["status"] = status
            item["exists"] = status == 200
            if error_type:
                item["errorType"] = error_type
        else:
            item["exists"] = path.exists()
            text = read_text(path) if path.exists() else ""
        if text:
            apply_public_text_checks(item, text)
        if item["exists"]:
            item["missingStrings"] = [value for value in REQUIRED_STRINGS.get(rel, []) if value not in text]
        items.append(item)

    failures = [
        item
        for item in items
        if not item["exists"] or item["missingStrings"] or item["secretHitCount"] or item["leakHitCount"]
    ]
    report = {
        "schemaVersion": "static_site.verifier.v1",
        "site": "MultiAgentMemory.com",
        "mode": "live" if args.base_url else "local",
        "siteRoot": str(site_root),
        "baseUrl": args.base_url,
        "staticHtmlCompanion": True,
        "ok": not failures,
        "fileCount": len(items),
        "failureCount": len(failures),
        "items": items,
        "failures": failures,
        "valuesRedacted": True,
    }
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
