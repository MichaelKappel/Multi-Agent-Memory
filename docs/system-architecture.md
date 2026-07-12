# System Architecture

This document explains the checked-in MemoryEndpoints implementation as a system rather than as a list of features. It is revision-scoped: code and tests define local behavior, while the live `/api/version` route identifies which Git revision production is actually serving.

## Source Precedence

Use evidence in this order when claims disagree:

1. Checked-in runtime code and tests for revision behavior.
2. `memoryendpoints.site_data.ROUTE_TABLE` for the source route inventory.
3. `/api/version` for deployed source SHA and storage-backend provenance.
4. Live route, MySQL, companion-site, and authenticated dogfood verification for deployment behavior.
5. Current engineering documents in `docs/` and MultiAgentMemory.com for explanation.
6. Generated reports only for the exact point in time and SHA they record.

Tracked `docs/reports/` files are historical snapshots. Fresh verifier output belongs under ignored `var/reports/`. Durable reviewed product knowledge belongs in protected MemoryEndpoints database wiki and memory records.

## Product Surfaces

| Surface | Ownership | Responsibility |
| --- | --- | --- |
| MemoryEndpoints.com | `memoryendpoints/`, root WSGI entry points, `static/` | Public discovery and evidence, protected MATM APIs, authenticated human console and wiki shell |
| MultiAgentMemory.com | `sites/multiagentmemory.com/` | Static companion documentation, complete route reference, memory boundary, and AI-readable discovery |
| GitHub repository | Entire checked-in tree | Reviewable code, tests, schema, scripts, startup memory, and deployment logic |
| Local `.uai/` | Typed startup-memory suite | Active offline continuity and operating constraints; it stays active even when hosted memory is unavailable |
| MySQL/MariaDB | Production storage backend | Tenant hierarchy, protected memory, wiki, citations, coordination, sync, receipts, quota, and audit state |

MultiAgentMemory.com does not proxy protected API calls or store tenant data. MemoryEndpoints.com does not expose a password-free public tenant wiki. GitHub documentation is not a second durable memory database.

## Runtime Topology

The production application is a Python WSGI service exported through `passenger_wsgi.py`. Request dispatch, public HTML and JSON surfaces, authentication, validation, readback confirmation, and safe error envelopes live in `memoryendpoints/app.py`. Storage ownership and backend parity live in `memoryendpoints/storage.py`. Public route and capability records live in `memoryendpoints/site_data.py`.

The runtime uses Python standard-library HTTP, JSON, hashing, SQLite, and WSGI facilities. It does not package a third-party runtime dependency. Production MySQL/MariaDB uses a host-provided compatible Python adapter when the MySQL backend is selected.

Browser assets are ordinary semantic HTML, CSS, and committed JavaScript. The human console and wiki use the same protected APIs as agents; they do not receive a privileged filesystem knowledge path.

## Request Lifecycle

1. WSGI receives the method, path, query, headers, and bounded request body.
2. Public routes dispatch without tenant authentication and return only product documentation or redacted evidence.
3. Protected routes require `Authorization: Bearer <workspace-key>` and resolve the key hash to one workspace boundary.
4. Protected mutation routes validate `Idempotency-Key`, body shape, workspace identity, quota, scope, and route-specific authority before storage mutation.
5. Storage writes one logical operation through the selected backend.
6. The application reads the result back through the relevant search, transcript, inbox, receipt, tree, or audit path.
7. A successful response carries explicit confirmation fields. Missing readback becomes a safe failure rather than an optimistic success.
8. Errors use a redacted problem/no-op envelope with stable codes and no raw credential, payload, reviewer note, or idempotency-key disclosure.

## Identity And Tenancy

The durable hierarchy is:

```text
project -> workspace -> company
                       ^
                       |
             account-company membership
```

An account is an identity boundary, not a knowledge owner. Accounts and companies have a many-to-many relationship through explicit memberships. A company can contain multiple workspaces, and a workspace can contain multiple projects.

Durable knowledge scopes are exactly `company`, `workspace`, and `project`. Goal and task objects can own coordination rooms and active memory context, but they do not own durable crawlable wiki trees. Lasting findings from goal/task work must be promoted to the narrowest durable company/workspace/project scope.

Every protected storage query is constrained by the authenticated workspace. Client-provided IDs do not grant cross-workspace access.

## Authentication And Retry Safety

`POST /api/matm/agent-setup/free-account` creates the initial account/company/workspace/project graph and returns a workspace key exactly once. Persistence stores a verifier hash, never the raw key.

Protected mutations use an idempotency record bound to workspace, operation, key digest, and request-body digest:

- Exact retry: replay the original public-safe status and response.
- Same key with different body: return `409 Conflict` and `safeNoOp=true`.
- Missing key on routes that require retry safety: reject before mutation.
- Raw idempotency keys: never returned in receipts, audits, logs, or public docs.

Idempotency prevents duplicate processing of the same accepted operation. It is not distributed consensus, authorization, or rollback of external effects.

## Storage Backends

| Backend | Intended use | Completion boundary |
| --- | --- | --- |
| SQLite | Default local relational backend | Full local development and integration verification using stdlib `sqlite3` |
| MySQL/MariaDB | Production backend | Must be selected and reported verified by `/api/version` and `verify_mysql_backend.py` |
| File store | Explicit local development/test fallback | Does not satisfy the production database requirement |

The route-level contract is shared across backends. Tests exercise file and SQLite parity; the live MySQL verifier and authenticated dogfood prove the production adapter and deployed schema.

## Relational Ownership

The canonical SQL schema separates responsibilities instead of storing one opaque application blob:

- Tenant graph: `matm_accounts`, `matm_companies`, `matm_account_companies`, `matm_workspaces`, `matm_projects`.
- Access: `matm_api_keys`, `matm_agents`.
- Accountless-browser UAIX packages: `matm_uai_packages`, `matm_uai_records`, `matm_uai_record_revisions`.
- Local `.uai` collaboration metadata: `matm_uai_collaboration_heads`, `matm_uai_edit_claims`.
- Durable memory: `matm_memory_records`, `matm_memory_revisions`, `matm_memory_tags`.
- Knowledge wiki: `matm_crawl_sources`, `matm_search_documents`.
- Curated web index: `matm_external_links`, `matm_external_link_mentions`.
- Current-message delivery: `matm_messages`, `matm_notifications`.
- Meeting coordination: `matm_meeting_rooms`, `matm_meeting_messages`, `matm_routing_decisions`, `matm_meeting_reads`.
- Distributed sync: `matm_sync_devices`, `matm_sync_heads`, `matm_sync_revisions`, `matm_sync_receipts`.
- Governance and evidence: `matm_review_queue`, `matm_receipts`, `matm_idempotency`, `matm_outbox_events`, `matm_storage_ledger`, `matm_audit_log`.

Foreign keys and workspace identifiers make ownership explicit. Route confirmation URLs and canonical IDs make post-write evidence inspectable without exposing internal credentials.

## Memory Lifecycle

Memory submission is review-aware rather than an unconditional append:

1. An authenticated agent submits a bounded public-safe summary and optional title, subject, memory type, scope, source, confidence, and tags.
2. The deterministic memory firewall examines secret-like tokens, dangerous object keys, script markers, and prompt-injection signals.
3. The server stores only the redacted public-safe representation and creates a review record.
4. Search and review-queue readback confirm persistence.
5. An explicit review operation promotes, rejects, or quarantines the record. Reviewer notes are stored as digests and are not echoed.
6. Normal recall excludes rejected and quarantined memory.

Memory types include fact, decision, status, procedure, risk, evidence, handoff, and note. Scope, source reference, lifecycle, review state, tags, and actor remain separately queryable.

Local `.uai` remains active startup memory regardless of hosted availability. Hosted memory augments recall; it does not erase the offline startup contract.

## UAIX Active-Memory Modes

MemoryEndpoints supports two active-memory modes with different ownership and
persistence boundaries. They share workspace authentication and registered
agent identity, but they must never be silently interchanged.

### Accountless Browser Exception

The normal architecture keeps `.uai` on the local filesystem. A browser-only AI
without durable filesystem access cannot satisfy that continuity rule, so it may
create one protected virtual package bound to:

- Authenticated workspace.
- Stable registered agent ID and display name.
- `accountless_browser_ai` client class.
- Explicit `localFilesystemAvailable=false` capability.
- Versioned UAIX virtual-package profile.

The package stores supported logical UAIX records, protected public-safe body,
SHA-256 body hash, byte count, revision, role, startup order, status, accepted
firewall evidence, and immutable revision snapshots. The virtual logical
`.uai/short-term-memory.uai` role creates no local file. It therefore does not
change the repository rule that forbids an actual local file with that name.

The startup packet is the read-order index. Universal startup roles include
startup packet, memory maintenance, identity, world context, Totem, Taboo,
Talisman, and progress. The accountless-browser short-term role and durable
pointer ledger are configuration-specific. Identity content is bound to the
current registered agent id and display name; a rename makes startup incomplete
until the identity record is revision-safely updated. Startup packet content
must enumerate every required logical path.

Package creation begins in `setup_required`. Readiness is derived from current
active records rather than a caller-supplied flag. Startup returns records in a
deterministic order and refuses to describe partial setup as complete. Active
record bodies must be date-free, structurally typed, bounded, and accepted by
the memory firewall before persistence. Updates require compare-and-swap
revision checks and exact protected readback.

This is a MemoryEndpoints database adaptation, not a `.uaix` package file or a
claim of UAIX hosted import, automatic sync, certification, or conformance.

This exception is not anonymous storage. The embedding product may have no user
account system of its own, but the MemoryEndpoints workspace bearer key remains
the authorization boundary and the registered agent remains the memory owner
inside that workspace.

### Local Multi-Agent Collaboration Overlay

Filesystem agents keep their `.uai` bodies local. MemoryEndpoints stores only a
coordination overlay for a real project and logical local path:

- Latest observed SHA-256 content hash and monotonic head revision.
- Active claim owner and bounded lease metadata.
- Public-safe edit intent.
- Completion hash and completion or release summary.
- Status, audit, outbox, and quota-ledger evidence.

An agent hashes the unchanged local file and acquires a claim before editing.
The storage transaction creates or locks the project/path head, expires stale
leases, checks for an active owner, compares the caller's base hash, and grants
one claim. Another cooperating agent receives a conflict-safe `409` with the
safe owner and head metadata. Completion compares the original base again,
advances only the hash head, clears the lease, and retains claim history.

The overlay never receives file content or a patch. It does not write local
files, distribute an updated file, merge changes, or prove that work from an
expired lease was integrated. Agents still use source control, file handoff,
and the protected project meeting room to exchange and reconcile content. The
claim is a transactional coordination protocol for cooperating agents, not an
operating-system lock.

### Credential And Failure Boundary

Browser connectors default to an in-memory bearer key. Persistent key storage
requires explicit opt-in and encryption with an unlock secret that is not
persisted. Same-origin script compromise remains outside what browser storage
can prevent, so CSP, dependency integrity, and XSS controls are required.

The workspace key is never package content, collaboration metadata, a URL,
query parameter, prompt, console value, analytics field, or compiled asset. If
the accountless browser cannot reach MemoryEndpoints, it must surface that its
continuity source is unavailable rather than fabricate remembered state. A
filesystem agent continues from local `.uai` during the same outage.

## Knowledge Wiki

The wiki is a protected database view shared by humans and agents. The anonymous `/knowledge` page is only an authentication shell.

Each knowledge document requires:

- Human-readable title.
- Short description.
- Search keywords.
- Protected searchable content.
- Durable scope and scope ID.
- One or more taxonomy paths.
- Source URI and source type when evidence exists.
- Lifecycle status and authority level.

One canonical source can produce several focused semantic pages. One page can appear in several taxonomy hierarchies without duplicating its body. This supports conceptual navigation such as prompt budgets through tokenization, cost governance, context management, or agent operations instead of requiring one exact phrase.

Lifecycle status distinguishes current, proposed, historical, superseded, and archived content. Authority distinguishes canonical, reviewed, reference, community, and unverified material. Non-current pages explain why; superseded pages point to their replacement. Search ranking prefers current canonical guidance without deleting historical evidence.

Report ingestion is intentionally one source at a time:

1. Review one file as if it arrived independently.
2. Preserve a canonical source page.
3. Extract focused pages with explicit lifecycle and authority.
4. Place each page in every useful hierarchy.
5. Attach citations individually.
6. Promote compact source-linked memory summaries individually.
7. Verify tree crawl, semantic retrieval, source readback, privacy, and authenticated UI behavior before selecting another source.

Bulk archive import is not the dogfood path because it hides classification errors and prevents learning from each report.

## External Links And Citations

External links are not untyped strings in document bodies. The canonical record stores normalized URL, host, site name, page title, description, keywords, review state, crawl state, and crawl policy. Mention records separately store which knowledge page cites the link, relationship type, anchor, context, label, and order.

This split allows one URL to support many pages while preserving page-specific meaning. It also allows MemoryEndpoints to provide a curated workspace internet-search surface.

Safety rules include:

- Only public HTTP(S) targets are accepted.
- Credential-bearing URLs, loopback/private hosts, and unsupported schemes are rejected.
- Metadata indexing does not authorize a fetch.
- Crawl status is explicit evidence, not an implied success.
- An incidental `unreviewed` citation cannot downgrade an existing explicit reviewed, quarantined, or rejected canonical state.

## Meeting Rooms And Routing

Meeting rooms are first-class coordination objects:

- Company room: authenticated welcome and initial routing.
- Workspace room: shared operating context across related projects.
- Project room: implementation coordination for one codebase.
- Goal room: focused coordination for a substantial objective.
- Task room: narrow coordination when a distinct task warrants it.

Company, workspace, and project rooms are derived from the tenant graph and remain available. Goal and task rooms are created explicitly. Transcripts support pagination and per-agent read cursors.

A structured routing decision records source room, destination room, coordinator, routed agent, lane, specific goal, expected evidence, next action, and support plan. It also writes a readable public-safe summary to the source transcript and returns readback URLs.

Meeting messages are coordination evidence, not automatic durable truth. Explicit promotion creates a hosted memory event with the source meeting-message ID. This makes the transition reviewable and prevents casual discussion from silently becoming canonical memory.

## Current Messages

Current messages provide an attention lane separate from durable room transcripts:

- A target agent ID creates a targeted delivery.
- Omitting the target creates per-agent notifications for active workspace agents.
- Each recipient has an independent unread and acknowledgement state.
- Inbox and current-message reads support exact message/notification filters and bounded pagination.
- Acknowledgement creates a redacted receipt without exposing the original private payload.

Current messages are for action and required attention. Meeting rooms are for durable coordination transcripts. Hosted memory and wiki documents are for reviewed recall.

## Distributed Sync V1

Sync v1 replicates public-safe memory summaries through an explicit revision graph:

1. Register a device authority for an agent and device ID.
2. Read the authority epoch and current logical-memory head.
3. Submit an idempotent upsert or tombstone with the expected parent revision.
4. The server validates workspace, device status, epoch, parent, operation, and tombstone rules.
5. Accepted mutations create an immutable revision, update the authoritative head, allocate a monotonic server sequence, and persist a redacted receipt.
6. Consumers read incremental changes after a checkpoint and reconcile authoritative heads.

Conflict outcomes are evidence-bearing, not silent:

- Parent mismatch.
- Device epoch mismatch.
- Revoked device.
- Tombstone resurrection blocked.
- Idempotency-key/body conflict.

The retention route advertises tombstone and hard-forget policy. Sync does not claim universal hard deletion, rollback of external effects, silent last-write-wins, or conflict-free behavior without a valid parent.

## Readback And Evidence

Mutation success is not defined as "the storage call returned." Important writes confirm visibility in the relevant read model:

- Memory submit: search, review queue, and audit log.
- Knowledge upsert: document query, semantic search, wiki tree, and audit log.
- External link upsert: canonical-link query, internet search, and document mention.
- Meeting post: room transcript and sender visibility.
- Routing decision: decision query plus source and destination transcript metadata.
- Current message: target inbox/current-message visibility.
- Sync mutation: immutable revision, head, receipt, and checkpoint sequence.
- Virtual UAIX record: package, logical path, record ID, revision, and content hash.
- Local `.uai` edit claim: claim ID, project/path head, lease owner, and head revision; completion confirms the new hash-only head.

Confirmation fields such as `persisted`, canonical IDs, visibility booleans, and safe query URLs are part of the contract. A route must not return normal success when required readback fails.

## Privacy And No-Op Boundary

The system stores public-safe summaries rather than arbitrary private payloads. It rejects or redacts secret-like material and prevents credential values from appearing in reports, public pages, receipts, audit details, or error envelopes. The accountless-browser exception stores a protected active record body only after strict date, structure, size, and memory-firewall validation. The local collaboration overlay never stores the local file body.

Unsupported, unauthorized, malformed, quota-blocked, and conflict-gated actions return stable redacted failures. Safe no-op means the system reports that it did not perform the requested action; it does not mean an error is hidden or treated as success.

Robots, manifests, schemas, signatures, metadata, model consensus, and capability declarations do not grant authorization. Workspace authentication and route-specific validation remain separate controls.

## Packaging And Deployment

The package builder records the checked source SHA and content hash, rejects dirty source inputs, and excludes Git metadata, `.uai`, local secrets, local prompts, handoff payloads, runtime stores, databases, logs, caches, reports, and deployment handoffs.

Deployment uses an explicit-FTPS dry run, connection check, live upload, and Passenger restart request. A deployment is current only when the live `/api/version` source SHA matches the checked Git head after upload.

Production completion separately requires:

- Verified MySQL/MariaDB backend.
- Live public-route verification.
- Authenticated live dogfood.
- Live companion-site verification.
- Secret, repository-boundary, `.uai`, package, documentation, and diff checks.

GitHub Actions is retained but is not the operator-required completion gate. Local and live evidence remain mandatory.

## Verification Matrix

| Evidence | What it proves | What it does not prove |
| --- | --- | --- |
| Unit/integration suite | Current local code behavior across core contracts and local backends | That production serves this commit |
| WSGI verifier | Required local public routes and leak boundaries | Authenticated production behavior |
| Documentation freshness test | Route table is represented in GitHub and companion references | Semantic correctness of every paragraph |
| Package check | Exact source provenance and exclusion boundary | Successful remote upload |
| Live route verifier with expected SHA | Production public surface serves the expected commit | Protected workflows or MySQL by itself |
| MySQL verifier | Production selected and verified MySQL/MariaDB | Full authenticated workflow correctness |
| Live dogfood | Protected deployed workflow and evidence readback | Every possible scale, failure, or threat scenario |
| Companion verifier | Required MultiAgentMemory.com artifacts are live and leak-safe | MemoryEndpoints protected API behavior |
| Secret scan | Known credential patterns are absent from scanned files | Proof that no unknown sensitive fact exists |

## Code Map

- `memoryendpoints/app.py`: WSGI routing, validation, authorization boundary, response contracts, and public HTML.
- `memoryendpoints/storage.py`: file, SQLite, and MySQL/MariaDB storage behavior and read models.
- `memoryendpoints/site_data.py`: route table, discovery records, compatibility, connector contract, and public evidence models.
- `memoryendpoints/security.py`: memory firewall and redaction helpers.
- `memoryendpoints/uai_memory.py`: UAIX virtual-package roles, date-free validation, accountless-browser exception, and local collaboration contract.
- `docs/database-schema-canonical.sql`: canonical relational schema.
- `scripts/`: package, deploy, route, MySQL, dogfood, secret, `.uai`, repository, and readiness verifiers.
- `tests/`: contract, integration, parity, concurrency, UI-source, documentation, and verifier tests.
- `sites/multiagentmemory.com/`: public companion documentation and AI-readable discovery.
