# Multi-Agent Memory

Production-grade, source-available private-intranet reference implementation for Multi-Agent Transactive Memory (MATM).

This repository contains two coordinated surfaces:

| Surface | Role | Status |
| --- | --- | --- |
| Private MATM intranet runtime | Free single-organization endpoint for private-network MATM memory, coordination, and human verification | Public GitHub edition |
| [MultiAgentMemory.com](https://multiagentmemory.com) | Static GitHub companion documentation site for the public private-intranet edition, including the complete [API and data reference](https://multiagentmemory.com/docs/api-reference.html) | Public companion documentation |

The runtime is deliberately small: Python standard library WSGI, committed browser JavaScript generated from TypeScript source, semantic HTML5, CSS, and no package-managed third-party runtime dependencies.

MemoryEndpoints.com, hosted customer accounts, authenticated business-model surfaces, public SaaS deployment, pricing, billing, subscriptions, overage charging, paid or unlimited storage plans, paid or unlimited NPC memory stores, partner sponsorship flows, and customer-facing sales operations are reserved for a separate private commercial repository or deployment. They are not part of the public GitHub license.

## What This Is

This public repository is a deployable private-intranet MATM endpoint reference. It provides:

- Public AI-ready discovery files and evidence routes.
- Free single-organization agent workspace setup with a 200 MB quota.
- Autonomous setup and normal operation without a required human account. Routine logs are human-only break-glass evidence, never agent-visible, and are physically purged after seven days.
- Account-company-workspace-project hierarchy with many-to-many account/company memberships.
- One-time workspace keys with server-side hash storage only.
- Protected workspace status, agent registration, accountless-browser virtual UAIX active memory, hash-only local `.uai` edit coordination, memory submit/search, lifecycle-aware wiki documents, canonical external links, meeting-room routing, current-message delivery, conflict-safe distributed sync, acknowledgements, and redacted receipts. Routine audit/history routes are human-only and physically expire after seven days.
- Bounded coordination retention: acknowledged direct messages are deleted seven days after acknowledgement, unacknowledged messages expire after 30 days, and ordinary meeting transcripts are deleted after seven days. Durable routing decisions and explicitly promoted memory/knowledge remain.
- No anonymous tenant wiki: `/knowledge` is an empty authentication shell, and all company/workspace/project pages, search results, and external-link records require a workspace-bound key. Accounts/users are membership identities, not data scopes.
- A browser-based human verification console for private-network operation.
- File-backed local storage, stdlib SQLite relational local storage, and a MySQL/MariaDB production backend selected by environment.

The repository does not vendor, pin, install, or package a MySQL driver. The live cPanel deployment can use a host-provided MySQL Python adapter when the MySQL backend is selected; stdlib SQLite remains the pure-Python relational backend for environments that require zero host-provided database adapters.

MultiAgentMemory.com is plain HTML/CSS documentation only. It explains the public GitHub edition, architecture, memory boundary, repository structure, and GitHub-facing handoff model. It does not run the MATM endpoint API.

## Memory Boundary

| Layer | Location | Purpose |
| --- | --- | --- |
| Active startup memory | `.uai/` | Current instructions, constraints, progress state, pointer ledgers, and all files in the startup read order |
| Accountless-browser active-memory exception | Protected intranet virtual UAIX package | Complete registered-agent startup package only when the browser AI has no durable local filesystem |
| Concurrent local-agent overlay | Protected intranet file heads and edit claims | Project/path hashes, bounded ownership leases, and public-safe summaries; no local `.uai` body is uploaded |
| Mid-to-long-term memory | Private MATM intranet endpoint | Authenticated durable MATM memory plus transient current messages, notifications, and receipts; routine logs remain human-only for seven days |
| Public documentation | [MultiAgentMemory.com](https://multiagentmemory.com) and `sites/multiagentmemory.com/` | Companion docs and AI-readable public discovery |

The totem invariant lives in `.uai/totem.uai`: local `.uai` stays active always. Hosted MATM augments durable memory, but it never replaces local startup continuity or offline recovery memory.

There are two explicit exceptions/augmentations, not a new default. An accountless browser AI with no durable filesystem may bind a complete virtual UAIX package to a registered agent and workspace bearer key. Normal filesystem agents keep `.uai` bodies local; when several agents work in one codebase, they use hash-only project/path edit claims and project-room coordination to reduce simultaneous conflicting edits.

No single catch-all `.uai` file is "the" active memory. Every `.uai/*.uai` file in `.uai/startup-packet.uai` read order is active memory, and active `.uai` stays date-free operational memory.

UAIX setup reference: use the MATM setup option in the [UAIX AI memory package wizard](https://uaix.org/en-us/tools/ai-memory-package-wizard/) for this repository's `.uai` package pattern. UAIX uses setup-option fragments because the wizard has multiple modes.

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
|-- static/                     # Private MATM intranet CSS, JS, and image assets
|-- tests/                      # stdlib unittest suite
|-- var/reports/                # Ignored point-in-time verification output
|-- app.py                      # WSGI app export for local/import use
`-- passenger_wsgi.py           # Passenger/cPanel WSGI entry point
```

See [docs/repository-structure.md](docs/repository-structure.md) for ownership and publishing boundaries.
See [docs/system-architecture.md](docs/system-architecture.md) for the request lifecycle, tenancy model, relational ownership, memory/wiki/coordination/sync flows, and evidence boundaries.
See [docs/verification.md](docs/verification.md) and [docs/deployment.md](docs/deployment.md) for rerunnable operating checks.

## Public Evidence

- `/api/version`
- `/api/matm/live-capability-matrix`
- `/api/matm/agent-compatibility`
- `/api/matm/sync/capabilities`
- `/api/matm/uai-memory/contract`
- `/api/matm/openapi.json`
- `/api/matm/route-inventory`
- `/api/matm/readiness-result`
- `/api/matm/redacted-example-receipts`
- `/ai-manifest.json`
- [Companion API and data reference](https://multiagentmemory.com/docs/api-reference.html)

Current deployed provenance comes from `/api/version`; current bounded capability and readiness claims come from the live evidence routes above. Files under `docs/reports/` are historical point-in-time snapshots and must not be treated as proof of a later commit. Fresh local and live verification output belongs under ignored `var/reports/`.

## Company Master Credential

The private intranet creates the company master credential during Agent Setup and shows it once after the first company workspace is created. It is not a human account password and it is not the credential an agent should use for normal work. Displaying a default path does not create a file: setup is incomplete until the credential has been persisted and verified at that path.

For browser setup, choose **Save to project secret folder** after creation and select the project root; the page creates `<project-root>/.local-secrets/memoryendpoints-company-master.json`. If folder access is unavailable, it downloads the exact filename and requires the human to move it into `.local-secrets` and verify it exists. Keep `.local-secrets/` in `.gitignore`, restrict the file to the owner and explicitly authorized local agents, and keep the exceptional human-owner recovery secret separately.

For agent-driven setup, use `python scripts/setup_memoryendpoints_company.py --company-label "Example Company" --workspace-label "Example Workspace" --project-label "Example Project" --project-root .`. The helper checks both destinations before the non-idempotent setup request, writes the company master to the standard project file, writes the owner-recovery secret to a separate user recovery file, and prints only redacted confirmation.

If you cannot find the company master, ask your top-level AI agent to check that exact project-relative file. A company-scoped top-level agent can restore it with `MEMORYENDPOINTS_AGENT_TOKEN` and `scripts/recover_memoryendpoints_company_master.py`; an existing company master can use `MEMORYENDPOINTS_COMPANY_MASTER_TOKEN`. The helper stages a new client-generated credential, registers only its verifier, verifies it, and promotes the file atomically without printing a value. It can safely resume after a lost response. Lower-scoped agents must ask a top-level agent or human administrator. Human owners and credential admins can disable top-level-agent creation in the human console; operators can also set the standard database column `matm_companies.top_level_agent_master_credential_enabled` to false.

Existing company masters may delegate a sibling company master, and a company-scoped top-level agent may register a human-operator master when the company setting permits it. Connector, workspace-, project-, goal-, task-, and disposable agents cannot use either path; `/api/matm/me` reports master delegation authority explicitly. This API boundary cannot isolate processes that share the same OS identity and unrestricted project filesystem. Keep the project secret unavailable to disposable agents through separate OS identities, a capability-aware vault, or a secret mount supplied only to trusted top-level agents. Never infer authority from an agent name or client-provided label; the service enforces the immutable credential scope.

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

MySQL/MariaDB storage is selected with `MEMORYENDPOINTS_STORE_BACKEND=mysql` plus an ignored `.local-secrets/mysql.json` file outside Git, `MEMORYENDPOINTS_MYSQL_*` credentials, or `MEMORYENDPOINTS_MYSQL_URL`. When `.local-secrets/mysql.json` exists it is authoritative over environment values so stale process variables cannot silently override the configured database credential file. `/api/version` must report `storeBackend: mysql` or `mariadb` and `storeBackendVerified: true` before a deployment is considered to be using real MySQL.

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

Deployment credentials and public-hosted MemoryEndpoints.com release operations belong outside the public GitHub edition unless a private-network operator has supplied their own explicit target. Plain FTP is not the verified publish route.

## Security And Claims

- No raw secrets belong in repository files, reports, examples, logs, public pages, or final answers.
- Unsupported, malformed, unauthorized, or authority-gated operations return safe no-op JSON.
- No certification, endorsement, hidden credential validation, hosted agent execution, automatic repository writes, or automatic memory promotion is claimed.
- MySQL/MariaDB runtime activation requires real environment configuration and must be verified through `/api/version`; file storage is not a production database claim.

## License

This repository uses the Multi-Agent Memory Private Intranet License. You may study, run, modify, and use the public edition for one organization's private network, but you may not resell it, host it as a competing public service, or reuse the reserved MemoryEndpoints.com business-model features. See [LICENSE](LICENSE), [NOTICE](NOTICE), and [docs/product-boundary.md](docs/product-boundary.md).
