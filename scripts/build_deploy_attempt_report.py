import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "docs" / "reports"


def load(name):
    path = REPORTS / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run-report", default="deploy-dry-run-latest.json")
    parser.add_argument("--live-report", default="deploy-live-attempt-latest.json")
    parser.add_argument("--json-out", default="deploy-attempt-20260709.json")
    args = parser.parse_args(argv)

    dry = load(args.dry_run_report) or {}
    live = load(args.live_report) or {}
    dogfood = load("dogfood-memory-run.json") or {}
    live_status = live.get("status")
    live_uploaded = live.get("uploadedCount", 0)
    latest_live = live_status == "uploaded" and live_uploaded > 0
    report = {
        "schemaVersion": "memoryendpoints.deploy_attempt.v1",
        "generatedAt": "2026-07-09",
        "target": "MemoryEndpoints.com FTP login root",
        "remoteDir": ".",
        "dryRun": {
            "status": dry.get("status"),
            "plannedUploadCount": dry.get("plannedUploadCount"),
            "packageExists": dry.get("packageExists"),
            "valuesRedacted": True,
        },
        "liveAttempt": {
            "status": live_status,
            "errorType": live.get("errorType"),
            "failedPhase": live.get("failedPhase"),
            "uploadedCount": live_uploaded,
            "safeNoOp": live.get("safeNoOp", live_uploaded == 0),
            "valuesRedacted": True,
        },
        "secretBoundary": {
            "hostPrinted": False,
            "userPrinted": False,
            "passwordPrinted": False,
            "credentialValuesPrinted": False,
        },
        "claimBoundary": {
            "newCodeLiveDeployed": latest_live,
            "liveDogfoodVerified": bool(dogfood.get("liveDogfoodVerified")),
            "localDogfoodVerified": bool(dogfood.get("localDogfoodVerified")),
            "blocker": None if latest_live else "FTPS login rejected before upload; credential or server access must be refreshed outside the repository.",
        },
        "valuesRedacted": True,
    }
    out = REPORTS / args.json_out
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if dry.get("status") == "ready" else 1


if __name__ == "__main__":
    sys.exit(main())
