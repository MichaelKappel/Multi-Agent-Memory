import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memoryendpoints.storage import SQLiteStore


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(ROOT / "var" / "matm_store.json"))
    parser.add_argument("--sqlite-path", default=str(ROOT / "var" / "matm_store.sqlite3"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    source = Path(args.source)
    report = {
        "schemaVersion": "memoryendpoints.store_migration.v1",
        "sourceExists": source.exists(),
        "dryRun": args.dry_run,
        "valuesRedacted": True,
    }
    if not source.exists():
        report["status"] = "missing_source"
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1

    with source.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    report["workspaceCount"] = len(data.get("workspaces", {}))
    report["memoryEventCount"] = len(data.get("memoryEvents", []))
    report["messageCount"] = len(data.get("messages", []))
    report["notificationCount"] = len(data.get("notifications", []))
    report["receiptCount"] = len(data.get("receipts", []))
    if args.dry_run:
        report["status"] = "ready"
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    SQLiteStore(args.sqlite_path)._save(data)
    with sqlite3.connect(args.sqlite_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    report["relationalTablesPresent"] = sorted(name for name in tables if name.startswith("matm_"))
    report["status"] = "migrated"
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
