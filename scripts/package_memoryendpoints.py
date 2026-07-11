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


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
    return "unknown"


def git_status_lines():
    completed = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
    )
    if completed.returncode != 0:
        return []
    return [line for line in completed.stdout.splitlines() if line.strip()]


def status_path(line):
    text = line[3:] if len(line) > 3 else ""
    if " -> " in text:
        text = text.split(" -> ", 1)[1]
    return text.strip().strip('"').replace("\\", "/")


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
    generated = {"memoryendpoints/build_info.generated.json"}
    dirty = []
    for line in git_status_lines():
        rel_text = status_path(line)
        if not rel_text or rel_text in generated:
            continue
        if rel_text in included or should_include_rel(Path(rel_text)):
            dirty.append(rel_text)
    return sorted(set(dirty))


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_build_info(content_hash, dirty_paths):
    source_sha = git_head_sha()
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
    BUILD_INFO.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def write_current_build_info():
    files = list(iter_files())
    dirty_paths = packaged_dirty_paths(files)
    return write_build_info(source_content_hash(files), dirty_paths)


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

    files = list(iter_files())
    dirty_paths = packaged_dirty_paths(files)
    build_info = write_build_info(source_content_hash(files), dirty_paths)
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
    }
    if not args.check_only:
        DIST.mkdir(exist_ok=True)
        with zipfile.ZipFile(str(PACKAGE), "w", zipfile.ZIP_DEFLATED) as archive:
            for path, rel in files:
                archive.write(str(path), str(rel).replace(os.sep, "/"))
        report["written"] = True
        report["bytes"] = PACKAGE.stat().st_size
        report["packageSha256"] = file_sha256(PACKAGE)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
