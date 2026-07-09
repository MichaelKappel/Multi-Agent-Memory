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


def connection_item(report):
    if not report:
        return None
    return {
        "protocol": report.get("protocol"),
        "transportSecurity": report.get("transportSecurity"),
        "status": report.get("status"),
        "errorType": report.get("errorType"),
        "failedPhase": report.get("failedPhase"),
        "uploadedCount": report.get("uploadedCount", 0),
        "safeNoOp": report.get("safeNoOp", True),
        "valuesRedacted": True,
    }


def connection_blocker(reports):
    present = [report for report in reports if report]
    if not present:
        return None
    failed_protocols = [
        report.get("protocol")
        for report in present
        if report.get("status") == "connection_check_failed"
        and report.get("failedPhase") == "login"
        and report.get("uploadedCount") == 0
        and report.get("protocol")
    ]
    if failed_protocols and len(failed_protocols) == len(present):
        return "Connection checks for protocol(s) %s failed at login with zero uploads; credential or hosting account access must be refreshed outside the repository." % ", ".join(sorted(set(failed_protocols)))
    return None


def nested_get(data, path):
    current = data or {}
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def build_freshness(dry, package):
    dry_count = dry.get("plannedUploadCount")
    package_count = package.get("fileCount")
    dry_sha = nested_get(dry, ("build", "sourceSha"))
    package_sha = nested_get(package, ("build", "sourceSha"))
    return {
        "dryRunPlannedUploadCount": dry_count,
        "packageFileCount": package_count,
        "plannedUploadCountMatchesPackage": bool(dry_count is not None and dry_count == package_count),
        "dryRunSourceSha": dry_sha,
        "packageSourceSha": package_sha,
        "sourceShaMatchesPackage": bool(dry_sha and dry_sha == package_sha),
        "valuesRedacted": True,
    }


def freshness_blocker(freshness):
    blockers = []
    if not freshness.get("plannedUploadCountMatchesPackage"):
        blockers.append(
            "deploy dry-run planned upload count does not match package file count"
        )
    if not freshness.get("sourceShaMatchesPackage"):
        blockers.append("deploy dry-run source SHA does not match package source SHA")
    return "; ".join(blockers) if blockers else None


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run-report", default="deploy-dry-run-latest.json")
    parser.add_argument("--live-report", default="deploy-live-attempt-latest.json")
    parser.add_argument("--json-out", default="deploy-attempt-20260709.json")
    args = parser.parse_args(argv)

    dry = load(args.dry_run_report) or {}
    live = load(args.live_report) or {}
    package = load("package-verification-report.json") or {}
    connection_ftps = load("deploy-connection-check-latest.json")
    connection_ftp = load("deploy-connection-check-ftp-latest.json")
    dogfood = load("dogfood-memory-run.json") or {}
    live_status = live.get("status")
    live_uploaded = live.get("uploadedCount", 0)
    latest_live = live_status == "uploaded" and live_uploaded > 0
    freshness = build_freshness(dry, package)
    dry_run_stale_blocker = freshness_blocker(freshness)
    connection_gate = connection_blocker([connection_ftps, connection_ftp])
    report = {
        "schemaVersion": "memoryendpoints.deploy_attempt.v1",
        "generatedAt": "2026-07-09",
        "target": "MemoryEndpoints.com FTP login root",
        "remoteDir": ".",
        "dryRun": {
            "status": dry.get("status"),
            "plannedUploadCount": dry.get("plannedUploadCount"),
            "packageExists": dry.get("packageExists"),
            "sourceSha": nested_get(dry, ("build", "sourceSha")),
            "valuesRedacted": True,
        },
        "package": {
            "status": package.get("status"),
            "fileCount": package.get("fileCount"),
            "sourceSha": nested_get(package, ("build", "sourceSha")),
            "valuesRedacted": True,
        },
        "freshness": freshness,
        "liveAttempt": {
            "status": live_status,
            "errorType": live.get("errorType"),
            "failedPhase": live.get("failedPhase"),
            "uploadedCount": live_uploaded,
            "safeNoOp": live.get("safeNoOp", live_uploaded == 0),
            "valuesRedacted": True,
        },
        "connectionChecks": [
            item for item in (connection_item(connection_ftps), connection_item(connection_ftp)) if item
        ],
        "secretBoundary": {
            "hostPrinted": False,
            "userPrinted": False,
            "passwordPrinted": False,
            "credentialValuesPrinted": False,
        },
        "claimBoundary": {
            "newCodeLiveDeployed": latest_live,
            "dryRunMatchesPackage": not bool(dry_run_stale_blocker),
            "liveDogfoodVerified": bool(dogfood.get("liveDogfoodVerified")),
            "localDogfoodVerified": bool(dogfood.get("localDogfoodVerified")),
            "blocker": None if latest_live else (
                dry_run_stale_blocker
                or connection_gate
                or "FTPS login rejected before upload; credential or server access must be refreshed outside the repository."
            ),
            "externalConnectionBlocker": connection_gate,
        },
        "valuesRedacted": True,
    }
    out = REPORTS / args.json_out
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if dry.get("status") == "ready" else 1


if __name__ == "__main__":
    sys.exit(main())
