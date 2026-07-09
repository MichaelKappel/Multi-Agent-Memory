# MemoryEndpoints.com

MemoryEndpoints.com is a pure Python, TypeScript, and HTML5 reference implementation for Multi-Agent Transactive Memory (MATM).

MultiAgentMemory.com is the GitHub companion documentation site for the same repository. MemoryEndpoints.com is the real endpoint site; MultiAgentMemory.com explains the public architecture, repository handoff, and AI-ready documentation boundary.

The project is designed as an AI-ready web endpoint: clear to humans, deterministic for agents, honest about authority boundaries, and usable without third-party runtime packages.

## Current Scope

- Pure Python stdlib WSGI app for cPanel/Passenger or local `wsgiref`.
- File-backed MATM storage for local and first deployment use.
- Docs-backed durable memory under `docs/` until hosted long-term memory is promoted.
- UAIX-style `.uai` startup memory and Agent File Handoff buckets.
- Public discovery routes for AI-ready crawlers and MCP-compatible hosts.
- Protected MATM routes for workspace setup, memory events, current messages, acknowledgements, and redacted receipts.
- Idempotent protected mutation routes for safe retries.
- Public readiness evidence at `/api/matm/readiness-result`.
- Workspace quota readback at `/api/matm/workspace`; free agent workspaces provide 200 MB without checkout or coupons.
- No raw secrets in repository files.

## Memory Boundary

- Short-term/startup memory: repository `.uai/` files.
- Mid-to-long-term memory: MemoryEndpoints.com protected MATM routes.
- Public documentation: `MultiAgentMemory.com/`.
- UAIX setup reference: https://uaix.org/en-us/tools/ai-memory-package-wizard/#setup-llm-wiki

## Runtime

```powershell
python run_dev.py
```

Then open `http://127.0.0.1:8088/`.

Default storage is a JSON file under `var/`. For stdlib database-backed storage, set:

```powershell
$env:MEMORYENDPOINTS_STORE_BACKEND='sqlite'
$env:MEMORYENDPOINTS_SQLITE_PATH='E:\MemoryEndpoints.com\var\matm_store.sqlite3'
python run_dev.py
```

## Verification

```powershell
python -m unittest discover -s tests
python scripts\verify_memoryendpoints.py --wsgi
python scripts\package_memoryendpoints.py --check-only
python scripts\secret_scan.py
```

API details are documented in [docs/api-contract.md](docs/api-contract.md). Public route inventory is exposed at `/api/matm/route-inventory`.

Current-message work is read through `/api/matm/current-message` and acknowledged through `/api/matm/notifications/ack`.

Database structure is documented in [docs/database-structure.md](docs/database-structure.md), with the canonical MySQL/MariaDB proposal in [docs/database-schema-canonical.sql](docs/database-schema-canonical.sql).

## Deployment

Deployment credentials stay outside this repo. The local `E:\ftp_Deploy.txt` handoff is read only by deploy tooling and must never be committed or printed.

```powershell
python scripts\package_memoryendpoints.py
python scripts\ftp_deploy_memoryendpoints.py --dry-run --handoff E:\ftp_Deploy.txt --remote-dir .
```

Remove `--dry-run` only after local tests, package checks, and live-route expectations are satisfied.
The FTP login directory is the MemoryEndpoints.com deployment root, so live deployment must also pass `--remote-dir .`.

## License

This repository uses the MemoryEndpoints Source-Available License. You may study, run, test, and contribute to the work, but you may not copy the whole project, strip attribution, and present it as your own original product. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
