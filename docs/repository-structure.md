# Repository Structure

The repository is organized around a deployable endpoint app plus a documentation companion site.

## Runtime Surface

- `app.py` exposes the WSGI application for local and import-based use.
- `passenger_wsgi.py` is the Passenger/cPanel entry point.
- `memoryendpoints/` contains the pure Python runtime package.
- `static/` contains browser assets used by MemoryEndpoints.com.

## Documentation Surface

- `docs/` contains curated architecture, API, storage, schema, reports, prompts, and long-term memory records.
- `sites/multiagentmemory.com/` contains the public documentation companion site for https://multiagentmemory.com, including its GitHub repository links and AI-readable discovery files.
- `examples/` contains public-safe request examples.

## Agent Memory Surface

- `.uai/` contains short-term/startup memory and pointer ledgers.
- `agent-file-handoff/` contains local intake buckets. Raw active intake files are ignored by Git and should be summarized into reviewed reports or `.uai` ledgers.

## Operational Surface

- `scripts/` contains stdlib verification, packaging, migration, static-site deployment, endpoint deployment, and readiness helpers.
- `tests/` contains the standard-library unit test suite.
- `.github/` contains repository hygiene automation.

## Publishing Boundary

The repository root remains deployable for MemoryEndpoints.com. The companion documentation site lives under `sites/multiagentmemory.com/` so it is visible but not confused with the runtime package. MultiAgentMemory.com deploys as static files from that folder.

Local stores, deployment packages, logs, caches, FTP handoff files, and dropped raw intake files are excluded from version control.
