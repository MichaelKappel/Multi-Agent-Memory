import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
PACKAGE = DIST / "MemoryEndpoints.com-Production.zip"
BUILD_INFO = ROOT / "memoryendpoints" / "build_info.generated.json"
EXCLUDE_DIRS = {
    ".git",
    ".github",
    ".vs",
    ".uai",
    "__pycache__",
    ".pytest_cache",
    "var",
    "dist",
    ".local-secrets",
    "reports",
}
EXCLUDE_PATH_PREFIXES = {
    "agent-file-handoff/Archive",
    "agent-file-handoff/Content",
    "agent-file-handoff/Improvement",
    "docs/prompts",
    "docs/reports",
}
EXCLUDE_NAMES = {"ftp_Deploy.txt", ".gitattributes", ".gitignore", ".gitkeep", "workspace.uai"}
EXCLUDE_SUFFIXES = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".pyc",
    ".pyo",
    ".tmp",
    ".bak",
    ".log",
}
EXCLUDE_NAME_SUFFIXES = (
    "-journal",
    ".sqlite-journal",
    ".sqlite3-journal",
    ".db-journal",
    ".out.log",
    ".err.log",
)
GENERATED_SOURCE_PATHS = {"memoryendpoints/build_info.generated.json"}


class SourceRevisionError(RuntimeError):
    """Raised when Git cannot prove which revision the package represents."""


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def git_head_sha():
    completed = run_git(["rev-parse", "--verify", "HEAD"])
    source_sha = completed.stdout.strip()
    if not source_sha:
        raise SourceRevisionError("Git HEAD is unavailable")
    return source_sha


def run_git(arguments):
    try:
        completed = subprocess.run(
            ["git"] + list(arguments),
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
        )
    except OSError as exc:
        raise SourceRevisionError("Git inspection could not run") from exc
    if completed.returncode != 0:
        raise SourceRevisionError("Git inspection failed")
    return completed


def git_status_paths():
    completed = run_git(["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    records = completed.stdout.split("\0")
    paths = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if len(record) < 4:
            raise SourceRevisionError("Git status output was malformed")
        status = record[:2]
        paths.append(record[3:].replace("\\", "/"))
        if "R" in status or "C" in status:
            if index >= len(records) or not records[index]:
                raise SourceRevisionError("Git rename status output was malformed")
            paths.append(records[index].replace("\\", "/"))
            index += 1
    return paths


def git_tracked_paths():
    completed = run_git(["ls-files", "-z"])
    return {path.replace("\\", "/") for path in completed.stdout.split("\0") if path}


def should_include_rel(rel):
    rel_text = str(rel).replace(os.sep, "/")
    parts = set(Path(rel_text).parts)
    name = Path(rel_text).name
    suffix = Path(rel_text).suffix.lower()
    if parts & EXCLUDE_DIRS:
        return False
    if any(rel_text == prefix or rel_text.startswith(prefix + "/") for prefix in EXCLUDE_PATH_PREFIXES):
        return False
    if name in EXCLUDE_NAMES or suffix == ".pyc":
        return False
    if suffix in EXCLUDE_SUFFIXES:
        return False
    if name.endswith(EXCLUDE_NAME_SUFFIXES):
        return False
    return True


def source_content_hash(files):
    digest = hashlib.sha256()
    for path, rel in sorted(files, key=lambda item: str(item[1]).replace(os.sep, "/")):
        if path == BUILD_INFO:
            continue
        rel_text = str(rel).replace(os.sep, "/")
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        digest.update(rel_text.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def packaged_dirty_paths(files):
    included = {str(rel).replace(os.sep, "/") for _path, rel in files}
    tracked = git_tracked_paths()
    dirty = set()
    for rel_text in git_status_paths():
        if not rel_text or rel_text in GENERATED_SOURCE_PATHS:
            continue
        if rel_text in included or should_include_rel(Path(rel_text)):
            dirty.add(rel_text)

    # `git status` intentionally hides ignored files. Any included file that is
    # neither tracked nor a known generated artifact would otherwise evade the
    # exact-revision gate (for example, an ignored .env file).
    dirty.update(included - tracked - GENERATED_SOURCE_PATHS)
    expected_included = {path for path in tracked if should_include_rel(Path(path))}
    dirty.update(expected_included - included)
    return sorted(dirty)


def inspect_current_source(files=None):
    files = list(iter_files()) if files is None else list(files)
    source_sha = git_head_sha()
    dirty_paths = packaged_dirty_paths(files)
    content_hash = source_content_hash(files)
    if git_head_sha() != source_sha:
        raise SourceRevisionError("Git HEAD changed during source inspection")
    return {
        "files": files,
        "sourceSha": source_sha,
        "contentHash": content_hash,
        "dirtyPaths": dirty_paths,
    }


def capture_files(files):
    return [(str(rel).replace(os.sep, "/"), path.read_bytes()) for path, rel in files]


def captured_source_content_hash(snapshot):
    digest = hashlib.sha256()
    for rel_text, body in sorted(snapshot, key=lambda item: item[0]):
        if rel_text in GENERATED_SOURCE_PATHS:
            continue
        digest.update(rel_text.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(body).hexdigest().encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_build_info(content_hash, dirty_paths, source_sha=None, write=True):
    source_sha = source_sha or git_head_sha()
    payload = {
        "schemaVersion": "memoryendpoints.build_info.v1",
        "sourceSha": source_sha,
        "sourceShaShort": source_sha[:12],
        "sourceRepository": "https://github.com/MichaelKappel/Multi-Agent-Memory",
        "generatedAt": utc_now(),
        "generatedBy": "scripts/package_memoryendpoints.py",
        "contentHash": content_hash,
        "sourceWorktreeDirty": bool(dirty_paths),
        "sourceDirtyPathCount": len(dirty_paths),
        "valuesRedacted": True,
    }
    if write:
        BUILD_INFO.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def write_current_build_info():
    source = inspect_current_source()
    return write_build_info(
        source["contentHash"],
        source["dirtyPaths"],
        source["sourceSha"],
        write=not source["dirtyPaths"],
    )


def iter_files():
    for path in ROOT.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(ROOT)
        if not should_include_rel(rel):
            continue
        yield path, rel


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--json-out")
    args = parser.parse_args(argv)

    try:
        source = inspect_current_source()
    except SourceRevisionError:
        report = {
            "schemaVersion": "memoryendpoints.package_plan.v1",
            "reportScope": "point_in_time_snapshot",
            "status": "source_revision_unavailable",
            "checkOnly": args.check_only,
            "sourceRevisionVerified": False,
            "safeNoOp": True,
            "written": False,
            "valuesRedacted": True,
        }
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1

    dirty_paths = source["dirtyPaths"]
    build_info = write_build_info(
        source["contentHash"],
        dirty_paths,
        source["sourceSha"],
        write=not dirty_paths,
    )
    files = list(iter_files())
    report = {
        "schemaVersion": "memoryendpoints.package_plan.v1",
        "reportScope": "point_in_time_snapshot",
        "status": "ready",
        "checkOnly": args.check_only,
        "fileCount": len(files),
        "package": str(PACKAGE),
        "excludesSecrets": True,
        "excludesLocalRuntimeState": True,
        "excludedDirs": sorted(EXCLUDE_DIRS),
        "excludedNames": sorted(EXCLUDE_NAMES),
        "excludedPathPrefixes": sorted(EXCLUDE_PATH_PREFIXES),
        "excludedSuffixes": sorted(EXCLUDE_SUFFIXES),
        "sourceContentHash": build_info["contentHash"],
        "sourceWorktreeDirty": bool(dirty_paths),
        "sourceDirtyPathCount": len(dirty_paths),
        "sourceDirtyPaths": dirty_paths[:25],
        "thirdPartyRuntimeDependencies": False,
        "thirdPartyRuntimeDependencyNames": [],
        "packageManagedThirdPartyRuntimeDependencies": False,
        "hostProvidedRuntimeAdapters": [
            {
                "name": "mysql_python_driver",
                "source": "host_environment",
                "packagedWithRepository": False,
                "requiredWhen": "MEMORYENDPOINTS_STORE_BACKEND=mysql",
            }
        ],
        "productionDatabaseBackend": "mysql_or_mariadb_verified_when_host_adapter_available",
        "build": {
            "sourceSha": build_info["sourceSha"],
            "sourceShaShort": build_info["sourceShaShort"],
            "contentHash": build_info["contentHash"],
            "sourceWorktreeDirty": build_info["sourceWorktreeDirty"],
            "sourceDirtyPathCount": build_info["sourceDirtyPathCount"],
            "buildInfoFile": "memoryendpoints/build_info.generated.json",
            "valuesRedacted": True,
        },
        "sourceRevisionVerified": not dirty_paths,
        "safeNoOp": bool(args.check_only),
    }
    if dirty_paths:
        report["status"] = "dirty_packaged_source"
        report["safeNoOp"] = True
        report["written"] = False
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1

    try:
        snapshot = capture_files(files)
        snapshot_content_hash = captured_source_content_hash(snapshot)
        final_source = inspect_current_source()
    except (OSError, SourceRevisionError):
        report["status"] = "source_changed_during_packaging"
        report["sourceRevisionVerified"] = False
        report["safeNoOp"] = True
        report["written"] = False
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    report["snapshotContentHash"] = snapshot_content_hash
    if (
        snapshot_content_hash != build_info["contentHash"]
        or final_source["sourceSha"] != build_info["sourceSha"]
        or final_source["dirtyPaths"]
        or final_source["contentHash"] != build_info["contentHash"]
    ):
        report["status"] = "source_changed_during_packaging"
        report["sourceRevisionVerified"] = False
        report["safeNoOp"] = True
        report["written"] = False
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    if not args.check_only:
        DIST.mkdir(exist_ok=True)
        with zipfile.ZipFile(str(PACKAGE), "w", zipfile.ZIP_DEFLATED) as archive:
            for rel_text, body in snapshot:
                archive.writestr(rel_text, body)
        report["written"] = True
        report["safeNoOp"] = False
        report["bytes"] = PACKAGE.stat().st_size
        report["packageSha256"] = file_sha256(PACKAGE)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
