# Release Verification Summary

MemoryEndpoints.com has a verified public surface as of 2026-07-09, but the latest repository tranche is not proven live.

Current verified state:

- Live site: `https://memoryendpoints.com`
- Public route verification: 21 checked routes, 0 failures for the currently deployed public surface.
- `/docs` and `/docs/`: both valid documentation pages.
- Local readiness reports keep `completionClaimAllowed=false`; blockers include latest-code live deployment, live authenticated dogfood for the latest audit-log contract, and GitHub Actions CI.
- MultiAgentMemory.com source is populated locally under `sites/multiagentmemory.com/`, but live publishing is blocked because the target FTPS login is rejected before upload; uploaded file count was zero. Live site verification currently fails because the home page lacks the expected companion links and companion routes return 404.
- Package check: excludes local stores, journals, logs, caches, `dist`, `.uai`, local prompts, raw Agent File Handoff bucket contents, and credential handoff files.
- Storage: file backend and stdlib SQLite backend are active locally; MySQL/MariaDB remains adapter-gated.
- Secrets: package-eligible plus `.uai` secret scan passes with 0 hits; deploy reports are redacted.

Durable evidence:

- `docs/reports/final-readiness-report.md`
- `docs/reports/local-verification-report.json`
- `docs/reports/package-verification-report.json`
- `docs/reports/local-route-verification.json`
- `docs/reports/live-route-verification.json`
- `docs/reports/deploy-attempt-20260709.json`
- `docs/reports/multiagentmemory-deploy-live-attempt-latest.json`
- `docs/reports/multiagentmemory-live-site-verification.json`
- `docs/database-schema-canonical.sql`
- `docs/storage-backends.md`
