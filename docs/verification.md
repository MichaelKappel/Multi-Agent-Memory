# Verification

Date: 2026-07-09

This project uses repeatable local checks and bounded live checks. Passing local checks does not prove the newest code is live.

## Required Local Gate

Run from `E:\MemoryEndpoints.com`:

```powershell
python -m unittest discover -s tests
python scripts\verify_memoryendpoints.py --wsgi --expect-git-head --json-out docs\reports\local-route-verification.json
python scripts\verify_static_site.py --json-out docs\reports\multiagentmemory-static-site-verification.json
python scripts\audit_uai_memory.py --json-out docs\reports\uai-memory-audit.json
python scripts\package_memoryendpoints.py --check-only
python scripts\secret_scan.py --json-out docs\reports\secret-scan-report.json
python scripts\enterprise_readiness_audit.py --run-checks --json-out docs\reports\enterprise-readiness-audit.json
git diff --check
```

Expected current local state:

- Unit/integration tests pass.
- Protected workflow tests prove one-time workspace keys are revealed once, then persisted only as hashes in both the file store and SQLite relational backend; raw keys and `apiKeySecret` are not stored.
- WSGI route verifier checks 21 required public routes with 0 failures.
- Tracked route and package reports are point-in-time snapshots. When used as standalone evidence they must record the target Git SHA; after any commit or push, rerun no-write WSGI/package/live/CI checks for current-commit proof rather than treating the containing commit's tracked reports as self-proving.
- MultiAgentMemory.com static-site verifier checks the companion HTML, discovery files, GitHub repository links, MemoryEndpoints.com links, sitemap, and secret-safety boundary.
- `.uai` audit passes with `.uai/startup-packet.uai` as the bootstrap index, `.uai/memory-maintenance.uai` first in the required memory order, `localUaiStaysActiveAlways=true`, date-free active `.uai`, and a hard ban on catch-all files such as `.uai/short-term-memory.uai`, `.uai/active-memory.uai`, and `.uai/current-state.uai`.
- Package check excludes `.git`, `.github`, `.uai`, local prompt drafts, raw Agent File Handoff bucket contents, `var`, `dist`, logs, databases, caches, and credential handoff files.
- Deploy dry-run evidence must match the package report file count and source SHA, and dry-run reports must be marked `safeNoOp=true`.
- Secret scan reports 0 hits.
- Enterprise readiness audit reports local hardening as verified while keeping `completionClaimAllowed=false` until live deploy, live dogfooding, and external CI are proven.

## Live Public Route Gate

```powershell
python scripts\verify_memoryendpoints.py --base-url https://memoryendpoints.com --json-out docs\reports\live-route-verification.json
python scripts\verify_memoryendpoints.py --base-url https://memoryendpoints.com --expect-git-head --json-out docs\reports\live-latest-code-verification.json
```

The first command proves the currently deployed public surface responds correctly. The second command proves whether `/api/version` reports the expected source SHA. Do not treat public-route success alone as proof that the newest local commit was deployed.

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

Live dogfood proves the currently deployed MemoryEndpoints.com API workflow, not that the newest local commit has been deployed. The report distinguishes `liveCoreDogfoodVerified` from full `liveDogfoodVerified`: the current deployed API can prove the core MATM workflow even while the latest protected audit-log readback contract remains blocked until the latest route tranche is deployed.

## Report Refresh

After verification commands and deploy attempts, refresh bounded reports:

```powershell
python scripts\build_deploy_attempt_report.py
python scripts\build_readiness_reports.py --write
```

Reports must remain public-safe and evidence-bound. If a report is stale or overclaims, update the report before pushing.

## GitHub CI Signal

The repository has a CI workflow under `.github/workflows/ci.yml`. Refresh the public-safe CI evidence with the stdlib-only public API checker:

```powershell
python scripts\check_github_actions.py --json-out docs\reports\github-ci-status-report.json
```

The checker exits nonzero when the latest matching run is not successful. A failed run with zero recorded job steps means GitHub did not execute the workflow commands, so treat it as an external GitHub runner/account gate, not as a passing CI signal and not as a local test failure. The checker also reads public check-run annotations when available; the current public-safe status is recorded in `docs/reports/github-ci-status-report.json`.

The readiness audit treats the CI report as current only when `latestObservedHeadSha` equals the current local Git HEAD. After every push, rerun this checker before using the CI report as evidence for the pushed commit.

The CI workflow sets `MEMORYENDPOINTS_SOURCE_SHA` from the GitHub commit SHA and runs the WSGI verifier with `--expect-source-sha`, so a successful CI run must prove `/api/version` build provenance as well as route availability.
