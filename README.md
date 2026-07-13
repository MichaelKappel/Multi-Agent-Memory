# Multi-Agent Memory

Production-grade, source-available reference implementation for Multi-Agent Transactive Memory (MATM).

This repository contains two coordinated surfaces:

| Surface | Role | Status |
| --- | --- | --- |
| [MemoryEndpoints.com](https://memoryendpoints.com) | MATM endpoint, public AI-ready discovery, protected workspace memory APIs | Live-verified and deployed from the pushed source SHA |
| [MultiAgentMemory.com](https://multiagentmemory.com) | Static GitHub companion documentation site, including the complete [API and data reference](https://multiagentmemory.com/docs/api-reference.html) | Live-published companion documentation |

The runtime is deliberately small: Python standard library WSGI, committed browser JavaScript generated from TypeScript source, semantic HTML5, CSS, and no package-managed third-party runtime dependencies.

## What This Is

MemoryEndpoints.com is a deployable MATM endpoint reference. It provides:

- Public AI-ready discovery files and evidence routes.
- Free agent workspace setup with a 200 MB quota.
- Account-company-workspace-project hierarchy with many-to-many account/company memberships.
- One-time workspace keys with server-side hash storage only.
- Protected workspace status, agent registration, accountless-browser virtual UAIX active memory, hash-only local `.uai` edit coordination, memory submit/search, lifecycle-aware wiki documents, canonical external links, meeting-room routing, current-message delivery, conflict-safe distributed sync, acknowledgements, and redacted receipt and audit routes.
- No anonymous tenant wiki: `/knowledge` is an empty authentication shell, and all company/workspace/project pages, search results, and external-link records require a workspace-bound key. Accounts/users are membership identities, not data scopes.
- A browser-based human verification console at [MemoryEndpoints.com/console](https://memoryendpoints.com/console).
- File-backed local storage, stdlib SQLite relational local storage, and a MySQL/MariaDB production backend selected by environment.

The repository does not vendor, pin, install, or package a MySQL driver. The live cPanel deployment can use a host-provided MySQL Python adapter when the MySQL backend is selected; stdlib SQLite remains the pure-Python relational backend for environments that require zero host-provided database adapters.

MultiAgentMemory.com is plain HTML/CSS documentation only. It explains the architecture, memory boundary, GitHub repository structure, and GitHub-facing handoff model. It does not run the MATM endpoint API; MemoryEndpoints.com owns that runtime.

## Memory Boundary

| Layer | Location | Purpose |
| --- | --- | --- |
| Active startup memory | `.uai/` | Current instructions, constraints, progress state, pointer ledgers, and all files in the startup read order |
| Accountless-browser active-memory exception | Protected MemoryEndpoints virtual UAIX package | Complete registered-agent startup package only when the browser AI has no durable local filesystem |
| Concurrent local-agent overlay | Protected MemoryEndpoints file heads and edit claims | Project/path hashes, bounded ownership leases, and public-safe summaries; no local `.uai` body is uploaded |
| Mid-to-long-term memory | [MemoryEndpoints.com](https://memoryendpoints.com) | Authenticated durable MATM memory, current messages, notifications, receipts, and redacted audit trails |
| Public documentation | [MultiAgentMemory.com](https://multiagentmemory.com) and `sites/multiagentmemory.com/` | Companion docs and AI-readable public discovery |

The totem invariant lives in `.uai/totem.uai`: local `.uai` stays active always. Hosted MATM augments durable memory, but it never replaces local startup continuity or offline recovery memory.

There are two explicit exceptions/augmentations, not a new default. An accountless browser AI with no durable filesystem may bind a complete virtual UAIX package to a registered agent and workspace bearer key. Normal filesystem agents keep `.uai` bodies local; when several agents work in one codebase, they use hash-only project/path edit claims and project-room coordination to reduce simultaneous conflicting edits.

No single catch-all `.uai` file is "the" active memory. Every `.uai/*.uai` file in `.uai/startup-packet.uai` read order is active memory, and active `.uai` stays date-free operational memory.

UAIX setup reference: use the [MemoryEndpoints.com MATM setup option](https://uaix.org/en-us/tools/ai-memory-package-wizard/#setup-MATM-MemoryEndpoints) for this repository's `.uai` package pattern. UAIX uses setup-option fragments because the wizard has multiple modes. MemoryEndpoints.com inbound links should use the [home page](https://memoryendpoints.com); it currently has one setup surface, and any future setup-specific MemoryEndpoints URLs should be clean readable routes.

## Repository Layout

```text
.
|-- .github/                    # CI and PR hygiene
|-- .uai/                       # Agent startup memory, totem invariant, and pointer ledgers
|-- agent-file-handoff/         # Local-only intake buckets, tracked as empty inboxes
|-- docs/                       # Checked-in engineering docs, schema, and historical snapshots
|-- examples/                   # Public-safe request examples
|-- memoryendpoints/            # Pure Python stdlib WSGI application package
|-- scripts/                    # Verification, packaging, migration, and deploy helpers
|-- sites/multiagentmemory.com/ # Companion documentation site
|-- static/                     # MemoryEndpoints.com CSS, JS, and image assets
|-- tests/                      # stdlib unittest suite
|-- var/reports/                # Ignored point-in-time verification output
|-- app.py                      # WSGI app export for local/import use
`-- passenger_wsgi.py           # Passenger/cPanel WSGI entry point
```

See [docs/repository-structure.md](docs/repository-structure.md) for ownership and publishing boundaries.
See [docs/system-architecture.md](docs/system-architecture.md) for the request lifecycle, tenancy model, relational ownership, memory/wiki/coordination/sync flows, and evidence boundaries.
See [docs/verification.md](docs/verification.md) and [docs/deployment.md](docs/deployment.md) for rerunnable operating checks.

## Public Evidence

- [Version](https://memoryendpoints.com/api/version)
- [Capability matrix](https://memoryendpoints.com/api/matm/live-capability-matrix)
- [Agent compatibility](https://memoryendpoints.com/api/matm/agent-compatibility)
- [Sync capabilities](https://memoryendpoints.com/api/matm/sync/capabilities)
- [UAIX active-memory and local collaboration contract](https://memoryendpoints.com/api/matm/uai-memory/contract)
- [Bounded OpenAPI contract](https://memoryendpoints.com/api/matm/openapi.json)
- [Route inventory](https://memoryendpoints.com/api/matm/route-inventory)
- [Readiness result](https://memoryendpoints.com/api/matm/readiness-result)
- [Redacted receipt examples](https://memoryendpoints.com/api/matm/redacted-example-receipts)
- [AI manifest](https://memoryendpoints.com/ai-manifest.json)
- [Companion API and data reference](https://multiagentmemory.com/docs/api-reference.html)

Current deployed provenance comes from `/api/version`; current bounded capability and readiness claims come from the live evidence routes above. Files under `docs/reports/` are historical point-in-time snapshots and must not be treated as proof of a later commit. Fresh local and live verification output belongs under ignored `var/reports/`.

## Company Master Credential

MemoryEndpoints creates the company master credential during [Agent Setup](https://memoryendpoints.com/agent-setup) and shows it once after the first company workspace is created. It is not a human account password and it is not the credential an agent should use for normal work.

For an AI-assisted local project, the default agent-readable file is `<project-root>/.local-secrets/memoryendpoints-company-master.json`. Store JSON fields for `baseUrl`, `companyId`, `workspaceId`, and `companyMasterTokenSecret`; keep `.local-secrets/` in `.gitignore`, restrict the file to the owner and explicitly authorized local agents, and prefer a managed secret store when available. Keep the exceptional human-owner recovery secret separately.

If you cannot find the company master, ask your AI agent to check that exact project-relative file. The agent must read it directly instead of asking you to paste the credential into chat. If the file is missing, the agent stops and asks which governed secret store was used; it must not scan outside the project or request, echo, or log the raw value. Normal agents should use their own bound agent credential and access the company master only for an explicit owner-authorized company operation.

## Quick Start

```powershell
python run_dev.py
```

Open `http://127.0.0.1:8088/`.

Default local storage is the stdlib SQLite relational database under `var/`. Override its path when an isolated local database is useful:

```powershell
$env:MEMORYENDPOINTS_STORE_BACKEND='sqlite'
$env:MEMORYENDPOINTS_SQLITE_PATH='.\var\matm_store.sqlite3'
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

Deployment credentials stay outside this repository in ignored local handoffs or the operator's FileZilla profile. They must never be committed or printed.

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
