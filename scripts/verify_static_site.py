import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

try:
    from .multiagentmemory_release_identity import (
        FINAL_PHASE,
        PREACTIVATION_PHASE,
        RELEASE_CLAIM_PATHS,
        RELEASE_PHASES,
        ReleaseIdentityError,
    )
    from .package_multiagentmemory_static_site import (
        ALLOWED_SITE_FILES,
        SitePackageError,
        verify_package,
    )
    from .render_multiagentmemory_release_history import (
        ReleaseProjectionError,
        projection_drift,
    )
except ImportError:
    script_directory = str(Path(__file__).resolve().parent)
    if script_directory not in sys.path:
        sys.path.insert(0, script_directory)
    from multiagentmemory_release_identity import (
        FINAL_PHASE,
        PREACTIVATION_PHASE,
        RELEASE_CLAIM_PATHS,
        RELEASE_PHASES,
        ReleaseIdentityError,
    )
    from package_multiagentmemory_static_site import (
        ALLOWED_SITE_FILES,
        SitePackageError,
        verify_package,
    )
    from render_multiagentmemory_release_history import (
        ReleaseProjectionError,
        projection_drift,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SITE_ROOT = ROOT / "sites" / "multiagentmemory.com"
CANONICAL_LIVE_BASE_URL = "https://multiagentmemory.com"

REQUIRED_FILES = [
    "index.html",
    "docs/how-it-works.html",
    "docs/api-reference.html",
    "docs/chatgpt-mcp.html",
    "docs/memory-boundary.html",
    "releases/index.html",
    "releases.json",
    "llms.txt",
    "ai.txt",
    "ai-manifest.json",
    ".well-known/ai-agent.json",
    ".well-known/mcp.json",
    "robots.txt",
    "sitemap.xml",
]

NON_CLAIM_FILES = tuple(
    sorted(path for path in ALLOWED_SITE_FILES if path not in RELEASE_CLAIM_PATHS)
)

EXPECTED_MEDIA_TYPES = {
    ".well-known/ai-agent.json": "application/json",
    ".well-known/mcp.json": "application/json",
    "README.md": "text/markdown",
    "ai-manifest.json": "application/json",
    "ai.txt": "text/plain",
    "docs/api-reference.html": "text/html",
    "docs/chatgpt-mcp.html": "text/html",
    "docs/how-it-works.html": "text/html",
    "docs/memory-boundary.html": "text/html",
    "index.html": "text/html",
    "llms.txt": "text/plain",
    "releases.json": "application/json",
    "releases/index.html": "text/html",
    "robots.txt": "text/plain",
    "sitemap.xml": "application/xml",
    "static/chatgpt-app-icon.png": "image/png",
    "static/favicon.svg": "image/svg+xml",
    "static/site.css": "text/css",
}


class LiveOriginError(ValueError):
    """Fail-closed canonical production-origin validation error."""


class RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "redirects are forbidden", headers, fp)


REQUIRED_STRINGS = {
    "index.html": [
        "https://github.com/MichaelKappel/Multi-Agent-Memory",
        "https://memoryendpoints.com",
        "/docs/how-it-works.html",
        "/docs/api-reference.html",
    ],
    "docs/how-it-works.html": [
        "static companion documentation site",
        "https://github.com/MichaelKappel/Multi-Agent-Memory",
        "https://memoryendpoints.com",
        ".uai/",
        "/api/matm/memory-events/submit",
        "/api/matm/routing-decisions",
        "/api/matm/sync/capabilities",
    ],
    "docs/api-reference.html": [
        "https://github.com/MichaelKappel/Multi-Agent-Memory",
        "https://memoryendpoints.com/api/matm/route-inventory",
        "/api/matm/external-links/upsert",
        "/api/matm/routing-decisions",
        "/api/matm/sync/mutations",
        "Tracked reports are point-in-time evidence",
    ],
    "docs/memory-boundary.html": [
        "https://github.com/MichaelKappel/Multi-Agent-Memory",
        "https://uaix.org/en-us/tools/ai-memory-package-wizard/#setup-MATM-MemoryEndpoints",
    ],
    "releases/index.html": [
        '<link rel="canonical" href="https://multiagentmemory.com/releases/">',
        "Public edition 0.2.0",
        "Public edition 0.1.0",
        "Website version 1.0.0",
        'data-release-status="deployed"',
        "August 29, 2026 (UTC)",
        "https://multiagentmemory.com/releases/#release-list",
        '"numberOfItems": 1',
        '"value": "deployed"',
        "multiagentmemory-site-v1.0.0",
        'href="/releases.json"',
    ],
    "releases.json": [
        '"schema": "multiagentmemory.public-release-history.v1"',
        '"currentProductionWebsiteVersion": "1.0.0"',
        '"currentVersion": "0.2.0"',
        '"releaseCount": 2',
        '"releaseCount": 1',
        '"status": "deployed"',
        '"activationDate": "2026-08-29"',
        "9f53a3cf0ab96e64ad3827e688c1dba52bd7059a",
        "a97443b00915d64d1342107ee243dda4dce5da9a",
        "multiagentmemory-site-v1.0.0",
    ],
    "llms.txt": [
        "Source repository: https://github.com/MichaelKappel/Multi-Agent-Memory",
        "Hosted endpoint: https://memoryendpoints.com",
        "Production release history: https://multiagentmemory.com/releases/",
        "Machine-readable release ledger: https://multiagentmemory.com/releases.json",
        "Current public edition: 0.2.0.",
        "Verified public edition release count: 2.",
        "Current production website version: 1.0.0.",
        "Latest release status: deployed.",
        "multiagentmemory-site-v1.0.0",
    ],
    "ai.txt": [
        "Current public edition: 0.2.0.",
        "Verified public edition release count: 2.",
        "Current production website version: 1.0.0.",
        "Verified production release count: 1.",
        "Latest release status: deployed.",
        "multiagentmemory-site-v1.0.0",
    ],
    "ai-manifest.json": [
        '"sourceRepository": "https://github.com/MichaelKappel/Multi-Agent-Memory"',
        '"primaryEndpointSite": "https://memoryendpoints.com"',
        '"releaseHistory": "https://multiagentmemory.com/releases/"',
        '"currentProductionWebsiteVersion": "1.0.0"',
        '"currentVersion": "0.2.0"',
        '"exactSourceCommit": "9f53a3cf0ab96e64ad3827e688c1dba52bd7059a"',
        '"releaseCount": 1',
        '"latestReleaseStatus": "deployed"',
    ],
    "robots.txt": [
        "Sitemap: https://multiagentmemory.com/sitemap.xml",
    ],
    "sitemap.xml": [
        "https://multiagentmemory.com/docs/how-it-works.html",
        "https://multiagentmemory.com/docs/api-reference.html",
        "https://multiagentmemory.com/releases/",
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
    (
        "posix_home_path",
        re.compile(
            r"(?<!https:)(?<!http:)(?<![A-Za-z0-9._-])/(?:Users|home)/[^\s<>'\")]+"
        ),
    ),
    (
        "private_runtime_path",
        re.compile(
            r"(?<!https:)(?<!http:)(?<![A-Za-z0-9._-])/(?:tmp|var/tmp|private/var)/[^\s<>'\")]+"
        ),
    ),
    ("python_traceback", re.compile(r"Traceback \(most recent call last\):")),
    ("python_traceback_frame", re.compile(r"File \"[^\"]+\", line \d+, in ")),
]


def read_text(path):
    return path.read_text(encoding="utf-8", errors="replace")


def live_route_for(rel):
    if rel == "index.html":
        return "/"
    if rel.endswith("/index.html"):
        return "/" + rel[: -len("index.html")].replace("\\", "/")
    return "/" + rel.replace("\\", "/")


def validate_live_base_url(base_url):
    if base_url != CANONICAL_LIVE_BASE_URL:
        raise LiveOriginError("live_base_url_not_canonical")
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "multiagentmemory.com"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.netloc != "multiagentmemory.com"
    ):
        raise LiveOriginError("live_base_url_not_canonical")
    return base_url


def live_activation_gate(release_identity, utc_date=None):
    utc_date = utc_date or datetime.now(timezone.utc).date().isoformat()
    activation_date = (release_identity or {}).get("activationDate")
    return {
        "checked": bool(release_identity),
        "ok": bool(release_identity) and activation_date == utc_date,
        "deploymentUtcDate": utc_date,
        "releaseActivationDate": activation_date,
        "valuesRedacted": True,
    }


def build_live_opener():
    return build_opener(RejectRedirects())


def _response_media_type(response):
    headers = getattr(response, "headers", None)
    if headers is None or not hasattr(headers, "get_all"):
        return None
    values = headers.get_all("Content-Type", [])
    if not isinstance(values, list) or len(values) != 1:
        return None
    value = values[0]
    if not isinstance(value, str) or not value.strip():
        return None
    media_type = value.split(";", 1)[0].strip().lower()
    return media_type or None


def fetch_live(base_url, rel, opener=None):
    validate_live_base_url(base_url)
    route = live_route_for(rel)
    url = base_url + route
    opener = opener or build_live_opener()
    try:
        with opener.open(url, timeout=20) as response:
            final_url = response.geturl()
            return {
                "status": response.status,
                "data": response.read(),
                "errorType": None,
                "requestedUrl": url,
                "finalUrl": final_url,
                "canonicalFinalUrl": final_url == url,
                "mediaType": _response_media_type(response),
            }
    except HTTPError as exc:
        return {
            "status": exc.code,
            "data": exc.read(),
            "errorType": exc.__class__.__name__,
            "requestedUrl": url,
            "finalUrl": None,
            "canonicalFinalUrl": False,
            "mediaType": None,
        }
    except URLError as exc:
        return {
            "status": None,
            "data": b"",
            "errorType": exc.__class__.__name__,
            "requestedUrl": url,
            "finalUrl": None,
            "canonicalFinalUrl": False,
            "mediaType": None,
        }


def pattern_hits(patterns, text):
    return [name for name, pattern in patterns if pattern.search(text)]


def apply_public_text_checks(item, text):
    item["secretHitCount"] = sum(
        1 for pattern in SECRET_PATTERNS if pattern.search(text)
    )
    item["leakRules"] = pattern_hits(PUBLIC_LEAK_PATTERNS, text)
    item["leakHitCount"] = len(item["leakRules"])


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--site-root", default=str(DEFAULT_SITE_ROOT))
    parser.add_argument("--base-url")
    parser.add_argument("--package")
    parser.add_argument("--package-manifest")
    parser.add_argument("--phase", choices=sorted(RELEASE_PHASES))
    parser.add_argument("--json-out")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    site_root = Path(args.site_root)
    package_verification = None
    package_error = None
    base_url_accepted = False
    activation_gate_before_fetch = None
    if args.base_url:
        try:
            validate_live_base_url(args.base_url)
            base_url_accepted = True
        except LiveOriginError:
            package_error = "live_base_url_not_canonical"
        if package_error is None and args.phase is None:
            package_error = "live_verification_phase_required"
        elif package_error is None and not (args.package and args.package_manifest):
            package_error = "immutable_package_required_for_live_verification"
        elif package_error is None:
            try:
                package_verification = verify_package(
                    args.package,
                    args.package_manifest,
                    phase=args.phase,
                    repo_root=args.repo_root,
                    site_root=site_root,
                )
            except ReleaseIdentityError as exc:
                package_error = exc.code
            except (OSError, UnicodeError, SitePackageError):
                package_error = "package_verification_failed"
        if package_verification is not None:
            activation_gate_before_fetch = live_activation_gate(
                package_verification["releaseIdentity"]
            )
            if not activation_gate_before_fetch["ok"]:
                package_error = "activation_date_not_current_utc"
    elif args.package or args.package_manifest or args.phase:
        package_error = "package_arguments_require_live_verification"

    items = []
    required = (
        []
        if args.base_url and package_error
        else list(NON_CLAIM_FILES)
        if args.base_url and args.phase == PREACTIVATION_PHASE
        else list(ALLOWED_SITE_FILES)
        if args.base_url and args.phase == FINAL_PHASE
        else REQUIRED_FILES
    )
    verification_scope = (
        "preactivation_nonclaims"
        if args.base_url and args.phase == PREACTIVATION_PHASE
        else "final_full_release"
        if args.base_url and args.phase == FINAL_PHASE
        else "local_static"
    )
    expected_files = {
        entry["relativePath"].as_posix(): entry["bytes"]
        for entry in (package_verification or {}).get("files", [])
    }
    opener = build_live_opener() if args.base_url and not package_error else None
    for rel in required:
        path = site_root / rel
        item = {
            "file": rel,
            "missingStrings": [],
            "secretHitCount": 0,
            "leakHitCount": 0,
            "leakRules": [],
        }
        if args.base_url:
            fetched = fetch_live(args.base_url, rel, opener=opener)
            status = fetched["status"]
            data = fetched["data"]
            text = data.decode("utf-8", errors="replace")
            item["route"] = live_route_for(rel)
            item["status"] = status
            item["exists"] = status == 200
            item["canonicalFinalUrl"] = fetched["canonicalFinalUrl"]
            item["mediaType"] = fetched["mediaType"]
            item["expectedMediaType"] = EXPECTED_MEDIA_TYPES[rel]
            item["mediaTypeMatch"] = fetched["mediaType"] == EXPECTED_MEDIA_TYPES[rel]
            if package_verification:
                expected = expected_files.get(rel)
                item["expectedSha256"] = (
                    hashlib.sha256(expected).hexdigest()
                    if expected is not None
                    else None
                )
                item["actualSha256"] = (
                    hashlib.sha256(data).hexdigest() if item["exists"] else None
                )
                item["exactPackageByteMatch"] = bool(
                    item["exists"] and expected is not None and data == expected
                )
            if fetched["errorType"]:
                item["errorType"] = fetched["errorType"]
        else:
            item["exists"] = path.exists()
            text = read_text(path) if path.exists() else ""
        if text:
            apply_public_text_checks(item, text)
        if item["exists"]:
            item["missingStrings"] = [
                value for value in REQUIRED_STRINGS.get(rel, []) if value not in text
            ]
        items.append(item)

    retired_items = []
    if args.base_url and args.phase == FINAL_PHASE and not package_error:
        retired_paths = package_verification["releaseIdentityManifest"][
            "cutoverPolicy"
        ]["finalRetiredPathVerificationPaths"]
        for rel in retired_paths:
            fetched = fetch_live(args.base_url, rel, opener=opener)
            text = fetched["data"].decode("utf-8", errors="replace")
            item = {
                "file": rel,
                "route": live_route_for(rel),
                "expectedStatus": 404,
                "status": fetched["status"],
                "errorType": fetched["errorType"],
                "ordinaryNotFound": fetched["status"] == 404,
                "noRedirectVerified": fetched["status"] == 404,
                "requestedUrlVerified": fetched["requestedUrl"]
                == args.base_url + live_route_for(rel),
                "secretHitCount": 0,
                "leakHitCount": 0,
                "leakRules": [],
            }
            if text:
                apply_public_text_checks(item, text)
            item["verified"] = bool(
                item["ordinaryNotFound"]
                and item["noRedirectVerified"]
                and item["requestedUrlVerified"]
                and not item["secretHitCount"]
                and not item["leakHitCount"]
            )
            retired_items.append(item)

    failures = [
        item
        for item in items
        if (
            not item["exists"]
            or item["missingStrings"]
            or item["secretHitCount"]
            or item["leakHitCount"]
            or (
                args.base_url
                and package_verification
                and (
                    not item.get("exactPackageByteMatch")
                    or not item.get("canonicalFinalUrl")
                    or not item.get("mediaTypeMatch")
                )
            )
        )
    ]
    retired_failures = [item for item in retired_items if not item["verified"]]
    failures.extend(retired_failures)
    package_rechecked_after_fetch = False
    post_fetch_error = None
    activation_gate_after_fetch = None
    if args.base_url and package_verification is not None and not failures:
        try:
            post_fetch_verification = verify_package(
                args.package,
                args.package_manifest,
                phase=args.phase,
                repo_root=args.repo_root,
                site_root=site_root,
            )
            package_rechecked_after_fetch = (
                post_fetch_verification["package"] == package_verification["package"]
                and post_fetch_verification["releaseIdentity"]
                == package_verification["releaseIdentity"]
                and post_fetch_verification["sourceQualification"]
                == package_verification["sourceQualification"]
            )
            if not package_rechecked_after_fetch:
                post_fetch_error = "identity_changed_during_live_verification"
        except ReleaseIdentityError as exc:
            post_fetch_error = exc.code
        except (OSError, UnicodeError, SitePackageError):
            post_fetch_error = "package_reverification_failed"
        activation_gate_after_fetch = live_activation_gate(
            package_verification["releaseIdentity"]
        )
        if not activation_gate_after_fetch["ok"]:
            post_fetch_error = "activation_date_changed_during_live_verification"
    release_projection = {
        "checked": False,
        "ok": None,
        "driftFiles": [],
        "valuesRedacted": True,
    }
    if not args.base_url:
        release_projection["checked"] = True
        try:
            _ledger, drift = projection_drift(site_root)
            release_projection["ok"] = not drift
            release_projection["driftFiles"] = drift
        except ReleaseProjectionError:
            release_projection["ok"] = False
    projection_failed = release_projection["checked"] and not release_projection["ok"]
    live_gate_failed = post_fetch_error is not None
    report = {
        "schemaVersion": "static_site.verifier.v4",
        "site": "MultiAgentMemory.com",
        "mode": "live" if args.base_url else "local",
        "siteRootKind": "selected_static_site",
        "baseUrl": CANONICAL_LIVE_BASE_URL if base_url_accepted else None,
        "requestedBaseUrlAccepted": base_url_accepted,
        "canonicalOriginRequired": bool(args.base_url),
        "canonicalOriginVerified": bool(
            args.base_url
            and base_url_accepted
            and items
            and all(item.get("canonicalFinalUrl") for item in items)
            and all(item.get("noRedirectVerified") for item in retired_items)
        ),
        "redirectsAllowed": False if args.base_url else None,
        "verificationPhase": args.phase,
        "verificationScope": verification_scope,
        "staticHtmlCompanion": True,
        "ok": not failures
        and not projection_failed
        and package_error is None
        and not live_gate_failed,
        "fileCount": len(items),
        "failureCount": len(failures)
        + int(projection_failed)
        + int(package_error is not None)
        + int(live_gate_failed),
        "nonClaimFileCount": sum(
            1 for item in items if item["file"] not in RELEASE_CLAIM_PATHS
        ),
        "claimFileCount": sum(
            1 for item in items if item["file"] in RELEASE_CLAIM_PATHS
        ),
        "exactPackageByteMatchCount": sum(
            1 for item in items if item.get("exactPackageByteMatch")
        ),
        "mediaTypeMatchCount": sum(1 for item in items if item.get("mediaTypeMatch")),
        "items": items,
        "retiredRouteCount": len(retired_items),
        "retiredRouteVerifiedCount": sum(
            1 for item in retired_items if item["verified"]
        ),
        "retiredRouteItems": retired_items,
        "failures": failures,
        "releaseProjection": release_projection,
        "valuesRedacted": True,
    }
    if activation_gate_before_fetch is not None:
        report["releaseActivationGateBeforeFetch"] = activation_gate_before_fetch
    if activation_gate_after_fetch is not None:
        report["releaseActivationGateAfterFetch"] = activation_gate_after_fetch
    report["identityCheckedBeforeFetch"] = bool(args.base_url and package_verification)
    report["identityRecheckedAfterFetch"] = package_rechecked_after_fetch
    if package_verification:
        report["releaseIdentity"] = package_verification["releaseIdentity"]
        report["sourceQualification"] = package_verification["sourceQualification"]
        report["package"] = package_verification["package"]
        qualification = package_verification["sourceQualification"]
        report["sourceTagPublished"] = bool(qualification["remoteTagPresent"])
        report["sourceTagIdentityVerified"] = bool(
            args.phase == FINAL_PHASE
            and qualification["tagSiteBytesVerified"]
            and qualification["annotatedTagNameVerified"]
        )
        report["claimsVerified"] = bool(args.phase == FINAL_PHASE and report["ok"])
        if report["ok"]:
            report["status"] = (
                "nonclaims_live_verified_preactivation"
                if args.phase == PREACTIVATION_PHASE
                else "full_live_verified_final"
            )
    if package_error:
        report["status"] = package_error
    elif post_fetch_error:
        report["status"] = post_fetch_error
    elif args.base_url and failures:
        report["status"] = "live_route_verification_failed"
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
