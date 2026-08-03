import argparse
import fnmatch
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "reports" / "repository-boundary-audit.json"

CANONICAL_REPOSITORY_NAME = "Multi-Agent-Memory"
CANONICAL_REPOSITORY_URL = "https://github.com/MichaelKappel/Multi-Agent-Memory"
REPOSITORY_IDENTITY_MARKERS = (
    ("README.md", "# Multi-Agent Memory"),
    ("LICENSE", "Multi-Agent Memory Private Intranet License 1.0"),
    ("NOTICE", "Multi-Agent Memory Notice"),
)

DUPLICATE_PRODUCT_SITE_NAMES = {
    "DualSiteOperator-Publish",
    "MemoryEndpoints.com-Publish",
    "MultiAgentMemory.com",
    "MultiAgentMemory.com-Publish",
    "deployment-backups",
}

ROOT_RUNTIME_PATTERNS = (
    "*.db",
    "*.log",
    "*.sqlite",
    "*.sqlite3",
    "*-journal",
    "devserver-*.err.log",
    "devserver-*.out.log",
    "sqlite-write-check*",
)


def utc_now():
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def posix_path(path):
    return str(path).replace("\\", "/")


def immediate_drive_root(product_root):
    anchor = Path(product_root).anchor
    if anchor:
        return Path(anchor)
    return Path(product_root).resolve().parent


def duplicate_product_site_folders(drive_root):
    if not drive_root.exists():
        return []
    found = []
    for child in drive_root.iterdir():
        if child.is_dir() and child.name in DUPLICATE_PRODUCT_SITE_NAMES:
            found.append(posix_path(child))
    return sorted(found)


def repository_root_runtime_artifacts(product_root):
    if not product_root.exists():
        return []
    artifacts = []
    for child in product_root.iterdir():
        if not child.is_file():
            continue
        if any(
            fnmatch.fnmatch(child.name, pattern) for pattern in ROOT_RUNTIME_PATTERNS
        ):
            artifacts.append(posix_path(child.relative_to(product_root)))
    return sorted(artifacts)


def invalid_repository_identity_markers(product_root):
    invalid_markers = []
    for relative_path, expected_first_line in REPOSITORY_IDENTITY_MARKERS:
        marker_path = product_root / relative_path
        try:
            with marker_path.open("r", encoding="utf-8") as marker_file:
                actual_first_line = marker_file.readline().rstrip("\r\n")
        except (OSError, UnicodeError):
            invalid_markers.append(relative_path)
            continue
        if actual_first_line != expected_first_line:
            invalid_markers.append(relative_path)
    return invalid_markers


def build_report(product_root=ROOT, drive_root=None):
    product_root = Path(product_root).resolve()
    drive_root = (
        Path(drive_root).resolve()
        if drive_root
        else immediate_drive_root(product_root).resolve()
    )
    companion_root = product_root / "sites" / "multiagentmemory.com"
    duplicate_folders = duplicate_product_site_folders(drive_root)
    root_runtime_artifacts = repository_root_runtime_artifacts(product_root)
    invalid_identity_markers = invalid_repository_identity_markers(product_root)
    repository_identity_markers_valid = not invalid_identity_markers
    source_package_present = (product_root / "memoryendpoints").is_dir()
    companion_root_present = companion_root.is_dir()
    ok = bool(
        repository_identity_markers_valid
        and source_package_present
        and companion_root_present
        and not duplicate_folders
        and not root_runtime_artifacts
    )
    return {
        "schemaVersion": "multiagentmemory.repository_boundary_audit.v3",
        "generatedAt": utc_now(),
        "repositoryRoot": posix_path(product_root),
        "scannedImmediateDriveRoot": posix_path(drive_root),
        "canonicalRepositoryName": CANONICAL_REPOSITORY_NAME,
        "canonicalRepositoryUrl": CANONICAL_REPOSITORY_URL,
        "checkoutDirectoryName": product_root.name,
        "repositoryIdentityMarkerPaths": [
            path for path, _ in REPOSITORY_IDENTITY_MARKERS
        ],
        "invalidRepositoryIdentityMarkerPaths": invalid_identity_markers,
        "repositoryIdentityMarkersValid": repository_identity_markers_valid,
        "companionDocumentationRoot": posix_path(companion_root),
        "sourcePackageRoot": "memoryendpoints/",
        "sourcePackageRootIsExpectedRuntimePackage": source_package_present,
        "companionDocumentationRootPresent": companion_root_present,
        "duplicateProductSiteFolderNames": sorted(DUPLICATE_PRODUCT_SITE_NAMES),
        "duplicateProductSiteFoldersFound": duplicate_folders,
        "repositoryRootRuntimeArtifactsFound": root_runtime_artifacts,
        "truthBoundary": {
            "multiAgentMemoryRepositorySourceOfTruth": posix_path(product_root),
            "repositoryIdentityDependsOnCheckoutDirectoryName": False,
            "multiAgentMemoryIsCompanionDocsInsideRepo": companion_root_present,
            "neuralWikisIsConceptSourceOnly": True,
            "rawPrivateFolderNamesOrSecretsIncluded": False,
        },
        "ok": ok,
        "valuesRedacted": True,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--drive-root")
    parser.add_argument("--product-root")
    parser.add_argument("--json-out")
    args = parser.parse_args(argv)

    product_root = Path(args.product_root) if args.product_root else ROOT
    drive_root = Path(args.drive_root) if args.drive_root else None
    report = build_report(product_root=product_root, drive_root=drive_root)
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
