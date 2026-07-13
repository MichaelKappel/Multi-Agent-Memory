# Verification

This project uses repeatable local checks and bounded live checks. Passing local checks does not prove the newest code is live.

## Required Local Gate

Run from the repository root:

```powershell
python -m unittest discover -s tests
python scripts\verify_memoryendpoints.py --wsgi --expect-git-head --json-out var\reports\local-route-verification.json
python scripts\verify_static_site.py --json-out var\reports\multiagentmemory-static-site-verification.json
python scripts\audit_uai_memory.py --json-out var\reports\uai-memory-audit.json
python scripts\audit_repository_boundary.py --json-out var\reports\repository-boundary-audit.json
python scripts\package_memoryendpoints.py --check-only
python scripts\secret_scan.py --json-out var\reports\secret-scan-report.json
python scripts\enterprise_readiness_audit.py --run-checks --json-out var\reports\enterprise-readiness-audit.json
git diff --check
```

Expected current local state:

- Unit/integration tests pass.
- Protected workflow tests prove one-time workspace keys are revealed once, then persisted only as hashes in both the file store and SQLite relational backend; raw keys and `apiKeySecret` are not stored.
- WSGI route verifier checks the required public verification set with 0 failures, 0 secret hits, and 0 public leak hits for local filesystem paths, file URIs, or raw traceback fragments. The machine-readable route inventory is broader than this smoke set and is checked separately in unit tests.
- Tracked route and package reports are point-in-time snapshots. When used as standalone evidence they must record the target Git SHA; after any commit or push, rerun no-write WSGI/package/live/CI checks for current-commit proof rather than treating the containing commit's tracked reports as self-proving.
- MultiAgentMemory.com static-site verifier checks the companion HTML, discovery files, GitHub repository links, MemoryEndpoints.com links, sitemap, secret-safety boundary, and public leak boundary.
- Documentation freshness tests compare `memoryendpoints.site_data.ROUTE_TABLE` with `docs/route-inventory.md`, `docs/api-contract.md`, and the MultiAgentMemory.com API reference so new routes cannot ship without checked-in public documentation.
- `.uai` audit passes with `.uai/startup-packet.uai` as the bootstrap read-order index, `.uai/memory-maintenance.uai` as the first policy record after that index, `localUaiStaysActiveAlways=true`, date-free active `.uai`, and a hard actual-local-filename ban on `.uai/short-term-memory.uai`, `.uai/active-memory.uai`, `.uai/current-state.uai`, `.uai/project-state.uai`, `.uai/working-state.uai`, and equivalents. The accountless-browser virtual package may represent its configuration-specific short-term logical role because no local file is created.
- Virtual UAIX integration tests prove registered-agent ownership, tenant isolation, date/secret/structure rejection, immutable revisions, optimistic concurrency, complete startup ordering, and raw-key absence on file and SQLite backends. Collaboration tests prove overlapping claims and stale base hashes fail while only hash metadata is retained.
- Repository boundary audit passes with the configured repository root as the source of truth, `sites/multiagentmemory.com/` as the only companion docs source, no duplicate MemoryEndpoints/MultiAgentMemory site folders at the drive root, and no root-level runtime artifacts such as local SQLite write checks or devserver logs.
- Package check excludes `.git`, `.github`, `.uai`, local prompt drafts, raw Agent File Handoff bucket contents, `var`, `dist`, logs, databases, caches, and credential handoff files.
- Deploy dry-run evidence must match the package report file count and source SHA, and dry-run reports must be marked `safeNoOp=true`.
- Secret scan reports 0 hits.
- Enterprise readiness audit reports local hardening, live deployment, live dogfooding, and companion publishing as verified. GitHub Actions is retained as a repository workflow but is not a required completion gate per human direction; required evidence is local verification plus live deployment, live route, live dogfood, package, `.uai`, and secret-scan proof.

## Live Public Route Gate

```powershell
python scripts\verify_memoryendpoints.py --base-url https://memoryendpoints.com --json-out var\reports\live-route-verification.json
python scripts\verify_memoryendpoints.py --base-url https://memoryendpoints.com --expect-git-head --json-out var\reports\live-latest-code-verification.json
```

The first command proves the currently deployed public surface responds correctly. The second command proves whether `/api/version` reports the expected source SHA. Do not treat public-route success alone as proof that the newest local commit was deployed.

## Live Companion Site Gate

```powershell
python scripts\verify_static_site.py --base-url https://multiagentmemory.com --json-out var\reports\multiagentmemory-live-site-verification.json
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

Live dogfood proves the deployed MemoryEndpoints.com API workflow. Full live dogfood requires the durable memory and coordination readbacks plus a fail-closed check proving that the agent credential receives `403 human_owner_required` from the legacy audit-log path.

## Live UAIX Memory Gate

After the new routes are deployed, verify the public contract plus the existing
TinyRustLM registered-agent package and a synthetic hash-only claim/release:

```powershell
python scripts\verify_uai_memory_live.py --base-url https://memoryendpoints.com --auth-file .local-secrets\tinyrustlm-memoryendpoints-auth.json --json-out var\reports\uai-memory-live.json
```

The verifier never writes a virtual record body. It creates or resolves the
stable TinyRustLM package, reads the project, acquires a synthetic local-path
claim from the current head hash, and releases it without advancing the head.
Its report contains hashes of workspace, agent, package, project, and claim
identifiers rather than raw credentials or raw protected content. A public-only
contract probe is available with `--public-only`.

## Point-In-Time Reports

Write rerunnable evidence under ignored `var/reports/` so generated snapshots do not become a second documentation source of truth. For example:

```powershell
python scripts\dogfood_memoryendpoints.py --mode both --base-url https://memoryendpoints.com --no-progress-update --json-out var\reports\dogfood-release.json
python scripts\verify_mysql_backend.py --base-url https://memoryendpoints.com --json-out var\reports\mysql-release.json
python scripts\enterprise_readiness_audit.py --run-checks --json-out var\reports\enterprise-readiness-release.json
```

Reports must remain public-safe and evidence-bound. Existing checked-in `docs/reports/` files are historical snapshots and do not prove a later commit.

## GitHub CI Signal

The repository has a CI workflow under `.github/workflows/ci.yml`, but GitHub Actions is not a required completion gate per human direction. Do not keep retrying the GitHub API checker unless the human re-enables this gate.

If the gate is re-enabled later, refresh the public-safe CI evidence with the public API checker:

```powershell
python scripts\check_github_actions.py --json-out var\reports\github-ci-status-report.json
```

The checker exits nonzero when the latest matching run is not successful. A failed run with zero recorded job steps means GitHub did not execute the workflow commands, so treat it as an external GitHub runner/account gate, not as a passing CI signal and not as a local test failure. Do not keep retrying GitHub Actions unless the human re-enables it.

When the gate is re-enabled, the readiness audit should treat the CI report as current only when `latestObservedHeadSha` equals the current local Git HEAD.

The CI workflow sets `MEMORYENDPOINTS_SOURCE_SHA` from the GitHub commit SHA and runs the WSGI verifier with `--expect-source-sha`, so a successful CI run must prove `/api/version` build provenance as well as route availability.
