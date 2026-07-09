# Enterprise MATM Gap Matrix

Generated: 2026-07-09

## Current Verified Improvements

| Area | Status | Evidence |
| --- | --- | --- |
| `.uai` startup memory | Improved locally | Active `.uai/*.uai` files are typed, date-free, public-safe, update-route aware, and audited by `scripts/audit_uai_memory.py`. |
| `.uai` totem invariant | Implemented locally | `.uai/totem.uai` says local `.uai` stays active always and hosted MATM never replaces startup continuity. |
| Protected MATM workflows | Implemented locally | `tests/test_app.py` covers free account, one-time key hash persistence, registration, memory submit/search, firewall redaction, review queue, current message, ack, receipts, audit log, idempotency, and safe no-op errors. |
| Dogfood runner | Implemented locally | `scripts/dogfood_memoryendpoints.py` generated `docs/reports/dogfood-memory-run.json` with local WSGI readback, ack, receipts, and protected audit-log readback. |
| Latest-code MemoryEndpoints.com deployment | Verified | `docs/reports/deploy-live-attempt-latest.json` and `docs/reports/live-latest-code-verification.json`. |
| Live dogfood | Verified full live contract | `docs/reports/dogfood-memory-run.json` distinguishes `liveCoreDogfoodVerified` from full `liveDogfoodVerified`. |
| MultiAgentMemory.com live companion site | Verified | `docs/reports/multiagentmemory-deploy-live-attempt-latest.json` and `docs/reports/multiagentmemory-live-site-verification.json`. |
| Live MySQL/MariaDB database backend | Not verified | `docs/reports/live-mysql-backend-verification.json` and `/api/version` `storeBackendVerified`. |
| Prompt drafts | Local-only | `docs/prompts/*.md` is ignored and excluded from packaging. |

## Remaining Gaps Before Full Goal Completion

| Requirement | Current state | Needed evidence before claiming done |
| --- | --- | --- |
| Latest-code live deployment | Verified through FileZilla-backed explicit FTPS deploy; live `/api/version` source SHA match is `true` | Rerun package, dry-run, FTPS deploy, Passenger restart, and live route/latest-code verification after each source change. |
| MultiAgentMemory.com live publish | Verified through FileZilla-backed explicit FTPS publish and live static-site verification | Rerun static dry-run, publish, and live static-site verification after companion source changes. |
| Live dogfooding | Full live dogfood contract verified for the currently deployed API. | After each latest-code deploy, rerun live dogfood and refresh `docs/reports/dogfood-memory-run.json`. |
| Relational production database | Blocked; live runtime is not verified on MySQL/MariaDB | Configure real MySQL/MariaDB credentials outside Git, deploy, then rerun `scripts/verify_mysql_backend.py` until `/api/version` reports `storeBackendVerified: true`. |
| GitHub Actions CI | Not required by human direction; workflow retained in repository | Use local verification plus live deploy, live route, and live dogfood evidence; see `docs/reports/github-ci-gate-decision.json`. |
| Full enterprise completion audit | Ready only when current-commit deploy/live verification and live MySQL verification pass | Rerun package, deploy, live SHA/routes, MySQL backend verification, dogfood, secret scan, `.uai` audit, and remote SHA verification after the final commit. |

## Claim Boundary

The repository is improved, but completion is blocked until the live MemoryEndpoints.com runtime is verified on real MySQL/MariaDB and the current commit is redeployed and dogfooded.
