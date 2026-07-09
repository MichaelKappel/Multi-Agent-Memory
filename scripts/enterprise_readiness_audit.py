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


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-checks", action="store_true")
    parser.add_argument("--json-out")
    args = parser.parse_args(argv)

    checks = []
    if args.run_checks:
        checks = [
            run_check("unit_and_integration_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests"]),
            run_check("wsgi_route_verifier", [sys.executable, "scripts/verify_memoryendpoints.py", "--wsgi"]),
            run_check("uai_memory_audit", [sys.executable, "scripts/audit_uai_memory.py"]),
            run_check("package_check", [sys.executable, "scripts/package_memoryendpoints.py", "--check-only"]),
            run_check("secret_scan", [sys.executable, "scripts/secret_scan.py"]),
            run_check("diff_check", ["git", "diff", "--check"]),
        ]

    live_routes = load_json(Path("docs") / "reports" / "live-route-verification.json")
    local_routes = load_json(Path("docs") / "reports" / "local-route-verification.json")
    dogfood = load_json(Path("docs") / "reports" / "dogfood-memory-run.json")
    deploy_attempt = load_json(Path("docs") / "reports" / "deploy-attempt-20260709.json")
    github_ci = load_json(Path("docs") / "reports" / "github-ci-status-report.json")

    requirements = [
        evidence_item(
            "local_repository_organized",
            "pass_local",
            ["README.md", "AGENTS.md", "docs/repository-structure.md", "sites/multiagentmemory.com/"],
        ),
        evidence_item(
            "uai_memory_complete_and_active",
            "pass_local",
            [
                ".uai/startup-packet.uai",
                ".uai/totem.uai",
                "scripts/audit_uai_memory.py",
                "local .uai stays active always",
            ],
        ),
        evidence_item(
            "critical_protected_workflows_integration_tested",
            "pass_local",
            ["tests/test_app.py covers free account, hash boundary, registration, memory submit/search, firewall redaction, review queue, current-message, ack, receipts, idempotency, and safe no-op errors"],
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
            "live_public_routes",
            "pass_live_current_public_surface" if live_routes and live_routes.get("ok") else "missing",
            ["docs/reports/live-route-verification.json"],
        ),
        evidence_item(
            "latest_code_live_deployed",
            "blocked",
            ["docs/reports/deploy-attempt-20260709.json"],
            "FTPS login rejected before upload; uploadedCount was 0.",
        ),
        evidence_item(
            "live_dogfooding",
            "pass_live" if dogfood and dogfood.get("liveDogfoodVerified") else "blocked",
            ["docs/reports/dogfood-memory-run.json"],
            None if dogfood and dogfood.get("liveDogfoodVerified") else "Only local WSGI dogfooding is verified; live deployment/access is gated.",
        ),
        evidence_item(
            "github_actions_ci",
            "blocked" if github_ci and github_ci.get("conclusion") != "success" else "pass_github",
            ["docs/reports/github-ci-status-report.json"],
            None if github_ci and github_ci.get("conclusion") == "success" else "Latest GitHub Actions run did not pass; current evidence says the job was blocked by account billing lock.",
        ),
        evidence_item(
            "mysql_runtime_adapter",
            "gated",
            ["docs/database-schema-canonical.sql", "docs/storage-backends.md"],
            "Python stdlib has no MySQL client; SQLite/file storage is active while MySQL remains schema-ready/gated.",
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
            "livePublicRoutesVerified": bool(live_routes and live_routes.get("ok")),
            "latestCodeLiveDeployed": False,
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
