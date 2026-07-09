# MemoryEndpoints Build Plan, Verification, and Public Repo Quality Report

**Intended report path:** `E:\MemoryEndpoints.com\docs\reports\implementation-verification-plan.md`

This plan is written so a separate coding agent can execute the work file by file without implementing anything in this response. Two important limits apply at the start: the local paths `E:\MemoryEndpoints.com` and `E:\NeuralWikis.com` were not inspectable from this session, so the first implementation task must be a local inventory and gap audit before any edits; and the repo must be shaped around UAIX’s layered model of human pages, static discovery, structured content, action/API routes, capability records, evidence/memory, and governance artifacts, without copying UAIX text into the target site or pretending a certification exists. UAIX also recommends a split-memory design where hot `.uai` files remain the first-load continuity layer while a durable memory plane can live in docs or other storage until a richer memory system is online. citeturn2view5turn2view1turn0search2

The implementation order should be: local audit and source-boundary report; repo skeleton and public governance files; WSGI/server core; JSON fallback storage; public discovery files and human pages; MATM API routes and receipts; verification scripts and tests; packaging and dry-run deploy; then live deployment and post-deploy verification. The first tests to run should be `test_repo_hygiene.py`, `test_uai_package_contract.py`, `test_discovery.py`, `test_static_pages.py`, and `scripts/secret_scan.py`, because they protect the hard constraints that are easiest to violate early: no secret leakage, no hidden bot-only copy, no drift between human and machine truth, no malformed `.uai` package, and no accidental copying from the wrong source corpus. The deployment gates that must remain closed until proven are: live SQL runtime use, public write routes on production, real-token entry in the API explorer, public claims stronger than the evidence file set, and FTPS publish from `E:\ftp_Deploy.txt` until package integrity and dry-run upload both pass. citeturn2view5turn0search7turn5search0turn5search1turn5search2

## Repository blueprint

UAIX’s implementation guidance says to start with semantic HTML, stable discovery, clear route contracts, and a no-op path before adding more advanced agent interfaces; its architecture record also expects a public manifest, `.well-known` discovery, route inventory, readiness result, `robots.txt`, sitemap, `llms.txt`, visible support boundaries, and targeted checks. For production hosting on Passenger, Python apps are conventionally discovered through `passenger_wsgi.py`. citeturn0search4turn2view5turn5search21

### Exact implementation file tree

```text
E:\MemoryEndpoints.com
├─ app.py
├─ passenger_wsgi.py
├─ README.md
├─ LICENSE
├─ NOTICE
├─ CONTRIBUTING.md
├─ SECURITY.md
├─ CHANGELOG.md
├─ TRADEMARKS.md
├─ .gitignore
├─ .gitattributes
├─ memoryendpoints/
│  ├─ __init__.py
│  ├─ config.py
│  ├─ app_core.py
│  ├─ router.py
│  ├─ request_context.py
│  ├─ responses.py
│  ├─ problem_details.py
│  ├─ validation.py
│  ├─ auth.py
│  ├─ identifiers.py
│  ├─ capabilities.py
│  ├─ redaction.py
│  ├─ storage.py
│  ├─ json_backend.py
│  ├─ sql_backend.py
│  ├─ export_import.py
│  ├─ discovery.py
│  └─ pages.py
├─ static/
│  ├─ index.html
│  ├─ docs/index.html
│  ├─ explorer/index.html
│  ├─ setup/index.html
│  ├─ lifecycle/index.html
│  ├─ transparency/index.html
│  ├─ css/site.css
│  ├─ ts/site.ts
│  ├─ ts/explorer.ts
│  ├─ ts/setup.ts
│  ├─ ts/lifecycle.ts
│  ├─ js/site.js
│  ├─ js/explorer.js
│  ├─ js/setup.js
│  ├─ js/lifecycle.js
│  ├─ .well-known/ai-ready-manifest.json
│  ├─ .well-known/route-inventory.json
│  ├─ .well-known/readiness.json
│  ├─ robots.txt
│  ├─ sitemap.xml
│  └─ llms.txt
├─ .uai/
│  ├─ startup-packet.uai
│  ├─ system-profile.uai
│  ├─ receiver-brief.uai
│  ├─ index.uai
│  ├─ context.uai
│  ├─ constraints.uai
│  ├─ progress.uai
│  ├─ operations.uai
│  ├─ test-plan.uai
│  ├─ coding-standards.uai
│  ├─ architecture.uai
│  ├─ next-recursive-prompt.uai
│  ├─ decisions.uai
│  ├─ memory.uai
│  ├─ short-term-memory.uai
│  ├─ long-term-memory.uai
│  ├─ file-handoff.uai
│  ├─ exports/llms.uai
│  ├─ exports/llms-full.uai
│  └─ archives/.gitkeep
├─ docs/
│  ├─ README.md
│  ├─ architecture.md
│  ├─ api.md
│  ├─ data-model.md
│  ├─ deployment.md
│  ├─ repo-public-readiness.md
│  ├─ memory/README.md
│  ├─ memory/decision-log.md
│  ├─ memory/source-ledger.md
│  ├─ demo/screenshot-shotlist.md
│  └─ reports/
│     ├─ implementation-verification-plan.md
│     ├─ neuralwikis-pattern-intake.md
│     ├─ build-verification-report.md
│     ├─ public-repo-quality-report.md
│     ├─ deploy-dry-run.md
│     └─ post-deploy-live-check.md
├─ examples/
│  ├─ README.md
│  ├─ register-workspace.curl.txt
│  ├─ submit-memory-event.curl.txt
│  ├─ submit-message.curl.txt
│  ├─ redacted-receipt.json
│  └─ problem-details.json
├─ sql/
│  ├─ 001_mysql_schema.sql
│  ├─ 001_mariadb_schema.sql
│  ├─ 010_indexes.sql
│  └─ 020_json_to_sql_migration.sql
├─ tests/
│  ├─ __init__.py
│  ├─ test_repo_hygiene.py
│  ├─ test_app.py
│  ├─ test_router.py
│  ├─ test_validation.py
│  ├─ test_capabilities.py
│  ├─ test_redaction.py
│  ├─ test_storage_json.py
│  ├─ test_storage_sql_contract.py
│  ├─ test_discovery.py
│  ├─ test_static_pages.py
│  ├─ test_api_contracts.py
│  ├─ test_export_import.py
│  ├─ test_deploy_scripts.py
│  ├─ test_uai_package_contract.py
│  └─ fixtures/
│     ├─ sample_events.json
│     ├─ sample_messages.json
│     └─ sample_receipts.json
├─ scripts/
│  ├─ inventory_neuralwikis_patterns.py
│  ├─ generate_route_inventory.py
│  ├─ generate_readiness_record.py
│  ├─ validate_json.py
│  ├─ secret_scan.py
│  ├─ export_backup.py
│  ├─ migrate_json_to_sql.py
│  ├─ package_release.py
│  ├─ parse_ftp_deploy.py
│  ├─ deploy_ftp.py
│  ├─ restart_passenger.py
│  └─ live_check.py
├─ deploy/
│  ├─ include-globs.txt
│  ├─ exclude-globs.txt
│  ├─ live-routes.txt
│  ├─ package-manifest-template.json
│  └─ passenger-restart.txt.template
└─ runtime/
   ├─ README.md
   ├─ .gitignore
   ├─ data/.gitkeep
   └─ backups/.gitkeep
```

### File-by-file purpose

The tables below are intentionally normative. “Public” means safe to commit to the public GitHub repo. “Redacted-only” means commit only sanitized content. “Can contain secrets” means whether the file is ever allowed to store secrets. In this plan, no committed file should contain secrets; runtime secrets come only from the host or from `E:\ftp_Deploy.txt`, which must be parsed without logging the secret fields. UAIX explicitly allows `.uai` packages to be gitignored or checked in after redaction, and it expects a predictable `.uai/archives`, `.uai`, and `.uai/exports` structure. citeturn2view1turn5search2turn8search18

#### Root, package core, runtime, and deploy files

| File | Why it exists | Who reads it | Public | Can contain secrets | Tests that cover it |
|---|---|---|---|---|---|
| `app.py` | Local entry point; dev server bootstrap; imports WSGI app callable | Devs, Passenger wrapper, coding agents | Yes | No | `test_app.py`, `test_router.py` |
| `passenger_wsgi.py` | Passenger Python autodetection entry | Passenger, deploy operator | Yes | No | `test_app.py`, `test_deploy_scripts.py` |
| `README.md` | Primary repo overview and quick start | Humans, GitHub visitors, agents | Yes | No | `test_repo_hygiene.py` |
| `LICENSE` | Licensing terms | Humans, GitHub, legal reviewers | Yes | No | `test_repo_hygiene.py` |
| `NOTICE` | Attribution and notice retention | Humans, downstream users | Yes | No | `test_repo_hygiene.py` |
| `CONTRIBUTING.md` | Contribution workflow and boundaries | Contributors, agents | Yes | No | `test_repo_hygiene.py` |
| `SECURITY.md` | Vulnerability reporting path | Security reporters, GitHub | Yes | No | `test_repo_hygiene.py` |
| `CHANGELOG.md` | Human-readable release history | Humans, release reviewers | Yes | No | `test_repo_hygiene.py` |
| `TRADEMARKS.md` | Reservation of names/branding to reduce pass-off risk | Humans, downstream users | Yes | No | `test_repo_hygiene.py` |
| `.gitignore` | Prevent runtime data, secrets, caches, local memory drift in repo | Git, devs | Yes | No | `test_repo_hygiene.py` |
| `.gitattributes` | Normalize line endings and text treatment | Git, deploy packaging | Yes | No | `test_repo_hygiene.py` |
| `memoryendpoints/__init__.py` | Package marker and version surface | Python runtime, tests | Yes | No | `test_app.py` |
| `memoryendpoints/config.py` | Environment and path settings; no secret values hardcoded | App core, deploy scripts | Yes | No | `test_app.py`, `test_deploy_scripts.py` |
| `memoryendpoints/app_core.py` | WSGI app factory and request dispatch loop | `app.py`, `passenger_wsgi.py` | Yes | No | `test_app.py`, `test_api_contracts.py` |
| `memoryendpoints/router.py` | Route table and method dispatch | App core, route inventory generator | Yes | No | `test_router.py`, `test_api_contracts.py` |
| `memoryendpoints/request_context.py` | Request parsing, correlation IDs, UTC timestamps | App core, API handlers | Yes | No | `test_app.py`, `test_validation.py` |
| `memoryendpoints/responses.py` | JSON/HTML/text response helpers | App core, pages, API routes | Yes | No | `test_api_contracts.py`, `test_static_pages.py` |
| `memoryendpoints/problem_details.py` | RFC 9457-style error payload builder | API routes, tests | Yes | No | `test_api_contracts.py`, `test_validation.py` |
| `memoryendpoints/validation.py` | Handwritten schema-style validators | All write routes | Yes | No | `test_validation.py` |
| `memoryendpoints/auth.py` | Token parsing and auth boundary hooks; remains closed by gate until proven | API write routes | Yes | No | `test_api_contracts.py` |
| `memoryendpoints/identifiers.py` | Stable ID generation and parsing | Storage, receipts, routes | Yes | No | `test_validation.py`, `test_export_import.py` |
| `memoryendpoints/capabilities.py` | Capability matrix and blocked-action truth | API clients, docs, explorer | Yes | No | `test_capabilities.py`, `test_api_contracts.py` |
| `memoryendpoints/redaction.py` | Receipt redaction rules and field masks | Receipts, exports, UI | Yes | No | `test_redaction.py`, `test_api_contracts.py` |
| `memoryendpoints/storage.py` | Storage interface and backend selection | App core, tests | Yes | No | `test_storage_json.py`, `test_storage_sql_contract.py` |
| `memoryendpoints/json_backend.py` | JSON/NDJSON fallback store | Local/dev runtime, first deploy runtime | Yes | No | `test_storage_json.py`, `test_export_import.py` |
| `memoryendpoints/sql_backend.py` | SQL contract and query templates only; enable later | Future DB runtime, migration logic | Yes | No | `test_storage_sql_contract.py` |
| `memoryendpoints/export_import.py` | Canonical backup/export helpers | Admin scripts, migrations | Yes | No | `test_export_import.py` |
| `memoryendpoints/discovery.py` | `.well-known`, robots, sitemap, llms, readiness generation | Public discovery routes, scripts | Yes | No | `test_discovery.py`, `test_static_pages.py` |
| `memoryendpoints/pages.py` | Human page assembly helpers | Browser, tests | Yes | No | `test_static_pages.py` |
| `deploy/include-globs.txt` | Explicit package allow-list | Packaging and deploy scripts | Yes | No | `test_deploy_scripts.py` |
| `deploy/exclude-globs.txt` | Explicit package deny-list | Packaging and deploy scripts | Yes | No | `test_deploy_scripts.py` |
| `deploy/live-routes.txt` | Canonical live checks target list | Live checker, deploy operator | Yes | No | `test_deploy_scripts.py` |
| `deploy/package-manifest-template.json` | Package integrity manifest shape | Packager, reviewers | Yes | No | `test_deploy_scripts.py` |
| `deploy/passenger-restart.txt.template` | Restart marker template for Passenger | Deploy script, operator | Yes | No | `test_deploy_scripts.py` |
| `runtime/README.md` | Explains runtime-only folders and no-commit policy | Devs, operators, agents | Yes | No | `test_repo_hygiene.py` |
| `runtime/.gitignore` | Keeps runtime data out of Git | Git, devs | Yes | No | `test_repo_hygiene.py` |
| `runtime/data/.gitkeep` | Creates data folder in a clean checkout | Git, devs | Yes | No | `test_repo_hygiene.py` |
| `runtime/backups/.gitkeep` | Creates backup folder in a clean checkout | Git, devs | Yes | No | `test_repo_hygiene.py` |

#### Static pages, browser code, and public discovery files

| File | Why it exists | Who reads it | Public | Can contain secrets | Tests that cover it |
|---|---|---|---|---|---|
| `static/index.html` | Homepage with product boundary and quick links | Browsers, search engines, agents | Yes | No | `test_static_pages.py`, `test_discovery.py` |
| `static/docs/index.html` | Human docs landing page | Browsers, agents | Yes | No | `test_static_pages.py` |
| `static/explorer/index.html` | API explorer using placeholders only | Browsers, devs, agents | Yes | No | `test_static_pages.py`, `test_api_contracts.py` |
| `static/setup/index.html` | Agent setup page and first-use flow | Browsers, agents | Yes | No | `test_static_pages.py` |
| `static/lifecycle/index.html` | Memory lifecycle explanation and state machine | Browsers, reviewers | Yes | No | `test_static_pages.py` |
| `static/transparency/index.html` | Human transparency page: what works, what is blocked, what is redacted | Browsers, reviewers, agents | Yes | No | `test_static_pages.py`, `test_discovery.py` |
| `static/css/site.css` | Shared responsive styling | Browsers | Yes | No | `test_static_pages.py` |
| `static/ts/site.ts` | Shared browser behaviors and nav state | Frontend maintainers | Yes | No | `test_static_pages.py` |
| `static/ts/explorer.ts` | Placeholder request builder and copy actions | Frontend maintainers | Yes | No | `test_static_pages.py`, `test_api_contracts.py` |
| `static/ts/setup.ts` | Setup walkthrough interactions | Frontend maintainers | Yes | No | `test_static_pages.py` |
| `static/ts/lifecycle.ts` | Lifecycle page interactivity | Frontend maintainers | Yes | No | `test_static_pages.py` |
| `static/js/site.js` | Committed compiled JS for browsers | Browsers | Yes | No | `test_static_pages.py` |
| `static/js/explorer.js` | Compiled explorer logic | Browsers | Yes | No | `test_static_pages.py`, `test_api_contracts.py` |
| `static/js/setup.js` | Compiled setup logic | Browsers | Yes | No | `test_static_pages.py` |
| `static/js/lifecycle.js` | Compiled lifecycle logic | Browsers | Yes | No | `test_static_pages.py` |
| `static/.well-known/ai-ready-manifest.json` | Public-safe machine discovery manifest | Agents, validators, reviewers | Yes | No | `test_discovery.py` |
| `static/.well-known/route-inventory.json` | Public route inventory mirror | Agents, explorer, reviewers | Yes | No | `test_discovery.py`, `test_api_contracts.py` |
| `static/.well-known/readiness.json` | Evidence-backed readiness result | Agents, reviewers | Yes | No | `test_discovery.py` |
| `static/robots.txt` | Crawl boundary and policy pointer | Search engines, agents | Yes | No | `test_discovery.py` |
| `static/sitemap.xml` | Canonical public route list | Search engines, agents | Yes | No | `test_discovery.py` |
| `static/llms.txt` | Advisory AI-readable summary and pointers | AI crawlers, agents | Yes | No | `test_discovery.py` |

#### UAI package, docs, examples, and SQL files

| File | Why it exists | Who reads it | Public | Can contain secrets | Tests that cover it |
|---|---|---|---|---|---|
| `.uai/startup-packet.uai` | First-load project handoff packet | Coding agents, maintainers | Redacted-only | No | `test_uai_package_contract.py` |
| `.uai/system-profile.uai` | Operating rules and workspace profile | Coding agents, maintainers | Redacted-only | No | `test_uai_package_contract.py` |
| `.uai/receiver-brief.uai` | Short receiver startup brief | Coding agents | Redacted-only | No | `test_uai_package_contract.py` |
| `.uai/index.uai` | Pointer index across UAI files | Coding agents | Redacted-only | No | `test_uai_package_contract.py` |
| `.uai/context.uai` | Active context and scope | Coding agents | Redacted-only | No | `test_uai_package_contract.py` |
| `.uai/constraints.uai` | Hard constraints and blocked behavior | Coding agents | Redacted-only | No | `test_uai_package_contract.py` |
| `.uai/progress.uai` | Current implementation status | Coding agents | Redacted-only | No | `test_uai_package_contract.py` |
| `.uai/operations.uai` | Operating procedures and run order | Coding agents | Redacted-only | No | `test_uai_package_contract.py` |
| `.uai/test-plan.uai` | Condensed test plan | Coding agents | Redacted-only | No | `test_uai_package_contract.py` |
| `.uai/coding-standards.uai` | Repo-specific coding standards | Coding agents | Redacted-only | No | `test_uai_package_contract.py` |
| `.uai/architecture.uai` | Local system map | Coding agents | Redacted-only | No | `test_uai_package_contract.py` |
| `.uai/next-recursive-prompt.uai` | Resume artifact for continuation | Coding agents | Redacted-only | No | `test_uai_package_contract.py` |
| `.uai/decisions.uai` | Architectural decisions log | Coding agents, reviewers | Redacted-only | No | `test_uai_package_contract.py` |
| `.uai/memory.uai` | Compact working memory summary | Coding agents | Redacted-only | No | `test_uai_package_contract.py` |
| `.uai/short-term-memory.uai` | Hot continuity memory | Coding agents | Redacted-only | No | `test_uai_package_contract.py` |
| `.uai/long-term-memory.uai` | Pointer ledger to durable docs memory | Coding agents | Redacted-only | No | `test_uai_package_contract.py` |
| `.uai/file-handoff.uai` | File handoff instructions for agent-to-agent work | Coding agents | Redacted-only | No | `test_uai_package_contract.py` |
| `.uai/exports/llms.uai` | Compact public-safe export | Agents, reviewers | Redacted-only | No | `test_uai_package_contract.py` |
| `.uai/exports/llms-full.uai` | Full export with richer pointers, still redacted | Agents, reviewers | Redacted-only | No | `test_uai_package_contract.py` |
| `.uai/archives/.gitkeep` | Keeps archive folder structure | Git, devs | Yes | No | `test_repo_hygiene.py` |
| `docs/README.md` | Documentation map | Humans, agents | Yes | No | `test_repo_hygiene.py` |
| `docs/architecture.md` | Human-readable architecture doc | Humans, agents | Yes | No | `test_repo_hygiene.py` |
| `docs/api.md` | API contract guide | Humans, agents | Yes | No | `test_repo_hygiene.py`, `test_api_contracts.py` |
| `docs/data-model.md` | JSON and SQL model explanation | Humans, DB reviewers | Yes | No | `test_repo_hygiene.py` |
| `docs/deployment.md` | Deploy and rollback runbook | Operators, agents | Yes | No | `test_deploy_scripts.py` |
| `docs/repo-public-readiness.md` | Repo polish checklist and public-claim limits | Humans, agents | Yes | No | `test_repo_hygiene.py` |
| `docs/memory/README.md` | Explains docs as durable memory until live memory is online | Humans, coding agents | Yes | No | `test_repo_hygiene.py` |
| `docs/memory/decision-log.md` | Durable decisions log | Humans, coding agents | Yes | No | `test_repo_hygiene.py` |
| `docs/memory/source-ledger.md` | Source authority ledger and allowed pattern origins | Humans, coding agents | Yes | No | `test_repo_hygiene.py` |
| `docs/demo/screenshot-shotlist.md` | Screenshot/demo capture plan for GitHub and docs | Humans | Yes | No | `test_repo_hygiene.py` |
| `docs/reports/implementation-verification-plan.md` | This planning report | Humans, coding agents | Yes | No | `test_repo_hygiene.py` |
| `docs/reports/neuralwikis-pattern-intake.md` | Local source-boundary report naming allowed patterns only | Humans, coding agents | Yes | No | `test_repo_hygiene.py` |
| `docs/reports/build-verification-report.md` | Result of local validation suite | Humans, reviewers | Yes | No | `test_deploy_scripts.py` |
| `docs/reports/public-repo-quality-report.md` | Repo polish audit after implementation | Humans, reviewers | Yes | No | `test_repo_hygiene.py` |
| `docs/reports/deploy-dry-run.md` | Dry-run packaging and upload report | Humans, operators | Yes | No | `test_deploy_scripts.py` |
| `docs/reports/post-deploy-live-check.md` | Live-route verification report | Humans, operators | Yes | No | `test_deploy_scripts.py` |
| `examples/README.md` | Example index and usage notes | Humans, agents | Yes | No | `test_repo_hygiene.py` |
| `examples/register-workspace.curl.txt` | Placeholder-only curl example | Humans, agents | Yes | No | `test_api_contracts.py` |
| `examples/submit-memory-event.curl.txt` | Placeholder-only curl example | Humans, agents | Yes | No | `test_api_contracts.py` |
| `examples/submit-message.curl.txt` | Placeholder-only curl example | Humans, agents | Yes | No | `test_api_contracts.py` |
| `examples/redacted-receipt.json` | Redacted receipt example | Humans, agents | Yes | No | `test_redaction.py`, `test_api_contracts.py` |
| `examples/problem-details.json` | Error example following Problem Details | Humans, agents | Yes | No | `test_api_contracts.py` |
| `sql/001_mysql_schema.sql` | MySQL target tables | DB reviewers, migration operator | Yes | No | `test_storage_sql_contract.py` |
| `sql/001_mariadb_schema.sql` | MariaDB target tables with compatibility choices | DB reviewers, migration operator | Yes | No | `test_storage_sql_contract.py` |
| `sql/010_indexes.sql` | Shared indexes and lookup performance plan | DB reviewers | Yes | No | `test_storage_sql_contract.py` |
| `sql/020_json_to_sql_migration.sql` | SQL-side migration helpers and verification queries | DB reviewers, migration operator | Yes | No | `test_storage_sql_contract.py`, `test_export_import.py` |

#### Tests, fixtures, and scripts

| File | Why it exists | Who reads it | Public | Can contain secrets | Tests that cover it |
|---|---|---|---|---|---|
| `tests/__init__.py` | Test package marker | Python test runner | Yes | No | `python -m unittest` discovery |
| `tests/test_repo_hygiene.py` | Enforces repo boundaries, no secret files, no banned copy patterns | Test runner, reviewers | Yes | No | Self + suite |
| `tests/test_app.py` | WSGI app boot and basic route checks | Test runner | Yes | No | Self + suite |
| `tests/test_router.py` | Route registration and dispatch rules | Test runner | Yes | No | Self + suite |
| `tests/test_validation.py` | Schema-style validation checks | Test runner | Yes | No | Self + suite |
| `tests/test_capabilities.py` | Capability matrix correctness | Test runner | Yes | No | Self + suite |
| `tests/test_redaction.py` | Receipt masking and redaction behavior | Test runner | Yes | No | Self + suite |
| `tests/test_storage_json.py` | JSON backend persistence and query behavior | Test runner | Yes | No | Self + suite |
| `tests/test_storage_sql_contract.py` | SQL schema shape and migration contract verification | Test runner | Yes | No | Self + suite |
| `tests/test_discovery.py` | `.well-known`, robots, sitemap, llms, readiness checks | Test runner | Yes | No | Self + suite |
| `tests/test_static_pages.py` | HTML accessibility, semantic structure, link integrity | Test runner | Yes | No | Self + suite |
| `tests/test_api_contracts.py` | End-to-end route contracts, idempotency, no-op behavior | Test runner | Yes | No | Self + suite |
| `tests/test_export_import.py` | Backup/export and import roundtrip | Test runner | Yes | No | Self + suite |
| `tests/test_deploy_scripts.py` | Package manifest, deploy dry run, restart marker logic | Test runner | Yes | No | Self + suite |
| `tests/test_uai_package_contract.py` | Required `.uai` files and redaction safeties | Test runner | Yes | No | Self + suite |
| `tests/fixtures/sample_events.json` | Stable event fixtures | Tests only | Yes | No | `test_storage_json.py`, `test_export_import.py` |
| `tests/fixtures/sample_messages.json` | Stable message fixtures | Tests only | Yes | No | `test_api_contracts.py`, `test_export_import.py` |
| `tests/fixtures/sample_receipts.json` | Stable receipt fixtures | Tests only | Yes | No | `test_redaction.py`, `test_export_import.py` |
| `scripts/inventory_neuralwikis_patterns.py` | Audits `E:\NeuralWikis.com` and emits allowed-pattern report without copying content | Devs, operators, coding agents | Yes | No | `test_repo_hygiene.py`, `test_deploy_scripts.py` |
| `scripts/generate_route_inventory.py` | Generates route inventory JSON and docs view | Devs, CI-style local runs | Yes | No | `test_discovery.py`, `test_api_contracts.py` |
| `scripts/generate_readiness_record.py` | Generates evidence-backed readiness JSON | Devs, reviewers | Yes | No | `test_discovery.py`, `test_deploy_scripts.py` |
| `scripts/validate_json.py` | Validates example JSON and discovery files without third-party packages | Devs, reviewers | Yes | No | `test_validation.py`, `test_discovery.py` |
| `scripts/secret_scan.py` | Regex and entropy-style scan for secrets | Devs, reviewers, deploy operator | Yes | No | `test_repo_hygiene.py`, `test_deploy_scripts.py` |
| `scripts/export_backup.py` | Writes canonical backup/export package | Operators, migration agent | Yes | No | `test_export_import.py` |
| `scripts/migrate_json_to_sql.py` | Converts JSON export to SQL insert bundle and count checks | Operators, DB reviewers | Yes | No | `test_export_import.py`, `test_storage_sql_contract.py` |
| `scripts/package_release.py` | Packages only required files and computes integrity manifest | Operators | Yes | No | `test_deploy_scripts.py` |
| `scripts/parse_ftp_deploy.py` | Reads `E:\ftp_Deploy.txt` and masks secrets in logs | Operators, deploy script | Yes | No | `test_deploy_scripts.py` |
| `scripts/deploy_ftp.py` | FTP/FTPS upload using stdlib only | Operators | Yes | No | `test_deploy_scripts.py` |
| `scripts/restart_passenger.py` | Writes reviewed Passenger restart marker if needed | Operators | Yes | No | `test_deploy_scripts.py` |
| `scripts/live_check.py` | Uses stdlib HTTP client to verify live URLs and responses | Operators, reviewers | Yes | No | `test_deploy_scripts.py` |

## MATM feature contract and data model

The API surface should implement the minimum feature set the user named, but it should do so in a way that is inspectable by humans and agents: explicit route contracts, idempotent writes, capability disclosure, blocked-capability behavior, and Problem Details errors. That aligns with UAIX’s action/API layer, capability/consent layer, and evidence layer, which call for route inventories, idempotency keys, readback URLs, blocked-capability behavior, and no-op justifications. Problem Details is the right error format because RFC 9457 defines it specifically for machine-readable HTTP API errors. citeturn2view5turn9search6

### Minimum viable feature set and route design

The recommended MVP route surface is:

- `POST /api/v1/workspaces`
- `POST /api/v1/agents`
- `POST /api/v1/memory/events`
- `GET /api/v1/memory/events/{event_id}`
- `POST /api/v1/memory/search`
- `GET /api/v1/inbox/current?workspace_id={id}&agent_id={id}`
- `POST /api/v1/messages`
- `POST /api/v1/messages/{message_id}/ack`
- `GET /api/v1/receipts/{receipt_id}`
- `GET /api/v1/receipts/{receipt_id}?view=redacted`
- `GET /api/v1/capabilities`
- `GET /api/v1/routes`
- `POST /api/v1/actions` for safe no-op handling of unsupported actions

Use unknown-route `404` Problem Details for paths that do not exist, but use `POST /api/v1/actions` to return a **successful no-op** for known, intentionally unsupported actions. That no-op payload should always include `supported: false`, `status: "noop"`, `reason`, `capabilities_url`, `routes_url`, and a human review hint. This keeps unsupported agent actions safe and self-describing instead of silently failing. citeturn2view5

A concrete route capability matrix should be shipped in both machine and human form. Each row should include: `route`, `method`, `purpose`, `auth_required`, `idempotency_required`, `supports_redacted_receipts`, `supported`, `human_review_fallback`, and `status`. The dynamic JSON truth should live at `/api/v1/capabilities`; the static mirror should live in `static/.well-known/route-inventory.json`; and the human explanation should live on `/transparency/` and in `docs/api.md`. The coding agent should generate the static file from the runtime route table rather than maintaining two hand-edited truths. citeturn2view5turn0search4

### JSON fallback, SQL targets, and migration path

Because the repo must have no third-party runtime dependencies, the first deploy should use a stdlib-only JSON backend, while the repo still ships MySQL and MariaDB production table definitions and a migration/export path. This is the safest way to satisfy the storage requirement without binding the runtime to an extra Python DB package on day one. MySQL supports a native `JSON` data type with automatic validation and optimized storage, while MariaDB documents `JSON` as an alias added for MySQL compatibility. That difference is why the schema should keep a shared logical model but use separate DDL files for MySQL and MariaDB. citeturn7search0turn6search1

The JSON fallback should use these runtime files:

- `runtime/data/workspaces.json`
- `runtime/data/agents.json`
- `runtime/data/memory_events.ndjson`
- `runtime/data/messages.ndjson`
- `runtime/data/receipts.ndjson`
- `runtime/data/idempotency.json`

Use NDJSON for append-heavy event and message streams; use compact JSON dictionaries for small key-value collections such as workspaces, agents, and cached idempotency results. Every stored record must carry UTC timestamps, a stable opaque ID, and a `schema_version`. All writes should be atomic by writing temp files and replacing the target file, not by partially editing live JSON. The backup/export format should be a canonical JSON package with top-level metadata plus arrays for each entity type, and the export should also write a SHA-256 manifest so the DB migration step can prove counts and checksums before and after conversion. citeturn7search0turn6search1

The SQL model should use these tables:

- `workspaces`
- `agents`
- `memory_events`
- `messages`
- `receipts`
- `idempotency_keys`

Recommended shared columns:

- `id CHAR(26)` or equivalent stable opaque identifier
- `created_utc DATETIME(6)` and `updated_utc DATETIME(6)` where applicable
- `workspace_id`, `agent_id`, `sender_agent_id`, `recipient_agent_id`
- `status`, `visibility`, `event_type`, `receipt_type`
- text summary columns for filterable facts
- JSON document columns for payloads on MySQL and compatibility-safe text/JSON-valid columns on MariaDB
- `request_hash_sha256` and `checksum_sha256` for integrity
- narrow indexes on lookup paths used by inbox, readback, and receipts

The migration path should be: export runtime JSON to canonical bundle; validate counts and checksums; generate SQL insert bundle with `scripts/migrate_json_to_sql.py`; review and apply `sql/001_*` plus `sql/010_indexes.sql`; run SQL-side verification queries from `sql/020_json_to_sql_migration.sql`; keep JSON backend as rollback path until live SQL reads exactly match live JSON reads for a representative sample. The gate for enabling live SQL runtime should remain closed until that parity report is written to `docs/reports/build-verification-report.md`. citeturn7search0turn6search1

### Request and response examples

The API should use placeholder tokens only in docs and examples.

**Workspace registration**

```bash
curl -X POST "https://memoryendpoints.com/api/v1/workspaces" \
  -H "Authorization: Bearer TOKEN_PLACEHOLDER" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: IDEMPOTENCY_KEY_PLACEHOLDER" \
  --data-binary '{
    "workspace_slug": "demo-workspace",
    "display_name": "Demo Workspace",
    "description": "Public MATM demo workspace"
  }'
```

```json
{
  "workspace_id": "wrk_01JZEXAMPLE1234567890AB",
  "workspace_slug": "demo-workspace",
  "display_name": "Demo Workspace",
  "description": "Public MATM demo workspace",
  "status": "active",
  "created_utc": "2026-07-08T23:00:00Z",
  "links": {
    "agents": "/api/v1/agents?workspace_id=wrk_01JZEXAMPLE1234567890AB",
    "capabilities": "/api/v1/capabilities",
    "routes": "/api/v1/routes"
  }
}
```

**Agent registration**

```bash
curl -X POST "https://memoryendpoints.com/api/v1/agents" \
  -H "Authorization: Bearer TOKEN_PLACEHOLDER" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: IDEMPOTENCY_KEY_PLACEHOLDER" \
  --data-binary '{
    "workspace_id": "wrk_01JZEXAMPLE1234567890AB",
    "agent_slug": "portfolio-agent",
    "display_name": "Portfolio Agent",
    "role_name": "writer"
  }'
```

**Memory event submit**

```bash
curl -X POST "https://memoryendpoints.com/api/v1/memory/events" \
  -H "Authorization: Bearer TOKEN_PLACEHOLDER" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: IDEMPOTENCY_KEY_PLACEHOLDER" \
  --data-binary '{
    "workspace_id": "wrk_01JZEXAMPLE1234567890AB",
    "agent_id": "agt_01JZEXAMPLE1234567890CD",
    "event_type": "memory.note",
    "summary": "Agent finished route inventory draft",
    "tags": ["inventory", "docs"],
    "payload": {
      "route_count": 13,
      "artifact": "docs/api.md"
    }
  }'
```

```json
{
  "event_id": "mem_01JZEXAMPLE1234567890EF",
  "workspace_id": "wrk_01JZEXAMPLE1234567890AB",
  "agent_id": "agt_01JZEXAMPLE1234567890CD",
  "event_type": "memory.note",
  "summary": "Agent finished route inventory draft",
  "tags": ["inventory", "docs"],
  "created_utc": "2026-07-08T23:05:00Z",
  "receipt_id": "rcp_01JZEXAMPLE1234567890GH"
}
```

**Memory event read and search**

```bash
curl "https://memoryendpoints.com/api/v1/memory/events/mem_01JZEXAMPLE1234567890EF"
```

```bash
curl -X POST "https://memoryendpoints.com/api/v1/memory/search" \
  -H "Authorization: Bearer TOKEN_PLACEHOLDER" \
  -H "Content-Type: application/json" \
  --data-binary '{
    "workspace_id": "wrk_01JZEXAMPLE1234567890AB",
    "query": "route inventory docs",
    "limit": 10
  }'
```

**Current-message inbox**

```bash
curl "https://memoryendpoints.com/api/v1/inbox/current?workspace_id=wrk_01JZEXAMPLE1234567890AB&agent_id=agt_01JZEXAMPLE1234567890CD"
```

```json
{
  "workspace_id": "wrk_01JZEXAMPLE1234567890AB",
  "agent_id": "agt_01JZEXAMPLE1234567890CD",
  "messages": [
    {
      "message_id": "msg_01JZEXAMPLE1234567890JK",
      "subject": "Review generated readiness record",
      "status": "submitted",
      "created_utc": "2026-07-08T23:10:00Z"
    }
  ]
}
```

**Message submit and acknowledgement**

```bash
curl -X POST "https://memoryendpoints.com/api/v1/messages" \
  -H "Authorization: Bearer TOKEN_PLACEHOLDER" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: IDEMPOTENCY_KEY_PLACEHOLDER" \
  --data-binary '{
    "workspace_id": "wrk_01JZEXAMPLE1234567890AB",
    "sender_agent_id": "agt_01JZEXAMPLE1234567890CD",
    "recipient_agent_id": "agt_01JZEXAMPLE1234567890LM",
    "subject": "Review generated readiness record",
    "body": {
      "artifact": "static/.well-known/readiness.json"
    }
  }'
```

```bash
curl -X POST "https://memoryendpoints.com/api/v1/messages/msg_01JZEXAMPLE1234567890JK/ack" \
  -H "Authorization: Bearer TOKEN_PLACEHOLDER" \
  -H "Content-Type: application/json" \
  --data-binary '{
    "agent_id": "agt_01JZEXAMPLE1234567890LM"
  }'
```

**Redacted receipt**

```bash
curl "https://memoryendpoints.com/api/v1/receipts/rcp_01JZEXAMPLE1234567890GH?view=redacted"
```

```json
{
  "receipt_id": "rcp_01JZEXAMPLE1234567890GH",
  "message_id": "msg_01JZEXAMPLE1234567890JK",
  "receipt_type": "acknowledged",
  "created_utc": "2026-07-08T23:11:00Z",
  "detail_redacted": true,
  "actor": {
    "agent_id": "agt_01JZEXAMPLE1234567890LM",
    "display_name": "Redacted"
  },
  "redactions": ["auth_subject", "ip_address", "raw_headers"]
}
```

**Idempotency replay**

The contract should require `Idempotency-Key` on all write routes. When the same key and same canonical request body are replayed, return the original success body and add a replay indicator such as `X-Idempotent-Replay: true`. If the same key is reused with a different request hash, return `409 Conflict` Problem Details. This follows UAIX’s recommendation to make writes idempotent and explicit. citeturn2view5

**Problem Details error**

```json
{
  "type": "https://memoryendpoints.com/problems/validation-error",
  "title": "Validation failed",
  "status": 400,
  "detail": "recipient_agent_id is required",
  "instance": "/api/v1/messages",
  "trace_id": "trc_01JZEXAMPLE1234567890ZZ"
}
```

**Unsupported action no-op**

```bash
curl -X POST "https://memoryendpoints.com/api/v1/actions" \
  -H "Authorization: Bearer TOKEN_PLACEHOLDER" \
  -H "Content-Type: application/json" \
  --data-binary '{
    "action": "delete_workspace",
    "workspace_id": "wrk_01JZEXAMPLE1234567890AB"
  }'
```

```json
{
  "status": "noop",
  "supported": false,
  "reason": "unsupported_action",
  "action": "delete_workspace",
  "capabilities_url": "/api/v1/capabilities",
  "routes_url": "/api/v1/routes",
  "human_review_fallback": "/transparency/"
}
```

## Frontend and public evidence

UAIX’s implementation and architecture guidance strongly prefer human-first, server-rendered or static semantic content, stable headings, working forms without JavaScript for critical facts, public-safe discovery JSON, and separate public discovery from private configuration. WCAG 2.2 remains the accessibility baseline, and W3C’s semantic structure guidance is directly relevant here. UAIX’s GEO guidance also explicitly rejects cloaking, hidden bot text, fake claims, and other manipulative patterns. citeturn0search4turn2view5turn9search3turn9search19turn9search23turn0search7

The frontend should be intentionally simple and mostly static.

The **homepage** should explain what MemoryEndpoints is, what it can do now, what is intentionally blocked, and where the public route inventory and docs live. It should not promise hosted memory intelligence beyond what the API actually exposes. The main CTA should be “Read the docs,” not “connect a secret.” citeturn2view5turn0search4

The **docs page** should summarize the API, discovery files, support boundaries, and the exact definition of the current MVP. It should be a human-readable landing page that links into `docs/api.md`, `docs/data-model.md`, and `docs/deployment.md`. Keep headings stable and directly answer likely developer questions so both humans and agents can retrieve the same truth from the same canon. citeturn2view5turn8search19

The **API explorer** must never ask for or store a real token in the browser. It should be a copy-safe example generator that shows the route, method, placeholder headers, placeholder body, and expected response. Its copy buttons should emit `TOKEN_PLACEHOLDER` and `IDEMPOTENCY_KEY_PLACEHOLDER`, never an actual secret input field. This keeps the page useful while preserving the “do not print secrets” constraint. citeturn2view5

The **agent setup page** should show the boot order for agents: read `/transparency/`, read `/api/v1/capabilities`, read `/api/v1/routes`, register workspace, register agent, then start memory and messaging calls. It should also point agents to the committed `.uai` package as the hot memory layer and to `docs/memory/` as the durable memory layer until live memory is online. That split mirrors UAIX’s `.uai` plus durable-memory guidance. citeturn2view1

The **memory lifecycle page** should visualize the sequence `submitted -> stored -> searchable -> messaged -> acknowledged -> receipted -> redacted view available`. It should also state that unsupported destructive actions return explicit no-op responses and that unsupported capabilities will remain visibly blocked rather than silently simulated. citeturn2view5

The **human transparency page** should plainly list: supported routes, unsupported routes, auth requirement by route, whether live SQL is enabled, what is redacted in receipts, whether any deploy happened recently, and what claims are historical versus current. UAIX’s testing guidance warns against turning checks into certification theater, so this page must say “evidence-backed status” or “current implementation status,” not “certified.” citeturn0search2turn2view5

The quality bar is strict:

- semantic HTML first
- keyboard-usable navigation
- responsive layout without hiding critical facts in script-only UI
- no hidden bot-only copy
- no false certification or endorsement claims
- identical route/capability truth across HTML, JSON discovery, docs, examples, and explorer

That quality bar comes directly from the combination of UAIX implementation guidance, UAIX anti-cloaking guidance, and WCAG/WAI semantic guidance. citeturn0search4turn0search7turn9search3turn9search23

## Verification plan

Python’s standard library already provides the building blocks needed for the requested verification stack: `unittest` for test suites, `urllib.request` for route checks, and `ftplib`/`FTP_TLS` for deployment transport. Passenger’s Python deployment model also makes it reasonable to verify the WSGI entry point without any extra runtime dependency. citeturn5search0turn5search1turn5search2turn8search18turn5search21

### Test plan

Start with local, fast, deterministic tests before any deploy attempt.

Run these first:

```text
python -m unittest tests.test_repo_hygiene -v
python -m unittest tests.test_uai_package_contract -v
python -m unittest tests.test_discovery -v
python -m unittest tests.test_static_pages -v
python scripts/secret_scan.py
```

Then run the full local suite:

```text
python -m unittest discover -s tests -p "test_*.py" -v
python scripts/validate_json.py
python scripts/generate_route_inventory.py
python scripts/generate_readiness_record.py
python scripts/export_backup.py --dry-run
python scripts/package_release.py --dry-run
```

Then run route tests against the local server:

```text
python app.py --bind 127.0.0.1 --port 8000
python scripts/live_check.py --base-url http://127.0.0.1:8000
```

The scripts and tests should emit exact machine-readable success lines so a coding agent and a human operator can both gate the flow. Require these exact success markers:

```text
REPO_HYGIENE_OK
UAI_PACKAGE_OK
DISCOVERY_OK
STATIC_PAGES_OK
SECRET_SCAN_OK leaks=0
UNIT_TESTS_OK failures=0 errors=0
JSON_VALIDATION_OK
ROUTE_INVENTORY_OK
READINESS_RECORD_OK
EXPORT_DRY_RUN_OK
PACKAGE_DRY_RUN_OK
LIVE_CHECK_OK failures=0
```

### What each verification stage must prove

**Python unit tests using stdlib `unittest`**
Cover route dispatch, validation, idempotency, no-op behavior, redaction, JSON persistence, export/import, and deploy-script parsing. This matches Python’s intended testing framework and keeps the repo free of runtime test dependencies. citeturn5search0

**Route tests using stdlib `urllib`**
The live checker should use `urllib.request` to fetch every route in `deploy/live-routes.txt`, assert expected status codes, required content types, and required substrings. It should also send placeholder write requests against the local dev server and assert either success or explicit auth-block Problem Details, depending on local test config. citeturn5search1turn9search6

**JSON schema-style validation without third-party packages**
`memoryendpoints/validation.py` should implement explicit required-field checks, type checks, enum checks, string length checks, unknown-field policy, and nested object validation. `scripts/validate_json.py` should validate all example files, discovery JSON files, and readiness records. This replaces a `jsonschema` dependency with repo-local, readable rules. citeturn5search0

**Secret scan**
`scripts/secret_scan.py` should scan committed files for common secret indicators: PEM headers, `password=`, `token=`, API-key-like prefixes, JWT-like three-segment strings, private SSH markers, FTP credentials, and high-entropy suspicious literals. It must support an allowlist for known non-secret placeholders such as `TOKEN_PLACEHOLDER`. It must never print the matched secret candidate in full; print masked file path, line number, rule name, and a short masked excerpt only. citeturn9search4turn9search16

**Package integrity check**
`scripts/package_release.py --dry-run` should resolve the allow-list and deny-list, build a package manifest with byte counts and SHA-256 hashes, and confirm that `.git`, caches, local memory scratch files, backups, runtime data, and secret-bearing configs are excluded. This is also the place to reject accidentally included reports that are not explicitly public. citeturn2view5

**Deploy dry run**
This stage must read `E:\ftp_Deploy.txt`, redact secrets in logs, resolve FTP versus FTPS mode, compute the exact remote file set, and write `docs/reports/deploy-dry-run.md` without uploading anything. It passes only if the package manifest, destination paths, excludes, and restart plan are all internally consistent. For FTPS, use `FTP_TLS` and explicitly protect the data connection with `prot_p()`. citeturn5search2turn8search18

**Live post-deploy check**
After publish, `scripts/live_check.py --base-url https://memoryendpoints.com` must verify the exact public URLs listed below, assert the readiness and route inventory JSON is parseable, and confirm that blocked capabilities are visibly blocked rather than omitted. It should write `docs/reports/post-deploy-live-check.md` with status, timestamp, response hash, and a pass/fail table. citeturn2view5turn9search6

## Deployment and GitHub public readiness

GitHub’s own docs describe README, license, contributing guidance, and security policy as core health signals for public repositories, and GitHub exposes community-profile metrics based on those artifacts. For public repo quality, those files should be treated as required, not optional. citeturn8search1turn8search4turn8search15turn8search19turn9search0turn9search4

### Deployment plan

The deploy flow should be:

1. `scripts/parse_ftp_deploy.py --path E:\ftp_Deploy.txt`
2. `scripts/package_release.py --dry-run`
3. `scripts/secret_scan.py`
4. `python -m unittest discover -s tests -p "test_*.py" -v`
5. `scripts/deploy_ftp.py --config E:\ftp_Deploy.txt`
6. `scripts/restart_passenger.py --if-needed`
7. `scripts/live_check.py --base-url https://memoryendpoints.com`

`parse_ftp_deploy.py` must support a file format that can yield host, port, username, password, remote path, protocol, and passive mode, but it must never echo the password or a full connection string. `deploy_ftp.py` should package only the allowed files, upload only changed files where practical, and write a redacted deploy summary to `docs/reports/deploy-dry-run.md` or `docs/reports/post-deploy-live-check.md` as appropriate. `restart_passenger.py` should only touch the Passenger restart marker if the remote host needs it and only after upload success is confirmed. Passenger’s documentation makes `passenger_wsgi.py` the conventional Python entry point for autodetection, so the deploy scripts should treat that file as mandatory. citeturn5search21turn5search3turn5search17

The package allow-list should include: root runtime files required to serve the app, the `memoryendpoints` package, committed static pages and discovery files, committed `.uai` redacted files, docs and examples explicitly marked public, SQL DDL files, tests, and deploy scripts. The deny-list should explicitly exclude: `.git`, `__pycache__`, `.pyc`, local scratch notes, `runtime/data/*`, `runtime/backups/*`, non-public reports, temporary archives, and any file with a rule hit from the secret scanner. citeturn2view5turn5search2

### GitHub public-readiness set

The root README should be structured like this:

- Project summary
- What the public site does now
- What is intentionally unsupported
- Quick start
- Public route inventory and discovery files
- API examples
- Memory model
- Deployment model
- Repo structure
- Verification commands
- Security and responsible disclosure
- License, notices, and trademarks
- Screenshot/demo section
- Changelog link

That shape matches GitHub’s guidance that a README should tell people why the project is useful, what they can do with it, and how they can use it. citeturn8search19

`CONTRIBUTING.md` should explain local test expectations, the “no secrets in repo” rule, the “no NeuralWikis public wiki copy” rule, and the requirement to update route inventory, readiness record, docs, and examples whenever the API changes. GitHub’s docs explicitly call out the value of contribution guidelines in public repos. citeturn8search4turn8search12

`SECURITY.md` should include supported versions, where to report, a response timeline, a responsible disclosure policy, and a note that secrets must never be posted in issues or example requests. GitHub specifically recommends a `SECURITY.md` file for this purpose. citeturn9search0turn9search4

`CHANGELOG.md` should follow a stable human-readable pattern and be updated for each tagged release. GitHub’s release system can generate release notes, but a curated changelog remains useful as the governance record inside the repo. citeturn9search1turn9search9

The repo should include an `examples/` folder and a screenshot shot list. The first screenshot set should be: homepage, docs page, explorer page with placeholder token visible, transparency page, lifecycle page, and a redacted receipt example. None of the screenshots should include secrets, local file paths beyond the project root, or false badges. citeturn8search19turn9search16

### License recommendation

This requirement is the trickiest one in the report. GitHub’s licensing docs note that a repo is only truly open source when its license allows others to use, change, and distribute the software. Choose a License also notes that with no license, others generally have no permission beyond viewing/forking under site terms. Standard permissive licenses such as MIT and Apache 2.0 preserve notices but still allow redistribution; copyleft licenses such as OSL-3.0 go farther on source-sharing obligations, but they still do not actually prevent someone from copying the whole work and presenting it as their own so long as they comply with notice obligations. Because your constraint is specifically to prevent copying the entire work and presenting it as original, the best fit is **not** MIT, Apache 2.0, or a typical OSI-approved license. The best fit is a **custom source-available license** paired with `NOTICE` and `TRADEMARKS.md`, with explicit clauses for attribution retention, notice retention, change marking, trademark reservation, and a clear prohibition on removing origin attribution or representing the work as original authorship. That recommendation is an inference from the permissions and conditions described in GitHub and Choose a License documentation. citeturn8search8turn8search2turn8search17turn8search21turn8search10turn8search13

If you later decide that OSI-approved open source is more important than the anti-pass-off restriction, then OSL-3.0 is the strongest of the cited standard options for preserving notices and treating network use as distribution, but it still would not fully satisfy the “prevent copying the entire work and presenting it as original” constraint. Keep that tradeoff explicit in `docs/repo-public-readiness.md`. citeturn8search10turn8search13

## Definition of done

Done means the repo can be implemented, tested, packaged, deployed, and understood by both humans and agents without ambiguity, while staying inside the hard constraints. UAIX’s evidence model and GitHub’s public-repo guidance both point toward a concrete, inspectable evidence set rather than vague readiness claims. citeturn2view5turn8search1turn9search4

### Exact commands to run

Local implementation and verification:

```text
python scripts/inventory_neuralwikis_patterns.py --source-root E:\NeuralWikis.com --target-root E:\MemoryEndpoints.com
python -m unittest tests.test_repo_hygiene -v
python -m unittest tests.test_uai_package_contract -v
python -m unittest tests.test_discovery -v
python -m unittest tests.test_static_pages -v
python scripts/secret_scan.py
python -m unittest discover -s tests -p "test_*.py" -v
python scripts/validate_json.py
python scripts/generate_route_inventory.py
python scripts/generate_readiness_record.py
python scripts/export_backup.py --dry-run
python scripts/package_release.py --dry-run
python app.py --bind 127.0.0.1 --port 8000
python scripts/live_check.py --base-url http://127.0.0.1:8000
```

Deployment:

```text
python scripts/parse_ftp_deploy.py --path E:\ftp_Deploy.txt
python scripts/package_release.py
python scripts/deploy_ftp.py --config E:\ftp_Deploy.txt
python scripts/restart_passenger.py --if-needed
python scripts/live_check.py --base-url https://memoryendpoints.com
```

### Exact expected outputs

These exact success lines should be required:

```text
NEURALWIKIS_PATTERN_INTAKE_OK copied_content=0
REPO_HYGIENE_OK
UAI_PACKAGE_OK
DISCOVERY_OK
STATIC_PAGES_OK
SECRET_SCAN_OK leaks=0
UNIT_TESTS_OK failures=0 errors=0
JSON_VALIDATION_OK
ROUTE_INVENTORY_OK routes=13
READINESS_RECORD_OK
EXPORT_DRY_RUN_OK
PACKAGE_DRY_RUN_OK
LIVE_CHECK_OK failures=0
DEPLOY_OK uploaded_files=<n>
POST_DEPLOY_OK failures=0
```

The live write-route tests should only pass on production once auth, idempotency, logging hygiene, and rollback are proven. Until then, production write routes may intentionally return explicit auth-block or maintenance-block Problem Details while the public read/discovery surface is live. That is acceptable for first deploy as long as `/transparency/` says so. citeturn2view5turn9search6

### Exact live URLs to verify

Use these URLs after first deploy:

```text
https://memoryendpoints.com/
https://memoryendpoints.com/docs/
https://memoryendpoints.com/explorer/
https://memoryendpoints.com/setup/
https://memoryendpoints.com/lifecycle/
https://memoryendpoints.com/transparency/
https://memoryendpoints.com/api/v1/capabilities
https://memoryendpoints.com/api/v1/routes
https://memoryendpoints.com/.well-known/ai-ready-manifest.json
https://memoryendpoints.com/.well-known/route-inventory.json
https://memoryendpoints.com/.well-known/readiness.json
https://memoryendpoints.com/robots.txt
https://memoryendpoints.com/sitemap.xml
https://memoryendpoints.com/llms.txt
```

If the canonical host in `E:\ftp_Deploy.txt` is not `memoryendpoints.com`, substitute that single canonical host everywhere and update the route inventory, sitemap, and README before publish. The repo should never publish conflicting host truths. citeturn2view5

### Exact report files to produce

These reports should exist by the end of the first release cycle:

- `docs/reports/implementation-verification-plan.md`
- `docs/reports/neuralwikis-pattern-intake.md`
- `docs/reports/build-verification-report.md`
- `docs/reports/public-repo-quality-report.md`
- `docs/reports/deploy-dry-run.md`
- `docs/reports/post-deploy-live-check.md`

Each report should include UTC timestamps, the Git commit hash, the operator or agent name, pass/fail tables, blockers, and explicit next actions. Do not store secrets, do not embed raw credentials, and do not paste unredacted deploy configs into any report. citeturn9search4turn9search16

### What remains gated after first deploy

These gates should remain closed until proven:

- live SQL runtime backend
- any destructive write operation
- any public claim of certification, endorsement, or full production readiness
- any browser path that accepts or stores a real secret
- any copied content from NeuralWikis public wiki pages
- any receipt view that exposes raw auth subject, IP address, raw headers, or other sensitive operator metadata
- any claim that agents can do more than `/api/v1/capabilities` and `/transparency/` say they can do

That is the correct first-release boundary: a professional, portfolio-quality, human-readable, agent-readable MATM reference repo with a safe JSON runtime path, explicit evidence files, clean public docs, and closed gates around the risky parts until the evidence exists. citeturn2view5turn0search2turn0search7
