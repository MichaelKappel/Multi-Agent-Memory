# Multi-Agent Memory

[![CI](https://github.com/MichaelKappel/Multi-Agent-Memory/actions/workflows/ci.yml/badge.svg)](https://github.com/MichaelKappel/Multi-Agent-Memory/actions/workflows/ci.yml)

Production-grade, source-available reference implementation for Multi-Agent Transactive Memory (MATM).

This repository contains two coordinated surfaces:

| Surface | Role | Status |
| --- | --- | --- |
| [MemoryEndpoints.com](https://memoryendpoints.com) | MATM endpoint, public AI-ready discovery, protected workspace memory APIs | Current public routes live-verified; latest-code deployment gated |
| `sites/multiagentmemory.com/` | GitHub companion documentation site for the public memory model | Repository docs |

The runtime is deliberately small: Python standard library WSGI, committed browser JavaScript generated from TypeScript source, semantic HTML5, CSS, and no third-party runtime packages.

## What This Is

MemoryEndpoints.com is a deployable MATM endpoint reference. It provides:

- Public AI-ready discovery files and evidence routes.
- Free agent workspace setup with a 200 MB quota.
- One-time workspace keys with server-side hash storage only.
- Protected workspace status, agent registration, memory submit/search, current-message, acknowledgement, and redacted receipt routes.
- File-backed storage plus optional stdlib SQLite storage.
- A canonical MySQL/MariaDB schema with activation gated until a no-third-party-compatible adapter is explicitly approved.

MultiAgentMemory.com is documentation only. It explains the architecture, memory boundary, and GitHub-facing handoff model.

## Memory Boundary

| Layer | Location | Purpose |
| --- | --- | --- |
| Short-term/startup memory | `.uai/` | Current instructions, constraints, progress, and pointer ledgers |
| Mid-to-long-term memory | [MemoryEndpoints.com](https://memoryendpoints.com) | Authenticated durable MATM memory, current messages, notifications, and receipts |
| Public documentation | `sites/multiagentmemory.com/` | Companion docs and AI-readable public discovery |

The totem invariant lives in `.uai/totem.uai`: local `.uai` stays active always. Hosted MATM augments durable memory, but it never replaces local startup continuity or offline recovery memory.

UAIX setup reference: use [File Handoff plus MemoryEndpoints.com MATM](https://uaix.org/en-us/tools/ai-memory-package-wizard/#setup-file-handoff-MATM-MemoryEndpoints) for this repository’s `.uai` package pattern. The generic [MATM setup](https://uaix.org/en-us/tools/ai-memory-package-wizard/#setup-MATM) remains useful for non-MemoryEndpoints endpoint configurations.

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

Current bounded readiness status is recorded in [docs/reports/final-readiness-report.md](docs/reports/final-readiness-report.md). The currently deployed public surface and required live MATM dogfood workflow verify successfully, but the latest repository tranche is not proven live until the FTPS login blocker is resolved and post-deploy verification passes.

## Quick Start

```powershell
python run_dev.py
```

Open `http://127.0.0.1:8088/`.

Default storage is JSON under `var/`. For stdlib database-backed storage:

```powershell
$env:MEMORYENDPOINTS_STORE_BACKEND='sqlite'
$env:MEMORYENDPOINTS_SQLITE_PATH='E:\MemoryEndpoints.com\var\matm_store.sqlite3'
python run_dev.py
```

## Verification

```powershell
python -m unittest discover -s tests
python scripts\verify_memoryendpoints.py --wsgi
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
python scripts\ftp_deploy_memoryendpoints.py --dry-run --handoff E:\ftp_Deploy.txt --remote-dir .
```

The FTP login directory is the MemoryEndpoints.com deployment root, so live deployment also uses `--remote-dir .`.

The latest recorded live upload attempt failed during FTPS login before any file upload. See [docs/reports/deploy-attempt-20260709.json](docs/reports/deploy-attempt-20260709.json).

## Security And Claims

- No raw secrets belong in repository files, reports, examples, logs, public pages, or final answers.
- Unsupported, malformed, unauthorized, or authority-gated operations return safe no-op JSON.
- No certification, endorsement, hidden credential validation, hosted agent execution, automatic repository writes, or automatic memory promotion is claimed.
- MySQL/MariaDB runtime activation remains gated by the no-third-party-runtime requirement.

## License

This repository uses the MemoryEndpoints Source-Available License. You may study, run, test, and contribute to the work, but you may not copy the whole project, strip attribution, and present it as your own original product. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
