import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memoryendpoints import __version__

DEFAULT_SITE_ROOT = ROOT / "sites" / "multiagentmemory.com"

REQUIRED_FILES = [
    "index.html",
    "docs/how-it-works.html",
    "docs/api-reference.html",
    "docs/memory-boundary.html",
    "releases.html",
    "releases.json",
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
        "/docs/api-reference.html",
        "/releases.html",
        "Public edition v0.2.0",
    ],
    "docs/how-it-works.html": [
        "static companion documentation site",
        "https://github.com/MichaelKappel/Multi-Agent-Memory",
        "https://memoryendpoints.com",
        ".uai/",
        "/api/matm/memory-events/submit",
        "/api/matm/routing-decisions",
        "/api/matm/sync/capabilities",
        "/releases.html",
        "Public edition v0.2.0",
    ],
    "docs/api-reference.html": [
        "https://github.com/MichaelKappel/Multi-Agent-Memory",
        "https://memoryendpoints.com/api/matm/route-inventory",
        "/api/matm/external-links/upsert",
        "/api/matm/routing-decisions",
        "/api/matm/sync/mutations",
        "Tracked reports are point-in-time evidence",
        "/releases.html",
        "Public edition v0.2.0",
    ],
    "docs/memory-boundary.html": [
        "https://github.com/MichaelKappel/Multi-Agent-Memory",
        "https://uaix.org/en-us/tools/ai-memory-package-wizard/#setup-MATM-MemoryEndpoints",
        "/releases.html",
        "Public edition v0.2.0",
    ],
    "releases.html": [
        "Multi-Agent Memory Releases",
        "v0.2.0",
        "August 4, 2026",
        "/releases.json",
        "https://github.com/MichaelKappel/Multi-Agent-Memory/blob/main/CHANGELOG.md",
    ],
    "releases.json": [
        '"schemaVersion": "multiagentmemory.public_releases.v1"',
        '"currentVersion": "0.2.0"',
        '"currentReleaseDate": "2026-08-04"',
    ],
    "llms.txt": [
        "Source repository: https://github.com/MichaelKappel/Multi-Agent-Memory",
        "Hosted endpoint: https://memoryendpoints.com",
    ],
    "ai-manifest.json": [
        '"sourceRepository": "https://github.com/MichaelKappel/Multi-Agent-Memory"',
        '"primaryEndpointSite": "https://memoryendpoints.com"',
    ],
    "sitemap.xml": [
        "https://multiagentmemory.com/docs/how-it-works.html",
        "https://multiagentmemory.com/docs/api-reference.html",
        "https://multiagentmemory.com/releases.html",
        "https://multiagentmemory.com/releases.json",
    ],
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

RELEASE_CATALOG_TOP_LEVEL_KEYS = {
    "currentReleaseDate",
    "currentVersion",
    "releases",
    "runtimeVersionEvidence",
    "schemaVersion",
    "sourceRepository",
    "valuesRedacted",
}
RELEASE_ENTRY_KEYS = {"changes", "releaseDate", "status", "summary", "version"}
RELEASE_VERSION_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
FORBIDDEN_PUBLIC_KEY_FRAGMENTS = (
    "credential",
    "filepath",
    "filesystempath",
    "localpath",
    "password",
    "payload",
    "private",
    "secret",
    "token",
)


def decode_utf8(data):
    try:
        return data.decode("utf-8", errors="strict"), None
    except UnicodeDecodeError:
        return "", "invalid_utf8"


def read_text(path):
    text, error = decode_utf8(path.read_bytes())
    if error:
        raise UnicodeError(error)
    return text


def live_route_for(rel):
    if rel == "index.html":
        return "/"
    return "/" + rel.replace("\\", "/")


def fetch_live(base_url, rel):
    route = live_route_for(rel)
    url = base_url.rstrip("/") + route
    try:
        with urlopen(url, timeout=20) as response:
            text, decode_error = decode_utf8(response.read())
            return response.status, text, dict(response.headers), decode_error
    except HTTPError as exc:
        text, decode_error = decode_utf8(exc.read())
        return exc.code, text, dict(exc.headers), decode_error or exc.__class__.__name__
    except URLError as exc:
        return None, "", {}, exc.__class__.__name__


def pattern_hits(patterns, text):
    return [name for name, pattern in patterns if pattern.search(text)]


def apply_public_text_checks(item, text):
    item["secretHitCount"] = sum(1 for pattern in SECRET_PATTERNS if pattern.search(text))
    item["leakRules"] = pattern_hits(PUBLIC_LEAK_PATTERNS, text)
    item["leakHitCount"] = len(item["leakRules"])


def strict_json_loads(text):
    def closed_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object member")
            result[key] = value
        return result

    def reject_constant(_value):
        raise ValueError("non-finite JSON value")

    return json.loads(text, object_pairs_hook=closed_pairs, parse_constant=reject_constant)


def _forbidden_public_keys(value, path="$", failures=None):
    failures = failures if failures is not None else []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if any(fragment in normalized for fragment in FORBIDDEN_PUBLIC_KEY_FRAGMENTS):
                failures.append("forbidden public key at %s" % path)
            _forbidden_public_keys(child, path + "." + str(key), failures)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _forbidden_public_keys(child, "%s[%d]" % (path, index), failures)
    return failures


def _version_tuple(value):
    if not isinstance(value, str) or not RELEASE_VERSION_PATTERN.fullmatch(value):
        return None
    return tuple(int(part) for part in value.split("."))


def _valid_iso_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def validate_release_catalog(catalog, expected_version=__version__):
    failures = []
    if not isinstance(catalog, dict):
        return ["release catalog must be an object"]
    if set(catalog) != RELEASE_CATALOG_TOP_LEVEL_KEYS:
        failures.append("release catalog top-level fields must be exact")
    failures.extend(_forbidden_public_keys(catalog))
    if catalog.get("schemaVersion") != "multiagentmemory.public_releases.v1":
        failures.append("release catalog schema version must be exact")
    if catalog.get("sourceRepository") != "https://github.com/MichaelKappel/Multi-Agent-Memory":
        failures.append("release catalog source repository must be exact")
    if catalog.get("runtimeVersionEvidence") != "https://memoryendpoints.com/api/version":
        failures.append("release catalog runtime evidence must be exact")
    if catalog.get("valuesRedacted") is not True:
        failures.append("release catalog must be redacted")
    current_version = catalog.get("currentVersion")
    current_date = catalog.get("currentReleaseDate")
    if current_version != expected_version or _version_tuple(current_version) is None:
        failures.append("release catalog current version must match the public edition")
    if not _valid_iso_date(current_date):
        failures.append("release catalog current date must be canonical")

    releases = catalog.get("releases")
    if not isinstance(releases, list) or not releases or len(releases) > 100:
        failures.append("release catalog releases must be a bounded nonempty list")
        return failures
    versions = []
    statuses = []
    previous_version = None
    previous_date = None
    for index, release in enumerate(releases):
        if not isinstance(release, dict):
            failures.append("release entry must be an object")
            continue
        if set(release) != RELEASE_ENTRY_KEYS:
            failures.append("release entry fields must be exact")
        version = release.get("version")
        version_tuple = _version_tuple(version)
        release_date = release.get("releaseDate")
        status = release.get("status")
        summary = release.get("summary")
        changes = release.get("changes")
        if version_tuple is None:
            failures.append("release version must be canonical semantic version")
        if not _valid_iso_date(release_date):
            failures.append("release date must be canonical")
        if status not in ("current", "historical"):
            failures.append("release status must be closed")
        if not isinstance(summary, str) or not summary.strip() or len(summary.encode("utf-8")) > 500:
            failures.append("release summary must be bounded nonempty text")
        if not isinstance(changes, list) or not 1 <= len(changes) <= 32 or any(
            not isinstance(change, str) or not change.strip() or len(change.encode("utf-8")) > 500
            for change in (changes if isinstance(changes, list) else [])
        ):
            failures.append("release changes must be bounded nonempty text")
        if previous_version is not None and version_tuple is not None and version_tuple >= previous_version:
            failures.append("release versions must be strictly descending")
        if previous_date is not None and isinstance(release_date, str) and release_date > previous_date:
            failures.append("release dates must be descending")
        if version_tuple is not None:
            previous_version = version_tuple
        if isinstance(release_date, str):
            previous_date = release_date
        versions.append(version)
        statuses.append(status)
        if index == 0 and (version != current_version or release_date != current_date or status != "current"):
            failures.append("first release must match the current release")
    version_strings = [version for version in versions if isinstance(version, str)]
    if len(version_strings) != len(versions) or len(version_strings) != len(set(version_strings)):
        failures.append("release versions must be unique")
    if len(statuses) != len(releases) or statuses.count("current") != 1 or not statuses or statuses[0] != "current" or any(
        status != "historical" for status in statuses[1:]
    ):
        failures.append("release catalog must have exactly one first current release")
    return failures


def _human_release_date(value):
    parsed = date.fromisoformat(value)
    return "%s %d, %d" % (parsed.strftime("%B"), parsed.day, parsed.year)


def validate_release_surfaces(catalog, release_html, manifest_text, changelog_text, expected_version=__version__):
    failures = validate_release_catalog(catalog, expected_version=expected_version)
    if failures:
        return failures
    current_version = catalog["currentVersion"]
    current_date = catalog["currentReleaseDate"]
    try:
        manifest = strict_json_loads(manifest_text)
    except (TypeError, ValueError):
        failures.append("AI manifest must be strict JSON")
        manifest = {}
    if manifest.get("releaseVersion") != current_version or manifest.get("releaseDate") != current_date:
        failures.append("AI manifest release must match the catalog")
    if "v%s" % current_version not in release_html or _human_release_date(current_date) not in release_html:
        failures.append("release page must match the current catalog")
    if "## %s — %s" % (current_version, current_date) not in changelog_text:
        failures.append("CHANGELOG current release must match the catalog")
    return failures


def release_catalog_content_type_failures(content_type, live=False):
    if not live or content_type == "application/json":
        return []
    return ["release catalog content type must be application/json"]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-root", default=str(DEFAULT_SITE_ROOT))
    parser.add_argument("--base-url")
    parser.add_argument("--json-out")
    args = parser.parse_args(argv)

    site_root = Path(args.site_root)
    items = []
    public_texts = {}
    required = LIVE_FILES if args.base_url else REQUIRED_FILES
    for rel in required:
        path = site_root / rel
        item = {
            "file": rel,
            "missingStrings": [],
            "contractFailures": [],
            "secretHitCount": 0,
            "leakHitCount": 0,
            "leakRules": [],
        }
        if args.base_url:
            status, text, headers, error_type = fetch_live(args.base_url, rel)
            item["route"] = live_route_for(rel)
            item["status"] = status
            item["exists"] = status == 200
            item["contentType"] = str(headers.get("Content-Type") or headers.get("content-type") or "").split(";", 1)[0].strip().lower()
            if error_type:
                item["errorType"] = error_type
                if error_type == "invalid_utf8":
                    item["contractFailures"].append("response must be strict UTF-8")
        else:
            item["exists"] = path.exists()
            text = ""
            if path.exists():
                try:
                    text = read_text(path)
                except UnicodeError:
                    item["errorType"] = "invalid_utf8"
                    item["contractFailures"].append("file must be strict UTF-8")
        if text:
            public_texts[rel] = text
            apply_public_text_checks(item, text)
        if item["exists"]:
            item["missingStrings"] = [value for value in REQUIRED_STRINGS.get(rel, []) if value not in text]
        if rel == "releases.json":
            item["contractFailures"].extend(
                release_catalog_content_type_failures(
                    item.get("contentType"),
                    live=bool(args.base_url),
                )
            )
        items.append(item)

    release_item = next((item for item in items if item["file"] == "releases.json"), None)
    if release_item is not None and public_texts.get("releases.json"):
        try:
            release_catalog = strict_json_loads(public_texts["releases.json"])
        except (TypeError, ValueError):
            release_item["contractFailures"].append("release catalog must be strict JSON")
        else:
            changelog_text = read_text(ROOT / "CHANGELOG.md")
            release_item["contractFailures"].extend(
                validate_release_surfaces(
                    release_catalog,
                    public_texts.get("releases.html", ""),
                    public_texts.get("ai-manifest.json", ""),
                    changelog_text,
                )
            )

    failures = [
        item
        for item in items
        if not item["exists"]
        or item["missingStrings"]
        or item["contractFailures"]
        or item["secretHitCount"]
        or item["leakHitCount"]
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
