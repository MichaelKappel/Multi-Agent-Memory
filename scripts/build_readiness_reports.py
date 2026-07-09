import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "docs" / "reports"


def utc_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(name):
    path = REPORTS / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(name, data):
    path = REPORTS / name
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def run(command):
    completed = subprocess.run(command, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False)
    return {
        "command": " ".join("python" if part == sys.executable else part for part in command),
        "exitCode": completed.returncode,
        "ok": completed.returncode == 0,
        "valuesRedacted": True,
    }


def check_result(enterprise, name):
    for item in (enterprise or {}).get("checkResults", []):
        if item.get("name") == name:
            return item
    return None


def status(ok, blocked=False, gated=False):
    if blocked:
        return "blocked"
    if gated:
        return "gated"
    return "pass" if ok else "missing_or_failed"


def build_local_report():
    enterprise = load_json("enterprise-readiness-audit.json")
    local_routes = load_json("local-route-verification.json")
    uai = load_json("uai-memory-audit.json")
    dogfood = load_json("dogfood-memory-run.json")
    package = load_json("package-verification-report.json")
    secret = load_json("secret-scan-report.json")
    boundary = load_json("repository-boundary-audit.json")
    static_site = load_json("multiagentmemory-static-site-verification.json")
    github_ci = load_json("github-ci-status-report.json")

    checks = [
        {"id": "unit_and_integration_tests", "status": status((check_result(enterprise, "unit_and_integration_tests") or {}).get("ok")), "evidence": ["tests/test_app.py"]},
        {"id": "wsgi_public_routes", "status": status(bool(local_routes and local_routes.get("ok"))), "evidence": ["docs/reports/local-route-verification.json"]},
        {
            "id": "uai_startup_memory",
            "status": status(bool(uai and uai.get("ok"))),
            "evidence": ["docs/reports/uai-memory-audit.json", ".uai/memory-maintenance.uai", ".uai/startup-packet.uai", ".uai/totem.uai"],
        },
        {"id": "local_dogfood", "status": status(bool(dogfood and dogfood.get("localDogfoodVerified"))), "evidence": ["docs/reports/dogfood-memory-run.json"]},
        {"id": "package_check", "status": status(bool(package and package.get("status") == "ready")), "evidence": ["docs/reports/package-verification-report.json"]},
        {"id": "secret_scan", "status": status(bool(secret and secret.get("ok"))), "evidence": ["docs/reports/secret-scan-report.json"]},
        {"id": "repository_boundary", "status": status(bool(boundary and boundary.get("ok"))), "evidence": ["docs/reports/repository-boundary-audit.json", "sites/multiagentmemory.com/"]},
        {"id": "multiagentmemory_static_site", "status": status(bool(static_site and static_site.get("ok"))), "evidence": ["docs/reports/multiagentmemory-static-site-verification.json", "sites/multiagentmemory.com/"]},
        {"id": "diff_check", "status": status((check_result(enterprise, "diff_check") or {}).get("ok")), "evidence": ["git diff --check"]},
    ]
    report = {
        "schemaVersion": "memoryendpoints.local_verification_report.v1",
        "generatedAt": utc_now(),
        "scope": "local worktree, WSGI route handlers, package plan, .uai startup memory, and local dogfood runner",
        "ok": all(item["status"] == "pass" for item in checks),
        "checks": checks,
        "routeCount": (local_routes or {}).get("routeCount"),
        "routeFailureCount": (local_routes or {}).get("failureCount"),
        "uaiFileCount": (uai or {}).get("fileCount"),
        "localUaiStaysActiveAlways": bool(uai and uai.get("localUaiStaysActiveAlways")),
        "dateFreeHotMemory": bool(uai and uai.get("dateFreeHotMemory")),
        "noCatchAllActiveMemoryFile": bool(uai and uai.get("noCatchAllActiveMemoryFile")),
        "localDogfoodVerified": bool(dogfood and dogfood.get("localDogfoodVerified")),
        "liveDogfoodVerified": bool(dogfood and dogfood.get("liveDogfoodVerified")),
        "repositoryBoundaryOk": bool(boundary and boundary.get("ok")),
        "multiAgentMemoryStaticSiteVerified": bool(static_site and static_site.get("ok")),
        "externalSignals": {
            "githubCiConclusion": (github_ci or {}).get("conclusion"),
            "githubCiEvidence": "docs/reports/github-ci-status-report.json" if github_ci else None,
        },
        "valuesRedacted": True,
    }
    write_json("local-verification-report.json", report)
    return report


def build_final_markdown(local_report):
    enterprise = load_json("enterprise-readiness-audit.json") or {}
    local_routes = load_json("local-route-verification.json") or {}
    live_routes = load_json("live-route-verification.json") or {}
    deploy = load_json("deploy-attempt-20260709.json") or {}
    multiagentmemory_live = load_json("multiagentmemory-deploy-live-attempt-latest.json") or {}
    multiagentmemory_live_site = load_json("multiagentmemory-live-site-verification.json") or {}
    package = load_json("package-verification-report.json") or {}
    secret = load_json("secret-scan-report.json") or {}
    dogfood = load_json("dogfood-memory-run.json") or {}
    github_ci = load_json("github-ci-status-report.json") or {}

    latest_deployed = bool((deploy.get("claimBoundary") or {}).get("newCodeLiveDeployed"))
    live_dogfood = bool(dogfood.get("liveDogfoodVerified"))
    completion_allowed = bool(local_report.get("ok") and live_routes.get("ok") and latest_deployed and live_dogfood and not enterprise.get("blockers"))
    lines = [
        "# Final Readiness Report",
        "",
        "Date: 2026-07-09",
        "",
        "Status: not complete. `completionClaimAllowed` is `false`.",
        "",
        "## Verified",
        "",
        "- Local verification report: `%s`, see `docs/reports/local-verification-report.json`." % ("pass" if local_report.get("ok") else "not pass"),
        "- Unit and integration tests: pass through `scripts/enterprise_readiness_audit.py --run-checks`.",
        "- Local WSGI route verification: %s routes, %s failures." % (local_routes.get("routeCount"), local_routes.get("failureCount")),
        "- Live public route verification: %s routes, %s failures for the currently deployed public surface." % (live_routes.get("routeCount"), live_routes.get("failureCount")),
        "- `.uai` memory audit: pass; `.uai/startup-packet.uai` is the bootstrap index, `.uai/memory-maintenance.uai` is first in the read order, local `.uai` stays active always, Totem/Taboo/Talisman anchors are present, active `.uai` is date-free, active handoff buckets are empty or placeholder-only, and no catch-all active-memory file exists.",
        "- Local dogfooding: %s through WSGI; live dogfooding: %s." % (str(bool(dogfood.get("localDogfoodVerified"))).lower(), str(live_dogfood).lower()),
        "- Package verification: status `%s`, %s planned files, excludes local runtime state and secrets." % (package.get("status"), package.get("fileCount")),
        "- Secret scan: %s scanned files, %s hits." % (secret.get("scannedFileCount"), secret.get("hitCount")),
        "- MultiAgentMemory.com static source: %s; live publish status `%s`, uploaded count `%s`." % (
            "pass" if (load_json("multiagentmemory-static-site-verification.json") or {}).get("ok") else "not pass",
            multiagentmemory_live.get("status"),
            multiagentmemory_live.get("uploadedCount"),
        ),
        "- MultiAgentMemory.com live site verification: %s failures; home page is not serving expected companion links yet." % (multiagentmemory_live_site.get("failureCount")),
        "- GitHub Actions CI: `%s`; latest run did not prove code health because `%s`." % (github_ci.get("conclusion"), github_ci.get("blocker")),
        "",
        "## Blocked Or Gated",
        "",
        "- Latest-code live deployment: blocked. The recorded FTPS attempt failed at `%s` with `%s` before upload; uploaded count was `%s`." % ((deploy.get("liveAttempt") or {}).get("failedPhase"), (deploy.get("liveAttempt") or {}).get("errorType"), (deploy.get("liveAttempt") or {}).get("uploadedCount")),
        "- MultiAgentMemory.com live publish: blocked. The recorded static-site FTPS attempt failed at `%s` with `%s` before upload; uploaded count was `%s`." % (multiagentmemory_live.get("failedPhase"), multiagentmemory_live.get("errorType"), multiagentmemory_live.get("uploadedCount")),
        "- MultiAgentMemory.com live routes: blocked until `docs/reports/multiagentmemory-live-site-verification.json` passes.",
    ]
    if not live_dogfood:
        lines.append("- Live dogfooding: blocked until authenticated live MATM access is verified without exposing credentials.")
    lines.extend(
        [
            "- GitHub Actions CI: blocked by repository/account billing state before job execution, so the latest run is not a passing CI signal.",
            "- MySQL/MariaDB runtime adapter: gated by the no-third-party-runtime constraint; file storage and stdlib SQLite relational MATM tables are active locally.",
            "",
            "## Claim Boundary",
            "",
            "The repository has strong local MATM evidence, public route evidence, package evidence, and secret-safety evidence. Live dogfood must be rerun after latest-code deployment succeeds because the current local dogfood contract includes protected audit-log readback. The project must not be described as fully done until latest-code live deployment, live dogfood, GitHub Actions CI, and remaining gated items are verified.",
            "",
            "```json",
            json.dumps({"completionClaimAllowed": completion_allowed, "githubCiConclusion": github_ci.get("conclusion"), "latestCodeLiveDeployed": latest_deployed, "liveDogfoodVerified": live_dogfood, "multiAgentMemoryLiveDeployed": multiagentmemory_live.get("status") == "uploaded", "multiAgentMemoryLiveSiteVerified": bool(multiagentmemory_live_site.get("ok")), "valuesRedacted": True}, indent=2, sort_keys=True),
            "```",
        ]
    )
    path = REPORTS / "final-readiness-report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    if not args.write:
        print(json.dumps({"ok": False, "safeNoOp": True, "detail": "Pass --write to update reports.", "valuesRedacted": True}, indent=2))
        return 0
    local_report = build_local_report()
    final_path = build_final_markdown(local_report)
    print(json.dumps({"ok": local_report["ok"], "localReport": "docs/reports/local-verification-report.json", "finalReport": str(final_path.relative_to(ROOT)).replace("\\", "/"), "valuesRedacted": True}, indent=2, sort_keys=True))
    return 0 if local_report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
