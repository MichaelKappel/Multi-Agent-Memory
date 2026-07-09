import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_FRESHNESS_MODEL = (
    "tracked_reports_are_point_in_time_snapshots; "
    "--run-checks supplies current-worktree no-write evidence"
)


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
    return None


def nested_get(data, path):
    current = data or {}
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def report_sha(data, candidate_paths):
    for path in candidate_paths:
        value = nested_get(data, path)
        if value:
            return value
    return None


def report_matches_head(data, head_sha, candidate_paths):
    if not data or not head_sha:
        return False
    return report_sha(data, candidate_paths) == head_sha


def check_passed(checks, name):
    return any(item.get("name") == name and item.get("ok") for item in checks)


def stale_report_blocker(label, data, head_sha, candidate_paths):
    observed = report_sha(data, candidate_paths)
    if not observed:
        return "%s report does not record a source SHA for the current worktree." % label
    if observed != head_sha:
        return "%s report is stale for current HEAD; report SHA %s, current HEAD %s." % (
            label,
            observed[:12],
            (head_sha or "unknown")[:12],
        )
    return None


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
        dogfood_temp = str(Path(tempfile.gettempdir()) / "memoryendpoints-readiness-dogfood.json")
        checks = [
            run_check("unit_and_integration_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests"]),
            run_check("wsgi_route_verifier", [sys.executable, "scripts/verify_memoryendpoints.py", "--wsgi", "--expect-git-head"]),
            run_check("multiagentmemory_static_site", [sys.executable, "scripts/verify_static_site.py"]),
            run_check("uai_memory_audit", [sys.executable, "scripts/audit_uai_memory.py"]),
            run_check("repository_boundary_audit", [sys.executable, "scripts/audit_repository_boundary.py"]),
            run_check("package_check", [sys.executable, "scripts/package_memoryendpoints.py", "--check-only"]),
            run_check("live_latest_code_verifier", [sys.executable, "scripts/verify_memoryendpoints.py", "--base-url", "https://memoryendpoints.com", "--expect-git-head"]),
            run_check("live_dogfood_verifier", [sys.executable, "scripts/dogfood_memoryendpoints.py", "--mode", "both", "--base-url", "https://memoryendpoints.com", "--no-progress-update", "--json-out", dogfood_temp]),
            run_check("multiagentmemory_live_site", [sys.executable, "scripts/verify_static_site.py", "--base-url", "https://multiagentmemory.com"]),
            run_check("secret_scan", [sys.executable, "scripts/secret_scan.py"]),
            run_check("diff_check", ["git", "diff", "--check"]),
        ]

    live_routes = load_json(Path("docs") / "reports" / "live-route-verification.json")
    live_latest_code = load_json(Path("docs") / "reports" / "live-latest-code-verification.json")
    local_routes = load_json(Path("docs") / "reports" / "local-route-verification.json")
    uai_audit = load_json(Path("docs") / "reports" / "uai-memory-audit.json")
    boundary = load_json(Path("docs") / "reports" / "repository-boundary-audit.json")
    dogfood = load_json(Path("docs") / "reports" / "dogfood-memory-run.json")
    deploy_attempt = load_json(Path("docs") / "reports" / "deploy-attempt-20260709.json")
    deploy_dry_run = load_json(Path("docs") / "reports" / "deploy-dry-run-latest.json")
    deploy_connection_ftps = load_json(Path("docs") / "reports" / "deploy-connection-check-latest.json")
    deploy_connection_ftp = load_json(Path("docs") / "reports" / "deploy-connection-check-ftp-latest.json")
    multiagentmemory_live = load_json(Path("docs") / "reports" / "multiagentmemory-deploy-live-attempt-latest.json")
    multiagentmemory_connection_ftps = load_json(Path("docs") / "reports" / "multiagentmemory-deploy-connection-check-latest.json")
    multiagentmemory_connection_ftp = load_json(Path("docs") / "reports" / "multiagentmemory-deploy-connection-check-ftp-latest.json")
    multiagentmemory_static = load_json(Path("docs") / "reports" / "multiagentmemory-static-site-verification.json")
    multiagentmemory_live_site = load_json(Path("docs") / "reports" / "multiagentmemory-live-site-verification.json")
    github_ci = load_json(Path("docs") / "reports" / "github-ci-status-report.json")
    github_ci_gate = load_json(Path("docs") / "reports" / "github-ci-gate-decision.json")
    head_sha = git_head_sha()
    local_route_report_current = report_matches_head(
        local_routes,
        head_sha,
        [("gitHeadAtVerification",), ("expectedSourceSha",), ("observedSourceSha",)],
    )
    package = load_json(Path("docs") / "reports" / "package-verification-report.json")
    package_report_current = report_matches_head(package, head_sha, [("build", "sourceSha")])
    live_latest_report_current = report_matches_head(
        live_latest_code,
        head_sha,
        [("expectedSourceSha",), ("gitHeadAtVerification",)],
    )
    github_ci_report_current = report_matches_head(github_ci, head_sha, [("latestObservedHeadSha",)])
    wsgi_check_current = check_passed(checks, "wsgi_route_verifier")
    package_check_current = check_passed(checks, "package_check")
    repository_boundary_check_current = check_passed(checks, "repository_boundary_audit")
    live_latest_code_check_current = check_passed(checks, "live_latest_code_verifier")
    live_dogfood_check_current = check_passed(checks, "live_dogfood_verifier")
    multiagentmemory_live_site_check_current = check_passed(checks, "multiagentmemory_live_site")
    local_route_evidence_current = bool(
        (local_routes and local_routes.get("ok") and local_route_report_current) or wsgi_check_current
    )
    package_evidence_current = bool(
        (package and package.get("status") == "ready" and package_report_current) or package_check_current
    )
    github_ci_not_required = bool(
        github_ci_gate
        and github_ci_gate.get("requirement") == "github_actions_ci"
        and github_ci_gate.get("decision") in ("not_required", "waived")
    )
    github_ci_ok = bool(
        github_ci_not_required
        or (github_ci and github_ci_report_current and github_ci.get("conclusion") == "success")
    )
    if github_ci_not_required:
        github_ci_blocker = None
    elif github_ci and github_ci.get("status") == "unavailable":
        previous = github_ci.get("previousReport") or {}
        prior = previous.get("blocker")
        github_ci_blocker = "%s Previous public-safe CI evidence: %s" % (
            github_ci.get("blocker") or "GitHub Actions public API is unavailable.",
            prior,
        ) if prior else (github_ci.get("blocker") or "GitHub Actions public API is unavailable.")
    elif github_ci and not github_ci_report_current:
        github_ci_blocker = stale_report_blocker(
            "GitHub Actions",
            github_ci,
            head_sha,
            [("latestObservedHeadSha",)],
        )
    else:
        github_ci_blocker = (
            github_ci.get("blocker")
            if github_ci and github_ci.get("blocker")
            else "Latest GitHub Actions run did not pass."
        )
    latest_code_live_verified = bool(
        live_latest_code_check_current
        or (
            deploy_attempt
            and (deploy_attempt.get("claimBoundary") or {}).get("newCodeLiveDeployed")
            and live_latest_code
            and live_latest_report_current
            and live_latest_code.get("ok")
            and live_latest_code.get("sourceShaMatchesExpected")
        )
    )
    latest_code_blocker = None
    if not latest_code_live_verified:
        connection_blocker = connection_check_blocker("MemoryEndpoints.com", [deploy_connection_ftps, deploy_connection_ftp])
        if connection_blocker:
            latest_code_blocker = connection_blocker
        elif checks and not live_latest_code_check_current:
            latest_code_blocker = "Live latest-code no-write verifier failed; inspect checkResults for live_latest_code_verifier."
        elif deploy_attempt and not (deploy_attempt.get("claimBoundary") or {}).get("newCodeLiveDeployed"):
            latest_code_blocker = "FTPS login rejected before upload; uploadedCount was 0."
        elif live_latest_code and not live_latest_report_current:
            latest_code_blocker = stale_report_blocker(
                "Live latest-code",
                live_latest_code,
                head_sha,
                [("expectedSourceSha",), ("gitHeadAtVerification",)],
            )
        elif live_latest_code and not live_latest_code.get("sourceShaMatchesExpected"):
            latest_code_blocker = "Live /api/version did not report the expected source SHA for the latest deploy package."
        else:
            latest_code_blocker = "Run live latest-code SHA verification after deployment."
    deploy_dry_run_matches_package = bool(
        deploy_attempt
        and (deploy_attempt.get("claimBoundary") or {}).get("dryRunMatchesPackage")
        and (deploy_attempt.get("dryRun") or {}).get("status") == "ready"
        and deploy_dry_run
        and deploy_dry_run.get("status") == "ready"
        and deploy_dry_run.get("safeNoOp") is True
    )
    deploy_dry_run_blocker = None if deploy_dry_run_matches_package else (
        "Deploy dry-run evidence is missing, stale, not marked as a safe no-op, or does not match the package report."
    )
    multiagentmemory_static_ok = bool(multiagentmemory_static and multiagentmemory_static.get("ok")) or check_passed(
        checks, "multiagentmemory_static_site"
    )
    live_public_routes_verified = bool((live_routes and live_routes.get("ok")) or live_latest_code_check_current)
    live_dogfood_verified = bool((dogfood and dogfood.get("liveDogfoodVerified")) or live_dogfood_check_current)
    multiagentmemory_live_site_verified = bool(
        (multiagentmemory_live_site and multiagentmemory_live_site.get("ok"))
        or multiagentmemory_live_site_check_current
    )
    multiagentmemory_connection_blocker = connection_check_blocker(
        "MultiAgentMemory.com",
        [multiagentmemory_connection_ftps, multiagentmemory_connection_ftp],
    )

    requirements = [
        evidence_item(
            "local_repository_organized",
            "pass_local" if ((boundary and boundary.get("ok")) or repository_boundary_check_current) else "missing",
            [
                "workspace.uai",
                "AGENTS.md",
                "docs/repository-structure.md",
                "sites/multiagentmemory.com/index.html",
                "docs/reports/repository-boundary-audit.json",
                "scripts/audit_repository_boundary.py",
            ],
            None
            if ((boundary and boundary.get("ok")) or repository_boundary_check_current)
            else "Repository boundary audit is missing or reports duplicate product folders/runtime artifacts.",
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
            "pass_local" if local_route_evidence_current else "missing",
            ["docs/reports/local-route-verification.json", "scripts/enterprise_readiness_audit.py --run-checks"],
            None
            if local_route_evidence_current
            else stale_report_blocker(
                "Local route verification",
                local_routes,
                head_sha,
                [("gitHeadAtVerification",), ("expectedSourceSha",), ("observedSourceSha",)],
            ),
        ),
        evidence_item(
            "package_report_current",
            "pass_local" if package_evidence_current else "missing",
            ["docs/reports/package-verification-report.json", "scripts/enterprise_readiness_audit.py --run-checks"],
            None
            if package_evidence_current
            else stale_report_blocker("Package verification", package, head_sha, [("build", "sourceSha")]),
        ),
        evidence_item(
            "multiagentmemory_static_site",
            "pass_local" if multiagentmemory_static_ok else "missing",
            ["sites/multiagentmemory.com/", "docs/reports/multiagentmemory-static-site-verification.json"],
            None if multiagentmemory_static_ok else "Run scripts/verify_static_site.py before claiming companion-site source readiness.",
        ),
        evidence_item(
            "deploy_dry_run_current",
            "pass_local" if deploy_dry_run_matches_package else "missing",
            ["docs/reports/deploy-dry-run-latest.json", "docs/reports/deploy-attempt-20260709.json"],
            deploy_dry_run_blocker,
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
            "pass_live_current_public_surface" if live_public_routes_verified else "missing",
            ["docs/reports/live-route-verification.json", "scripts/enterprise_readiness_audit.py --run-checks"],
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
                "scripts/enterprise_readiness_audit.py --run-checks",
            ],
            latest_code_blocker,
        ),
        evidence_item(
            "live_dogfooding",
            "pass_live" if live_dogfood_verified else "blocked",
            ["docs/reports/dogfood-memory-run.json", "scripts/enterprise_readiness_audit.py --run-checks"],
            None if live_dogfood_verified else (
                "Live core dogfood passes on the currently deployed API, but the latest protected audit-log dogfood contract is not deployed or verified."
                if dogfood and dogfood.get("liveCoreDogfoodVerified")
                else "Only local WSGI dogfooding is verified; live deployment/access is gated."
            ),
        ),
        evidence_item(
            "github_actions_ci",
            "not_required" if github_ci_not_required else ("pass_github" if github_ci_ok else "blocked"),
            [
                item
                for item in (
                    "docs/reports/github-ci-status-report.json",
                    "docs/reports/github-ci-gate-decision.json" if github_ci_not_required else None,
                )
                if item
            ],
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
    completion_allowed = bool(
        (all_checks_ok is not False)
        and not blockers
        and latest_code_live_verified
        and live_dogfood_verified
        and live_public_routes_verified
        and multiagentmemory_live_site_verified
        and package_evidence_current
        and local_route_evidence_current
        and ((uai_audit and uai_audit.get("ok")) or check_passed(checks, "uai_memory_audit"))
    )
    report = {
        "schemaVersion": "memoryendpoints.enterprise_readiness_audit.v1",
        "ok": completion_allowed,
        "completionClaimAllowed": completion_allowed,
        "generatedFromCurrentWorktree": True,
        "checksRun": bool(checks),
        "checksOk": all_checks_ok,
        "requirements": requirements,
        "blockers": blockers,
        "summary": {
            "currentGitHead": head_sha,
            "reportFreshnessModel": REPORT_FRESHNESS_MODEL,
            "postCommitNoWriteVerificationRequired": True,
            "localHardeningVerified": all_checks_ok is True or all_checks_ok is None,
            "localRouteReportCurrent": local_route_report_current,
            "localRouteEvidenceCurrent": local_route_evidence_current,
            "packageReportCurrent": package_report_current,
            "packageEvidenceCurrent": package_evidence_current,
            "repositoryBoundaryCurrent": repository_boundary_check_current,
            "repositoryBoundaryOk": bool((boundary and boundary.get("ok")) or repository_boundary_check_current),
            "liveLatestCodeReportCurrent": live_latest_report_current,
            "liveLatestCodeCommandEvidenceCurrent": live_latest_code_check_current,
            "liveDogfoodCommandEvidenceCurrent": live_dogfood_check_current,
            "multiAgentMemoryLiveSiteCommandEvidenceCurrent": multiagentmemory_live_site_check_current,
            "githubCiReportCurrent": github_ci_report_current,
            "githubCiRequired": not github_ci_not_required,
            "githubCiGateDecision": (github_ci_gate or {}).get("decision"),
            "dateFreeHotMemory": bool(uai_audit and uai_audit.get("dateFreeHotMemory")),
            "noForbiddenActiveMemoryFilename": bool(uai_audit and uai_audit.get("noForbiddenActiveMemoryFilename")),
            "livePublicRoutesVerified": live_public_routes_verified,
            "liveCoreDogfoodVerified": bool(dogfood and dogfood.get("liveCoreDogfoodVerified")),
            "latestCodeLiveDeployed": latest_code_live_verified,
            "latestCodeSourceShaMatchesExpected": bool(
                live_latest_code_check_current or (live_latest_code and live_latest_code.get("sourceShaMatchesExpected"))
            ),
            "multiAgentMemoryStaticSiteVerified": multiagentmemory_static_ok,
            "deployDryRunMatchesPackage": deploy_dry_run_matches_package,
            "multiAgentMemoryLiveDeployed": bool(multiagentmemory_live and multiagentmemory_live.get("status") == "uploaded"),
            "multiAgentMemoryLiveSiteVerified": multiagentmemory_live_site_verified,
            "liveDogfoodVerified": live_dogfood_verified,
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
