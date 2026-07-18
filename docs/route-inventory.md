# Route Inventory

The route table below mirrors `memoryendpoints.site_data.ROUTE_TABLE`. The test suite fails when a code route is missing from this document or the companion API reference. The machine-readable inventory at `/api/matm/route-inventory` remains authoritative for the deployed private-intranet revision.

Public routes are readable without a durable credential. Connector request,
body-only authorization-code claim, and exchange routes instead require
one-use protocol material plus exact-retry
idempotency; they never accept a workspace key. Protected routes require the
credential named by their contract: a legacy workspace bearer, connector
bearer, company master, or authenticated human session. Tenant knowledge is
never exposed by the public `/knowledge` shell.

## Public Routes

| Route | Methods | Purpose |
| --- | --- | --- |
| `/` | GET | Human home page. |
| `/docs` | GET | Human-readable documentation. |
| `/docs/` | GET | Trailing-slash documentation alias. |
| `/agent-setup` | GET | Agent setup instructions. |
| `/agent-coordination` | GET | Authenticated agent coordination quickstart with copy-safe examples. |
| `/console` | GET | Human verification console for authenticated workspace keys. |
| `/knowledge` | GET | Authenticated human wiki shell backed by protected database knowledge routes. |
| `/tour` | GET | Browser-local public product tour using clearly labeled mock data. |
| `/tour/knowledge` | GET | Browser-local public knowledge tour using clearly labeled mock data. |
| `/tour/human` | GET | Browser-local human-access tour using the production renderer with clearly labeled session-only mock authority. |
| `/memory-lifecycle` | GET | Memory lifecycle explanation. |
| `/transparency` | GET | Support boundaries and no-op behavior. |
| `/api/version` | GET | Runtime version and dependency facts. |
| `/api/matm/live-capability-matrix` | GET | Current MATM capability state. |
| `/api/matm/agent-compatibility` | GET | L0-L7 agent ability contract, fallbacks, and route-record guidance. |
| `/api/matm/sync/capabilities` | GET | Public distributed-sync v1 capability negotiation. |
| `/api/matm/connector-contract` | GET | Public-safe optional connector integration contract for external agents and apps. |
| `/.well-known/memoryendpoints-connector` | GET | Public same-origin discovery for memoryendpoints.connector_pairing.v1. |
| `/connect/authorize/{publicRequestRef}` | GET | Human approval surface whose link already carries the short-lived public request reference; no pairing token is entered or prefilled. |
| `/tour/connect/authorize/{demoState}` | GET | Explicit mock sign-in, rejected-credential, approval, desktop-handoff, activation, and terminal states through the production renderer with zero protected network. |
| `/api/matm/connector-pairings/requests` | POST | Create an idempotent PKCE-bound connector pairing request. |
| `/api/matm/connector-pairings/authorization-code-claims` | POST | Claim a body-only, one-use authorization code after human approval using request proof, state, and an exact idempotency binding. |
| `/api/matm/connector-pairings/token` | POST | Exchange a one-use authorization code for a pending connector credential. |
| `/api/matm/uai-memory/contract` | GET | Public contract for protected database-backed UAIX active memory used by accountless browser agents. |
| `/api/matm/openapi.json` | GET | Bounded OpenAPI-style golden-path route schema. |
| `/api/matm/route-inventory` | GET | Route inventory with access boundaries. |
| `/api/matm/readiness-result` | GET | AI-ready web readiness evidence. |
| `/api/matm/redacted-example-receipts` | GET | Public-safe receipt examples. |
| `/api/matm/agent-setup/free-account` | GET, POST | Free 200 MB workspace setup. |
| `/mcp/resources` | GET | MCP-style public resource list. |
| `/robots.txt` | GET | Crawler policy. |
| `/sitemap.xml` | GET | Human page sitemap. |
| `/llms.txt` | GET | Compact AI-readable site summary. |
| `/llms-full.txt` | GET | Full AI-readable public summary. |
| `/ai.txt` | GET | Plain-text agent discovery pointer. |
| `/ai-manifest.json` | GET | AI-ready site manifest. |
| `/.well-known/mcp.json` | GET | MCP discovery pointer. |
| `/.well-known/ai-agent.json` | GET | Agent discovery pointer. |

The free-account setup route accepts only `GET` and `POST`; `PUT`, `PATCH`, and
`DELETE` return `405` with `Allow: GET, POST`. Its `POST` body must be a JSON
object. Company, workspace, and project labels are optional, but every supplied
canonical or alias label must be a string whose server-trimmed value is
nonempty and at most 120 characters. All setup responses are `no-store`.
Repeated valid posts intentionally create distinct hierarchies and one-time
credentials; compatibility setup does not replay or persist a raw key. New
LocalEndpoint integrations use `memoryendpoints.connector_pairing.v1` with a
provisional workspace and pending grant so cancellation, expiry, or a secure
store failure before activation leaves no durable hierarchy.

Connector v1 approval URLs contain only `publicRequestRef` (`pairref_` plus 43
base64url characters). The link already carries that reference: the human does
not enter, paste, or copy a pairing token, and the signed-out page never
reflects the reference. Approval returns a registered `wakeUpUrl` byte-for-byte
with no parameters; opening it is an explicit human action and grants no
authority. The desktop claims the code through JSON POST before PKCE exchange.
Browser progress remains conservative: an issued authorization does not prove
desktop receipt, and a prepared credential does not prove secure storage. The
browser may report activation, but only LocalEndpoint shows Connected after its
exact readbacks pass. Its canonical progress states are
`authorization_issued`, `credential_prepared`, and `activated`. Authenticated
browser actions remain disabled until same-origin session inspection hydrates a
fresh CSRF token.
While approval is pending, `202` includes `Retry-After`, `stateVerified=true`,
the exact `requestedScopes`, `scopeDigest`, `idempotencyKeyReserved=false`, and
a redacted receipt without reserving the idempotency key.
The exact identity is `localendpoint-agent`; the immutable ordered scopes are
`connector:self:readback`, `agent:self:register`,
`memory:public-safe:submit`, and `memory:search:read`, with digest
`sha256-v1:1358698c6ddba1a74a688d3718a739f78e4ef50d0773b22c96e025b38aa86594`.
Every unlisted connector route fails closed with `403
connector_scope_forbidden` before request-body or storage dispatch.

Discovery is bounded to 16 KiB, connector JSON requests to 32 KiB, and other
connector JSON responses to 64 KiB. The public `PairingRequest` projection uses
`claimExpiresAt` for the nullable claim deadline and no internal request or
tenant identifiers. The base `PairingSummary` allowlist is `pairingId`,
`status`, `workspaceId`, `agentId`, `credentialId`, `approvedScopes`,
`scopeDigest`, and `grant`; pending adds `activationExpiresInSeconds`, and
authenticated status adds bounded readable `workspace` and `agent` objects.
The grant is exactly `credentialType`, `scopeType`, `scopeId`, `workspaceId`,
`agentId`, `approvedScopes`, `scopeDigest`, `active`, `revoked`,
`canInvite=false`, and `canRevoke=false`.
The base `RotationSummary` is only `rotationId`, `status`, `credentialId`,
`approvedScopes`, and `scopeDigest`; pending adds
`activationExpiresInSeconds`. Every one-time request-proof, approved-code,
exchange, and rotation response attests
`credentialDeliveredToAuthorizedRecipient=true`,
`rawCredentialPersisted=false`, and `showCredentialOnce=true` at the top level.
Credential inventory item fields are exactly `credentialId`, `status`,
`isCurrent`, `approvedScopes`, `scopeDigest`, `createdAt`, `activatedAt`,
`revokedAt`, and `lastUsedAt`; only the outer envelope carries redaction flags.

## Protected Routes

Protected mutations require `Idempotency-Key` when their route contract advertises it. Exact retries replay the original safe response; key reuse with a different body returns a conflict-safe no-op. Connector `POST /api/matm/search` is read-only and rejects `Idempotency-Key`.

| Route | Methods | Purpose |
| --- | --- | --- |
| `/api/matm/me` | GET | Credential-derived principal, immutable scope, permission, and resource-context introspection. |
| `/api/matm/access/company-master-credentials` | GET, POST | Company-master metadata inventory plus idempotent registration by an existing company master or enabled company-scoped top-level agent. |
| `/api/matm/access/scope-catalog` | GET | Company-master-only catalog of company, workspace, project, game, session, goal, and task grant scopes. |
| `/api/matm/access/agent-name-requests` | GET, POST | List governed name requests or create one with required public-safe idempotent retry semantics. |
| `/api/matm/access/agent-name-requests/{requestId}/decision` | POST | Approve or deny a governed name request with required public-safe idempotent retry semantics. |
| `/api/matm/access/invites` | GET, POST | List invitation metadata or issue one non-replayable invitation URL once; issuance forbids Idempotency-Key. |
| `/api/matm/access/invites/redeem` | POST | Redeem a body-only one-time invitation and reveal one agent credential once; redemption forbids Idempotency-Key. |
| `/api/matm/access/invites/{inviteId}/revoke` | POST | Revoke an issued invitation with required public-safe idempotent retry semantics. |
| `/api/matm/access/agent-tokens` | GET | List redacted governed agent-credential metadata for a company master. |
| `/api/matm/access/agent-tokens/{credentialId}/revoke` | POST | Revoke an agent credential with required public-safe idempotent retry semantics. |
| `/api/matm/workspace` | GET | Workspace quota and status. |
| `/api/matm/projects` | GET, POST | Workspace project list and project upsert for company/workspace/project hierarchy. |
| `/api/matm/knowledge-tree` | GET | Database-backed company/workspace/project wiki tree for humans and agents. |
| `/api/matm/knowledge-documents` | GET, POST | Search, retrieve, and upsert protected knowledge documents from database search rows. |
| `/api/matm/knowledge-documents/upsert` | POST | Idempotent protected knowledge document upsert alias. |
| `/api/matm/external-links` | GET, POST | Search and store first-class external links with site, page, description, crawl state, and knowledge citations. |
| `/api/matm/external-links/upsert` | POST | Idempotent protected external-link and knowledge-citation upsert alias. |
| `/api/matm/internet-search` | GET | Search the workspace's reviewed curated-web link index. |
| `/api/matm/agents/register` | POST | Invite-only agent registration, connector self-confirmation, or the deprecated exact LocalEndpoint single-agent transition. |
| `/api/matm/human/connector-pairings/{publicRequestRef}/company-selection` | POST | Resolve a short-lived opaque company reference and rotate the authenticated human session for connector approval. |
| `/api/matm/human/connector-pairings/{publicRequestRef}/approve` | POST | Approve the exact canonical agent, exact four scopes, and an existing or provisional workspace through an authenticated human session. |
| `/api/matm/human/connector-pairings/{publicRequestRef}/cancel` | POST | Cancel a pending human approval request idempotently before any connector grant exists. |
| `/api/matm/human/companies/{companyId}/history` | GET | Read currently retained human-only break-glass history; physically purged after seven days and never available to agents. |
| `/api/matm/human/companies/{companyId}/top-level-agent-master-credential-setting` | GET, PATCH | Owner or credential-admin control for top-level-agent human-operator company-master creation. |
| `/api/matm/connector-pairings/{pairingId}` | GET | Verify exact workspace, agent, connector scope, and active grant state. |
| `/api/matm/connector-pairings/{pairingId}/activate` | POST | Activate a securely stored pending connector grant idempotently. |
| `/api/matm/connector-pairings/{pairingId}/rotations` | POST | Prepare and reveal a pending connector credential rotation once. |
| `/api/matm/connector-pairings/{pairingId}/rotations/{rotationId}/activate` | POST | Activate a pending rotation and revoke its predecessor atomically. |
| `/api/matm/connector-pairings/{pairingId}/credentials` | GET | Read redacted connector credential lifecycle metadata with no credential or verifier material. |
| `/api/matm/connector-pairings/{pairingId}/revoke` | POST | Revoke a connector grant with a company master credential. |
| `/api/matm/connector-pairings/{pairingId}/disconnect` | POST | Disconnect and revoke the calling connector credential. |
| `/api/matm/connector-pairings/{pairingId}/cancel` | POST | Cancel an unactivated connector grant without durable workspace or agent creation. |
| `/api/matm/uai-memory/packages` | GET, POST | Create or inspect a registered agent's protected virtual UAIX active-memory package. |
| `/api/matm/uai-memory/records` | GET, POST | Read or revision-safely write one date-free public-safe virtual UAIX record at a time. |
| `/api/matm/uai-memory/startup` | GET | Read an agent-bound virtual UAIX package in deterministic startup order with readiness evidence. |
| `/api/matm/uai-memory/file-heads` | GET | Read hash-only project file heads for local .uai multi-agent edit coordination without file content. |
| `/api/matm/uai-memory/edit-claims` | GET, POST | Inspect or acquire bounded project-scoped claims before editing a local .uai path. |
| `/api/matm/uai-memory/edit-claims/heartbeat` | POST | Extend an owned active local .uai edit claim within the bounded lease window. |
| `/api/matm/uai-memory/edit-claims/complete` | POST | Complete an owned claim and compare-and-swap the hash-only local .uai file head. |
| `/api/matm/uai-memory/edit-claims/release` | POST | Release an owned local .uai edit claim without changing the observed file head. |
| `/api/matm/memory-events/submit` | POST | Workspace memory summary write with hosted search and review-queue readback confirmation. |
| `/api/matm/memory-events` | GET | Workspace memory event search. |
| `/api/matm/search` | GET, POST | Hosted workspace memory search; connectors use exact body-only POST search. |
| `/api/matm/review-queue` | GET | Memory review and promotion queue readback. |
| `/api/matm/review-queue/decide` | POST | Idempotent memory promotion, rejection, or quarantine decision. |
| `/api/matm/meeting-rooms` | GET, POST | Always-present company, workspace, project room discovery plus goal/task/game/session room creation. |
| `/api/matm/meeting-messages` | GET, POST | Seven-day scoped meeting transcript read and public-safe post creation; durable content requires explicit promotion. |
| `/api/matm/meeting-messages/promote` | POST | Promote a public-safe meeting transcript message into hosted workspace memory with source linkage. |
| `/api/matm/meeting-rooms/read` | POST | Meeting room read cursor update for an agent. |
| `/api/matm/routing-decisions` | GET, POST | Structured coordinator routing decisions with lane, destination room, goal, next action, and expected evidence. |
| `/api/matm/agent-messages` | POST | Transient current-message creation with seven-day acknowledged and 30-day unacknowledged retention. |
| `/api/matm/current-message` | GET | Current-message lane readback. |
| `/api/matm/agent-inbox` | GET | Unread inbox readback. |
| `/api/matm/notifications/ack` | POST | Notification acknowledgement and receipt creation. |
| `/api/matm/receipts` | GET | Redacted receipt readback. |
| `/api/matm/audit-log` | GET | Denied legacy agent-plane audit path; routine logs are human-only and physically purged after seven days. |
| `/api/matm/sync/devices` | POST | Register a public-safe distributed-sync device authority. |
| `/api/matm/sync/devices/rotate` | POST | Rotate a sync device authority epoch. |
| `/api/matm/sync/devices/revoke` | POST | Revoke a sync device authority epoch. |
| `/api/matm/sync/mutations` | POST | Submit conflict-safe public-safe memory sync mutation. |
| `/api/matm/sync/receipts` | GET | Read mutation receipt by idempotency key or receipt id. |
| `/api/matm/sync/changes` | GET | Read monotonic sync revision changes after a checkpoint sequence. |
| `/api/matm/sync/heads` | GET | Read authoritative sync memory heads. |
| `/api/matm/sync/retention` | GET | Read sync tombstone and hard-forget retention policy. |

Operator packaging and deployment remain local administrative actions and are not exposed as public web routes.
