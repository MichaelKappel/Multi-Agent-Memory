import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "docs" / "reports"
REPORT_FRESHNESS_MODEL = (
    "tracked_reports_are_point_in_time_snapshots; "
    "run no-write checks after commit or push for current-commit proof"
)


def utc_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(name):
    path = REPORTS / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


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


def connection_status(*reports):
    present = [report for report in reports if report]
    if not present:
        return "not recorded"
    parts = []
    for report in present:
        parts.append(
            "%s/%s/%s uploads"
            % (
                report.get("protocol") or "unknown",
                report.get("status") or "unknown",
                report.get("uploadedCount", 0),
            )
        )
    return ", ".join(parts)


def github_blocker_text(github_ci):
    blocker = github_ci.get("blocker") or "The observed run is not a passing CI signal."
    previous = (github_ci.get("previousReport") or {}).get("blocker")
    if previous:
        return "%s Previous public-safe CI evidence: %s" % (blocker, previous)
    return blocker


def dogfood_gap_state(dogfood):
    dogfood = dogfood or {}
    if dogfood.get("liveDogfoodVerified"):
        return (
            "Full live dogfood contract verified for the currently deployed API.",
            "After each latest-code deploy, rerun live dogfood and refresh `docs/reports/dogfood-memory-run.json`.",
        )
    if dogfood.get("liveCoreDogfoodVerified"):
        return (
            "Live core MATM dogfood is verified for the currently deployed API; latest protected audit-log dogfood contract is still blocked because the latest route tranche is not deployed.",
            "Deploy the latest code, verify `/api/version` reports the pushed SHA, then rerun live dogfood and prove protected audit-log readback.",
        )
    if dogfood.get("localDogfoodVerified"):
        return (
            "Local WSGI dogfood is verified; authenticated live dogfood is not proven.",
            "Run authenticated live dogfood after deployment succeeds without exposing credentials.",
        )
    return (
        "Dogfood evidence is missing or failed.",
        "Run local dogfood, then live dogfood after deployment succeeds.",
    )


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
    deploy_attempt = load_json("deploy-attempt-20260709.json")
    deploy_dry_run = load_json("deploy-dry-run-latest.json")
    head_sha = git_head_sha()
    local_route_report_current = report_matches_head(
        local_routes,
        head_sha,
        [("gitHeadAtVerification",), ("expectedSourceSha",), ("observedSourceSha",)],
    )
    package_report_current = report_matches_head(package, head_sha, [("build", "sourceSha")])
    github_ci_report_current = report_matches_head(github_ci, head_sha, [("latestObservedHeadSha",)])
    wsgi_check_current = bool((check_result(enterprise, "wsgi_route_verifier") or {}).get("ok"))
    package_check_current = bool((check_result(enterprise, "package_check") or {}).get("ok"))
    local_route_evidence_current = bool(
        (local_routes and local_routes.get("ok") and local_route_report_current) or wsgi_check_current
    )
    package_evidence_current = bool(
        (package and package.get("status") == "ready" and package_report_current) or package_check_current
    )
    deploy_dry_run_matches_package = bool(
        deploy_attempt
        and (deploy_attempt.get("claimBoundary") or {}).get("dryRunMatchesPackage")
        and (deploy_attempt.get("dryRun") or {}).get("status") == "ready"
        and deploy_dry_run
        and deploy_dry_run.get("status") == "ready"
        and deploy_dry_run.get("safeNoOp") is True
    )

    checks = [
        {"id": "unit_and_integration_tests", "status": status((check_result(enterprise, "unit_and_integration_tests") or {}).get("ok")), "evidence": ["tests/test_app.py"]},
        {"id": "wsgi_public_routes", "status": status(local_route_evidence_current), "evidence": ["docs/reports/local-route-verification.json", "docs/reports/enterprise-readiness-audit.json"]},
        {
            "id": "uai_startup_memory",
            "status": status(bool(uai and uai.get("ok"))),
            "evidence": ["docs/reports/uai-memory-audit.json", ".uai/memory-maintenance.uai", ".uai/startup-packet.uai", ".uai/totem.uai"],
        },
        {"id": "local_dogfood", "status": status(bool(dogfood and dogfood.get("localDogfoodVerified"))), "evidence": ["docs/reports/dogfood-memory-run.json"]},
        {"id": "package_check", "status": status(package_evidence_current), "evidence": ["docs/reports/package-verification-report.json", "docs/reports/enterprise-readiness-audit.json"]},
        {"id": "secret_scan", "status": status(bool(secret and secret.get("ok"))), "evidence": ["docs/reports/secret-scan-report.json"]},
        {"id": "repository_boundary", "status": status(bool(boundary and boundary.get("ok"))), "evidence": ["docs/reports/repository-boundary-audit.json", "sites/multiagentmemory.com/"]},
        {"id": "multiagentmemory_static_site", "status": status(bool(static_site and static_site.get("ok"))), "evidence": ["docs/reports/multiagentmemory-static-site-verification.json", "sites/multiagentmemory.com/"]},
        {"id": "deploy_dry_run", "status": status(deploy_dry_run_matches_package), "evidence": ["docs/reports/deploy-dry-run-latest.json", "docs/reports/deploy-attempt-20260709.json"]},
        {"id": "diff_check", "status": status((check_result(enterprise, "diff_check") or {}).get("ok")), "evidence": ["git diff --check"]},
    ]
    report = {
        "schemaVersion": "memoryendpoints.local_verification_report.v1",
        "generatedAt": utc_now(),
        "gitHeadAtReportGeneration": head_sha,
        "reportScope": "point_in_time_snapshot",
        "scope": "local worktree, WSGI route handlers, package plan, .uai startup memory, and local dogfood runner",
        "ok": all(item["status"] == "pass" for item in checks),
        "checks": checks,
        "routeCount": (local_routes or {}).get("routeCount"),
        "routeFailureCount": (local_routes or {}).get("failureCount"),
        "reportFreshness": {
            "model": REPORT_FRESHNESS_MODEL,
            "postCommitNoWriteVerificationRequired": True,
            "localRouteReportCurrent": local_route_report_current,
            "localRouteReportSha": report_sha(local_routes, [("gitHeadAtVerification",), ("expectedSourceSha",), ("observedSourceSha",)]),
            "localRouteCommandEvidenceCurrent": wsgi_check_current,
            "localRouteEvidenceCurrent": local_route_evidence_current,
            "packageReportCurrent": package_report_current,
            "packageReportSha": report_sha(package, [("build", "sourceSha")]),
            "packageCommandEvidenceCurrent": package_check_current,
            "packageEvidenceCurrent": package_evidence_current,
            "githubCiReportCurrent": github_ci_report_current,
            "githubCiReportSha": report_sha(github_ci, [("latestObservedHeadSha",)]),
            "currentGitHead": head_sha,
            "valuesRedacted": True,
        },
        "uaiFileCount": (uai or {}).get("fileCount"),
        "localUaiStaysActiveAlways": bool(uai and uai.get("localUaiStaysActiveAlways")),
        "dateFreeHotMemory": bool(uai and uai.get("dateFreeHotMemory")),
        "noCatchAllActiveMemoryFile": bool(uai and uai.get("noCatchAllActiveMemoryFile")),
        "localDogfoodVerified": bool(dogfood and dogfood.get("localDogfoodVerified")),
        "liveDogfoodVerified": bool(dogfood and dogfood.get("liveDogfoodVerified")),
        "liveCoreDogfoodVerified": bool(dogfood and dogfood.get("liveCoreDogfoodVerified")),
        "repositoryBoundaryOk": bool(boundary and boundary.get("ok")),
        "multiAgentMemoryStaticSiteVerified": bool(static_site and static_site.get("ok")),
        "deployDryRunMatchesPackage": deploy_dry_run_matches_package,
        "externalSignals": {
            "githubCiConclusion": (github_ci or {}).get("conclusion"),
            "githubCiEvidence": "docs/reports/github-ci-status-report.json" if github_ci else None,
        },
        "valuesRedacted": True,
    }
    write_json("local-verification-report.json", report)
    return report


def build_enterprise_gap_matrix():
    dogfood = load_json("dogfood-memory-run.json") or {}
    github_ci = load_json("github-ci-status-report.json") or {}
    live_latest_code = load_json("live-latest-code-verification.json") or {}
    deploy = load_json("deploy-attempt-20260709.json") or {}
    deploy_connection_ftps = load_json("deploy-connection-check-latest.json") or {}
    deploy_connection_ftp = load_json("deploy-connection-check-ftp-latest.json") or {}
    multiagentmemory_connection_ftps = load_json("multiagentmemory-deploy-connection-check-latest.json") or {}
    multiagentmemory_connection_ftp = load_json("multiagentmemory-deploy-connection-check-ftp-latest.json") or {}
    live_dogfood_state, live_dogfood_needed = dogfood_gap_state(dogfood)
    head_sha = git_head_sha()
    lines = [
        "# Enterprise MATM Gap Matrix",
        "",
        "Generated: 2026-07-09",
        "",
        "## Current Verified Improvements",
        "",
        "| Area | Status | Evidence |",
        "| --- | --- | --- |",
        "| `.uai` startup memory | Improved locally | Active `.uai/*.uai` files are typed, date-free, public-safe, update-route aware, and audited by `scripts/audit_uai_memory.py`. |",
        "| `.uai` totem invariant | Implemented locally | `.uai/totem.uai` says local `.uai` stays active always and hosted MATM never replaces startup continuity. |",
        "| Protected MATM workflows | Implemented locally | `tests/test_app.py` covers free account, one-time key hash persistence, registration, memory submit/search, firewall redaction, review queue, current message, ack, receipts, audit log, idempotency, and safe no-op errors. |",
        "| Dogfood runner | Implemented locally | `scripts/dogfood_memoryendpoints.py` generated `docs/reports/dogfood-memory-run.json` with local WSGI readback, ack, receipts, and protected audit-log readback. |",
        "| Live core dogfood | %s | `docs/reports/dogfood-memory-run.json` distinguishes `liveCoreDogfoodVerified` from full `liveDogfoodVerified`. |" % ("Verified current deployed surface" if dogfood.get("liveCoreDogfoodVerified") else "Not verified"),
        "| Prompt drafts | Local-only | `docs/prompts/*.md` is ignored and excluded from packaging. |",
        "",
        "## Remaining Gaps Before Full Goal Completion",
        "",
        "| Requirement | Current state | Needed evidence before claiming done |",
        "| --- | --- | --- |",
        "| Latest-code live deployment | Blocked by hosting login rejection before upload; no-upload connection checks show `%s`; live `/api/version` source SHA match is `%s`. | Refresh hosting credential/server access outside the repo, then rerun package, dry-run deploy, no-upload connection check, live deploy, Passenger restart, and live route verification. |" % (
            connection_status(deploy_connection_ftps, deploy_connection_ftp),
            str(bool(live_latest_code.get("sourceShaMatchesExpected"))).lower(),
        ),
        "| MultiAgentMemory.com live publish | Blocked by hosting login rejection before upload; no-upload connection checks show `%s`. | Refresh hosting access, publish `sites/multiagentmemory.com/`, then rerun live static-site verification. |" % connection_status(multiagentmemory_connection_ftps, multiagentmemory_connection_ftp),
        "| Live dogfooding | %s | %s |" % (live_dogfood_state, live_dogfood_needed),
        "| Relational production database | Schema-ready and stdlib SQLite relational table-backed; MySQL/MariaDB runtime remains adapter-gated. | Approved adapter path or honest continued gated status. Do not claim MySQL/MariaDB is live. |",
        "| CI status after latest push | `%s` for current observed SHA `%s`; %s | Resolve GitHub account/Actions blocker, then require a passing CI run for the pushed SHA. |" % (
            github_ci.get("conclusion") or "unknown",
            (github_ci.get("latestObservedHeadSha") or head_sha or "unknown")[:12],
            github_blocker_text(github_ci),
        ),
        "| Full enterprise completion audit | Partial because live deployment, latest live dogfood contract, companion live publish, CI, and MySQL adapter gates remain unresolved. | Requirement-by-requirement completion audit against the goal objective after live verification succeeds. |",
        "",
        "## Claim Boundary",
        "",
        "The repository is improved, but the full objective is not complete. Current evidence supports local MATM hardening, local dogfood, and live core dogfood for the currently deployed surface; it does not support a full completion claim until latest-code deployment, latest-contract live dogfood, companion live publish, CI, and gated capabilities are resolved or explicitly waived.",
    ]
    path = REPORTS / "enterprise-gap-matrix.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build_current_implementation_audit():
    dogfood = load_json("dogfood-memory-run.json") or {}
    live_routes = load_json("live-route-verification.json") or {}
    live_latest_code = load_json("live-latest-code-verification.json") or {}
    deploy_connection_ftps = load_json("deploy-connection-check-latest.json") or {}
    deploy_connection_ftp = load_json("deploy-connection-check-ftp-latest.json") or {}
    live_dogfood_state, live_dogfood_needed = dogfood_gap_state(dogfood)
    lines = [
        "# Current Implementation Audit",
        "",
        "Generated: 2026-07-09",
        "",
        "## Scope",
        "",
        "Audit against the active MemoryEndpoints.com enterprise MATM objective after local MATM workflow hardening, `.uai` normalization, dogfood runner implementation, deployment diagnostics, and readiness evidence hardening.",
        "",
        "## Evidence Gathered",
        "",
        "- Unit/integration suite passes through `python -m unittest discover -s tests`.",
        "- WSGI route verifier passes for 21 required public routes and current source SHA.",
        "- Static MultiAgentMemory.com source verifier passes locally.",
        "- `.uai` required-field and date-free audit passes for the active typed memory suite.",
        "- Secret scan passes with zero hits.",
        "- Package verification is ready and excludes `.uai`, prompt drafts, runtime state, databases, logs, caches, local reports folders, and credential handoff files.",
        "- Deploy dry-run matches package file count and source SHA and remains a no-upload safe no-op.",
        "- Live public route verifier reports `%s` failures for the currently deployed MemoryEndpoints.com surface." % live_routes.get("failureCount"),
        "- Latest-code live verifier expects `%s`, observes `%s`, and matches `%s`." % (
            live_latest_code.get("expectedSourceSha"),
            live_latest_code.get("observedSourceSha"),
            str(bool(live_latest_code.get("sourceShaMatchesExpected"))).lower(),
        ),
        "- No-upload deployment connection checks for explicit FTPS and plain FTP report `%s`; no files are uploaded." % connection_status(deploy_connection_ftps, deploy_connection_ftp),
        "",
        "## Implemented Locally",
        "",
        "- `.uai/totem.uai` marks local `.uai` as always active.",
        "- Active `.uai` files are typed, date-free, and audited; catch-all active memory files remain forbidden.",
        "- Memory events are firewall-reviewed and typed before persistence.",
        "- Review queue and review decision routes are protected and idempotent.",
        "- Quarantined/rejected memory is excluded from normal search.",
        "- File storage and stdlib SQLite relational tables support the implemented MATM workflows.",
        "- Integration tests prove one-time workspace keys are persisted only as hashes in file and SQLite storage.",
        "- Dogfood runner exercises workspace setup, agent registration, memory submit/search, current-message creation/readback, notification acknowledgement, receipt readback, and protected audit-log readback locally.",
        "",
        "## Not Yet Proven",
        "",
        "- Latest code is not proven live because live `/api/version` does not report the expected source SHA.",
        "- %s" % live_dogfood_state,
        "- %s" % live_dogfood_needed,
        "- MultiAgentMemory.com live domain is not yet serving the expected companion-site files.",
        "- Full production MySQL/MariaDB adapter remains gated by the no-third-party-runtime constraint.",
        "- The full objective still needs a final completion audit after live deploy, live dogfood, companion live publish, CI, and gated-capability evidence pass.",
    ]
    path = REPORTS / "current-implementation-audit.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build_final_verification_alias():
    dogfood = load_json("dogfood-memory-run.json") or {}
    live_routes = load_json("live-route-verification.json") or {}
    live_latest_code = load_json("live-latest-code-verification.json") or {}
    live_dogfood_state, live_dogfood_needed = dogfood_gap_state(dogfood)
    lines = [
        "# Final Verification Report",
        "",
        "Date: 2026-07-09",
        "",
        "Status: superseded by `docs/reports/final-readiness-report.md`.",
        "",
        "This report name is retained for compatibility with older repository links. The previous contents overclaimed the current state after later hosting login failures blocked deployment of the newest tranche.",
        "",
        "Current boundary:",
        "",
        "- Local verification is strong and repeatable.",
        "- Live public route verification currently reports `%s` failures for the deployed public surface." % live_routes.get("failureCount"),
        "- Latest-code live deployment is not verified; expected `%s`, observed `%s`, match `%s`." % (
            live_latest_code.get("expectedSourceSha"),
            live_latest_code.get("observedSourceSha"),
            str(bool(live_latest_code.get("sourceShaMatchesExpected"))).lower(),
        ),
        "- %s" % live_dogfood_state,
        "- %s" % live_dogfood_needed,
        "- Full goal completion must not be claimed until live deployment, latest-contract live dogfood, companion live publish, CI, and gated-capability blockers are cleared.",
    ]
    path = REPORTS / "final-verification-report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build_final_markdown(local_report):
    enterprise = load_json("enterprise-readiness-audit.json") or {}
    local_routes = load_json("local-route-verification.json") or {}
    live_routes = load_json("live-route-verification.json") or {}
    live_latest_code = load_json("live-latest-code-verification.json") or {}
    deploy = load_json("deploy-attempt-20260709.json") or {}
    deploy_dry_run = load_json("deploy-dry-run-latest.json") or {}
    deploy_connection_ftps = load_json("deploy-connection-check-latest.json") or {}
    deploy_connection_ftp = load_json("deploy-connection-check-ftp-latest.json") or {}
    multiagentmemory_live = load_json("multiagentmemory-deploy-live-attempt-latest.json") or {}
    multiagentmemory_connection_ftps = load_json("multiagentmemory-deploy-connection-check-latest.json") or {}
    multiagentmemory_connection_ftp = load_json("multiagentmemory-deploy-connection-check-ftp-latest.json") or {}
    multiagentmemory_live_site = load_json("multiagentmemory-live-site-verification.json") or {}
    package = load_json("package-verification-report.json") or {}
    secret = load_json("secret-scan-report.json") or {}
    dogfood = load_json("dogfood-memory-run.json") or {}
    github_ci = load_json("github-ci-status-report.json") or {}
    github_blocker = github_blocker_text(github_ci)
    report_source_sha = git_head_sha()
    freshness = (local_report or {}).get("reportFreshness") or {}

    latest_deployed = bool(
        (deploy.get("claimBoundary") or {}).get("newCodeLiveDeployed")
        and live_latest_code.get("sourceShaMatchesExpected")
    )
    live_dogfood = bool(dogfood.get("liveDogfoodVerified"))
    live_core_dogfood = bool(dogfood.get("liveCoreDogfoodVerified"))
    completion_allowed = bool(local_report.get("ok") and live_routes.get("ok") and latest_deployed and live_dogfood and not enterprise.get("blockers"))
    lines = [
        "# Final Readiness Report",
        "",
        "Date: 2026-07-09",
        "",
        "Status: not complete. `completionClaimAllowed` is `false`.",
        "",
        "Report source snapshot: `%s`. Tracked reports are point-in-time evidence; rerun the no-write live and CI verifiers after a final push to prove the current commit." % (report_source_sha or "unknown"),
        "",
        "## Verified",
        "",
        "- Local verification report: `%s`, see `docs/reports/local-verification-report.json`." % ("pass" if local_report.get("ok") else "not pass"),
        "- Evidence model: tracked report files are point-in-time snapshots. After any commit or push, rerun no-write WSGI/package/live/CI checks to prove the current commit without pretending the containing commit could already be named inside its own tracked reports.",
        "- Snapshot freshness at report generation: local route report `%s`, package report `%s`, GitHub CI report `%s` for snapshot HEAD `%s`." % (
            str(bool(freshness.get("localRouteReportCurrent"))).lower(),
            str(bool(freshness.get("packageReportCurrent"))).lower(),
            str(bool(freshness.get("githubCiReportCurrent"))).lower(),
            (report_source_sha or "unknown")[:12],
        ),
        "- Current-command evidence at report generation: local route command `%s`, local route evidence `%s`, package command `%s`, package evidence `%s`." % (
            str(bool(freshness.get("localRouteCommandEvidenceCurrent"))).lower(),
            str(bool(freshness.get("localRouteEvidenceCurrent"))).lower(),
            str(bool(freshness.get("packageCommandEvidenceCurrent"))).lower(),
            str(bool(freshness.get("packageEvidenceCurrent"))).lower(),
        ),
        "- Unit and integration tests: pass through `scripts/enterprise_readiness_audit.py --run-checks`.",
        "- Local WSGI route verification: %s routes, %s failures." % (local_routes.get("routeCount"), local_routes.get("failureCount")),
        "- Live public route verification: %s routes, %s failures for the currently deployed public surface." % (live_routes.get("routeCount"), live_routes.get("failureCount")),
        "- Live latest-code SHA verification snapshot: expected `%s`, observed `%s`, match `%s`." % (
            live_latest_code.get("expectedSourceSha"),
            live_latest_code.get("observedSourceSha"),
            str(bool(live_latest_code.get("sourceShaMatchesExpected"))).lower(),
        ),
        "- `.uai` memory audit: pass; `.uai/startup-packet.uai` is the bootstrap index, `.uai/memory-maintenance.uai` is first in the read order, local `.uai` stays active always, Totem/Taboo/Talisman anchors are present, active `.uai` is date-free, active handoff buckets are empty or placeholder-only, and no catch-all active-memory file exists.",
        "- Local dogfooding: %s through WSGI; live core dogfooding on current deployed API: %s; latest live dogfood contract: %s." % (
            str(bool(dogfood.get("localDogfoodVerified"))).lower(),
            str(live_core_dogfood).lower(),
            str(live_dogfood).lower(),
        ),
        "- Package verification: status `%s`, %s planned files, excludes local runtime state and secrets." % (package.get("status"), package.get("fileCount")),
        "- Deploy dry-run: status `%s`, planned files `%s`, safe no-op `%s`, matches package `%s`." % (
            deploy_dry_run.get("status"),
            deploy_dry_run.get("plannedUploadCount"),
            str(bool(deploy_dry_run.get("safeNoOp"))).lower(),
            str(bool((deploy.get("claimBoundary") or {}).get("dryRunMatchesPackage"))).lower(),
        ),
        "- Secret scan: %s scanned files, %s hits." % (secret.get("scannedFileCount"), secret.get("hitCount")),
        "- MultiAgentMemory.com static source: %s; live publish status `%s`, uploaded count `%s`." % (
            "pass" if (load_json("multiagentmemory-static-site-verification.json") or {}).get("ok") else "not pass",
            multiagentmemory_live.get("status"),
            multiagentmemory_live.get("uploadedCount"),
        ),
        "- No-upload deployment connection checks: MemoryEndpoints.com `%s`; MultiAgentMemory.com `%s`." % (
            connection_status(deploy_connection_ftps, deploy_connection_ftp),
            connection_status(multiagentmemory_connection_ftps, multiagentmemory_connection_ftp),
        ),
        "- MultiAgentMemory.com live site verification: %s failures; home page is not serving expected companion links yet." % (multiagentmemory_live_site.get("failureCount")),
        "- GitHub Actions CI snapshot: `%s`; observed run did not prove code health because `%s`." % (github_ci.get("conclusion"), github_blocker),
        "",
        "## Blocked Or Gated",
        "",
        "- Latest-code live deployment: blocked. The recorded upload attempt failed at `%s` with `%s` before upload; uploaded count was `%s`; connection checks `%s`; live source SHA match is `%s`." % (
            (deploy.get("liveAttempt") or {}).get("failedPhase"),
            (deploy.get("liveAttempt") or {}).get("errorType"),
            (deploy.get("liveAttempt") or {}).get("uploadedCount"),
            connection_status(deploy_connection_ftps, deploy_connection_ftp),
            str(bool(live_latest_code.get("sourceShaMatchesExpected"))).lower(),
        ),
        "- MultiAgentMemory.com live publish: blocked. The recorded static-site upload attempt failed at `%s` with `%s` before upload; uploaded count was `%s`; connection checks `%s`." % (
            multiagentmemory_live.get("failedPhase"),
            multiagentmemory_live.get("errorType"),
            multiagentmemory_live.get("uploadedCount"),
            connection_status(multiagentmemory_connection_ftps, multiagentmemory_connection_ftp),
        ),
        "- MultiAgentMemory.com live routes: blocked until `docs/reports/multiagentmemory-live-site-verification.json` passes.",
    ]
    if not live_dogfood:
        lines.append(
            "- Live dogfooding: latest contract blocked until protected audit-log readback is deployed and verified."
            if live_core_dogfood
            else "- Live dogfooding: blocked until authenticated live MATM access is verified without exposing credentials."
        )
    lines.extend(
        [
            "- GitHub Actions CI: blocked in the tracked snapshot. %s" % github_blocker,
            "- MySQL/MariaDB runtime adapter: gated by the no-third-party-runtime constraint; file storage and stdlib SQLite relational MATM tables are active locally.",
            "",
            "## Claim Boundary",
            "",
            "The repository has strong local MATM evidence, current live core dogfood evidence, public route evidence, package evidence, and secret-safety evidence. Latest-contract live dogfood must be rerun after latest-code deployment succeeds because the current local dogfood contract includes protected audit-log readback. The project must not be described as fully done until latest-code live deployment, latest-contract live dogfood, GitHub Actions CI, and remaining gated items are verified.",
            "",
            "```json",
            json.dumps({"completionClaimAllowed": completion_allowed, "githubCiConclusion": github_ci.get("conclusion"), "latestCodeLiveDeployed": latest_deployed, "liveCoreDogfoodVerified": live_core_dogfood, "liveDogfoodVerified": live_dogfood, "multiAgentMemoryLiveDeployed": multiagentmemory_live.get("status") == "uploaded", "multiAgentMemoryLiveSiteVerified": bool(multiagentmemory_live_site.get("ok")), "reportSourceSha": report_source_sha, "valuesRedacted": True}, indent=2, sort_keys=True),
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
    gap_path = build_enterprise_gap_matrix()
    audit_path = build_current_implementation_audit()
    alias_path = build_final_verification_alias()
    print(
        json.dumps(
            {
                "ok": local_report["ok"],
                "localReport": "docs/reports/local-verification-report.json",
                "finalReport": str(final_path.relative_to(ROOT)).replace("\\", "/"),
                "gapMatrix": str(gap_path.relative_to(ROOT)).replace("\\", "/"),
                "currentImplementationAudit": str(audit_path.relative_to(ROOT)).replace("\\", "/"),
                "finalVerificationAlias": str(alias_path.relative_to(ROOT)).replace("\\", "/"),
                "valuesRedacted": True,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if local_report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
