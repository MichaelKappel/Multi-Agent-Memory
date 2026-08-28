"""Build and verify an immutable MultiAgentMemory.com static-site package."""

import argparse
import hashlib
import io
import json
import os
import re
import stat
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

try:
    from .multiagentmemory_release_identity import (
        PREACTIVATION_PHASE,
        RELEASE_CLAIM_PATHS,
        RELEASE_PHASES,
        ReleaseIdentityError,
        build_content_manifest,
        build_release_identity,
        canonical_json_bytes,
        identity_summary,
        qualify_release_source,
        validate_release_identity,
    )
    from .render_multiagentmemory_release_history import (
        ReleaseProjectionError,
        project_release_surfaces,
        validate_ledger,
    )
except ImportError:
    from multiagentmemory_release_identity import (
        PREACTIVATION_PHASE,
        RELEASE_CLAIM_PATHS,
        RELEASE_PHASES,
        ReleaseIdentityError,
        build_content_manifest,
        build_release_identity,
        canonical_json_bytes,
        identity_summary,
        qualify_release_source,
        validate_release_identity,
    )
    from render_multiagentmemory_release_history import (
        ReleaseProjectionError,
        project_release_surfaces,
        validate_ledger,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SITE_ROOT = ROOT / "sites" / "multiagentmemory.com"
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
ZIP_FILE_MODE = 0o100644
ALLOWED_SITE_FILES = (
    ".well-known/ai-agent.json",
    ".well-known/mcp.json",
    "README.md",
    "ai-manifest.json",
    "ai.txt",
    "docs/api-reference.html",
    "docs/chatgpt-mcp.html",
    "docs/how-it-works.html",
    "docs/memory-boundary.html",
    "index.html",
    "llms.txt",
    "releases.json",
    "releases/index.html",
    "robots.txt",
    "sitemap.xml",
    "static/favicon.svg",
    "static/site.css",
)
EXCLUDED_PARTS = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "__pycache__",
    "node_modules",
}
EXCLUDED_NAMES = {".env", ".env.local", ".gitkeep", "desktop.ini", "thumbs.db"}
EXCLUDED_SUFFIXES = {".bak", ".cache", ".log", ".pyc", ".pyo", ".swp", ".tmp"}
ALLOWED_SITE_DIRS = tuple(
    sorted(
        {
            str(parent)
            for item in ALLOWED_SITE_FILES
            for parent in PurePosixPath(item).parents
            if str(parent) != "."
        }
    )
)
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(rb"https?://[^\s/:@]+:[^\s/@]+@", re.I),
    re.compile(rb"\b[A-Za-z]:[\\/][^\s<>'\"]+"),
    re.compile(rb"\bfile://[^\s<>'\"]+", re.I),
    re.compile(rb"/(?:Users|home|tmp|var/tmp)/[^\s<>'\"]+"),
)
ARCHIVE_MANIFEST_FIELDS = {
    "fileName",
    "manifestFileName",
    "format",
    "bytes",
    "sha256",
    "entryCount",
    "entryOrder",
    "entryTimestampUtc",
    "entryMode",
    "compression",
}
ALLOWLIST_MANIFEST_FIELDS = {"policy", "paths"}
SITE_MANIFEST_FIELDS = {
    "schemaVersion",
    "algorithm",
    "fileCount",
    "totalBytes",
    "aggregateSha256",
    "files",
    "containment",
    "valuesRedacted",
}
CONTAINMENT_MANIFEST_FIELDS = {
    "regularFilesOnly",
    "symlinksJunctionsReparsePointsAllowed",
    "resolvedWithinSelectedRoot",
}
FILE_MANIFEST_FIELDS = {"path", "bytes", "sha256"}


class SitePackageError(ValueError):
    """Raised when the package cannot be proven safe and deterministic."""


class SitePackageWriteError(SitePackageError):
    """Raised when paired artifact publication fails, with final-state truth."""

    def __init__(self, partial_state):
        super().__init__("paired package publication failed")
        self.partial_state = bool(partial_state)


def _require(condition, message):
    if not condition:
        raise SitePackageError(message)


def _require_exact_fields(value, expected, label):
    _require(
        isinstance(value, dict) and set(value) == expected, f"{label} fields changed"
    )


def _relative_text(path, site_root):
    try:
        relative = path.relative_to(site_root)
    except ValueError as exc:
        raise SitePackageError("site file escaped the selected root") from exc
    text = relative.as_posix()
    pure = PurePosixPath(text)
    _require(
        not pure.is_absolute() and ".." not in pure.parts and text not in {"", "."},
        "site path is unsafe",
    )
    return text


def _is_excluded(relative):
    lowered_parts = {part.lower() for part in relative.parts}
    name = relative.name.lower()
    return bool(
        lowered_parts.intersection(EXCLUDED_PARTS)
        or name in EXCLUDED_NAMES
        or relative.suffix.lower() in EXCLUDED_SUFFIXES
    )


def _is_reparse_point(path, result=None):
    result = result or path.lstat()
    if stat.S_ISLNK(result.st_mode) or path.is_symlink():
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if getattr(result, "st_file_attributes", 0) & reparse_flag:
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _assert_resolved_within(path, resolved_root):
    try:
        resolved = path.resolve(strict=True)
        common = os.path.commonpath((str(resolved_root), str(resolved)))
    except (OSError, RuntimeError, ValueError) as exc:
        raise SitePackageError("site path cannot be resolved safely") from exc
    _require(
        os.path.normcase(common) == os.path.normcase(str(resolved_root)),
        "site path resolves outside the selected root",
    )
    return resolved


def _assert_safe_component(path, resolved_root):
    try:
        result = path.lstat()
    except OSError as exc:
        raise SitePackageError("site path is unavailable") from exc
    _require(
        not _is_reparse_point(path, result),
        "site path contains a symlink, junction, or reparse point",
    )
    _assert_resolved_within(path, resolved_root)
    return result


def _scan_public_bytes(data):
    for pattern in SECRET_PATTERNS:
        if pattern.search(data):
            raise SitePackageError(
                "a package file matched a prohibited secret signature"
            )


def iter_site_files(site_root, require_complete=False):
    """Yield sorted allowlisted files and reject non-excluded unexpected files."""
    site_root = Path(site_root).absolute()
    try:
        root_result = site_root.lstat()
        resolved_root = site_root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SitePackageError("site root is unavailable") from exc
    _require(stat.S_ISDIR(root_result.st_mode), "site root is not a directory")
    _require(
        not _is_reparse_point(site_root, root_result),
        "site root is a symlink, junction, or reparse point",
    )
    found = {}
    pending = [site_root]
    while pending:
        directory = pending.pop()
        _assert_safe_component(directory, resolved_root)
        try:
            children = sorted(
                (Path(entry.path) for entry in os.scandir(directory)),
                key=lambda item: item.name,
            )
        except OSError as exc:
            raise SitePackageError("site directory cannot be read safely") from exc
        for path in children:
            result = _assert_safe_component(path, resolved_root)
            relative = path.relative_to(site_root)
            if _is_excluded(relative):
                continue
            relative_text = _relative_text(path, site_root)
            if stat.S_ISDIR(result.st_mode):
                _require(
                    relative_text in ALLOWED_SITE_DIRS,
                    "site root contains a non-allowlisted directory",
                )
                pending.append(path)
            elif stat.S_ISREG(result.st_mode):
                _require(
                    relative_text in ALLOWED_SITE_FILES,
                    "site root contains a non-allowlisted file",
                )
                found[relative_text] = path
            else:
                raise SitePackageError("site root contains a special file")
    if require_complete:
        _require(
            tuple(sorted(found)) == tuple(sorted(ALLOWED_SITE_FILES)),
            "site allowlist is incomplete",
        )
    for relative_text in sorted(found):
        yield found[relative_text], Path(PurePosixPath(relative_text))


def _manifest_from_entries(entries):
    content = build_content_manifest(
        (entry["relativePath"].as_posix(), entry["bytes"]) for entry in entries
    )
    return {
        "schemaVersion": "static_site.file_manifest.v1",
        **content,
        "containment": {
            "regularFilesOnly": True,
            "symlinksJunctionsReparsePointsAllowed": False,
            "resolvedWithinSelectedRoot": True,
        },
        "valuesRedacted": True,
    }


def capture_site_snapshot(site_root, require_complete=False):
    """Capture immutable upload bytes plus a deterministic public-safe manifest."""
    entries = []
    site_root = Path(site_root).absolute()
    resolved_root = site_root.resolve(strict=True)
    for path, relative in iter_site_files(site_root, require_complete=require_complete):
        before = _assert_safe_component(path, resolved_root)
        _require(
            stat.S_ISREG(before.st_mode), "site package entry is not a regular file"
        )
        data = path.read_bytes()
        after = _assert_safe_component(path, resolved_root)
        _require(
            stat.S_ISREG(after.st_mode), "site package entry changed type while reading"
        )
        _scan_public_bytes(data)
        entries.append({"path": path, "relativePath": relative, "bytes": data})
    return {"files": entries, "manifest": _manifest_from_entries(entries)}


def site_snapshot_matches(first, second):
    return first["manifest"] == second["manifest"]


def snapshot_projection_drift(snapshot):
    """Validate the authoritative ledger and derive projection drift in memory."""
    source_files = {
        entry["relativePath"].as_posix(): entry["bytes"] for entry in snapshot["files"]
    }
    if "releases.json" not in source_files:
        return None, []
    try:
        ledger = json.loads(source_files["releases.json"].decode("utf-8"))
        validate_ledger(ledger)
        expected = project_release_surfaces(source_files, ledger)
        expected_claim_paths = set(expected) | {"releases.json"}
        _require(
            expected_claim_paths == set(RELEASE_CLAIM_PATHS)
            and len(expected_claim_paths) == len(RELEASE_CLAIM_PATHS),
            "release projection claim order contract changed",
        )
    except (UnicodeError, json.JSONDecodeError, ReleaseProjectionError) as exc:
        raise SitePackageError("release ledger or projection input is invalid") from exc
    drift = sorted(
        relative
        for relative, expected_bytes in expected.items()
        if source_files.get(relative) != expected_bytes
    )
    return ledger, drift


def build_zip_bytes(snapshot):
    output = io.BytesIO()
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for entry in snapshot["files"]:
            relative_text = entry["relativePath"].as_posix()
            info = zipfile.ZipInfo(relative_text, FIXED_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = ZIP_FILE_MODE << 16
            info.flag_bits = 0x800
            archive.writestr(
                info,
                entry["bytes"],
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
    return output.getvalue()


def canonical_package_names(version):
    _require(
        isinstance(version, str)
        and re.fullmatch(
            r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", version
        ),
        "website version is not canonical SemVer",
    )
    stem = f"multiagentmemory-site-v{version}"
    return stem + ".zip", stem + ".manifest.json"


def build_package_manifest(
    snapshot,
    zip_bytes,
    package_name,
    package_manifest_name,
    ledger,
    ledger_sha256,
    source_identity,
):
    package_manifest = {
        "schemaVersion": "multiagentmemory.static_site_package_manifest.v2",
        "archive": {
            "fileName": package_name,
            "manifestFileName": package_manifest_name,
            "format": "zip",
            "bytes": len(zip_bytes),
            "sha256": hashlib.sha256(zip_bytes).hexdigest(),
            "entryCount": snapshot["manifest"]["fileCount"],
            "entryOrder": "forward-slash path ascending",
            "entryTimestampUtc": "1980-01-01T00:00:00Z",
            "entryMode": "0100644",
            "compression": "deflate-9",
        },
        "allowlist": {
            "policy": "exact paths; cache, temporary, environment, and runtime-state files excluded",
            "paths": list(ALLOWED_SITE_FILES),
        },
    }
    return build_release_identity(
        source_identity,
        ledger,
        ledger_sha256,
        snapshot["manifest"],
        package_manifest,
    )


def manifest_bytes(manifest):
    return canonical_json_bytes(manifest)


def expected_package(
    site_root, package_name=None, package_manifest_name=None, repo_root=ROOT
):
    snapshot = capture_site_snapshot(site_root, require_complete=True)
    ledger, drift = snapshot_projection_drift(snapshot)
    _require(
        ledger is not None and not drift, "release projections drift from releases.json"
    )
    canonical_package, canonical_manifest = canonical_package_names(
        ledger["currentProductionWebsiteVersion"]
    )
    package_name = package_name or canonical_package
    package_manifest_name = package_manifest_name or canonical_manifest
    _require(
        package_name == canonical_package,
        "package filename does not match the website version",
    )
    _require(
        package_manifest_name == canonical_manifest,
        "package manifest filename does not match the website version",
    )
    zip_bytes = build_zip_bytes(snapshot)
    ledger_bytes = next(
        entry["bytes"]
        for entry in snapshot["files"]
        if entry["relativePath"].as_posix() == "releases.json"
    )
    source_qualification = qualify_release_source(
        repo_root,
        site_root,
        ledger,
        ALLOWED_SITE_FILES,
        snapshot["manifest"],
        phase=PREACTIVATION_PHASE,
    )
    package_manifest = build_package_manifest(
        snapshot,
        zip_bytes,
        package_name,
        package_manifest_name,
        ledger,
        hashlib.sha256(ledger_bytes).hexdigest(),
        source_qualification["sourceIdentity"],
    )
    return snapshot, zip_bytes, package_manifest, source_qualification["qualification"]


def _snapshot_from_zip(archive):
    _require(archive.comment == b"", "archive comment changed")
    entries = []
    names = []
    for info in archive.infolist():
        _require(not info.is_dir(), "directory entries are not allowed")
        name = info.filename
        pure = PurePosixPath(name)
        _require(
            not pure.is_absolute()
            and ".." not in pure.parts
            and name == pure.as_posix(),
            "archive path is unsafe",
        )
        _require(name in ALLOWED_SITE_FILES, "archive has a non-allowlisted entry")
        _require(
            info.date_time == FIXED_ZIP_TIMESTAMP,
            "archive timestamp is not deterministic",
        )
        _require(
            info.compress_type == zipfile.ZIP_DEFLATED, "archive compression changed"
        )
        _require(info.create_system == 3, "archive platform metadata changed")
        _require(
            info.create_version == 20 and info.extract_version == 20,
            "archive version metadata changed",
        )
        _require(
            (info.external_attr >> 16) == ZIP_FILE_MODE, "archive file mode changed"
        )
        _require(
            info.flag_bits == 0 and info.extra == b"" and info.comment == b"",
            "archive optional metadata changed",
        )
        data = archive.read(info)
        _scan_public_bytes(data)
        names.append(name)
        entries.append({"path": None, "relativePath": Path(pure), "bytes": data})
    _require(names == sorted(names), "archive entries are not sorted")
    _require(len(names) == len(set(names)), "archive contains duplicate entries")
    _require(
        tuple(names) == tuple(sorted(ALLOWED_SITE_FILES)),
        "archive allowlist is incomplete",
    )
    return {"files": entries, "manifest": _manifest_from_entries(entries)}


def verify_package(
    package_path,
    manifest_path,
    expected_source_snapshot=None,
    *,
    phase,
    repo_root=ROOT,
    site_root=None,
):
    _require(phase in RELEASE_PHASES, "explicit release phase is required")
    package_path = Path(package_path)
    manifest_path = Path(manifest_path)
    try:
        zip_bytes = package_path.read_bytes()
        manifest_raw = manifest_path.read_bytes()
        _scan_public_bytes(manifest_raw)
        manifest = json.loads(manifest_raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SitePackageError("package or manifest is unavailable or invalid") from exc
    _require(
        manifest_raw == manifest_bytes(manifest),
        "package manifest is not canonical JSON",
    )
    validate_release_identity(manifest, zip_bytes)
    version = manifest.get("websiteVersion")
    canonical_package, canonical_manifest = canonical_package_names(version)
    package_manifest = manifest["packageManifest"]
    archive_manifest = package_manifest["archive"]
    release_manifest = manifest["releaseLedger"]
    allowlist_manifest = package_manifest["allowlist"]
    site_manifest = manifest["siteManifest"]
    _require_exact_fields(archive_manifest, ARCHIVE_MANIFEST_FIELDS, "archive manifest")
    _require_exact_fields(
        allowlist_manifest, ALLOWLIST_MANIFEST_FIELDS, "allowlist manifest"
    )
    _require_exact_fields(site_manifest, SITE_MANIFEST_FIELDS, "site manifest")
    _require_exact_fields(
        site_manifest.get("containment"),
        CONTAINMENT_MANIFEST_FIELDS,
        "containment manifest",
    )
    _require(
        isinstance(site_manifest.get("files"), list), "site manifest files changed"
    )
    for item in site_manifest["files"]:
        _require_exact_fields(item, FILE_MANIFEST_FIELDS, "site manifest file")
    _require(
        package_path.name == canonical_package,
        "package filename does not match the website version",
    )
    _require(
        manifest_path.name == canonical_manifest,
        "package manifest filename does not match the website version",
    )
    _require(
        archive_manifest.get("fileName") == canonical_package,
        "package file name does not match manifest",
    )
    _require(
        archive_manifest.get("manifestFileName") == canonical_manifest,
        "package manifest relationship changed",
    )
    _require(
        archive_manifest.get("bytes") == len(zip_bytes),
        "package byte count does not match manifest",
    )
    _require(
        archive_manifest.get("sha256") == hashlib.sha256(zip_bytes).hexdigest(),
        "package hash does not match manifest",
    )
    _require(archive_manifest.get("format") == "zip", "package format changed")
    _require(
        archive_manifest.get("entryOrder") == "forward-slash path ascending",
        "package entry order contract changed",
    )
    _require(
        archive_manifest.get("entryTimestampUtc") == "1980-01-01T00:00:00Z",
        "package timestamp contract changed",
    )
    _require(
        archive_manifest.get("entryMode") == "0100644", "package mode contract changed"
    )
    _require(
        archive_manifest.get("compression") == "deflate-9",
        "package compression contract changed",
    )
    _require(
        tuple(allowlist_manifest.get("paths", ())) == ALLOWED_SITE_FILES,
        "package allowlist changed",
    )
    _require(
        allowlist_manifest.get("policy")
        == "exact paths; cache, temporary, environment, and runtime-state files excluded",
        "package allowlist policy changed",
    )
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as archive:
            snapshot = _snapshot_from_zip(archive)
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise SitePackageError("package ZIP is invalid") from exc
    _require(
        zip_bytes == build_zip_bytes(snapshot), "package ZIP bytes are not canonical"
    )
    _require(
        snapshot["manifest"] == site_manifest, "package contents do not match manifest"
    )
    _require(
        archive_manifest.get("entryCount") == snapshot["manifest"]["fileCount"],
        "package entry count changed",
    )
    ledger, packaged_drift = snapshot_projection_drift(snapshot)
    _require(
        ledger is not None and not packaged_drift,
        "packaged release projections drift from releases.json",
    )
    ledger_entry = next(
        entry
        for entry in snapshot["files"]
        if entry["relativePath"].as_posix() == "releases.json"
    )
    _require(
        ledger["currentProductionWebsiteVersion"] == version,
        "package website version differs from its ledger",
    )
    _require(
        release_manifest.get("currentProductionWebsiteVersion") == version,
        "manifest website version relationship changed",
    )
    _require(
        release_manifest.get("releaseCount") == ledger["releaseCount"],
        "manifest release count differs from its ledger",
    )
    _require(
        release_manifest.get("sha256")
        == hashlib.sha256(ledger_entry["bytes"]).hexdigest(),
        "manifest release hash differs from its ledger",
    )
    site_root = (
        Path(site_root)
        if site_root is not None
        else Path(repo_root) / "sites" / "multiagentmemory.com"
    )
    source_qualification = qualify_release_source(
        repo_root,
        site_root,
        ledger,
        ALLOWED_SITE_FILES,
        snapshot["manifest"],
        phase=phase,
        expected_commit_sha=manifest["source"]["commitSha"],
        expected_remote_main_commit_sha=manifest["source"][
            "preactivationRemoteMainCommitSha"
        ],
    )
    _require(
        source_qualification["sourceIdentity"] == manifest["source"],
        "manifest source identity changed",
    )
    if expected_source_snapshot is not None:
        _require(
            site_snapshot_matches(snapshot, expected_source_snapshot),
            "package does not match the frozen source snapshot",
        )
    release_identity = identity_summary(manifest, manifest_raw)
    return {
        "files": snapshot["files"],
        "manifest": snapshot["manifest"],
        "releaseIdentity": release_identity,
        "releaseIdentityManifest": manifest,
        "sourceQualification": source_qualification["qualification"],
        "package": {
            "fileName": package_path.name,
            "bytes": len(zip_bytes),
            "sha256": hashlib.sha256(zip_bytes).hexdigest(),
            "releaseIdentityManifestSha256": hashlib.sha256(manifest_raw).hexdigest(),
            "packageManifestSha256": manifest["packageManifestSha256"],
            "websiteVersion": manifest.get("websiteVersion"),
            "valuesRedacted": True,
        },
    }


def _artifact_matches(path, original_bytes):
    try:
        if original_bytes is None:
            return not path.exists()
        return path.is_file() and path.read_bytes() == original_bytes
    except OSError:
        return False


def publish_package_pair(
    package_path,
    manifest_path,
    zip_bytes,
    package_manifest,
    source_snapshot,
    *,
    repo_root=ROOT,
    site_root=DEFAULT_SITE_ROOT,
):
    """Stage, verify, and transactionally publish the paired artifacts."""
    package_path = Path(package_path).absolute()
    manifest_path = Path(manifest_path).absolute()
    _require(package_path != manifest_path, "package and manifest paths must differ")
    package_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    original_package = package_path.read_bytes() if package_path.exists() else None
    original_manifest = manifest_path.read_bytes() if manifest_path.exists() else None
    package_stage_root = Path(
        tempfile.mkdtemp(
            prefix=".multiagentmemory-package-stage-", dir=package_path.parent
        )
    )
    manifest_stage_root = Path(
        tempfile.mkdtemp(
            prefix=".multiagentmemory-manifest-stage-", dir=manifest_path.parent
        )
    )
    staged_package = package_stage_root / package_path.name
    staged_manifest = manifest_stage_root / manifest_path.name
    package_backup = package_stage_root / "previous-package.backup"
    manifest_backup = manifest_stage_root / "previous-manifest.backup"
    package_published = False
    manifest_published = False
    try:
        staged_package.write_bytes(zip_bytes)
        staged_manifest.write_bytes(manifest_bytes(package_manifest))
        verify_package(
            staged_package,
            staged_manifest,
            source_snapshot,
            phase=PREACTIVATION_PHASE,
            repo_root=repo_root,
            site_root=site_root,
        )
        try:
            if package_path.exists():
                os.replace(package_path, package_backup)
            if manifest_path.exists():
                os.replace(manifest_path, manifest_backup)
            os.replace(staged_package, package_path)
            package_published = True
            os.replace(staged_manifest, manifest_path)
            manifest_published = True
            return verify_package(
                package_path,
                manifest_path,
                source_snapshot,
                phase=PREACTIVATION_PHASE,
                repo_root=repo_root,
                site_root=site_root,
            )
        except Exception as exc:
            try:
                if package_published and package_path.exists():
                    package_path.unlink()
                if manifest_published and manifest_path.exists():
                    manifest_path.unlink()
                if package_backup.exists():
                    os.replace(package_backup, package_path)
                if manifest_backup.exists():
                    os.replace(manifest_backup, manifest_path)
            except Exception:
                pass
            partial_state = not (
                _artifact_matches(package_path, original_package)
                and _artifact_matches(manifest_path, original_manifest)
            )
            raise SitePackageWriteError(partial_state) from exc
    finally:
        shutil.rmtree(package_stage_root, ignore_errors=True)
        shutil.rmtree(manifest_stage_root, ignore_errors=True)


def _report_base(mode):
    return {
        "schemaVersion": "multiagentmemory.static_site_package_report.v3",
        "mode": mode,
        "safeNoOp": mode != "write",
        "written": False,
        "valuesRedacted": True,
    }


def _emit(report, args):
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(report, indent=2, sort_keys=True))


def build_parser():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--inspect",
        action="store_true",
        help="prove clean preactivation source and absent required tags without writing",
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help="write a package only when the expected site hash matches",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="compare an existing package with the current source",
    )
    mode.add_argument(
        "--verify",
        action="store_true",
        help="requalify an existing package in explicit preactivation or final phase",
    )
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--site-root", default=str(DEFAULT_SITE_ROOT))
    parser.add_argument("--phase", choices=sorted(RELEASE_PHASES))
    parser.add_argument("--package")
    parser.add_argument("--manifest")
    parser.add_argument("--expected-site-aggregate-sha256")
    parser.add_argument("--json-out")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    mode_name = (
        "inspect"
        if args.inspect
        else "write"
        if args.write
        else "check"
        if args.check
        else "verify"
    )
    report = _report_base(mode_name)
    try:
        if args.phase is None:
            raise ReleaseIdentityError("release_phase_required")
        if not args.verify and args.phase != PREACTIVATION_PHASE:
            raise ReleaseIdentityError("package_creation_requires_preactivation")
        report["releasePhase"] = args.phase
        if args.verify:
            _require(
                args.package and args.manifest, "verify requires package and manifest"
            )
            verified = verify_package(
                args.package,
                args.manifest,
                phase=args.phase,
                repo_root=args.repo_root,
                site_root=args.site_root,
            )
            report.update(
                {
                    "status": "verified",
                    "ok": True,
                    "siteManifest": verified["manifest"],
                    "releaseIdentity": verified["releaseIdentity"],
                    "sourceQualification": verified["sourceQualification"],
                    "package": verified["package"],
                }
            )
        else:
            package_name = Path(args.package).name if args.package else None
            package_manifest_name = Path(args.manifest).name if args.manifest else None
            snapshot, expected_zip, expected_manifest, source_qualification = (
                expected_package(
                    Path(args.site_root),
                    package_name,
                    package_manifest_name,
                    args.repo_root,
                )
            )
            report["siteManifest"] = snapshot["manifest"]
            report["websiteVersion"] = expected_manifest["websiteVersion"]
            report["releaseLedger"] = expected_manifest["releaseLedger"]
            report["releaseIdentity"] = identity_summary(
                expected_manifest, manifest_bytes(expected_manifest)
            )
            report["sourceQualification"] = source_qualification
            report["expectedPackageSha256"] = expected_manifest["packageManifest"][
                "archive"
            ]["sha256"]
            if args.inspect:
                report.update({"status": "inspected", "ok": True})
            else:
                _require(
                    args.package and args.manifest,
                    "write and check require package and manifest",
                )
                if args.write:
                    _require(
                        args.expected_site_aggregate_sha256
                        == snapshot["manifest"]["aggregateSha256"],
                        "write requires the exact inspected site aggregate",
                    )
                    package_path = Path(args.package)
                    manifest_path = Path(args.manifest)
                    verified = publish_package_pair(
                        package_path,
                        manifest_path,
                        expected_zip,
                        expected_manifest,
                        snapshot,
                        repo_root=args.repo_root,
                        site_root=args.site_root,
                    )
                    report.update(
                        {
                            "status": "written",
                            "ok": True,
                            "written": True,
                            "safeNoOp": False,
                            "releaseIdentity": verified["releaseIdentity"],
                            "sourceQualification": verified["sourceQualification"],
                            "package": verified["package"],
                        }
                    )
                else:
                    package_path = Path(args.package)
                    manifest_path = Path(args.manifest)
                    _require(
                        package_path.read_bytes() == expected_zip,
                        "package differs from deterministic source output",
                    )
                    _require(
                        manifest_path.read_bytes() == manifest_bytes(expected_manifest),
                        "package manifest differs from deterministic source output",
                    )
                    verified = verify_package(
                        package_path,
                        manifest_path,
                        snapshot,
                        phase=PREACTIVATION_PHASE,
                        repo_root=args.repo_root,
                        site_root=args.site_root,
                    )
                    report.update(
                        {
                            "status": "matched",
                            "ok": True,
                            "releaseIdentity": verified["releaseIdentity"],
                            "sourceQualification": verified["sourceQualification"],
                            "package": verified["package"],
                        }
                    )
    except SitePackageWriteError as exc:
        report.update(
            {
                "status": "write_failed_partial_possible"
                if exc.partial_state
                else "write_failed_rolled_back",
                "ok": False,
                "errorType": exc.__class__.__name__,
                "partialArtifactState": exc.partial_state,
                "safeNoOp": not exc.partial_state,
                "written": exc.partial_state,
            }
        )
    except ReleaseIdentityError as exc:
        report.update(
            {
                "status": exc.code,
                "ok": False,
                "errorType": exc.__class__.__name__,
                "safeNoOp": True,
            }
        )
    except (OSError, UnicodeError, SitePackageError) as exc:
        report.update(
            {
                "status": "verification_failed",
                "ok": False,
                "errorType": exc.__class__.__name__,
                "safeNoOp": True,
            }
        )
    _emit(report, args)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
