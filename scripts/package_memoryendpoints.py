import argparse
import json
import os
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
PACKAGE = DIST / "MemoryEndpoints.com-Production.zip"
EXCLUDE_DIRS = {".git", ".github", ".uai", "__pycache__", ".pytest_cache", "var", "dist", ".local-secrets"}
EXCLUDE_PATH_PREFIXES = {"docs/prompts"}
EXCLUDE_NAMES = {"ftp_Deploy.txt", ".gitattributes", ".gitignore", ".gitkeep"}
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


def iter_files():
    for path in ROOT.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(ROOT)
        rel_text = str(rel).replace(os.sep, "/")
        parts = set(rel.parts)
        if parts & EXCLUDE_DIRS:
            continue
        if any(rel_text == prefix or rel_text.startswith(prefix + "/") for prefix in EXCLUDE_PATH_PREFIXES):
            continue
        if path.name in EXCLUDE_NAMES or path.suffix == ".pyc":
            continue
        if path.suffix.lower() in EXCLUDE_SUFFIXES:
            continue
        if path.name.endswith(EXCLUDE_NAME_SUFFIXES):
            continue
        yield path, rel


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--json-out")
    args = parser.parse_args(argv)

    files = list(iter_files())
    report = {
        "schemaVersion": "memoryendpoints.package_plan.v1",
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
        "thirdPartyRuntimeDependencies": False,
    }
    if not args.check_only:
        DIST.mkdir(exist_ok=True)
        with zipfile.ZipFile(str(PACKAGE), "w", zipfile.ZIP_DEFLATED) as archive:
            for path, rel in files:
                archive.write(str(path), str(rel).replace(os.sep, "/"))
        report["written"] = True
        report["bytes"] = PACKAGE.stat().st_size
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
