# Verification

Date: 2026-07-09

This project uses repeatable local checks and bounded live checks. Passing local checks does not prove the newest code is live.

## Required Local Gate

Run from `E:\MemoryEndpoints.com`:

```powershell
python -m unittest discover -s tests
python scripts\verify_memoryendpoints.py --wsgi --json-out docs\reports\local-route-verification.json
python scripts\verify_static_site.py --json-out docs\reports\multiagentmemory-static-site-verification.json
python scripts\audit_uai_memory.py --json-out docs\reports\uai-memory-audit.json
python scripts\package_memoryendpoints.py --check-only
python scripts\secret_scan.py --json-out docs\reports\secret-scan-report.json
python scripts\enterprise_readiness_audit.py --run-checks --json-out docs\reports\enterprise-readiness-audit.json
git diff --check
```

Expected current local state:

- Unit/integration tests pass.
- WSGI route verifier checks 21 required public routes with 0 failures.
- MultiAgentMemory.com static-site verifier checks the companion HTML, discovery files, GitHub repository links, MemoryEndpoints.com links, sitemap, and secret-safety boundary.
- `.uai` audit passes with `.uai/startup-packet.uai` as the bootstrap index, `.uai/totem.uai` first in the required memory order, and `localUaiStaysActiveAlways=true`.
- Package check excludes `.git`, `.github`, `.uai`, local prompt drafts, raw Agent File Handoff bucket contents, `var`, `dist`, logs, databases, caches, and credential handoff files.
- Secret scan reports 0 hits.
- Enterprise readiness audit reports local hardening as verified while keeping `completionClaimAllowed=false` until live deploy and live dogfooding are proven.

## Live Public Route Gate

```powershell
python scripts\verify_memoryendpoints.py --base-url https://memoryendpoints.com --json-out docs\reports\live-route-verification.json
```

This proves the currently deployed public surface responds correctly. It does not prove the newest local commit was deployed.

## Live Companion Site Gate

```powershell
python scripts\verify_static_site.py --base-url https://multiagentmemory.com --json-out docs\reports\multiagentmemory-live-site-verification.json
```

This proves the currently deployed MultiAgentMemory.com static files, not merely the local `sites/multiagentmemory.com/` source tree. The current live domain must not be treated as ready while this check fails.

## Dogfood Gate

```powershell
python scripts\dogfood_memoryendpoints.py
```

Current dogfooding can run locally and against the live HTTP API. Reports must distinguish local WSGI dogfooding from live HTTP dogfooding.

To exercise the current live HTTP API as well:

```powershell
python scripts\dogfood_memoryendpoints.py --mode both --base-url https://memoryendpoints.com
```

Live dogfood proves the currently deployed MemoryEndpoints.com API workflow, not that the newest local commit has been deployed. Optional newer routes can still be absent from the live site until deployment succeeds; required dogfood steps are recorded separately from optional step failures.

## Report Refresh

After verification commands and deploy attempts, refresh bounded reports:

```powershell
python scripts\build_deploy_attempt_report.py
python scripts\build_readiness_reports.py --write
```

Reports must remain public-safe and evidence-bound. If a report is stale or overclaims, update the report before pushing.

## GitHub CI Signal

The repository has a CI workflow under `.github/workflows/ci.yml`. Recent public runs did not start because GitHub reported an account billing lock. Treat that as an external GitHub-state blocker, not as a passing CI signal and not as a local test failure. The current public-safe status is recorded in `docs/reports/github-ci-status-report.json`.
