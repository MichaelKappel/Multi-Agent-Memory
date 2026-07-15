# Repository Structure

The repository is organized around a deployable private-intranet endpoint app plus a public documentation companion site.

## Runtime Surface

- `app.py` exposes the WSGI application for local and import-based use.
- `passenger_wsgi.py` is the Passenger/cPanel entry point.
- `memoryendpoints/` contains the pure Python runtime package.
- `memoryendpoints/uai_memory.py` defines the accountless-browser virtual UAIX profile, date-free record validation, and hash-only local `.uai` collaboration contract; persistence remains in `memoryendpoints/storage.py` and routing remains in `memoryendpoints/app.py`.
- `static/` contains browser assets used by the private MATM intranet runtime.

## Documentation Surface

- `docs/` contains checked-in engineering architecture, API, storage, schema, verification, product-boundary, and deployment guidance. Historical reports and strategy notes are point-in-time evidence, not the durable product knowledge source of truth.
- `sites/multiagentmemory.com/` contains the public documentation companion site for https://multiagentmemory.com, including its complete API/data reference, GitHub repository links, and AI-readable discovery files for the public GitHub edition.
- `examples/` contains public-safe request examples.

## Agent Memory Surface

- `.uai/` contains the typed active startup memory suite, pointer ledgers, totem invariant, and local continuity records. Every file in the startup read order is active memory, and forbidden duration/state filenames such as `short-term-memory.uai` and `current-state.uai` are not allowed as actual local files. The protected accountless-browser package can represent its configuration-specific short-term logical role virtually because it creates no repository file.
- When multiple local agents share this codebase, their `.uai` bodies remain local. They coordinate a path before editing through protected hash-only file heads and bounded edit claims, then use the project meeting room and source control for content reconciliation.
- `agent-file-handoff/` contains local intake buckets. Raw active intake files are ignored by Git and are reviewed one item at a time into protected MATM database wiki pages and source-linked memory. `.uai` retains compact startup continuity and semantic pointers, not report bodies.

## Operational Surface

- `scripts/` contains stdlib verification, packaging, migration, static-site deployment, endpoint deployment, and readiness helpers.
- `tests/` contains the standard-library unit and integration suite, including route/documentation freshness, backend parity, protected workflow, sync, and verifier coverage.
- `var/reports/` contains ignored point-in-time verifier output for the current worktree or live release.
- `.github/` contains repository hygiene automation.

## Publishing Boundary

The repository root remains deployable as the free private-intranet MATM edition. The companion documentation site lives under `sites/multiagentmemory.com/` so it is visible but not confused with the runtime package. MultiAgentMemory.com deploys as static files from that folder and remains the public GitHub companion site.

MemoryEndpoints.com public hosted branding, authenticated business-model code, pricing, billing, paid storage, paid NPC memory stores, sponsored partner setup, and customer-facing sales operations belong in a separate private commercial repository. See [product-boundary.md](product-boundary.md).

Local stores, deployment packages, logs, caches, FTP handoff files, and dropped raw intake files are excluded from version control.
