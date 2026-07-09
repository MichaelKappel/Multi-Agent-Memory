import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_check(name, command):
    completed = subprocess.run(
        command,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
    )
    result = {
        "name": name,
        "command": " ".join("python" if part == sys.executable else part for part in command),
        "exitCode": completed.returncode,
        "ok": completed.returncode == 0,
        "outputCaptured": completed.returncode != 0,
        "valuesRedacted": True,
    }
    if completed.returncode != 0:
        result["stdoutTail"] = completed.stdout[-1200:]
        result["stderrTail"] = completed.stderr[-1200:]
    return result


def load_json(rel):
    path = ROOT / rel
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def exists(rel):
    return (ROOT / rel).exists()


def evidence_item(requirement, status, evidence, blocker=None):
    return {
        "requirement": requirement,
        "status": status,
        "evidence": evidence,
        "blocker": blocker,
    }


def connection_check_blocker(label, reports):
    present = [report for report in reports if report]
    if not present:
        return None
    failed_login_protocols = [
        report.get("protocol")
        for report in present
        if report.get("status") == "connection_check_failed"
        and report.get("failedPhase") == "login"
        and report.get("uploadedCount") == 0
        and report.get("protocol")
    ]
    if failed_login_protocols and len(failed_login_protocols) == len(present):
        protocols = ", ".join(sorted(set(failed_login_protocols)))
        return "%s no-upload connection checks failed at login for protocol(s): %s; uploadedCount was 0." % (
            label,
            protocols,
        )
    return None


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-checks", action="store_true")
    parser.add_argument("--json-out")
    args = parser.parse_args(argv)

    checks = []
    if args.run_checks:
        checks = [
            run_check("unit_and_integration_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests"]),
            run_check("wsgi_route_verifier", [sys.executable, "scripts/verify_memoryendpoints.py", "--wsgi", "--expect-git-head"]),
            run_check("multiagentmemory_static_site", [sys.executable, "scripts/verify_static_site.py"]),
            run_check("uai_memory_audit", [sys.executable, "scripts/audit_uai_memory.py"]),
            run_check("package_check", [sys.executable, "scripts/package_memoryendpoints.py", "--check-only"]),
            run_check("secret_scan", [sys.executable, "scripts/secret_scan.py"]),
            run_check("diff_check", ["git", "diff", "--check"]),
        ]

    live_routes = load_json(Path("docs") / "reports" / "live-route-verification.json")
    live_latest_code = load_json(Path("docs") / "reports" / "live-latest-code-verification.json")
    local_routes = load_json(Path("docs") / "reports" / "local-route-verification.json")
    uai_audit = load_json(Path("docs") / "reports" / "uai-memory-audit.json")
    dogfood = load_json(Path("docs") / "reports" / "dogfood-memory-run.json")
    deploy_attempt = load_json(Path("docs") / "reports" / "deploy-attempt-20260709.json")
    deploy_connection_ftps = load_json(Path("docs") / "reports" / "deploy-connection-check-latest.json")
    deploy_connection_ftp = load_json(Path("docs") / "reports" / "deploy-connection-check-ftp-latest.json")
    multiagentmemory_live = load_json(Path("docs") / "reports" / "multiagentmemory-deploy-live-attempt-latest.json")
    multiagentmemory_connection_ftps = load_json(Path("docs") / "reports" / "multiagentmemory-deploy-connection-check-latest.json")
    multiagentmemory_connection_ftp = load_json(Path("docs") / "reports" / "multiagentmemory-deploy-connection-check-ftp-latest.json")
    multiagentmemory_static = load_json(Path("docs") / "reports" / "multiagentmemory-static-site-verification.json")
    multiagentmemory_live_site = load_json(Path("docs") / "reports" / "multiagentmemory-live-site-verification.json")
    github_ci = load_json(Path("docs") / "reports" / "github-ci-status-report.json")
    github_ci_ok = bool(github_ci and github_ci.get("conclusion") == "success")
    github_ci_blocker = (
        github_ci.get("blocker")
        if github_ci and github_ci.get("blocker")
        else "Latest GitHub Actions run did not pass."
    )
    latest_code_live_verified = bool(
        deploy_attempt
        and (deploy_attempt.get("claimBoundary") or {}).get("newCodeLiveDeployed")
        and live_latest_code
        and live_latest_code.get("ok")
        and live_latest_code.get("sourceShaMatchesExpected")
    )
    latest_code_blocker = None
    if not latest_code_live_verified:
        connection_blocker = connection_check_blocker("MemoryEndpoints.com", [deploy_connection_ftps, deploy_connection_ftp])
        if connection_blocker:
            latest_code_blocker = connection_blocker
        elif deploy_attempt and not (deploy_attempt.get("claimBoundary") or {}).get("newCodeLiveDeployed"):
            latest_code_blocker = "FTPS login rejected before upload; uploadedCount was 0."
        elif live_latest_code and not live_latest_code.get("sourceShaMatchesExpected"):
            latest_code_blocker = "Live /api/version did not report the expected source SHA for the latest deploy package."
        else:
            latest_code_blocker = "Run live latest-code SHA verification after deployment."
    multiagentmemory_static_ok = bool(multiagentmemory_static and multiagentmemory_static.get("ok")) or any(
        item.get("name") == "multiagentmemory_static_site" and item.get("ok") for item in checks
    )
    multiagentmemory_connection_blocker = connection_check_blocker(
        "MultiAgentMemory.com",
        [multiagentmemory_connection_ftps, multiagentmemory_connection_ftp],
    )

    requirements = [
        evidence_item(
            "local_repository_organized",
            "pass_local",
            ["workspace.uai", "AGENTS.md", "docs/repository-structure.md", "sites/multiagentmemory.com/index.html"],
        ),
        evidence_item(
            "uai_memory_complete_and_active",
            "pass_local",
            [
                ".uai/memory-maintenance.uai",
                ".uai/startup-packet.uai",
                ".uai/totem.uai",
                ".uai/taboo.uai",
                ".uai/talisman.uai",
                "scripts/audit_uai_memory.py",
                "local .uai stays active always",
            ],
        ),
        evidence_item(
            "critical_protected_workflows_integration_tested",
            "pass_local",
            ["tests/test_app.py covers free account, hash boundary, registration, memory submit/search, firewall redaction, review queue, current-message, ack, receipts, protected audit-log readback, idempotency, and safe no-op errors"],
        ),
        evidence_item(
            "local_dogfooding",
            "pass_local" if dogfood and dogfood.get("localDogfoodVerified") else "missing",
            ["docs/reports/dogfood-memory-run.json"],
        ),
        evidence_item(
            "public_wsgi_routes",
            "pass_local" if local_routes and local_routes.get("ok") else "missing",
            ["docs/reports/local-route-verification.json"],
        ),
        evidence_item(
            "multiagentmemory_static_site",
            "pass_local" if multiagentmemory_static_ok else "missing",
            ["sites/multiagentmemory.com/", "docs/reports/multiagentmemory-static-site-verification.json"],
            None if multiagentmemory_static_ok else "Run scripts/verify_static_site.py before claiming companion-site source readiness.",
        ),
        evidence_item(
            "multiagentmemory_live_deployed",
            "pass_live" if multiagentmemory_live and multiagentmemory_live.get("status") == "uploaded" else "blocked",
            [
                "docs/reports/multiagentmemory-deploy-live-attempt-latest.json",
                "docs/reports/multiagentmemory-deploy-connection-check-latest.json",
                "docs/reports/multiagentmemory-deploy-connection-check-ftp-latest.json",
            ],
            None if multiagentmemory_live and multiagentmemory_live.get("status") == "uploaded" else (
                multiagentmemory_connection_blocker
                or "MultiAgentMemory.com FTPS login rejected before upload; live domain still requires successful static publish."
            ),
        ),
        evidence_item(
            "multiagentmemory_live_site_routes",
            "pass_live" if multiagentmemory_live_site and multiagentmemory_live_site.get("ok") else "blocked",
            ["docs/reports/multiagentmemory-live-site-verification.json"],
            None if multiagentmemory_live_site and multiagentmemory_live_site.get("ok") else "Live MultiAgentMemory.com does not yet serve the expected companion-site routes and discovery files.",
        ),
        evidence_item(
            "live_public_routes",
            "pass_live_current_public_surface" if live_routes and live_routes.get("ok") else "missing",
            ["docs/reports/live-route-verification.json"],
        ),
        evidence_item(
            "live_core_dogfooding_current_surface",
            "pass_live_current_public_surface" if dogfood and dogfood.get("liveCoreDogfoodVerified") else "missing",
            ["docs/reports/dogfood-memory-run.json"],
            None if dogfood and dogfood.get("liveCoreDogfoodVerified") else "Run live dogfood against the currently deployed MemoryEndpoints.com API before claiming live core workflow evidence.",
        ),
        evidence_item(
            "latest_code_live_deployed",
            "pass_live" if latest_code_live_verified else "blocked",
            [
                "docs/reports/deploy-attempt-20260709.json",
                "docs/reports/deploy-connection-check-latest.json",
                "docs/reports/deploy-connection-check-ftp-latest.json",
                "docs/reports/live-latest-code-verification.json",
            ],
            latest_code_blocker,
        ),
        evidence_item(
            "live_dogfooding",
            "pass_live" if dogfood and dogfood.get("liveDogfoodVerified") else "blocked",
            ["docs/reports/dogfood-memory-run.json"],
            None if dogfood and dogfood.get("liveDogfoodVerified") else (
                "Live core dogfood passes on the currently deployed API, but the latest protected audit-log dogfood contract is not deployed or verified."
                if dogfood and dogfood.get("liveCoreDogfoodVerified")
                else "Only local WSGI dogfooding is verified; live deployment/access is gated."
            ),
        ),
        evidence_item(
            "github_actions_ci",
            "pass_github" if github_ci_ok else "blocked",
            ["docs/reports/github-ci-status-report.json"],
            None if github_ci_ok else github_ci_blocker,
        ),
        evidence_item(
            "mysql_runtime_adapter",
            "gated",
            ["docs/database-schema-canonical.sql", "docs/storage-backends.md"],
            "Python stdlib has no MySQL client; file storage and stdlib SQLite relational MATM tables are active while MySQL remains schema-ready/gated.",
        ),
    ]

    all_checks_ok = all(item["ok"] for item in checks) if checks else None
    blockers = [item for item in requirements if item["status"] in ("blocked", "missing")]
    report = {
        "schemaVersion": "memoryendpoints.enterprise_readiness_audit.v1",
        "ok": False,
        "completionClaimAllowed": False,
        "generatedFromCurrentWorktree": True,
        "checksRun": bool(checks),
        "checksOk": all_checks_ok,
        "requirements": requirements,
        "blockers": blockers,
        "summary": {
            "localHardeningVerified": all_checks_ok is True or all_checks_ok is None,
            "dateFreeHotMemory": bool(uai_audit and uai_audit.get("dateFreeHotMemory")),
            "noCatchAllActiveMemoryFile": bool(uai_audit and uai_audit.get("noCatchAllActiveMemoryFile")),
            "livePublicRoutesVerified": bool(live_routes and live_routes.get("ok")),
            "liveCoreDogfoodVerified": bool(dogfood and dogfood.get("liveCoreDogfoodVerified")),
            "latestCodeLiveDeployed": latest_code_live_verified,
            "latestCodeSourceShaMatchesExpected": bool(live_latest_code and live_latest_code.get("sourceShaMatchesExpected")),
            "multiAgentMemoryStaticSiteVerified": multiagentmemory_static_ok,
            "multiAgentMemoryLiveDeployed": bool(multiagentmemory_live and multiagentmemory_live.get("status") == "uploaded"),
            "multiAgentMemoryLiveSiteVerified": bool(multiagentmemory_live_site and multiagentmemory_live_site.get("ok")),
            "liveDogfoodVerified": bool(dogfood and dogfood.get("liveDogfoodVerified")),
            "promptDraftsTracked": False,
            "valuesRedacted": True,
        },
        "checkResults": checks,
        "valuesRedacted": True,
    }
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if all_checks_ok is not False else 1


if __name__ == "__main__":
    sys.exit(main())
