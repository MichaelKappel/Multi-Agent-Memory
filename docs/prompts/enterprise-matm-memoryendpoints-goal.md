# Enterprise MATM Goal Prompt for MemoryEndpoints.com

Use this prompt when assigning an agent to finish MemoryEndpoints.com and the companion MultiAgentMemory.com documentation site as a production-quality MATM reference implementation.

## Mission

Build `E:\MemoryEndpoints.com` into the public, enterprise-quality reference implementation for pure MATM Multi-Agent Transactive Memory. The finished result must be good enough to publicly represent the MemoryEndpoints.com project and the `MichaelKappel/Multi-Agent-Memory` GitHub repository without looking like a prototype, scrapbook, or partial migration.

This is not complete until the repository, live site, documentation site, memory system, automated verification, deployment packaging, and GitHub state all prove the goal is satisfied.

## Primary Properties

- Repository root: `E:\MemoryEndpoints.com`
- GitHub repository: `https://github.com/MichaelKappel/Multi-Agent-Memory`
- Main product site: `https://memoryendpoints.com`
- Companion documentation site: MultiAgentMemory.com content lives inside this repository, under `sites/multiagentmemory.com`
- Requested MATM wizard setup reference: `https://uaix.org/en-us/tools/ai-memory-package-wizard/#setup-MATM`
- Requested File Handoff plus MATM setup reference: `https://uaix.org/en-us/tools/ai-memory-package-wizard/#setup-file-handoff-MATM`
- Mid-term and long-term memory system of record: MemoryEndpoints.com
- Local long-term memory fallback until hosted memory is fully verified: `E:\MemoryEndpoints.com\docs` and `.uai`
- NeuralWikis concept source: `E:\NeuralWikis.com`

## Non-Negotiable Outcome

The result must feel and behave like an enterprise application:

- Organized repository structure.
- High-quality Python code.
- Clear, bounded public claims.
- Strong docs.
- Integration tests that prove actual workflows.
- Automation that can be rerun.
- Secret-safe reports.
- Deployment packaging that excludes runtime state and credentials.
- GitHub presentation that looks intentional and professional.
- A working MATM dogfooding flow that uses MemoryEndpoints.com for mid-term and long-term memory rather than merely describing memory in prose.

Do not call the goal done because pages render. Do not call the goal done because tests pass if the tests are shallow. Do not call the goal done because a deployment succeeded if the deployed system has not been verified end-to-end.

## Source Material Rules

Use `E:\NeuralWikis.com` only as a private concept and architecture reference. Extract lessons, patterns, workflow ideas, verification discipline, and MATM operating concepts. Do not copy over public NeuralWikis wiki pages, branding, marketing language, generated public wiki content, public claims, or unrelated site material.

When inspecting NeuralWikis:

- Prefer file names, architecture docs, tests, schemas, and non-secret implementation concepts.
- Avoid copying prose directly.
- Avoid importing public wiki content.
- Avoid secrets, `.env`, FTP handoff files, private keys, tokens, local runtime databases, logs, or generated deployment artifacts.
- If secrets must be consulted to understand deployment boundaries, never print them, never commit them, and never include them in logs, reports, summaries, or final answers.

The finished MemoryEndpoints.com codebase should show what was learned from NeuralWikis, but it must be its own product with its own public identity.

## Technology Constraints

Build the runtime using:

- Python standard library.
- TypeScript where already appropriate for frontend source.
- HTML5, CSS, and browser-native JavaScript.

Do not add third-party runtime dependencies unless the human explicitly approves them later. If tooling dependencies are used for local verification, keep the runtime boundary clear.

Because the Python standard library has no MySQL/MariaDB client, do not pretend that MySQL is live unless it is actually wired with an approved dependency or deployment adapter. Provide and verify a standard-library persistence path, such as SQLite or file-backed storage, and document exactly where MySQL activation is gated.

## Product Boundary

MemoryEndpoints.com is the real MATM memory endpoint product site and API.

MultiAgentMemory.com is the companion documentation and GitHub-facing explanation site. It should help agents and humans understand how to use the system, but it should not become a confusing duplicate repository or independent deployment tree outside `E:\MemoryEndpoints.com`.

The `E:\` drive must not contain duplicate active site folders for the same product. Keep `E:\MemoryEndpoints.com` as the source of truth for both MemoryEndpoints.com and MultiAgentMemory.com content.

## MATM Capability Requirements

Implement and verify the following capabilities as real, testable behavior:

- Public AI-ready website with human-readable pages.
- Agent-readable discovery routes.
- Public evidence routes.
- Free account creation without checkout.
- One-time workspace API key reveal.
- Server-side API key hashing.
- 200 MB free workspace quota.
- Workspace status and quota inspection.
- Agent registration.
- Durable memory event submission.
- Durable memory search.
- Documentation-backed long-term memory search.
- Current-message creation.
- Current-message readback.
- Notification acknowledgement.
- Redacted receipt readback.
- Review and promotion queue for memory events.
- Safe memory redaction before persistence and before public reporting.
- Audit logging for protected operations.
- Idempotent mutation handling.
- Safe no-op behavior for unsupported, malformed, unauthorized, gated, or unavailable operations.

Protected mutation routes must support idempotency:

- Exact retry with the same idempotency key and the same body returns the original response and status.
- Reuse of the same idempotency key with a different body returns a conflict-safe no-op response.
- Idempotency records must not leak secrets.

Current messages must use clear response states:

- `required_response`
- `viewed_acknowledgement`

Avoid vague `optional` wording in agent-facing instruction surfaces.

## Required Public Routes

Verify at least these public routes:

- `/`
- `/docs`
- `/docs/`
- `/agent-setup`
- `/memory-lifecycle`
- `/transparency`
- `/robots.txt`
- `/sitemap.xml`
- `/llms.txt`
- `/llms-full.txt`
- `/ai.txt`
- `/ai-manifest.json`
- `/.well-known/mcp.json`
- `/.well-known/ai-agent.json`
- `/mcp/resources`
- `/api/version`
- `/api/matm/live-capability-matrix`
- `/api/matm/route-inventory`
- `/api/matm/readiness-result`
- `/api/matm/redacted-example-receipts`

Known issue to explicitly verify: `/docs` may redirect to `/docs/`. Both must return a valid MemoryEndpoints documentation experience.

## Required Protected API Workflows

Build integration tests that exercise the real route handlers, not just isolated helper functions:

1. Create a free workspace.
2. Capture the one-time workspace key from the response.
3. Prove the stored key is hashed and the raw key is not persisted.
4. Register an agent.
5. Submit a memory event.
6. Search memory and retrieve the event.
7. Submit a memory event containing secret-like test strings.
8. Prove the secret-like values are redacted or rejected according to the memory firewall policy.
9. Create a current message.
10. Read the current message back.
11. Acknowledge notification state.
12. Read back redacted receipts.
13. Retry an idempotent mutation with the same key and same body.
14. Reuse the same idempotency key with a different body and prove conflict-safe no-op behavior.
15. Exercise unauthorized, malformed, unsupported, and authority-gated paths and prove safe no-op JSON responses.

## Dogfooding Requirement

MemoryEndpoints.com must dogfood itself.

Implement a repeatable local dogfood runner that uses the actual MemoryEndpoints API surface, preferably through the WSGI app or a live URL mode:

- Create or use a MemoryEndpoints dogfood workspace.
- Register a MemoryEndpoints build/release agent.
- Submit a public-safe memory event summarizing the current repo state.
- Search for that memory through the MemoryEndpoints memory search endpoint.
- Create a current message for a follow-up agent.
- Read the current message back.
- Acknowledge notification state.
- Generate a redacted dogfood report under `docs/reports`.
- Update `.uai` progress memory with a public-safe summary and an update URL.

The dogfood runner must never persist raw API secrets, one-time keys, FTP credentials, database passwords, or private handoff material in reports or `.uai`.

The final claim must distinguish between:

- Local dogfooding verified.
- Live dogfooding verified.
- GitHub evidence published.
- Remaining gated items.

Do not imply live dogfooding if only local WSGI dogfooding was run.

## `.uai` Requirements

The `.uai` directory must function as startup/file-handoff memory for agents.

Every active `.uai` handoff or progress file should include:

- Purpose.
- Last verified date.
- Memory scope.
- Public-safe status.
- Update URL or intended update route.
- Source-of-truth location.
- What agents should do next.
- What agents must not expose.

Add an explicit prompt for the UAIX.org agent requesting that the UAIX spec, wizard, and setup guidance support MATM-backed `.uai` packages. That prompt should reference:

- `https://uaix.org/en-us/tools/ai-memory-package-wizard/#setup-MATM`
- `https://uaix.org/en-us/tools/ai-memory-package-wizard/#setup-file-handoff-MATM`
- The need to distinguish short-term `.uai` startup/file-handoff memory from MemoryEndpoints.com mid-term and long-term MATM memory.
- The requirement that agents know the configured MATM `update_url` where safe memory updates should be submitted without guessing.
- The requirement that MemoryEndpoints.com is presented only as a suggested/example MATM endpoint, not as UAIX certification or endorsement.

## Database and Storage Requirements

Improve the database model before live data depends on it.

Maintain a canonical relational schema covering:

- Clients.
- Workspaces.
- Projects.
- API keys.
- Agents.
- Scoped durable memory.
- Memory revisions.
- Memory tags.
- Crawl sources.
- Searchable documents.
- Current messages.
- Notifications.
- Receipts.
- Review and promotion queue.
- Idempotency records.
- Outbox events.
- Storage ledger.
- Audit log.

The implementation must clearly document:

- What storage backend is active locally.
- What storage backend is active in production.
- Whether SQLite is used.
- Whether file storage is used.
- Whether MySQL/MariaDB is only schema-ready or actually active.
- What migration path exists between file, SQLite, and MySQL/MariaDB.
- How secrets are excluded from storage and reports.

If the active code still uses a JSON blob inside SQLite or a file store, do not represent it as a full relational production database. State the boundary honestly and prioritize a real relational upgrade if required by the goal.

## Python Quality Bar

Treat the Python code like a serious enterprise codebase:

- Clear module boundaries.
- Typed data structures where helpful.
- Small, testable functions.
- Consistent error envelopes.
- No accidental global mutable state beyond controlled store instances.
- Secret redaction before logging, reporting, receipts, and persistence.
- Deterministic tests.
- No hidden network calls in unit tests.
- No reliance on local machine secrets for default test success.
- No broad exception swallowing without safe structured output.
- No public route that can expose local paths, credentials, raw traceback data, or private runtime state.

Prefer boring, reliable code over cleverness.

## Frontend and Site Quality Bar

The public sites must look intentional and professional:

- MemoryEndpoints.com must present the real product and evidence routes.
- MultiAgentMemory.com must present companion documentation without pretending to be a separate codebase.
- Avoid public wiki copy from NeuralWikis.
- Avoid overclaiming readiness.
- Route inventory, capability matrix, and readiness status must match verified behavior.
- Human docs and agent docs must agree.
- Public pages must not leak internal paths, secrets, local machine details, raw deploy credentials, or private handoff content.

## Documentation Requirements

The repository must include or update:

- `README.md`
- `AGENTS.md`
- `SECURITY.md`
- `CONTRIBUTING.md`
- `NOTICE`
- `CHANGELOG.md`
- API contract docs.
- Storage backend docs.
- Database docs.
- Route inventory.
- Repository structure docs.
- Test and verification docs.
- Deployment docs.
- Dogfood memory report.
- NeuralWikis concept intake report.
- UAIX update URL prompt.
- `.uai` startup/progress handoff memory.

Documentation must be consistent with implementation. If a capability is not implemented, label it as planned, gated, or schema-ready rather than live.

## Secret Safety Requirements

Keep secrets out of:

- Git.
- Reports.
- Logs.
- Public pages.
- Test fixtures.
- `.uai` files.
- Final answers.
- Deployment packages.

Never print:

- Passwords.
- API keys.
- Bearer tokens.
- Private keys.
- Raw one-time workspace keys.
- Full credential values.
- FTP secrets.
- Database passwords.

`E:\ftp_Deploy.txt` may contain deployment and database handoff material. Read it only when needed, redact all values, and never print credential values.

Deployment packages must exclude:

- `.git`
- `.local-secrets`
- Runtime databases.
- Local stores.
- Logs.
- Caches.
- `dist`
- Temporary files.
- Credential handoff files.
- Any generated report that contains secret-like values.

## Verification Commands

Before claiming completion, run and record the result of:

- Unit tests.
- Integration tests.
- WSGI route verifier.
- Package builder or package check.
- Secret scan.
- `git diff --check`.
- Deploy dry-run targeting the FTP root.
- Live deploy.
- Live route verifier against `https://memoryendpoints.com`.
- Package exclusion verification.
- GitHub push verification.

Completion requires zero live route failures for the required public routes.

## Required Reports

Create or update reports under `docs/reports`:

- Current implementation audit.
- NeuralWikis concept intake report.
- Enterprise gap matrix.
- Dogfood memory run report.
- Local verification report.
- Package verification report.
- Live route verification report.
- Final readiness report.

Each report must be public-safe, dated, and bounded by evidence.

## GitHub Requirements

The GitHub repository must look enterprise-quality:

- Clean root directory.
- Clear README.
- Professional docs layout.
- Useful examples.
- CI workflow.
- No duplicate abandoned site folders.
- No credentials.
- No generated noise.
- No misleading readiness claims.
- Commit history updated with the corrective work.
- Main branch pushed to `MichaelKappel/Multi-Agent-Memory`.

After pushing, verify the remote branch SHA.

## Definition of Done

The goal is done only when all of the following are true:

- The local repository is clean and organized.
- MemoryEndpoints.com source code implements the required MATM workflows.
- MultiAgentMemory.com companion docs are present inside the same repo.
- `.uai` memory includes safe update URL guidance.
- Dogfooding is implemented and verified.
- Integration tests cover the critical MATM workflows.
- Secret scanning passes.
- Package verification passes.
- WSGI route verification passes.
- Live route verification against `https://memoryendpoints.com` passes with zero required-route failures.
- Deployment package excludes secrets and local runtime state.
- Documentation matches implementation.
- Claims are bounded by evidence.
- GitHub main branch contains the final work.
- The final response clearly states what is complete, what was verified, and what remains gated if anything is not truly live.

If any item is incomplete, do not mark the goal complete. Record the blocker, record the evidence gathered, and continue the work or state the exact remaining gap.

## Final Response Requirements

The final response must be short, honest, and evidence-based. It must include:

- What changed.
- What was verified.
- What was pushed to GitHub.
- Whether live MemoryEndpoints.com was verified.
- Whether dogfooding was local or live.
- Any remaining gated items.

Do not say "fully done" unless every Definition of Done item above is satisfied.
