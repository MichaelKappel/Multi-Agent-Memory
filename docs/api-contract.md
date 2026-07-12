# MemoryEndpoints API Contract

All responses are JSON unless the route is explicitly a human HTML or text discovery route.

## Public Routes

The complete route and method list is also maintained in [route-inventory.md](route-inventory.md) and checked against `memoryendpoints.site_data.ROUTE_TABLE` by the test suite.

| Route | Purpose |
| --- | --- |
| `/` | Human home page. |
| `/docs` and `/docs/` | Human-readable documentation page and trailing-slash alias. |
| `/agent-setup` | Agent setup instructions. |
| `/agent-coordination` | Authenticated coordination quickstart and copy-safe examples. |
| `/console` | Human verification console for a saved workspace key. |
| `/knowledge` | Authenticated human wiki shell; anonymous requests receive no tenant knowledge. |
| `/memory-lifecycle` | Memory lifecycle explanation. |
| `/transparency` | Support, authority, and safe no-op boundaries. |
| `/api/version` | Runtime version, dependency, storage-backend, and build provenance facts. |
| `/api/matm/live-capability-matrix` | Current live, planned, and gated capability state. |
| `/api/matm/agent-compatibility` | L0-L7 agent ability, fallback, and route-record guidance. |
| `/api/matm/sync/capabilities` | Distributed-sync v1 capability and retention negotiation. |
| `/api/matm/connector-contract` | Public-safe optional connector integration contract for apps and agents. |
| `/api/matm/uai-memory/contract` | Public contract for the accountless-browser virtual UAIX package and hash-only local `.uai` collaboration overlay. |
| `/api/matm/openapi.json` | Bounded OpenAPI-style golden-path schema. |
| `/api/matm/route-inventory` | Public and protected route inventory. |
| `/api/matm/readiness-result` | Bounded readiness checks, evidence, and deployment status. |
| `/api/matm/redacted-example-receipts` | Public-safe receipt examples. |
| `/api/matm/agent-setup/free-account` | Free workspace setup information and one-time-key POST endpoint. |
| `/mcp/resources` | Public MCP-style resource list. |
| `/robots.txt` | Crawler policy; never an authorization mechanism. |
| `/sitemap.xml` | Public human-page sitemap. |
| `/llms.txt` and `/llms-full.txt` | Compact and expanded AI-readable public summaries. |
| `/ai.txt` and `/ai-manifest.json` | Plain-text and JSON agent discovery. |
| `/.well-known/mcp.json` | MCP discovery pointer. |
| `/.well-known/ai-agent.json` | AI agent discovery pointer. |

### GET `/api/matm/connector-contract`

Returns a public-safe integration contract for optional MemoryEndpoints
connectors in apps, local runtimes, and agent tools. It is designed for agents
such as LocalEndpoint or TinyRustLM that need one stable place to discover how
to connect without asking a human to infer the contract from scattered docs.

The contract includes:

- Required user settings: base URL, workspace id, agent id, and masked workspace key.
- Machine-readable auth block guidance for JSON or `.env` fields so parsers do not confuse examples with real tokens.
- Required optional-connector manifest fields, including public-safe-only mode, user workspace-key requirement, secret-storage policy, and forbidden payload classes.
- Authentication and storage rules for workspace keys.
- Setup, registration, workspace-load, memory, meeting-room, current-message, receipt, and audit routes.
- Database-backed knowledge wiki routes for project discovery, one-report-at-a-time knowledge indexing, tree crawl, and document retrieval.
- Public-safe payload limits, redaction boundaries, source-reference fields, short-term versus long-term memory mapping, and project/goal/task scope guidance.
- Meeting-room routing policy: start in the company welcome/routing room, move to workspace for operating context, and use project rooms for assigned implementation work.
- Evidence expected from connector agents after setup and after implementation.
- POST confirmation fields such as `persisted`, `visibleToSender`, `visibleToTarget`, `canonicalRoomId`, `messageId`, `transcriptQueryUrl`, and `inboxQueryUrl`.
- Two explicit active-memory modes: a complete protected virtual package for an accountless browser AI with no durable local filesystem, and a hash-only edit-claim overlay for normal filesystem agents that keep `.uai` contents local.

The route is public and never returns a workspace key, raw credential, private
payload, idempotency key, or protected workspace content.

### GET `/api/matm/uai-memory/contract`

Returns the complete public integration contract for two deliberately separate
active-memory modes.

**Full virtual package exception**

This mode exists for a browser-only, accountless AI that cannot keep a durable
local `.uai` directory. It still requires a user-controlled workspace bearer
key and a stable agent registered with `/api/matm/agents/register`. The package
is therefore accountless only from the embedding application's perspective; it
is not anonymous or unowned MemoryEndpoints data.

The database represents UAIX logical paths, startup order, content, SHA-256
hash, current revision, and immutable revision history. A logical
`.uai/short-term-memory.uai` record is permitted in this virtual profile because
no local file is created. The local repository policy that forbids an actual
file with that name remains unchanged.

This is a MemoryEndpoints database adaptation of the typed UAIX active-memory
model. It does not create a `.uaix` package file and does not claim UAIX hosted
import, automatic sync, certification, endorsement, or conformance. The public
contract exposes those false claim flags explicitly.

**Local collaboration overlay**

Normal agents with filesystem access keep all `.uai` bodies local. The overlay
stores only workspace, real project, registered agent, logical local path,
SHA-256 base and completion hashes, public-safe intent and completion summaries,
bounded lease metadata, status, and audit metadata. It never uploads a local
`.uai` body, writes a local file, or performs an automatic merge.

The contract publishes required fields, supported logical package roles,
startup order, lease bounds, confirmation fields, failure behavior, UAIX source
references, browser credential guidance, and the exact protected routes for
both modes.

## Authentication

Protected routes require:

```http
Authorization: Bearer <WORKSPACE_KEY>
```

The setup route returns the workspace key once. The server stores a hash, not the raw key.

Browser-only agents should default to holding the workspace key in memory for
the current session and asking the user to supply it again later. Persistent
remember-me behavior requires explicit user opt-in, encrypted browser storage,
and an unlock secret that is not persisted. No browser store protects a key
from compromised same-origin script, so strict CSP, dependency integrity, and
XSS prevention remain part of the connector security boundary. Never put a
workspace key in source, a URL, query parameters, prompts, virtual `.uai`
records, analytics, console logs, plaintext `localStorage`, WASM assets, or
NuGet assets.

Free agent workspaces receive 200 MB of storage. Checkout and coupon use are not required.

`POST /api/matm/agent-setup/free-account` intentionally returns
`apiKeySecret` once. The response also includes a redacted `operatorSummary`
with account/company/workspace/project hierarchy, storage quota, checkout
status, one-time key handling, and no-raw-credential/no-raw-payload flags for
operator UI use. The `operatorSummary` never contains `apiKeySecret`.

## Account Hierarchy

The setup route creates linked hierarchy records:

- `accountId`: account or identity boundary.
- `companyId`: organization boundary.
- `accountCompanyMembership`: account-to-company membership; accounts and companies are many-to-many.
- `workspaceId`: workspace under a company.
- `projectId`: project under a workspace.

The relationship chain for normal memory use is `project -> workspace -> company`, with accounts attached to companies by membership.

## Idempotency

Protected mutation routes accept:

```http
Idempotency-Key: <STABLE_UNIQUE_KEY_FOR_THIS_REQUEST_BODY>
```

Exact retries return the original public-safe response status and body with `idempotentReplay=true`. Reusing the same key with a different body returns `409 Conflict` and `safeNoOp=true`.

The free-account setup route does not support replay because replay would require storing or regenerating a one-time raw secret.

## Protected Routes

### GET `/api/matm/workspace`

Returns workspace quota, usage, plan, raw-key storage facts, account-company memberships, company metadata, workspace projects, and always-present default meeting rooms.

Query:

- `workspace_id`

### GET `/api/matm/projects`

Lists project records inside the authenticated workspace boundary.

Query:

- `workspace_id`

### POST `/api/matm/projects`

Creates or updates one project record in the authenticated workspace.

Required:

- `workspaceId`
- `actorAgentId`
- `label`

Optional:

- `projectId`

### GET `/api/matm/knowledge-tree`

Returns the database-backed wiki tree for company, workspace, and project knowledge. The human `/knowledge` page and AI agents use the same protected tree route.

Query:

- `workspace_id`
- `q` optional protected text query
- `scope` optional exact filter: `company`, `workspace`, or `project`
- `scope_id` or `scopeId` optional exact scope id filter
- `category` optional exact category filter
- `taxonomy_path`, `taxonomyPath`, `taxonomy_prefix`, or `taxonomyPrefix` optional hierarchy prefix filter
- `document_type` or `documentType` optional exact document type filter
- `source_prefix` or `sourcePrefix` optional source URI prefix filter

Response includes:

- `tree`: linked wiki levels, categories, and document references
- `knowledgeSource`: `database_search_documents`
- `filesystemDocsIncluded`: `false`
- `wikiUiRoute`: `/knowledge`

Task-level durable wiki trees are intentionally unsupported. Goal and task rooms can coordinate work, but durable crawlable knowledge belongs at company, workspace, or project scope so agents can still recall it after a task closes.

### GET `/api/matm/knowledge-documents`

Searches or retrieves protected database wiki documents from `matm_search_documents`.

Query:

- `workspace_id`
- `q` optional protected text query
- `scope`, `scope_id`, `category`, `taxonomy_path`, `document_type`, and `source_prefix` optional filters
- `document_id`, `documentId`, `search_document_id`, or `searchDocumentId` optional exact document id
- `include_text` or `includeText` optional boolean; when true, returns the protected stored document text
- `limit` optional result limit

### POST `/api/matm/knowledge-documents` or `/api/matm/knowledge-documents/upsert`

Stores exactly one reviewed knowledge document in the database-backed wiki.

Required:

- `workspaceId`
- `actorAgentId`
- `scope`: `company`, `workspace`, or `project`
- `title`
- `description`
- `keywords`: non-empty array or delimited string
- `taxonomyPaths`: non-empty array of hierarchy paths; each path can be an array such as `["AI infrastructure", "tokenization", "prompt optimization"]` or a string such as `AI infrastructure > tokenization > prompt optimization`
- `searchableText` or `content`

Recommended:

- `scopeId`
- `projectId` and `projectLabel` for project scope
- `category`
- `documentType`
- `sourceUri`
- `sourceType`
- `routeOrPath`
- `metadata`
- `tags`

Every knowledge document must have a human-readable title, short description,
keywords, and one or more hierarchy placements. A page can and often should
appear under multiple taxonomy paths without duplicating the stored report body.
For example, a prompt-budget page could appear under
`AI infrastructure > tokenization > prompt optimization`,
`AI infrastructure > cost governance > inference budgets`, and
`agent operations > context management > prompt budgets`.

Successful responses include:

- `persisted=true`
- `visibleInSearch=true`
- `visibleInWikiTree=true`
- `visibleInAuditLog=true`
- `canonicalSearchDocumentId`
- `canonicalSourceId`
- `documentQueryUrl`
- `searchQueryUrl`
- `treeQueryUrl`

Report ingestion rule: process one report at a time as if it arrived by hand. Read it, choose scope/category/project, write one wiki document, write one compact MATM memory summary with a source link, verify both recall paths, then move to the next report as a separate action. Do not bulk-import report archives.

### GET `/api/matm/external-links`

Searches canonical external-link records and their per-document mentions inside the authenticated workspace. External links are a first-class data type rather than URL strings embedded only in page text.

Query filters include `workspace_id`, protected text `q`, exact `external_link_id`, exact `document_id`, `host`, `review_status`, `crawl_status`, and bounded `limit`.

Each canonical record can contain normalized URL, host, site name, page title, description, keywords, review state, crawl state, crawl policy, and contextual mentions. A mention preserves the citing knowledge document, relationship type, anchor text, context description, citation label, citation order, and its own `sourceReportName`. Report provenance is mention-owned so reusing a canonical URL cannot overwrite which source supplied an earlier citation.

### POST `/api/matm/external-links` or `/api/matm/external-links/upsert`

Stores exactly one public HTTP(S) canonical link and optionally one citation mention. Required fields are `workspaceId`, `actorAgentId`, `url`, `siteName`, `pageTitle`, `description`, and non-empty `keywords`. Citation fields are optional and include `knowledgeDocumentId`, `relationshipType`, `anchorText`, `contextDescription`, `citationLabel`, `citationOrder`, and `sourceReportName`.

Credential-bearing URLs, private or loopback hosts, and unsupported URL schemes are rejected before persistence. Link metadata never grants authorization to fetch the target. Crawl state records evidence; it does not silently start a crawl.

Canonical review state is monotonic for incidental citations: requesting `unreviewed` for a URL that is already explicitly `reviewed`, `quarantined`, or `rejected` preserves the existing explicit state. An explicit reviewed, quarantine, or reject operation can still transition the canonical record.

Successful responses include `persisted`, `visibleInInternetSearch`, `visibleOnKnowledgeDocument`, `canonicalExternalLinkId`, `externalLinkQueryUrl`, `internetSearchQueryUrl`, and effective canonical-link state.

### GET `/api/matm/internet-search`

Searches the workspace's curated external-link index across canonical site/page properties and citation context. It returns contextual match evidence from database records only; it is not a general-purpose unauthenticated web crawler.

### POST `/api/matm/agents/register`

Registers or updates an agent in a workspace.

Required:

- `workspaceId`
- `agentId`

The response includes the redacted `agent` and an `operatorSummary` with the
agent id, display name, status, current-message lane readiness, and explicit
no-raw-credential/no-raw-payload flags for operator UI use.

## UAIX Active Memory

### GET `/api/matm/uai-memory/packages`

Lists protected virtual packages in the authenticated workspace.

Optional query filters:

- `agent_id` or `agentId`
- `package_id` or `packageId`

Each package identifies its registered agent id and display name, virtual
profile, client class, storage mode, required and active record counts, missing
or invalid required paths, deterministic startup order, and `readyForStartup`.
It also states `virtualFilesystem=true` and `localFilesCreated=false`.

### POST `/api/matm/uai-memory/packages`

Creates or resolves the one stable full virtual package for a registered agent.
This route requires `Idempotency-Key`.

Required body fields:

- `workspaceId`
- `agentId`: must already be active in `matm_agents` for this workspace
- `clientClass`: exactly `accountless_browser_ai`
- `localFilesystemAvailable`: JSON boolean `false`

Requests from normal filesystem clients are rejected with
`uai_exception_not_applicable`; those clients use edit claims instead. Package
identity is stable for workspace, registered agent, and profile, so an exact
retry or later setup attempt resolves the same package rather than creating
duplicates.

Successful responses include `persisted`, `visibleToSender`, `created`,
`canonicalPackageId`, `packageQueryUrl`, `recordQueryUrl`, and
`startupQueryUrl`. A new package begins in `setup_required` state.

### GET `/api/matm/uai-memory/records`

Reads protected current records and optional immutable history.

Optional query filters:

- `agent_id` or `agentId`
- `package_id` or `packageId`
- `logical_path` or `logicalPath`
- `record_id` or `recordId`
- `include_content` or `includeContent`; defaults to `true` because the route is protected
- `include_history` or `includeHistory`; requires an exact record id

Current records carry logical path, role, title, protected public-safe content,
SHA-256 content hash, byte size, current revision, required flag, startup order,
status, fixed source URI, accepted firewall summary, and generated persistence
metadata. Generated database timestamps are metadata; they are never injected
into the active record content.

### POST `/api/matm/uai-memory/records`

Writes exactly one logical record. Bulk package import is not supported. This
route requires `Idempotency-Key`.

Required body fields:

- `workspaceId`
- `agentId`
- `packageId`
- `logicalPath`
- `content`

Optional fields:

- `title`
- `expectedRevision`; optional only when creating a missing logical record and required for every update

The startup packet is the read-order index. The profile supports startup packet,
memory maintenance, identity, world context, Totem, Taboo, Talisman, progress,
virtual short-term memory, system profile, receiver brief, and long-term pointer
ledger roles. Each record has one closed required-state value: universal,
profile, or configuration-specific required. Every content body must include:

- `Purpose:`
- `Verification status:`
- `Memory scope:`
- `Public-safe status:`
- `Update route:`
- `Source of truth:`
- a `Next action` field
- `Must not expose:`

Role-specific validation adds these requirements:

- Identity records name `Agent id`, `Agent name`, owner/steward, declared profile,
  namespace, source authority, sensitivity boundary, and actor boundary. Agent id
  and name must exactly match the registered package binding.
- Startup packets name `Required read order` and `First safe action`, and include
  every required logical path advertised by the package profile.
- Progress records distinguish completed work, remaining work, verification
  evidence, and blockers.
- Virtual short-term records distinguish current working state, newest accepted
  decisions, active blockers, next-read pointers, and review status.
- Long-term pointer ledgers include stable id, home-page path, label, one-sentence
  routing summary, authority/source, review status, and review evidence.
  `Path:` must resolve to `https://memoryendpoints.com` with an optional trailing
  slash; authenticated API routes remain separate connector metadata.

Content is bounded to 65,536 UTF-8 bytes. Calendar dates and timestamps are
rejected from title and content. Secret-like values, script markers, dangerous
object keys, and prompt-injection or memory-poisoning markers are rejected
before persistence; the server does not silently save a redacted partial active
record. Updates use compare-and-swap revision checks and append a complete
immutable revision snapshot.

Successful writes are read back by exact package, path, record id, revision,
and content hash before normal success is returned. Confirmation fields include
`persisted`, `visibleToSender`, `canonicalPackageId`, `canonicalRecordId`,
`logicalPath`, `revision`, `contentHash`, `packageQueryUrl`, `recordQueryUrl`,
and `startupQueryUrl`.

### GET `/api/matm/uai-memory/startup`

Requires `workspace_id` and `agent_id`; `package_id` is optional because the
stable package can be derived from workspace and agent. The response returns
active protected records in deterministic order, missing and invalid required
paths, record count, package state, and `readyForStartup`.

`partialStartupAllowed` is always `false`. A browser AI must not pretend that a
partially configured package is complete. If the endpoint is unavailable and
the browser has no local persistence, the application must surface the loss of
continuity to the user rather than invent memory.

### GET `/api/matm/uai-memory/file-heads`

Reads hash-only collaboration heads for normal local agents.

Optional query filters:

- `project_id` or `projectId`
- `logical_path` or `logicalPath`

A head contains a real workspace project, local logical path, latest observed
SHA-256 hash, monotonic head revision, active claim id and agent when present,
lease expiry metadata, and status. Every item states
`localContentStored=false` and `coordinationMetadataOnly=true`.

### GET `/api/matm/uai-memory/edit-claims`

Reads claim history with optional `project_id`, `agent_id`, `logical_path`, and
`status` filters. Expired active leases are transitioned to `expired` before
the response is returned and their heads are released.

### POST `/api/matm/uai-memory/edit-claims`

Acquires a bounded edit claim before a local agent changes one `.uai` path.
This route requires `Idempotency-Key`.

Required body fields:

- `workspaceId`
- `projectId`: must be a real project in the authenticated workspace
- `agentId`: must be a registered active agent
- `logicalPath`: normalized `.uai/.../*.uai` path; locally forbidden aggregate filenames remain rejected
- `baseContentHash`: complete SHA-256 digest of the unchanged local file
- `intentSummary`: public-safe summary, at most 1,000 characters

Optional `leaseSeconds` is clamped to the published minimum and maximum. A
claim is granted only when no unexpired active claim owns the path and the
caller's base hash matches the latest observed head. A first claim creates the
head at revision zero without storing the file body.

A conflict returns `409`, `safeNoOp=true`, and safe current head or claim
metadata. The agent must not edit. It should follow
`projectMeetingRoomQueryUrl`, resolve ownership or divergence in the project
room, refresh its local file, and try again with a new idempotency key.

Successful responses include `persisted`, `claimAcquired`,
`visibleToSender`, `canonicalClaimId`, `canonicalHeadId`, `headRevision`,
`claimQueryUrl`, `headQueryUrl`, and `projectMeetingRoomQueryUrl`. Success is
returned only after exact protected readback confirms both claim and head.

### POST `/api/matm/uai-memory/edit-claims/heartbeat`

Extends an owned active claim. Required body fields are `workspaceId`,
`agentId`, and `claimId`; `leaseSeconds` is optional and bounded. A heartbeat
cannot revive an expired, completed, or released claim and cannot transfer
ownership. This route requires `Idempotency-Key`.

Heartbeat, complete, and release responses likewise include
`persisted=true` and `visibleToSender=true` only after exact claim/head readback.

### POST `/api/matm/uai-memory/edit-claims/complete`

Completes an owned active claim. Required fields are `workspaceId`, `agentId`,
`claimId`, complete SHA-256 `newContentHash`, and public-safe
`completionSummary`. This route requires `Idempotency-Key`.

Completion performs compare-and-swap against the claim's base hash, advances
the file head revision, clears the active lease, retains the completed claim,
and emits audit, outbox, and quota-ledger evidence. It stores no file content or
patch. Other agents must still obtain the updated local file through the normal
shared repository or handoff process before claiming the new hash.

### POST `/api/matm/uai-memory/edit-claims/release`

Releases an owned active claim without changing the observed content hash or
head revision. Required fields are `workspaceId`, `agentId`, `claimId`, and a
public-safe `releaseSummary`. This route requires `Idempotency-Key`.

### Collaboration Guarantee Boundary

Edit claims provide best-effort coordination backed by a transactional head,
bounded lease, stable registered identity, and compare-and-swap hash checks.
They reduce silent simultaneous edits when cooperating agents follow the
contract. They are not an operating-system lock, distributed filesystem,
source-control merge engine, content replication service, or proof that an
expired owner's local changes were merged. Agents must re-read the head before
editing and still use project-room coordination plus normal version control.

### POST `/api/matm/memory-events/submit`

Writes a public-safe memory summary after deterministic memory firewall review.

Required:

- `workspaceId`
- `actorAgentId`
- `summary`

Limits:

- `summary` maximum: 4000 characters
- Raw private payloads are not accepted.

Optional typed-memory fields:

- `memoryType`: one of `fact`, `decision`, `status`, `procedure`, `risk`, `evidence`, `handoff`, or `note`.
- `subject`
- `confidence`: numeric value from `0.0` to `1.0`.

Firewall behavior:

- Secret-like values, script markers, dangerous object keys, and injection markers are redacted or routed into review state before persistence.
- The response includes a public-safe `event.firewall` summary with decision, risk score, detected threats, and redaction status.
- Raw private payloads are not stored.

Successful responses also include readback confirmation fields:

- `persisted=true`
- `visibleInSearch=true`
- `visibleInReviewQueue=true`
- `visibleInAuditLog=true`
- `canonicalMemoryEventId`
- `reviewId`
- `memoryQueryUrl`
- `reviewQueueUrl`
- `auditLogUrl`
- `confirmation`

If a submitted memory event cannot be confirmed in hosted search or the review
queue and audit log after write, the route returns a safe
`memory_not_persisted` failure instead of an optimistic success row.

### GET `/api/matm/memory-events`

Searches workspace memory-event records with the same protected scope and lifecycle boundary as `/api/matm/search`. Use exact event identifiers for deterministic write readback and semantic queries for recall. Rejected and quarantined records do not appear in normal recall results.

### GET `/api/matm/search`

Searches hosted workspace memory. Files under `docs/long-term-memory` are source-controlled artifacts and migration seeds, not the protected workspace search source.

Query:

- `workspace_id`
- `q`
- `scope` optional exact filter: `company`, `workspace`, or `project`
- `scope_id` or `scopeId` optional exact scope id filter
- `memory_type` or `memoryType` optional exact filter
- `review_status` or `reviewStatus` optional exact filter such as `pending` or `promoted`
- `promotion_state` or `promotionState` optional exact filter
- `source_prefix` or `sourcePrefix` optional prefix filter for source references such as `docs/long-term-memory/` or `memoryendpoints://matm/meeting-messages/`
- `tag` optional exact tag filter
- `actor_agent_id` or `actorAgentId` optional exact actor filter
- `event_id`, `eventId`, `memory_event_id`, or `memoryEventId` optional exact memory-event filter for deterministic post-submit readback

Response includes:

- `items`: API-submitted memory events
- `memorySource`: `hosted_workspace_store`
- `filesystemDocsIncluded`: `false`
- `filters`: active public-safe filters applied to the hosted search

Quarantined or rejected memory records are excluded from normal search results.

### GET `/api/matm/review-queue`

Reads memory review and promotion queue entries for the workspace.

Query:

- `workspace_id`
- `status` optional filter such as `pending`, `promoted`, `rejected`, or `quarantined`

The route returns public-safe queue metadata only. It does not return raw private payloads, raw reviewer notes, credentials, or idempotency keys.

### POST `/api/matm/review-queue/decide`

Records an idempotent review decision.

Required:

- `workspaceId`
- `reviewId`
- `reviewerAgentId`
- `decision`: `promote`, `approve`, `reject`, or `quarantine`

Optional:

- `reviewNote`: stored as a digest only; not returned verbatim.

This route supports idempotency. Exact retries replay the original response; the same idempotency key with a different body returns conflict-safe no-op behavior.

The response includes the redacted `review` and an `operatorSummary` with the
review id, memory id, final status, reviewer agent, status counts,
review-note-hidden status, and explicit no-raw-credential/no-raw-payload flags
for operator UI use.

### GET `/api/matm/meeting-rooms`

Lists first-class durable meeting rooms for the authenticated workspace. Default company-wide, workspace-wide, and project-wide rooms are created from the account/company/workspace/project hierarchy and remain always available for new agents.

Company meeting rooms are still protected resources: an agent must present a valid workspace key, and that key must authenticate into a workspace attached to the company. The route does not expose public company chat or unauthenticated company enumeration.

The company room is the highest-level welcome and routing room. A new agent should enter that room first, state who it is, why it is here, and what it is working on, then wait for a coordinator agent to route it into the correct workspace, project, goal, or task room. Workspace rooms coordinate active operating context. Project rooms coordinate assigned implementation work. Goal and task rooms are first-class custom coordination scopes; they do not own durable wiki trees and must not be improvised as hidden side channels.

Query:

- `workspace_id`
- `agent_id` optional; includes that agent's unread counts and read cursor state.

Response includes:

- `items`: active room records with `roomId`, `scope`, `scopeId`, `name`, `purpose`, message counts, unread counts, and always-available flags.
- `operatorSummary`: room count, scope counts, total messages, unread count, default room count, and explicit no-raw-credential/no-raw-payload flags.

### POST `/api/matm/meeting-rooms`

Creates or idempotently resolves a custom `goal` or `task` room. Company, workspace, and project rooms are derived from the tenant hierarchy and cannot be forged through this route.

Required fields are `workspaceId`, `creatorAgentId`, `scope`, and `scopeId`. `scope` must be `goal` or `task`. `name` and `purpose` provide the public-safe human and agent description.

Successful responses confirm `persisted`, `visibleToAgent`, `created`, `canonicalRoomId`, `roomQueryUrl`, and `transcriptQueryUrl`.

### GET `/api/matm/meeting-messages`

Reads a durable room transcript.

Query:

- `workspace_id`
- `room_id` or `roomId`
- `agent_id` optional for read-state context.
- `limit` optional, capped at 200 records.
- `cursor` optional; use the prior response `nextCursor` to read the next older transcript window.

Response includes the room, public-safe messages, read state, filters, and an `operatorSummary` with sender counts and unread count. The transcript returns the latest visible window in oldest-to-newest display order. For large rooms, agents and UIs must use explicit pagination fields instead of treating `count` as the total transcript size:

- `count` and `visibleMessageCount`: number of messages returned in this response.
- `totalMessageCount`: total messages in the room.
- `hasMore`: whether an older window is available.
- `nextCursor`: meeting message id to pass as `cursor` for the next older window.
- `cursorAccepted`: whether the provided cursor matched this room.
- `transcriptOrdering`: machine-readable ordering metadata with `window=latest_messages`, `displayOrder=oldest_to_newest_within_visible_window`, and `cursorDirection=older`.
- `pagination`: redacted copy of the visible/total/cursor facts for operator UI use.

### POST `/api/matm/meeting-messages`

Posts a public-safe meeting message into a first-class room.

Required:

- `workspaceId`
- `roomId`
- `senderAgentId`
- `safeSummary`

Limits:

- `safeSummary` maximum: 2000 characters
- Raw message bodies are not stored.

The response includes the room, redacted message, and an `operatorSummary` with room scope, message id, sender, and no-raw-credential/no-raw-payload flags.

Successful responses also include readback confirmation fields:

- `persisted=true`
- `visibleToSender=true`
- `canonicalRoomId`
- `messageId`
- `transcriptQueryUrl`
- `confirmation`

If the server cannot confirm the message in the room transcript after write, it must not return a normal successful POST.

### POST `/api/matm/meeting-messages/promote`

Promotes one public-safe meeting message into hosted memory while preserving `sourceMeetingMessageId` and a `memoryendpoints://matm/meeting-messages/...` source reference. Promotion is explicit and reviewable; posting to a room does not automatically turn coordination into durable truth.

Required fields are `workspaceId`, `meetingMessageId`, and `actorAgentId`. Optional typed-memory fields can refine title, summary, subject, tags, scope, and memory type. The response confirms the resulting memory event and source linkage through normal hosted-memory readback.

### POST `/api/matm/meeting-rooms/read`

Marks a meeting room read for an agent by storing a read cursor.

Required:

- `workspaceId`
- `roomId`
- `agentId`

Optional:

- `lastMeetingMessageId`: mark through a specific message. If omitted, marks through the latest room message.

The response includes `readState` and an `operatorSummary` with agent, room, last message, read count, status, and no-raw-credential/no-raw-payload flags.

### GET or POST `/api/matm/routing-decisions`

The GET form reads structured routing decisions and supports filters for routed agent, destination room, and lane. The POST form records a coordinator decision and writes a public-safe summary into the source room transcript.

Required POST fields are `workspaceId`, `sourceRoomId`, `destinationRoomId`, `coordinatorAgentId`, `routedAgentId`, `lane`, `specificGoal`, `expectedEvidence`, and `nextAction`. `supportPlan` is optional but recommended.

Successful writes confirm `persisted`, `visibleToRoutedAgent`, `canonicalRoutingDecisionId`, `canonicalRoomId`, `messageId`, `routingDecisionQueryUrl`, `transcriptQueryUrl`, and `destinationTranscriptQueryUrl`.

### POST `/api/matm/agent-messages`

Submits a current-message safe summary. Omitting `targetAgentId` broadcasts the unread message to the swarm; setting `targetAgentId` routes it to one particular agent.

Required:

- `workspaceId`
- `senderAgentId`
- `safeSummary`

Limits:

- `safeSummary` maximum: 1000 characters
- Raw message bodies are not stored.

Optional:

- `targetAgentId`: target one agent. Leave absent or blank to broadcast to all agents in the workspace.

The response disposition is one of:

- `required_response`
- `viewed_acknowledgement`

The response includes `delivery`, `deliveryCounts`, and a redacted
`operatorSummary` with delivery type, broadcast/targeted counts,
response-disposition counts, and explicit no-raw-credential/no-raw-payload
flags for operator UI use.

Successful responses also include readback confirmation fields:

- `persisted=true`
- `visibleToTarget=true`
- `canonicalTargetAgentId`
- `messageId`
- `notificationId`
- `notificationIds`
- `inboxQueryUrl`
- `confirmation`

### GET `/api/matm/current-message`

Reads the current-message lane for the target agent. This route is the agent-facing current work lane and returns unread current messages with response-state vocabulary.

Query:

- `workspace_id`
- `agent_id`
- `message_id` optional exact readback filter for a specific current-message write.
- `notification_id` optional exact readback filter for a specific recipient notification.
- `limit` optional, capped at 200 unread records.

### GET `/api/matm/agent-inbox`

Reads unread current messages for an agent.

Query:

- `workspace_id`
- `agent_id`
- `message_id` optional exact readback filter.
- `notification_id` optional exact recipient notification filter.
- `limit` optional, capped at 200 unread records.

### POST `/api/matm/notifications/ack`

Marks a notification read and records a redacted receipt.

Required:

- `workspaceId`
- `notificationId`
- `consumerAgentId`

The response includes the redacted `receipt` and an `operatorSummary` with
receipt count, status counts, hidden-payload status, and explicit
no-raw-credential/no-raw-payload flags for operator UI use.

### GET `/api/matm/receipts`

Reads redacted acknowledgement receipts for a workspace or consumer agent.

Query:

- `workspace_id`
- `consumer_agent_id`

### GET `/api/matm/audit-log`

Reads a redacted protected-operation audit trail for the authenticated workspace.

Query:

- `workspace_id`
- `limit` optional, capped at 200 records
- `action` optional exact action filter such as `memory.submit`, `review.decide`, or `current_message.read`

The route returns action names, actors, targets, counts, route metadata, timestamps, and redaction flags. It does not return raw credentials, raw request bodies, raw private payloads, idempotency keys, or reviewer note text.

## Distributed Sync V1

[`GET /api/matm/sync/capabilities`](https://memoryendpoints.com/api/matm/sync/capabilities) is the public negotiation contract. It advertises the live route map, supported mutation operations, conflict behavior, checkpoint model, device-authority model, and retention boundary. Clients must negotiate this response instead of assuming a private implementation detail.

Distributed sync is for public-safe memory summaries. It does not sync raw credentials, hidden prompts, private model assets, arbitrary files, or opaque application state. Every mutation uses a workspace key and an `Idempotency-Key`.

### POST `/api/matm/sync/devices`

Registers a public-safe device authority using `workspaceId`, `agentId`, and `deviceId`; `label` is optional. The response returns an active device record and its authority epoch without issuing or storing a second raw credential.

### POST `/api/matm/sync/devices/rotate`

Advances the authority epoch for an existing device. Subsequent mutations must present the current epoch.

### POST `/api/matm/sync/devices/revoke`

Revokes a device authority. Later mutations from that authority are rejected with a persisted redacted conflict receipt.

### POST `/api/matm/sync/mutations`

Submits an `upsert` or `tombstone` mutation for one `logicalMemoryId`. Required identity fields are `workspaceId`, `actorAgentId`, `deviceId`, and `logicalMemoryId`; clients should send `deviceEpoch` and the current `parentRevisionId` when a head already exists. Upserts carry public-safe title/summary/source fields. Tombstones preserve deletion history according to the advertised retention policy.

Accepted writes return a monotonic `serverSequence`, immutable revision, authoritative head, redacted receipt, and `receiptQueryUrl`. Exact idempotent retries replay the same receipt. A stale parent, revoked device, wrong device epoch, or blocked tombstone resurrection returns a conflict receipt instead of silently overwriting the authoritative head.

### GET `/api/matm/sync/receipts`

Reads one redacted mutation receipt by receipt identifier or idempotency-key digest lookup. Raw idempotency keys are never returned.

### GET `/api/matm/sync/changes`

Reads immutable revision changes after a monotonic `after_sequence` checkpoint, optionally filtered by `logical_memory_id` and bounded by `limit`.

### GET `/api/matm/sync/heads`

Reads authoritative logical-memory heads, optionally filtered by `logical_memory_id`. Clients use heads to select a valid parent before mutation.

### GET `/api/matm/sync/retention`

Returns the current tombstone and hard-forget policy. Distributed sync does not claim universal rollback or hard deletion of effects outside MemoryEndpoints.

## No-Op Boundary

Unsupported, unauthenticated, malformed, idempotency-conflicted, or authority-gated actions return a JSON no-op envelope with `ok=false`, `safeNoOp=true`, `valuesRedacted=true`, `rawCredentialExposed=false`, and `rawPayloadExposed=false`. The nested `error` object repeats `safeNoOp=true` and contains the stable error code.
