# Architecture And API Contract Report

## Executive summary

MemoryEndpoints.com should be designed as a **layered, human-first, agent-readable MATM endpoint system**. The correct architectural stance is not “AI-only middleware,” but a public website whose human pages, discovery files, route inventory, API contracts, and durable memory all agree with each other. That matches UAIX’s AI-Ready Web model: accessible human pages first, public-safe discovery second, deterministic APIs third, portable handoff/memory records fourth, and richer runtime protocols only where the implementation can honestly support them. UAIX is explicit that public manifests, `.well-known` discovery, route inventory, readiness evidence, `robots.txt`, `llms.txt`, visible support boundaries, and targeted checks should align, and that sites must not claim capabilities they do not actually operate. citeturn13search0turn15view5turn15view4turn3view6

For MemoryEndpoints.com, that means the most stable design is a **small WSGI Python application plus static HTML/CSS/JS**, with a repository-local `.uai` memory contract and `agent-file-handoff/` intake folders that operate before any database-backed long-term memory is introduced. UAIX’s Project Handoff and Agent File Handoff material strongly favors a compact hot-memory packet, explicit read order, quarantine-first intake, proof-of-use records, and durable cold-memory pointers rather than hidden chat history or private runtime state. citeturn21view0turn18view0turn23view0turn23view2turn23view3

The most important design constraint is also the largest technical risk: **pure Python with no third-party runtime libraries conflicts with a MySQL/MariaDB production requirement**, because Python’s standard library does not ship a MySQL or MariaDB client driver. The standard library does include WSGI tooling through `wsgiref`, but not a MySQL DB-API connector. Therefore, the architecture should intentionally separate the storage abstraction from the storage implementation and launch with **file-backed durable memory first**, then move to MySQL/MariaDB only after one narrow database-adapter exception is explicitly approved or a custom in-house adapter is accepted as scope. citeturn25search0turn24view0turn24view2

The recommended contract is to make the site publicly understandable at the root, deterministic at the API boundary, conservative on security and authority, explicit in no-op behavior, and incremental in milestones. Milestone one should ship a deployable public site with homepage, root discovery surfaces, a public capability matrix, a route inventory, `.uai` hot-memory files, `agent-file-handoff/` intake folders, file-backed receipts/examples, and test scaffolding. Database persistence, search indexing, and richer inbox workflows should arrive only after the storage seam, redaction policy, and support-boundary claims are proven in the repository. citeturn28view1turn23view1turn21view0turn23view3

## UAIX principles and runtime assumptions

### System principles from UAIX AI-Ready Web

UAIX’s architecture model is layered: human-first pages remain accessible and complete; machine discovery exposes public-safe route and policy facts; APIs and OpenAPI handle route contracts; UAI-1 carries portable exchange, evidence, memory, and trust declarations; and MCP or other agent-runtime systems belong only where a real implementation exists. UAIX also requires “one source of truth”: the human page, route manifest, OpenAPI document, schema, examples, validator result, release note, and long-memory evidence should agree before a support claim becomes current. citeturn15view5turn28view3

UAIX’s implementation guidance is particularly relevant here. It says implementation should begin with low-cost evidence that helps both humans and agents: clean HTML, stable discovery, clear route contracts, and a no-op path. It also warns against hidden bot-only text, fabricated citations, unverifiable support claims, and runtime overclaiming. The site’s AI-facing materials must therefore be **public-safe, cacheable, and bounded**, not substitutes for private configuration or authorization. citeturn3view6turn3view7turn15view4

The discovery layer should use standards with mature footing where possible. `robots.txt` has an IETF standard in RFC 9309, but it is explicitly **not** an authorization mechanism. `/.well-known/` locations are governed by RFC 8615. This means paths like `/.well-known/mcp.json` and `/.well-known/ai-agent.json` can be used as discoverable metadata locations, but they should never contain secrets or imply protected execution rights by their mere existence. citeturn9search0turn7search3

For `llms.txt`, the current footing is a public proposal rather than an IETF or W3C standard. The proposal defines `/llms.txt` as a root-level Markdown file that helps LLMs use a site at inference time and recommends linkable Markdown companions. That is strong enough to justify publishing both `/llms.txt` and `/llms-full.txt`, but not strong enough to treat them as formal authority. They should be advisory summaries that remain aligned with the public site and route inventory. citeturn29view0turn30search0turn30search2

The same caution applies to the well-known agent and MCP surfaces. The MCP ecosystem currently has an official registry in preview based on `server.json`, and current MCP work is discussing a cacheable `.well-known/mcp.json` “Server Card” concept. Separately, an IETF Internet-Draft on HTTP-based AI agent discovery discusses agent metadata, agent cards, and possible well-known metadata locations such as `/.well-known/agent-card.json`. Those signals are useful, but they are still evolving. MemoryEndpoints.com should therefore publish the required paths as **project-bounded discovery documents**, explicitly labeled with `specStatus` fields like `stable-project-contract`, `proposal-aligned`, or `preview-aligned`, instead of claiming finalized cross-vendor standards where none yet exist. citeturn15view1turn15view2turn15view3turn31view1turn31view2

### Runtime assumptions

The hosting assumption is **cPanel Application Manager with Passenger and Python WSGI**. cPanel documents that Application Manager deploys applications through Phusion Passenger, supports Apache and NGINX setups, and defaults to system Python paths configurable through Passenger settings. cPanel’s Python WSGI guidance also documents the `passenger_wsgi.py` entrypoint pattern for Python apps. citeturn24view0turn24view1turn33view0

That environment supports a conservative runtime design: a standard-library-oriented Python application using WSGI request handling, HTML template rendering, JSON responses, file I/O, hashing, HMAC, and minimal static asset serving. Python’s standard library includes `wsgiref`, a reference WSGI implementation and validator, which is enough for local development and contract testing even if production is fronted by Passenger instead of `wsgiref.simple_server`. citeturn25search0turn24view2

For the frontend, TypeScript is acceptable as a **development-time language only**. TypeScript’s own documentation is clear that TypeScript compiles to standards-based JavaScript, and that DOM typings ship with the compiler via `lib.dom.d.ts`. Browsers do not execute TypeScript directly, so production artifacts should be emitted browser-safe JavaScript and checked into the deployable output or built during a development step, with **no runtime Node dependency on the server**. citeturn26search1turn26search2turn26search9

For HTML, the right baseline is semantic HTML5 with WCAG-driven accessibility: headings, landmarks, form labels, keyboard reachability, meaningful link text, and primary facts present in source order rather than hidden behind post-load scripts. UAIX explicitly says primary content and policy text should not depend on JavaScript, and W3C/MDN accessibility guidance reinforces semantic HTML as the foundation for assistive technology compatibility. citeturn3view7turn25search3turn25search8turn25search4turn26search3

### Recommended architectural stance

The architecture should therefore be:

- **Python WSGI application** for routing, templating, JSON APIs, auth, receipts, and redaction.
- **Static HTML-first pages** for homepage, documentation, transparency, and route inventory.
- **Browser-safe JavaScript** for enhancement only, not for core facts or policy text.
- **Repository-local `.uai` files and `agent-file-handoff/` buckets** as the first durable memory mechanism.
- **File store first, database second**, because the “no third-party runtime libraries” rule makes immediate MySQL/MariaDB runtime access the only truly unstable part of the design. citeturn21view0turn23view2turn23view3turn24view0turn25search0

## Repository architecture and memory bootstrap

### Folder structure proposal

The repository should use a **boring, inspectable, root-oriented layout**. The structure below is optimized for cPanel/Passenger deploys, UAIX handoff files, browser-safe static assets, and eventual storage swapping without moving public routes.

```text
E:\MemoryEndpoints.com\
  AGENTS.md
  LICENSE
  NOTICE
  README.md
  SECURITY.md
  CONTRIBUTING.md
  TRADEMARKS.md
  passenger_wsgi.py
  requirements.txt
  tsconfig.json

  .uai\
    memory-maintenance.uai
    identity.uai
    world-context.uai
    totem.uai
    taboo.uai
    talisman.uai
    short-term-memory.uai
    startup-packet.uai
    constraints.uai
    progress.uai
    long-term-memory.uai
    file-handoff.uai
    intake-outcome-ledger.uai
    readme.human

  agent-file-handoff\
    Content\
      .keep
    Improvement\
      .keep

  app\
    __init__.py
    routes.py
    request_context.py
    responses.py
    problem_details.py
    auth\
      api_keys.py
      scopes.py
      idempotency.py
    matm\
      capabilities.py
      memory_service.py
      message_service.py
      receipt_service.py
      redaction.py
      authority.py
    storage\
      contracts.py
      file_store.py
      mysql_store.py
      search_contracts.py
    templates\
      base.html
      home.html
      docs_index.html
      transparency.html
    static\
      css\
      js\
      img\

  docs\
    index.md
    route-inventory.json
    readiness-result.json
    ai-ready-site-manifest.json
    reports\
      architecture-api-contract.md
    memory\
      public\
      workspaces\
      receipts-redacted\
      archives\
      pointers\
    schemas\
    examples\
    policies\

  tests\
    unit\
    smoke\
    fixtures\

  tools\
    build_llms_files.py
    check_secret_leaks.py
    check_uaix_readiness.py
    verify_route_inventory.py
    export_docs_memory.py
```

This layout mirrors UAIX’s requirement that launch-baseline `.uai` files travel first, that Project Handoff files remain explicit and reviewable, and that Agent File Handoff use visible `Content/` and `Improvement/` buckets rather than hidden queues or background daemons. cPanel’s guidance also supports a root-level WSGI entrypoint file through `passenger_wsgi.py`. citeturn17view0turn18view0turn19view0turn20view3turn23view2turn23view3turn33view0

### File-based memory bootstrap

UAIX’s memory model is clear: `.uai` hot memory should be **current, compact, and reviewed**, while long history belongs in cold memory with pointers and evidence. `short-term-memory.uai` carries the current compact working state, newest decisions, blockers, and next-read pointers. `startup-packet.uai` gives the next agent a bounded startup sequence and safe first actions. `constraints.uai` records hard technical, legal, product, workflow, and deployment limits. `progress.uai` tracks completed work, remaining work, verification, and delta since the last handoff. `long-term-memory.uai` points to durable archive/wiki/evidence systems without treating all stored history as current truth. `file-handoff.uai` governs intake-bucket scans, dispositions, archive rules, source-site removal, and proof-of-use expectations. citeturn18view0turn19view0turn20view0turn20view1turn20view2turn20view3

That maps cleanly onto a bootstrap strategy for MemoryEndpoints.com:

- `.uai/short-term-memory.uai` is the **hot startup memory** for the next human or agent.
- `.uai/startup-packet.uai` is the **first-read operational sequence** for repository work.
- `.uai/constraints.uai` is the **red-line contract** for technology, policy, authority, and deploy limits.
- `.uai/progress.uai` is the **current delivery ledger**.
- `.uai/long-term-memory.uai` is the **pointer ledger** to `docs/memory/...`.
- `docs/memory/...` is the **durable cold-memory layer** until database-backed long-term memory is approved.
- `.uai/intake-outcome-ledger.uai` is the **proof-of-use record** for loose-file intake. citeturn21view0turn23view2turn23view3turn22view1

The durable docs layer should be split by **review state and audience**, not by tool internals. A practical structure is:

```text
docs/memory/
  public/
    capabilities/
    policies/
    receipts-redacted/
  workspaces/
    default/
      promoted/
      current/
      events/
      archives/
  pointers/
    long-term-ledger.md
```

That preserves UAIX’s “hot context, cold memory” model and keeps public-safe outputs separated from authenticated workspace memory. The promoted/current split matters because UAIX repeatedly warns against treating raw intake, old chats, or unresolved brainstorming as current truth. citeturn17view2turn18view0turn20view2turn23view0

### Intake processing workflow

Agent File Handoff should be treated as a **strict, local intake lane**, not a passive upload folder. UAIX’s specification is unusually concrete here: the next AI must enumerate active buckets, open every pending file, summarize risk, state a disposition, perform safe concrete work when appropriate, record the outcome in durable state, preserve configured durable-memory evidence, and then remove the source-site copy before claiming completion. It also explicitly says the folder contents themselves are the intake index and that no hand-maintained intake-index file should be introduced. citeturn23view2turn23view3turn22view1

For MemoryEndpoints.com, the processing workflow should be:

1. On startup or on any prompt referencing intake, enumerate `agent-file-handoff/Content/` and `agent-file-handoff/Improvement/`.
2. Classify misplaced root-level intake files before any broader planning.
3. For each active file, record:
   - summary
   - risk class
   - target surface
   - recommended disposition
   - checks required
   - processed outcome
4. Apply a safe slice of work immediately where possible.
5. Update `.uai/short-term-memory.uai` and `.uai/progress.uai`.
6. Record proof-of-use in `.uai/intake-outcome-ledger.uai`.
7. Preserve the durable pointer in `docs/memory/...` if configured.
8. Remove the active intake file from the source bucket once the durable record exists. citeturn22view0turn22view1turn23view2turn23view3

### Frontend UX

The public site should have a very small, trust-building information architecture:

- **Home**: what MemoryEndpoints.com is, what MATM means here, what is public, what is authenticated, what is not supported.
- **Capabilities**: machine and human matrix of implemented routes and support boundaries.
- **Docs**: route inventory, schemas, examples, readiness record, changelog.
- **Receipts examples**: redacted public examples only.
- **Transparency**: version, storage mode, public support boundary, no-op behavior, privacy notes.
- **Report library**: architecture report and later verifier reports. citeturn15view4turn28view1turn3view6turn23view1

The homepage copy should be plain and explicit. UAIX’s implementation guidance stresses accurate pages, stable routes, transparent evidence, and fewer hallucinated answers; MDN and W3C accessibility guidance push toward semantic structure and plain language. So the homepage should explain MemoryEndpoints.com in simple terms: a public sample implementation of MATM endpoints, with discovery files for agents, deterministic APIs, receipts, and visible support boundaries. It should also state what the site **does not** do yet, especially where database-backed persistence, live MCP transport, or external authority validation remains incomplete. citeturn3view7turn25search4turn25search8

## API contract and authority boundaries

### Discovery contract

The public discovery surfaces should be treated as **aligned views over the same truth**, not separate authoring systems. The AI-Ready site manifest should contain site identity, public routes, discovery files, capability profiles, API contracts, policy boundaries, evidence links, freshness, and unsupported claims. UAIX explicitly says it is designed for public-safe data only. citeturn28view2

The discovery contract should therefore be:

| Route | Format | Purpose | Notes |
|---|---|---|---|
| `/robots.txt` | `text/plain` | Crawl guidance | Advisory only, never authorization |
| `/llms.txt` | `text/plain; charset=utf-8` | Concise AI-readable index | Human-readable Markdown structure |
| `/llms-full.txt` | `text/plain; charset=utf-8` | Single-file expanded AI-readable context | Advisory companion, not source of truth |
| `/ai.txt` | `text/plain; charset=utf-8` | Brief project-defined AI guidance | Keep minimal and bounded |
| `/ai-manifest.json` | `application/json` | Main public machine manifest | Canonical discovery object |
| `/.well-known/mcp.json` | `application/json` | Preview-aligned cacheable MCP discovery metadata | Do not imply a live MCP transport unless implemented |
| `/.well-known/ai-agent.json` | `application/json` | Project-defined agent-card-style metadata | Keep fields aligned with public auth/capability facts |

This design is grounded in RFC 8615 for well-known URIs, RFC 9309 for `robots.txt`, the `llms.txt` proposal for root-level LLM-readable discovery, UAIX’s public-safe manifest model, and the still-evolving MCP/agent-card work. citeturn7search3turn9search0turn29view0turn28view2turn15view1turn31view2

### MATM route inventory

All API errors should use **RFC 9457 Problem Details**, with a MemoryEndpoints extension field such as `no_op: true|false`, and all mutating POST routes should require an `Idempotency-Key`. The no-op behavior should follow UAIX’s safe-stop pattern: return a stable explanation, a review URL if available, and stop instead of retry-looping, inventing credentials, or escalating capabilities that were never proven. citeturn9search1turn9search17turn10search2turn10search3turn23view1

| Route | Method | Access | Purpose | Request schema | Response schema | Failure and no-op behavior |
|---|---|---|---|---|---|---|
| `/` | GET | Public | Human homepage | none | HTML page with overview, boundaries, links | `200` always if site is healthy enough to serve static HTML |
| `/api/v1/health` | GET | Public | Health and version route | none | `{ status, version, build_utc, storage_mode, commit, readiness }` | `503` if unhealthy; never expose secrets or private config |
| `/api/v1/capabilities` | GET | Public | Capability matrix route | optional `view=public` | `{ version, discovery, api, auth_modes, storage_mode, supported_actions, unsupported_actions }` | `200` with honest support boundary; never advertise unimplemented transports |
| `/api/v1/memory/submit` | POST | Authenticated | Memory submit route | `{ workspace_id, agent_id, memory_type, content, source_ref?, tags?, authority_context? }` | `{ ok, memory_id, receipt_id, created_utc, status }` | `401/403` on auth failure; `422` or `409` with Problem Details + `no_op:true` if authority gate blocks or input is unsupported |
| `/api/v1/memory/search` | POST | Authenticated | Memory search route | `{ workspace_id, q, filters?, limit?, cursor? }` | `{ results:[...], next_cursor?, count_estimate?, search_mode }` | `422` for invalid filters; `200` empty set when no matches |
| `/api/v1/memory/{memory_id}` | GET | Authenticated | Memory read route | path id, optional `view=summary|full` | `{ memory_id, workspace_id, content, redactions?, receipts?, created_utc }` | `404` if not found; `403` if read not allowed; apply redaction before return |
| `/api/v1/agents/{agent_id}/inbox/current` | GET | Authenticated | Agent inbox current-message route | path id, optional `workspace_id` | `204` no message or `{ message_id, thread_id, from_agent_id, subject, body, created_utc, receipt_required }` | `204` preferred over `404` when inbox exists but is empty |
| `/api/v1/agents/{agent_id}/messages` | POST | Authenticated | Agent message submit route | `{ workspace_id, from_agent_id, subject, body, body_format, priority?, receipt_required? }` | `{ ok, message_id, receipt_id, status, created_utc }` | `422`/`409` no-op when recipient unsupported, blocked, or authority not satisfied |
| `/api/v1/receipts/ack` | POST | Authenticated | Receipt/ack route | `{ receipt_id?, message_id?, ack_code, note?, external_ref? }` | `{ ok, ack_receipt_id, related_receipt_id, status, created_utc }` | Idempotent replay on duplicate key; no-op if item already acknowledged |
| `/api/v1/receipts/examples/redacted` | GET | Public | Redacted example receipts route | optional `kind`, `limit` | `{ examples:[{...}] }` | `200` with public-safe redacted artifacts only |
| `/ai-manifest.json` | GET | Public | Canonical manifest | none | `{ site, discovery, routes, supportBoundary, evidence, freshness }` | `200`; must remain public-safe |
| `/.well-known/mcp.json` | GET | Public | Preview-aligned MCP surface | none | `{ specStatus, server, capabilities, auth, transport_status }` | If MCP runtime is absent, document discovery only and set transport status to unsupported |
| `/.well-known/ai-agent.json` | GET | Public | Agent metadata surface | none | `{ specStatus, id, name, description, capabilities, auth, invoke, docs }` | If only public metadata exists, omit protected invocation operations |

The route design above intentionally keeps **public discovery public, authenticated memory private, reviewer promotion separate, and operator deploy out of the public API**. That follows UAIX’s insistence on bounded capabilities, no-op fallbacks, and support-boundary honesty. It also avoids using `robots.txt`, `llms.txt`, or well-known files as control planes. citeturn15view5turn3view6turn23view1turn9search0

### Authority boundaries

Authority needs its own explicit matrix because the user requirement is not just route design, but **anti-overclaiming**. The cleanest contract is:

| Boundary | Who can read | Who can write | Notes |
|---|---|---|---|
| Public docs and discovery | Anyone | Operator/reviewer only | Public-safe, cacheable, no secrets |
| Authenticated memory | Scoped API key holder | Scoped API key holder, subject to workspace rules | Memory read/write never implied by discovery docs |
| Reviewer memory promotion | Reviewer role only | Reviewer role only | Promotion from intake or draft to accepted memory |
| Operator-only deploy/config | Operator only | Operator only | Uses `ftp_Deploy.txt` during deploy/config only |
| External authority receipts | Public redacted examples; full receipts authenticated or operator-scoped | Only trusted internal pipeline | External evidence is linked, not overclaimed |

This matches UAIX’s Memory Firewall rule that imported packets are quarantined public data until validated and accepted by local policy, and its No-Op Protocol rule that unsupported, unproven, or high-impact actions must stop safely rather than pretending authority. citeturn23view0turn23view1

The practical consequence is that unsupported actions should never return vague errors like “failed” or “coming soon.” They should return a Problem Details document with a stable problem type, a specific reason, a `no_op: true` flag, and an alternative such as a review URL, a supported read-only endpoint, or guidance to submit a narrower request. That reflects UAIX’s required behavior: explain the missing capability or consent, provide the public URL if available, and stop. citeturn23view1turn3view6

## Persistence and security model

### Database schema proposal

MemoryEndpoints.com should use **UTC-named columns**, `utf8mb4`, InnoDB, additive migrations, and relational tables for the core domain. `utf8mb4` is the correct Unicode-safe baseline in MySQL. Both MySQL and MariaDB support InnoDB foreign keys, and both support InnoDB `FULLTEXT` indexes for text columns. citeturn27search3turn27search7turn27search2turn27search14turn8search2turn8search14

One portability caution matters: **MySQL and MariaDB differ in JSON semantics**. MySQL has a native validated `JSON` type, while MariaDB documents JSON behavior differently and stores JSON strings as normal strings with different comparison semantics. To keep one schema portable across both engines, the safer design is to store contract payloads as `LONGTEXT`/`TEXT` with application-side JSON validation, plus extracted scalar columns where query performance needs them. citeturn27search1turn27search5

#### Core tables

**`agents`**

- `agent_id` PK
- `agent_slug` unique
- `display_name`
- `agent_kind` (`human`, `ai`, `system`, `external`)
- `status`
- `public_description`
- `capabilities_text`
- `metadata_json_text`
- `created_utc`
- `updated_utc`

Indexes: unique on `agent_slug`, index on `status`, index on `updated_utc`.

**`workspaces`**

- `workspace_id` PK
- `workspace_slug` unique
- `display_name`
- `visibility` (`public`, `private`, `mixed`)
- `default_redaction_class`
- `retention_policy_json_text`
- `created_utc`
- `updated_utc`

Indexes: unique on `workspace_slug`, index on `visibility`.

**`memory_events`**

- `memory_event_id` PK
- `workspace_id` FK
- `agent_id` FK
- `parent_memory_event_id` nullable FK
- `event_type` (`submit`, `promote`, `correct`, `archive`, `redact`, `import`)
- `authority_gate_id` nullable FK
- `receipt_id` nullable FK
- `visibility`
- `redaction_class`
- `title`
- `summary_text`
- `content_text`
- `payload_json_text`
- `content_sha256`
- `source_ref`
- `created_utc`
- `superseded_utc` nullable

Indexes: `(workspace_id, created_utc desc)`, `(workspace_id, event_type, created_utc desc)`, `(content_sha256)`, `(receipt_id)`.

**`memory_search_index`**

- `memory_event_id` PK/FK
- `workspace_id` FK
- `title_text`
- `summary_text`
- `body_text`
- `keywords_text`
- `language_code`
- `last_indexed_utc`

Indexes: InnoDB `FULLTEXT(title_text, summary_text, body_text)`, plus `(workspace_id, last_indexed_utc desc)`. citeturn8search2turn8search3turn8search14

**`messages`**

- `message_id` PK
- `workspace_id` FK
- `from_agent_id` FK
- `to_agent_id` FK
- `thread_id`
- `subject`
- `body_text`
- `body_json_text`
- `priority`
- `delivery_state` (`pending`, `current`, `acked`, `closed`, `noop`)
- `receipt_required`
- `created_utc`
- `acked_utc` nullable
- `expires_utc` nullable

Indexes: `(to_agent_id, delivery_state, created_utc desc)`, `(workspace_id, thread_id, created_utc)`.

**`notifications`**

- `notification_id` PK
- `workspace_id` FK
- `agent_id` FK
- `notification_kind`
- `related_type`
- `related_id`
- `status`
- `message_text`
- `created_utc`
- `read_utc` nullable

Indexes: `(agent_id, status, created_utc desc)`.

**`receipts`**

- `receipt_id` PK
- `workspace_id` FK
- `receipt_kind` (`submit`, `ack`, `promotion`, `external_authority`, `noop`, `error`)
- `related_type`
- `related_id`
- `status`
- `public_example_allowed`
- `redacted_receipt_json_text`
- `full_receipt_json_text`
- `external_authority_uri` nullable
- `external_authority_hash` nullable
- `created_utc`

Indexes: `(workspace_id, receipt_kind, created_utc desc)`, `(related_type, related_id)`.

**`authority_gates`**

- `authority_gate_id` PK
- `workspace_id` nullable FK
- `gate_code`
- `scope_type`
- `allow_public_read`
- `allow_authenticated_write`
- `allow_reviewer_promotion`
- `operator_only`
- `requires_external_receipt`
- `rule_json_text`
- `status`
- `created_utc`
- `updated_utc`

Indexes: unique on `(workspace_id, gate_code)`.

**`audit_log`**

- `audit_log_id` PK
- `workspace_id` nullable FK
- `actor_agent_id` nullable FK
- `actor_role`
- `request_id`
- `route`
- `http_method`
- `action_code`
- `target_type`
- `target_id`
- `status_code`
- `outcome_code`
- `idempotency_key_hash`
- `ip_hash`
- `user_agent_hash`
- `created_utc`

Indexes: `(created_utc desc)`, `(route, created_utc desc)`, `(workspace_id, created_utc desc)`, `(request_id)`.

**Recommended support tables**

- `api_keys`
- `idempotency_records`
- `schema_migrations`

These are not optional in practice if authenticated writes and replay-safe POST semantics are required. citeturn10search2turn10search3

### Redaction rules

The system should distinguish at least four redaction classes:

| Redaction class | Public examples | Authenticated workspace read | Operator read |
|---|---|---|---|
| `public-safe` | Full | Full | Full |
| `workspace-sensitive` | Summary only | Full | Full |
| `review-sensitive` | Omit body, keep metadata | Reviewer-scoped | Full |
| `secret-bearing` | Metadata only | Metadata only unless explicitly authorized | Full |

This is consistent with UAIX’s Memory Firewall stance that imported packets should be quarantined, provenance-inspected, redacted where needed, and promoted only after review. It also matches the requirement not to expose raw credentials or unsupported claims. citeturn23view0turn18view0turn20view0

Public receipt examples should therefore expose things like `receipt_id`, `receipt_kind`, `status`, `created_utc`, `workspace_slug` or public alias, and a redacted “what happened” summary, but not full memory bodies, private agent identifiers, raw request headers, secrets, or deploy internals. A redacted example route is only useful if it demonstrates the contract without leaking private state. citeturn23view1turn28view2

### Migration strategy

The migration strategy should be **flat SQL files plus a tiny Python runner**, not an ORM migration framework. That keeps the runtime dependency surface clean and aligns with the no-third-party-runtime goal.

Recommended pattern:

- `db/migrations/0001_init.sql`
- `db/migrations/0002_receipts.sql`
- `db/migrations/0003_fulltext_index.sql`
- `app/storage/migrate.py`
- `schema_migrations` table with:
  - `migration_id`
  - `applied_utc`
  - `checksum_sha256`

Rules:

- additive first
- destructive only after reviewer approval
- every migration idempotent where feasible
- rebuildable search index from `memory_events`
- one-time file-to-db import script once persistence is approved

This matches UAIX’s emphasis on visible evidence, reviewability, and promotion of reviewed current facts rather than silent mutation. citeturn21view0turn23view0

### Security model

#### Credential handling

`E:\ftp_Deploy.txt` should be treated as an **operator-only deploy/config source**, never a runtime content source and never a committed repository artifact. The application should read deploy credentials during provisioning and place effective secrets into server-local environment variables or a non-web-accessible config file with restrictive filesystem permissions. OWASP’s secrets guidance is clear that secrets need centralized control, auditing, lifecycle handling, and leak prevention. citeturn9search3turn9search23

The public APIs must never echo raw DSNs, usernames, passwords, or connection diagnostics. Public health/version output should disclose storage mode and version information, not connection strings, exception traces, or hostnames tied to private infrastructure. That is both a straightforward security requirement and a direct consequence of UAIX’s public-safe discovery boundary. citeturn28view2turn23view1

#### API keys

For authenticated memory and inbox routes, the minimal acceptable design is **scoped API keys**. OWASP’s REST security guidance notes that API keys can help with denial-of-service control but should not be the only protection for sensitive or high-value resources. The right pattern here is API keys plus route-level scope checks plus authority-gate decisions plus audit logging. citeturn10search16turn10search19

Recommended key model:

- prefix-based identifiers such as `mep_live_...` and `mep_test_...`
- store only `key_id`, `key_hash`, scope, workspace, status, created/revoked UTC
- verify by constant-time comparison
- scope examples:
  - `memory:write`
  - `memory:read`
  - `message:write`
  - `message:read`
  - `receipt:ack`
  - `review:promote`
  - `operator:deploy`

#### Idempotency keys

Every POST that can create or mutate state should require `Idempotency-Key`. MDN describes the header as the way to make POST and PATCH requests safely replayable, and the IETF draft requires uniqueness and recommends UUID-like identifiers. The server should persist the key hash, request hash, original status code, response body hash, and expiry time so retries can return the original outcome instead of duplicating writes. citeturn10search2turn10search3turn10search6

#### Secret scanning

A no-third-party-runtime stance does not prevent strong repository hygiene. A built-in scanner can still look for high-risk patterns such as:

- `ftp_Deploy.txt`
- `mysql://`
- `mariadb://`
- `password=`
- PEM headers
- obvious API key prefixes
- service tokens
- SMTP secrets

OWASP’s DevSecOps and secrets guidance explicitly recommends detection of secrets in repositories and pre-commit prevention. citeturn9search23turn9search3

#### CORS

CORS should be **deliberately narrow**. MDN’s guidance shows that cross-origin writes involve preflight `OPTIONS` requests and cached policy decisions. Public GET discovery surfaces may use permissive `Access-Control-Allow-Origin: *` if they carry no credentials and no private data. Authenticated APIs should default to same-origin only, or to a short explicit allowlist of trusted origins, with `Allow-Credentials` disabled for public endpoints. citeturn9search2turn9search6turn9search14

#### Rate limits

OWASP’s API guidance is unambiguous: endpoints must enforce limits appropriate to their resource cost. Recommended starting limits:

- public discovery GETs: generous, proxy-enforced
- public examples GETs: moderate per IP
- authenticated search: moderate per API key
- authenticated writes: stricter per API key and per workspace
- inbox polling: short-burst allowed, sustained capped

Because Passenger deployments may run multiple processes, exact app-level in-memory rate limiting should be treated as best effort unless enforced at Apache/hosting level. That is a design caveat worth documenting publicly. citeturn10search19turn10search13turn24view0

## Verification, licensing, milestones, and risks

### Verifier and test plan

UAIX’s validator/testing guidance centers on targeted checks, readiness evidence, blockers, and skipped checks rather than vague declarations. MemoryEndpoints.com should follow that model with a mixed suite of unit tests, smoke tests, readiness checks, and deploy verification. citeturn15view4turn28view1

#### Unit tests

Unit tests should cover:

- route dispatch
- request parsing
- Problem Details generation
- no-op escalation paths
- API key verification
- scope enforcement
- idempotency replay
- receipt redaction
- memory event promotion rules
- file-handoff intake classification
- route inventory generation
- manifest alignment checks

Python’s standard library plus `wsgiref` validation and basic HTTP tooling are enough to build the first pass of this suite without runtime framework lock-in. citeturn25search0turn24view2

#### Route smoke tests

Smoke tests should confirm:

- root routes return expected content types
- `robots.txt` is at root and valid for the host
- well-known files exist and return cacheable JSON
- health/version returns no secrets
- capability matrix does not overclaim
- authenticated routes reject unauthenticated callers
- POST routes require `Idempotency-Key`
- no-op responses are stable and reviewable

The `robots.txt` checks should explicitly confirm root placement, UTF-8 plain-text formatting, and host-scoped validity. citeturn29view1turn9search0

#### Secret leak checks

Secret checks should fail the build if they detect:

- deploy credential files in staged output
- DSNs or raw passwords in docs or JSON
- private environment dumps in health/version
- receipt examples containing secret-bearing data
- `.well-known` or manifest files exposing private URLs or credentials

That is directly aligned with OWASP secret-management guidance and with the requirement not to expose raw credentials. citeturn9search3

#### UAIX readiness checks

The readiness checker should compare:

- homepage boundary text
- `ai-manifest.json`
- route inventory JSON
- readiness-result JSON
- `llms.txt`
- no-op documentation
- public capability matrix
- redacted receipt examples

against one authoritative route/config registry. UAIX’s “one source of truth” requirement means the checker should fail when those surfaces drift. citeturn28view3turn15view4

#### Deploy verification

Deploy verification for cPanel/Passenger should confirm:

- `passenger_wsgi.py` exists and resolves the app entrypoint
- static files serve correctly
- app restart path is documented
- environment variables load without leaking to the public
- effective Python version is the intended one
- health/version and homepage are reachable after restart

cPanel’s WSGI documentation explicitly documents the `passenger_wsgi.py` entrypoint pattern and restart behavior via Passenger. citeturn33view0turn24view1

### Licensing and notice structure

The stated licensing goal is unusual but internally consistent: allow viewing, learning, and contributing, while discouraging people from copying the whole project and presenting it as their own original product. A plain permissive open-source license does **not** satisfy that goal, because open-source licenses allow reuse for any purpose. ChooseALicense states that open-source licenses allow anyone to use, modify, and share software for any purpose. citeturn11search2

The best fit is therefore a **source-available code license plus attribution and trademark controls**, rather than an OSI-style permissive license. Business Source License 1.1 is the strongest fit among the sources reviewed because it explicitly allows copying, modification, redistribution, and non-production use, while allowing the licensor to define an Additional Use Grant for limited production scenarios. MariaDB’s own BSL FAQ also confirms that non-production use is always free and that the licensor may grant limited production rights. citeturn11search0turn11search15turn32search3turn32search6turn32search16

For documentation, tutorials, and explanatory content, **CC BY-NC-SA 4.0** is a better complement than the code license because it permits adaptation and sharing for noncommercial use with attribution and ShareAlike obligations. Creative Commons describes CC BY-NC-SA as permitting remixing, adapting, and building upon the material for noncommercial purposes with attribution and reciprocal licensing of derivatives. citeturn32search2

The recommended licensing stack is:

- **Code**: `BUSL-1.1` with an Additional Use Grant allowing:
  - personal use
  - educational use
  - internal evaluation
  - non-production self-hosting
  - contributions and public forks for review
  - no offering of a competing hosted or commercial product without separate permission
- **Docs and reports**: `CC BY-NC-SA 4.0`
- **Brand name and logos**: separate `TRADEMARKS.md`; no trademark license granted through code or docs

That trademark separation matters because copyright licenses do not solve passing-off problems by themselves. Trademark law is about source identity and confusion, and public trademark policies commonly separate mark usage from software code rights. citeturn12search1turn12search3turn12search10

Recommended legal files:

- `LICENSE`
- `NOTICE`
- `TRADEMARKS.md`
- `ATTRIBUTION.md`
- `CONTRIBUTORS.md`

`NOTICE` should follow the general structure used in mature projects: product identity, copyright notice, license pointer, third-party notices, and a statement that contributors retain attribution in `CONTRIBUTORS.md`. Apache’s licensing guidance is a good model for keeping NOTICE specific to the product while leaving the license text itself unmodified in `LICENSE`. citeturn12search2turn12search5

Recommended README language:

> MemoryEndpoints.com is a public reference implementation of MATM endpoint design. The repository is published for study, evaluation, issue reporting, discussion, and contribution. The code is source-available, not permissive open source. You may inspect, fork, test, and propose improvements under the repository license terms, but you may not present the project, its deployable product surface, brand identity, or materially complete derivative as your own original commercial offering without separate permission.

Recommended contributor attribution rules:

- all merged contributors listed in `CONTRIBUTORS.md`
- significant design/report authorship noted in `NOTICE` or `ATTRIBUTION.md`
- modified forks must preserve origin attribution
- modified forks must not imply endorsement
- use of project name/logo governed by `TRADEMARKS.md` only

### Implementation milestones

#### Milestone one

**Minimal deployable site**

Deliver:

- homepage
- accessibility baseline
- `robots.txt`
- `llms.txt`
- `llms-full.txt`
- `ai.txt`
- `ai-manifest.json`
- `/.well-known/mcp.json`
- `/.well-known/ai-agent.json`
- public health/version
- capability matrix
- route inventory JSON
- readiness-result JSON
- `.uai` launch-baseline files
- `agent-file-handoff/Content/`
- `agent-file-handoff/Improvement/`
- file-backed redacted receipt examples
- smoke tests and secret checks

This milestone is consistent with UAIX’s guidance to start with clean HTML, stable discovery, route contracts, and a no-op path before richer agent interfaces. citeturn3view6turn28view1

#### Milestone two

**MATM API**

Add:

- memory submit
- memory search/read
- agent inbox current-message
- message submit
- receipt ack
- Problem Details error model
- scoped API keys
- idempotency persistence
- audit logging to file store

#### Milestone three

**DB persistence**

Add:

- approved DB adapter seam
- MySQL/MariaDB schema
- migration runner
- file-to-db import
- DB-backed receipts, messages, and memory events

#### Milestone four

**Search**

Add:

- FULLTEXT indexing
- search ranking profiles
- search filters
- snippet/highlight generation
- reindex jobs

#### Milestone five

**Dogfood memory**

Add:

- real repo self-use of `.uai` and `agent-file-handoff/`
- reviewer promotion workflow
- durable cold-memory docs export
- receipt examples from real internal events after redaction

#### Milestone six

**Public GitHub polish**

Add:

- contributor docs
- governance docs
- licensing polish
- screenshots
- public examples
- deploy notes
- badges only after tests are real

### Highest-risk design decisions

The highest-risk decisions are the ones where requirements collide with runtime reality:

- **MySQL/MariaDB without third-party runtime libraries**. Python’s standard library does not include a MySQL/MariaDB client, so DB-backed runtime persistence requires either an approved exception or a custom adapter. This is the largest unresolved implementation risk. citeturn25search0turn24view0
- **Publishing `/.well-known/mcp.json` without overclaiming MCP runtime support**. MCP discovery/server-card work is still evolving, and the official registry is in preview. The file should be metadata-only until a real transport exists. citeturn15view1turn15view2turn15view3
- **Publishing `/.well-known/ai-agent.json` when current draft language discusses agent cards and example well-known paths like `agent-card.json`**. The route can satisfy the product requirement, but it must be labeled as a project-defined alias rather than a finalized cross-vendor standard. citeturn31view1turn31view2
- **Rate limiting on Passenger**. Application-level throttling can become approximate under multi-process hosting, so limits should be documented as app-level best effort unless hosting-level enforcement is available. citeturn24view0turn10search19
- **Keeping multiple discovery surfaces aligned**. The route inventory, readiness result, homepage copy, well-known JSON, and `llms` files must come from one canonical configuration or drift will happen quickly. UAIX treats that alignment as mandatory before support claims become current. citeturn28view3turn15view4

### Recommended milestone one file list

The recommended milestone one file list is:

- `AGENTS.md`
- `README.md`
- `LICENSE`
- `NOTICE`
- `SECURITY.md`
- `CONTRIBUTING.md`
- `TRADEMARKS.md`
- `passenger_wsgi.py`
- `app/routes.py`
- `app/responses.py`
- `app/problem_details.py`
- `app/templates/base.html`
- `app/templates/home.html`
- `app/templates/transparency.html`
- `app/static/css/site.css`
- `app/static/js/site.js`
- `.uai/memory-maintenance.uai`
- `.uai/identity.uai`
- `.uai/world-context.uai`
- `.uai/totem.uai`
- `.uai/taboo.uai`
- `.uai/talisman.uai`
- `.uai/short-term-memory.uai`
- `.uai/startup-packet.uai`
- `.uai/constraints.uai`
- `.uai/progress.uai`
- `.uai/long-term-memory.uai`
- `.uai/file-handoff.uai`
- `.uai/intake-outcome-ledger.uai`
- `.uai/readme.human`
- `agent-file-handoff/Content/.keep`
- `agent-file-handoff/Improvement/.keep`
- `docs/reports/architecture-api-contract.md`
- `docs/route-inventory.json`
- `docs/readiness-result.json`
- `docs/ai-ready-site-manifest.json`
- `docs/memory/public/README.md`
- `docs/memory/workspaces/default/README.md`
- `docs/memory/receipts-redacted/README.md`
- `tests/smoke/test_public_routes.py`
- `tests/unit/test_problem_details.py`
- `tests/unit/test_no_op_contract.py`
- `tools/check_secret_leaks.py`
- `tools/check_uaix_readiness.py`
- `tools/build_llms_files.py`
- root `robots.txt`
- root `llms.txt`
- root `llms-full.txt`
- root `ai.txt`
- root `ai-manifest.json`
- `/.well-known/mcp.json`
- `/.well-known/ai-agent.json`

### Open questions and limitations

A few items remain intentionally unresolved at the architecture stage:

- The contents of `E:\ftp_Deploy.txt` were not available here, so this report designs the **credential handling boundary**, not environment-specific deploy syntax.
- The exact schema for `/.well-known/mcp.json` and `/.well-known/ai-agent.json` should be treated as **project-defined and standards-aligned**, not standards-final, because the underlying ecosystems are still evolving. citeturn15view1turn15view2turn15view3turn31view1
- `ai.txt` does not have the same maturity as `robots.txt`; it should remain a small advisory surface and never outrank the manifest or route inventory in authority.
- The report path requested by the project is:

`E:\MemoryEndpoints.com\docs\reports\architecture-api-contract.md`
