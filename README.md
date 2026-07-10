# Multi-Agent Memory

[![CI](https://github.com/MichaelKappel/Multi-Agent-Memory/actions/workflows/ci.yml/badge.svg)](https://github.com/MichaelKappel/Multi-Agent-Memory/actions/workflows/ci.yml)

Production-grade, source-available reference implementation for Multi-Agent Transactive Memory (MATM).

This repository contains two coordinated surfaces:

| Surface | Role | Status |
| --- | --- | --- |
| [MemoryEndpoints.com](https://memoryendpoints.com) | MATM endpoint, public AI-ready discovery, protected workspace memory APIs | Live-verified and deployed from the pushed source SHA |
| [MultiAgentMemory.com](https://multiagentmemory.com) | Static GitHub companion documentation site for the public memory model | Live-published companion documentation |

The runtime is deliberately small: Python standard library WSGI, committed browser JavaScript generated from TypeScript source, semantic HTML5, CSS, and no package-managed third-party runtime dependencies.

## What This Is

MemoryEndpoints.com is a deployable MATM endpoint reference. It provides:

- Public AI-ready discovery files and evidence routes.
- Free agent workspace setup with a 200 MB quota.
- Account-company-workspace-project hierarchy with many-to-many account/company memberships.
- One-time workspace keys with server-side hash storage only.
- Protected workspace status, agent registration, memory submit/search, current-message, acknowledgement, and redacted receipt routes.
- A browser-based human verification console at [MemoryEndpoints.com/console](https://memoryendpoints.com/console).
- File-backed local storage, stdlib SQLite relational local storage, and a MySQL/MariaDB production backend selected by environment.

The repository does not vendor, pin, install, or package a MySQL driver. The live cPanel deployment can use a host-provided MySQL Python adapter when the MySQL backend is selected; stdlib SQLite remains the pure-Python relational backend for environments that require zero host-provided database adapters.

MultiAgentMemory.com is plain HTML/CSS documentation only. It explains the architecture, memory boundary, GitHub repository structure, and GitHub-facing handoff model. It does not run the MATM endpoint API; MemoryEndpoints.com owns that runtime.

## Memory Boundary

| Layer | Location | Purpose |
| --- | --- | --- |
| Active startup memory | `.uai/` | Current instructions, constraints, progress state, pointer ledgers, and all files in the startup read order |
| Mid-to-long-term memory | [MemoryEndpoints.com](https://memoryendpoints.com) | Authenticated durable MATM memory, current messages, notifications, receipts, and redacted audit trails |
| Public documentation | [MultiAgentMemory.com](https://multiagentmemory.com) and `sites/multiagentmemory.com/` | Companion docs and AI-readable public discovery |

The totem invariant lives in `.uai/totem.uai`: local `.uai` stays active always. Hosted MATM augments durable memory, but it never replaces local startup continuity or offline recovery memory.

No single catch-all `.uai` file is "the" active memory. Every `.uai/*.uai` file in `.uai/startup-packet.uai` read order is active memory, and active `.uai` stays date-free operational memory.

UAIX setup reference: use the [MemoryEndpoints.com MATM setup option](https://uaix.org/en-us/tools/ai-memory-package-wizard/#setup-MATM-MemoryEndpoints) for this repository's `.uai` package pattern. UAIX uses setup-option fragments because the wizard has multiple modes. MemoryEndpoints.com inbound links should use the [home page](https://memoryendpoints.com); it currently has one setup surface, and any future setup-specific MemoryEndpoints URLs should be clean readable routes.

## Repository Layout

```text
.
|-- .github/                    # CI and PR hygiene
|-- .uai/                       # Agent startup memory, totem invariant, and pointer ledgers
|-- agent-file-handoff/         # Local-only intake buckets, tracked as empty inboxes
|-- docs/                       # API, storage, schema, reports, prompts, and architecture docs
|-- examples/                   # Public-safe request examples
|-- memoryendpoints/            # Pure Python stdlib WSGI application package
|-- scripts/                    # Verification, packaging, migration, and deploy helpers
|-- sites/multiagentmemory.com/ # Companion documentation site
|-- static/                     # MemoryEndpoints.com CSS, JS, and image assets
|-- tests/                      # stdlib unittest suite
|-- app.py                      # WSGI app export for local/import use
`-- passenger_wsgi.py           # Passenger/cPanel WSGI entry point
```

See [docs/repository-structure.md](docs/repository-structure.md) for ownership and publishing boundaries.
See [docs/verification.md](docs/verification.md) and [docs/deployment.md](docs/deployment.md) for rerunnable operating checks.

## Public Evidence

- [Version](https://memoryendpoints.com/api/version)
- [Capability matrix](https://memoryendpoints.com/api/matm/live-capability-matrix)
- [Route inventory](https://memoryendpoints.com/api/matm/route-inventory)
- [Readiness result](https://memoryendpoints.com/api/matm/readiness-result)
- [Redacted receipt examples](https://memoryendpoints.com/api/matm/redacted-example-receipts)
- [AI manifest](https://memoryendpoints.com/ai-manifest.json)

Current bounded readiness status is recorded in [docs/reports/final-readiness-report.md](docs/reports/final-readiness-report.md). Tracked reports are point-in-time evidence; rerun the verification commands after source changes before claiming the live site is current.

## Quick Start

```powershell
python run_dev.py
```

Open `http://127.0.0.1:8088/`.

Default local storage is JSON under `var/`. For stdlib SQLite relational database-backed storage:

```powershell
$env:MEMORYENDPOINTS_STORE_BACKEND='sqlite'
$env:MEMORYENDPOINTS_SQLITE_PATH='E:\MemoryEndpoints.com\var\matm_store.sqlite3'
python run_dev.py
```

Production MySQL/MariaDB storage is selected with `MEMORYENDPOINTS_STORE_BACKEND=mysql` plus an ignored `.local-secrets/mysql.json` file outside Git, `MEMORYENDPOINTS_MYSQL_*` credentials, or `MEMORYENDPOINTS_MYSQL_URL`. When `.local-secrets/mysql.json` exists it is authoritative over environment values so cPanel/stale process variables cannot silently override the deployed database credential file. `/api/version` must report `storeBackend: mysql` or `mariadb` and `storeBackendVerified: true` before the live site is considered to be using real MySQL.

## Verification

```powershell
python -m unittest discover -s tests
python scripts\verify_memoryendpoints.py --wsgi
python scripts\verify_static_site.py
python scripts\secret_scan.py
python scripts\package_memoryendpoints.py --check-only
python scripts\audit_uai_memory.py
python scripts\enterprise_readiness_audit.py --run-checks
python scripts\build_readiness_reports.py --write
```

## Deployment

Deployment credentials stay outside this repository. The local `E:\ftp_Deploy.txt` handoff is read only by deploy tooling and must never be committed or printed.

```powershell
python scripts\package_memoryendpoints.py
python scripts\ftp_deploy_memoryendpoints.py --dry-run --filezilla-site-match memoryendpoints --protocol ftps
```

The verified deployment path uses the FileZilla MemoryEndpoints profile with explicit FTPS. Plain FTP is not the verified publish route.

## Security And Claims

- No raw secrets belong in repository files, reports, examples, logs, public pages, or final answers.
- Unsupported, malformed, unauthorized, or authority-gated operations return safe no-op JSON.
- No certification, endorsement, hidden credential validation, hosted agent execution, automatic repository writes, or automatic memory promotion is claimed.
- MySQL/MariaDB runtime activation requires real environment configuration and must be verified through `/api/version`; file storage is not a production database claim.

## License

This repository uses the MemoryEndpoints Source-Available License. You may study, run, test, and contribute to the work, but you may not copy the whole project, strip attribution, and present it as your own original product. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
