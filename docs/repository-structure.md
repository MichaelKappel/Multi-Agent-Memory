# Repository Structure

The repository is organized around a deployable endpoint app plus a documentation companion site.

## Runtime Surface

- `app.py` exposes the WSGI application for local and import-based use.
- `passenger_wsgi.py` is the Passenger/cPanel entry point.
- `memoryendpoints/` contains the pure Python runtime package.
- `static/` contains browser assets used by MemoryEndpoints.com.

## Documentation Surface

- `docs/` contains checked-in engineering architecture, API, storage, schema, verification, and deployment guidance. Historical reports and strategy notes are point-in-time evidence, not the durable product knowledge source of truth.
- `sites/multiagentmemory.com/` contains the public documentation companion site for https://multiagentmemory.com, including its complete API/data reference, GitHub repository links, and AI-readable discovery files.
- `examples/` contains public-safe request examples.

## Agent Memory Surface

- `.uai/` contains the typed active startup memory suite, pointer ledgers, totem invariant, and local continuity records. Every file in the startup read order is active memory, and forbidden duration/state filenames such as `short-term-memory.uai` and `current-state.uai` are not allowed.
- `agent-file-handoff/` contains local intake buckets. Raw active intake files are ignored by Git and are reviewed one item at a time into protected MemoryEndpoints database wiki pages and source-linked memory. `.uai` retains compact startup continuity and semantic pointers, not report bodies.

## Operational Surface

- `scripts/` contains stdlib verification, packaging, migration, static-site deployment, endpoint deployment, and readiness helpers.
- `tests/` contains the standard-library unit and integration suite, including route/documentation freshness, backend parity, protected workflow, sync, and verifier coverage.
- `var/reports/` contains ignored point-in-time verifier output for the current worktree or live release.
- `.github/` contains repository hygiene automation.

## Publishing Boundary

The repository root remains deployable for MemoryEndpoints.com. The companion documentation site lives under `sites/multiagentmemory.com/` so it is visible but not confused with the runtime package. MultiAgentMemory.com deploys as static files from that folder.

Local stores, deployment packages, logs, caches, FTP handoff files, and dropped raw intake files are excluded from version control.
