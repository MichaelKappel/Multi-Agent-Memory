# Release Verification Summary

MemoryEndpoints.com has a verified public surface as of 2026-07-09, and the latest deployed source SHA is proven live when `/api/version` matches the checked Git head.

Current verified state:

- Live site: `https://memoryendpoints.com`
- Public route verification: 21 checked routes, 0 failures for the deployed public surface.
- `/docs` and `/docs/`: both valid documentation pages.
- GitHub Actions is retained as a repository workflow but is not a required completion gate per human direction. MySQL/MariaDB runtime verification is required before production completion.
- MultiAgentMemory.com source is populated locally under `sites/multiagentmemory.com/`, published through the FileZilla-backed explicit FTPS profile, and live-verified with zero route/discovery failures. The stale handoff section for this domain still fails login and is retained only as redacted diagnostic evidence.
- Package check: excludes local stores, journals, logs, caches, `dist`, `.uai`, local prompts, raw Agent File Handoff bucket contents, and credential handoff files.
- Storage: file backend and SQLite relational MATM tables are active locally; production completion requires live MySQL/MariaDB verification.
- Secrets: package-eligible plus `.uai` secret scan passes with 0 hits; deploy reports are redacted.

Durable evidence:

- `docs/reports/final-readiness-report.md`
- `docs/reports/local-verification-report.json`
- `docs/reports/package-verification-report.json`
- `docs/reports/local-route-verification.json`
- `docs/reports/live-route-verification.json`
- `docs/reports/deploy-attempt-20260709.json`
- `docs/reports/deploy-connection-check-latest.json`
- `docs/reports/deploy-connection-check-ftp-latest.json`
- `docs/reports/multiagentmemory-deploy-live-attempt-latest.json`
- `docs/reports/multiagentmemory-deploy-connection-check-latest.json`
- `docs/reports/multiagentmemory-deploy-connection-check-ftp-latest.json`
- `docs/reports/multiagentmemory-live-site-verification.json`
- `docs/database-schema-canonical.sql`
- `docs/storage-backends.md`
