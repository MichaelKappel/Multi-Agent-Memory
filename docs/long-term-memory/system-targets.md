# System Targets

Purpose: durable target memory for MemoryEndpoints.com engineering strategy.

## Python Engineering Targets

- Keep dependencies explicit and minimal; the MySQL/MariaDB Python driver is approved because production completion requires a real MySQL/MariaDB backend.
- Keep `memoryendpoints/` as the application package boundary and avoid unrelated framework migration.
- Continue expanding tests around storage backends, protected MATM workflows, idempotency, memory firewall behavior, and report generation.
- Add abstractions only where they reduce real duplication or clarify a repeated route/storage contract.
- Keep command-line verification scripts deterministic and redacted.

## Testing And Verification Targets

- Maintain the required local gate: unit tests, WSGI verifier, `.uai` audit, package check, secret scan, enterprise readiness audit, and `git diff --check`.
- Maintain live gates separately: live public-route verifier, live MySQL/MariaDB backend verification, live MATM dogfood, and latest-code deployment verification.
- Keep dogfood reports public-safe: no raw workspace ids, API keys, bearer tokens, one-time keys, FTP credentials, database passwords, or private payload bodies.
- Expand integration tests for review queue decisions, SQLite parity, quota boundaries, idempotency replay, and redacted receipt guarantees.
- Add regression checks whenever a readiness report changes claim boundaries.

## Database And MySQL Targets

- Keep file storage and SQLite relational MATM tables active for local development and verification only.
- Require MySQL/MariaDB for production completion, with `/api/version` proving `storeBackendVerified: true`.
- Preserve canonical schema coverage for hierarchy memory, crawl/search metadata, current messages, receipts, review queue, idempotency, outbox, quota ledger, and audit.
- Before any MySQL production claim, require migration dry runs, restore drills, least-privilege role review, TLS/encryption review, observability, and RPO/RTO documentation.
- Avoid database topology overclaims. Distinguish single instance, source/replica, managed HA, InnoDB Cluster, cross-region DR, and sharding.

## MATM Product Targets

- Keep MemoryEndpoints.com as the mid-to-long-term MATM endpoint and MultiAgentMemory.com as companion documentation with direct links to the GitHub repository and detailed architecture guidance.
- Keep `.uai/totem.uai` as a non-retirement invariant: local `.uai` stays active always.
- Keep `.uai` as a typed active suite. Do not add files named `short-term-memory.uai`, `active-memory.uai`, `current-state.uai`, `project-state.uai`, `working-state.uai`, or equivalent under any purpose or interpretation.
- Make every protected mutation idempotent where retries are realistic.
- Keep public evidence routes current and bounded: readiness, capability matrix, route inventory, redacted receipts, AI manifest, and discovery files.
- Improve hosted MATM toward richer review decisions, pointer-ledger export, memory graph traversal, and authenticated durable-memory search without exposing secrets.

## Operational System Targets

- Keep latest-code live deployment verified through the FileZilla-backed explicit FTPS profile, followed by `/api/version` SHA verification.
- Keep the GitHub Actions workflow in the repository, but do not treat the account/billing-locked runner as a required completion gate unless the human re-enables it.
- Keep package exclusions strict for `.git`, `.github`, `.uai`, local prompts, raw Agent File Handoff bucket contents, runtime stores, databases, logs, caches, `dist`, and credential handoffs.
- Keep deploy reports redacted and safe no-op when credentials or remote access fail before upload.

## Inbound-Link And Documentation Targets

- UAIX setup option for this repository: `https://uaix.org/en-us/tools/ai-memory-package-wizard/#setup-MATM-MemoryEndpoints`.
- MemoryEndpoints.com inbound URL: `https://memoryendpoints.com`.
- MemoryEndpoints.com currently has one setup surface; inbound links should use the home page.
- Future MemoryEndpoints setup URLs should be clean readable routes, not fragment-style option URLs.
- MultiAgentMemory.com should explain architecture and memory boundaries, not act as the hosted endpoint.
- MultiAgentMemory.com live publishing must be verified separately from MemoryEndpoints.com deployment; a local companion site source tree is not enough to claim the domain is live.
