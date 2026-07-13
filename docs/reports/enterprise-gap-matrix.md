# Enterprise MATM Gap Matrix

Generated: 2026-07-13

## Current Verified Improvements

| Area | Status | Evidence |
| --- | --- | --- |
| `.uai` startup memory | Improved locally | Active `.uai/*.uai` files are typed, date-free, public-safe, update-route aware, and audited by `scripts/audit_uai_memory.py`. |
| `.uai` totem invariant | Implemented locally | `.uai/totem.uai` says local `.uai` stays active always and hosted MATM never replaces startup continuity. |
| Protected MATM workflows | Implemented locally | `tests/test_app.py` covers free account, one-time key hash persistence, registration, memory submit/search, firewall redaction, review queue, current message, ack, receipts, audit log, idempotency, and safe no-op errors. |
| Dogfood runner | Implemented locally | `scripts/dogfood_memoryendpoints.py` generated `docs/reports/dogfood-memory-run.json` with local WSGI readback, meeting-message promotion to hosted memory, source-id memory readback, ack, receipts, and protected audit-log readback. |
| Hosted coordination memory loop | Verified locally | `Meeting-room coordination is dogfooded into hosted memory and verified by memory id plus source meeting-message id readback.` |
| Hosted long-term memory migration | Verified | `Hosted long-term memory is promoted and searchable from MemoryEndpoints storage; filesystem docs are excluded and duplicate seed copies are rejected.` |
| Latest-code MemoryEndpoints.com deployment | Verified | `docs/reports/deploy-live-attempt-latest.json` and `docs/reports/live-latest-code-verification.json`. |
| Live dogfood | Verified full live contract | `docs/reports/dogfood-memory-run.json` distinguishes `liveCoreDogfoodVerified` from full `liveDogfoodVerified`. |
| Live memory submit consistency | Verified | `Live memory submit response/readback consistency is verified across search, review queue, and audit log.` |
| Current-message fanout and acknowledgement isolation | Verified runtime and discovery | `docs/reports/current-message-fanout-verification.json` verifies runtime behavior; `docs/reports/live-connector-contract-verification.json` verifies public discovery contract fields. |
| MultiAgentMemory.com live companion site | Verified | `docs/reports/multiagentmemory-deploy-live-attempt-latest.json` and `docs/reports/multiagentmemory-live-site-verification.json`. |
| Live MySQL/MariaDB database backend | Verified | `docs/reports/live-mysql-backend-verification.json` and `/api/version` `storeBackendVerified`. |
| Prompt drafts | Local-only | `docs/prompts/*.md` is ignored and excluded from packaging. |

## Remaining Gaps Before Full Goal Completion

| Requirement | Current state | Needed evidence before claiming done |
| --- | --- | --- |
| Latest-code live deployment | Verified through FileZilla-backed explicit FTPS deploy; live `/api/version` source SHA match is `true` | Rerun package, dry-run, FTPS deploy, Passenger restart, and live route/latest-code verification after each source change. |
| MultiAgentMemory.com live publish | Verified through FileZilla-backed explicit FTPS publish and live static-site verification | Rerun static dry-run, publish, and live static-site verification after companion source changes. |
| Live dogfooding | Full live dogfood contract verified for the currently deployed API. | After each latest-code deploy, rerun live dogfood and refresh `docs/reports/dogfood-memory-run.json`. |
| Live memory submit consistency | Live memory submit response/readback consistency is verified across search, review queue, and audit log. | Rerun `scripts/verify_live_memory_submit_consistency.py` after each deployment or storage-path change. |
| Hosted long-term memory | Hosted long-term memory is promoted and searchable from MemoryEndpoints storage; filesystem docs are excluded and duplicate seed copies are rejected. | Rerun migration, promotion, duplicate-cleanup, and protected search readback after any long-term-memory source change. |
| Current-message fanout discovery contract | Full live current-message fanout and discovery contract verified. | Rerun fanout and connector-contract verifiers after each deployment. |
| Source worktree cleanliness | Dirty source paths remain | Commit or otherwise resolve source changes, then rerun no-write verification. |
| Relational production database | Verified live MySQL/MariaDB | Configure real MySQL/MariaDB credentials outside Git, deploy, then rerun `scripts/verify_mysql_backend.py` until `/api/version` reports `storeBackendVerified: true`. |
| GitHub Actions CI | Not required by human direction; workflow retained in repository | Use local verification plus live deploy, live route, and live dogfood evidence; see `docs/reports/github-ci-gate-decision.json`. |
| Full enterprise completion audit | Ready only when current-commit deploy/live verification and live MySQL verification pass | Rerun package, deploy, live SHA/routes, MySQL backend verification, dogfood, secret scan, `.uai` audit, and remote SHA verification after the final commit. |

## Claim Boundary

The repository is improved, but completion is blocked until the remaining tracked source cleanliness, live deployment, dogfood, MySQL/MariaDB, or companion-site gates are verified.
