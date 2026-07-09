# Enterprise MATM Gap Matrix

Generated: 2026-07-09

## Current Verified Improvements

| Area | Status | Evidence |
| --- | --- | --- |
| `.uai` startup memory | Improved locally | Active `.uai/*.uai` files are typed, date-free, public-safe, update-route aware, and audited by `scripts/audit_uai_memory.py`. |
| `.uai` totem invariant | Implemented locally | `.uai/totem.uai` says local `.uai` stays active always and hosted MATM never replaces startup continuity. |
| Protected MATM workflows | Implemented locally | `tests/test_app.py` covers free account, one-time key hash persistence, registration, memory submit/search, firewall redaction, review queue, current message, ack, receipts, audit log, idempotency, and safe no-op errors. |
| Dogfood runner | Implemented locally | `scripts/dogfood_memoryendpoints.py` generated `docs/reports/dogfood-memory-run.json` with local WSGI readback, ack, receipts, and protected audit-log readback. |
| Live core dogfood | Verified current deployed surface | `docs/reports/dogfood-memory-run.json` distinguishes `liveCoreDogfoodVerified` from full `liveDogfoodVerified`. |
| Prompt drafts | Local-only | `docs/prompts/*.md` is ignored and excluded from packaging. |

## Remaining Gaps Before Full Goal Completion

| Requirement | Current state | Needed evidence before claiming done |
| --- | --- | --- |
| Latest-code live deployment | Blocked by hosting login rejection before upload; no-upload connection checks show `ftps/connection_check_failed/0 uploads, ftp/connection_check_failed/0 uploads`; live `/api/version` source SHA match is `false`. | Refresh hosting credential/server access outside the repo, then rerun package, dry-run deploy, no-upload connection check, live deploy, Passenger restart, and live route verification. |
| MultiAgentMemory.com live publish | Blocked by hosting login rejection before upload; no-upload connection checks show `ftps/connection_check_failed/0 uploads, ftp/connection_check_failed/0 uploads`. | Refresh hosting access, publish `sites/multiagentmemory.com/`, then rerun live static-site verification. |
| Live dogfooding | Live core MATM dogfood is verified for the currently deployed API; latest protected audit-log dogfood contract is still blocked because the latest route tranche is not deployed. | Deploy the latest code, verify `/api/version` reports the pushed SHA, then rerun live dogfood and prove protected audit-log readback. |
| Relational production database | Schema-ready and stdlib SQLite relational table-backed; MySQL/MariaDB runtime remains adapter-gated. | Approved adapter path or honest continued gated status. Do not claim MySQL/MariaDB is live. |
| CI status after latest push | `failure` for current observed SHA `7234135b8075`; Latest GitHub Actions run failed before workflow steps executed: The job was not started because your account is locked due to a billing issue. | Resolve GitHub account/Actions blocker, then require a passing CI run for the pushed SHA. |
| Full enterprise completion audit | Partial because live deployment, latest live dogfood contract, companion live publish, CI, and MySQL adapter gates remain unresolved. | Requirement-by-requirement completion audit against the goal objective after live verification succeeds. |

## Claim Boundary

The repository is improved, but the full objective is not complete. Current evidence supports local MATM hardening, local dogfood, and live core dogfood for the currently deployed surface; it does not support a full completion claim until latest-code deployment, latest-contract live dogfood, companion live publish, CI, and gated capabilities are resolved or explicitly waived.
