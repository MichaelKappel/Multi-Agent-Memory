# LocalEndpoint Connector Pairing v1

This is the human-readable contract for
`memoryendpoints.connector_pairing.v1`. The machine-readable authorities are
`GET /.well-known/memoryendpoints-connector`,
`GET /api/matm/connector-contract`, and
`GET /api/matm/openapi.json`. All four publications must change together.

## Fixed identity and scope

The only v1 client and agent are `localendpoint-connect` and the byte-for-byte
agent id `localendpoint-agent` (display name `LocalEndpoint Agent`). The request
and human approval must contain this exact ordered, unique scope array:

1. `connector:self:readback`
2. `agent:self:register`
3. `memory:public-safe:submit`
4. `memory:search:read`

Its digest is
`sha256-v1:1358698c6ddba1a74a688d3718a739f78e4ef50d0773b22c96e025b38aa86594`.
It is SHA-256 over compact, sorted-key UTF-8 JSON with keys `schemaVersion` and
`scopes`. Identity or scope mismatch is a fixed 422 safe no-op.

## Pairing sequence

1. Validate the entered root as exactly `https://memoryendpoints.com`, fetch
   discovery without redirects, and negotiate the exact schema version.
2. Generate 256-bit state and PKCE S256 values locally. Create an idempotent
   request with exact identity and scopes. Retain the body-only
   `pairingRequestProof` in secure setup state. The one-time response wrapper
   attests `credentialDeliveredToAuthorizedRecipient=true`,
   `rawCredentialPersisted=false`, and `showCredentialOnce=true`; its
   `proofDelivery` records body-only, show-once, non-persistence, and exact-retry
   recovery facts.
3. Open `/connect/authorize/{publicRequestRef}`. The reference is exactly
   `pairref_` plus 43 base64url characters. It is public, tenant-neutral,
   short-lived, non-secret, and non-authorizing. No other value belongs in the
   URL.
4. The logged-in human selects a company and workspace through short-lived,
   account/session/request-bound opaque `companyRef` and `workspaceRef` values,
   or supplies labels for a provisional workspace/project. The UI displays the
   fixed agent label and all four scope impacts. It renders no tenant or agent
   identifiers.
5. Approval returns `approved_awaiting_connector_claim` and the registered
   `wakeUpUrl` byte-for-byte with no additions. A human may explicitly open it;
   it grants no authority and v1 never auto-navigates.
6. POST the proof, state, client, and redirect URI to
   `/api/matm/connector-pairings/authorization-code-claims`. A pending `202`
   has `Retry-After`, `stateVerified=true`, exact `requestedScopes`,
   `scopeDigest`, `idempotencyKeyReserved=false`, and a redacted receipt; it
   does not bind the idempotency key. First approved
   success atomically binds exact key/body and returns one body-only 60-second
   code with `stateVerified=true` plus the same three top-level secure-delivery
   attestations. Exact retry rederives it before exchange;
   changed body or any different key returns `409 idempotency_conflict`.
7. Exchange the body-only code with PKCE. Securely store the one-time pending
   connector credential before activation. Exact lost-response retry recovers
   the same pending secret without persisting it. The response repeats the
   three top-level secure-delivery attestations and includes the
   purpose-specific `credentialDelivery` recovery and scope-binding facts.
8. Activate within 600 seconds. Activation atomically confirms the canonical
   agent and commits a provisional hierarchy. Then verify exact pairing,
   credential inventory, `/api/matm/me`, and `/api/matm/workspace` before
   showing Connected.

Requests expire after 600 seconds, authorization codes after 60 seconds, and
pending grants/rotations after 600 seconds. Connector JSON request bodies are
limited to 32 KiB; discovery responses to 16 KiB; other connector JSON
responses to 64 KiB. API operations do not redirect and sensitive responses
are `private, no-store`, `no-referrer`, JSON, and bounded.
Credential-partitioned operational limits are 5 self-registration confirmations
per 10 minutes, 60 public-safe submissions per minute, and 120 searches per
minute; `429` is redacted and carries `Retry-After`.

## Exact public response projections

The public `PairingRequest` summary contains exactly `publicRequestRef`,
`status`, `clientDisplayName`, `agentDisplayName`, `requestedScopes`,
`approvedScopes`, `scopeDigest`, `scopeImpacts`, `expiresAt`, and
`claimExpiresAt`. Creation adds `expiresInSeconds=600`; cancellation omits it.
`claimExpiresAt` is nullable before approval and is the only public name for the
claim deadline. No alternate code-expiry timestamp name is public.

The base `PairingSummary` contains exactly `pairingId`, `status`, `workspaceId`,
`agentId`, `credentialId`, `approvedScopes`, `scopeDigest`, and `grant`. Pending
adds only `activationExpiresInSeconds`. Authenticated status readback adds only
`workspace={workspaceId,readable}` and `agent={agentId,readable}`. The exact
`grant` allowlist is `credentialType`, `scopeType`, `scopeId`, `workspaceId`,
`agentId`, `approvedScopes`, `scopeDigest`, `active`, `revoked`,
`canInvite=false`, and `canRevoke=false`.

The base `RotationSummary` contains exactly `rotationId`, `status`,
`credentialId`, `approvedScopes`, and `scopeDigest`; pending adds only
`activationExpiresInSeconds`. No summary echoes an internal `requestId`,
`companyId`, `projectId`, request reason, predecessor or supersession
identifier, raw timestamp, or nested redaction flags.

Credential inventory items contain exactly `credentialId`, `status`,
`isCurrent`, `approvedScopes`, `scopeDigest`, `createdAt`, `activatedAt`,
`revokedAt`, and `lastUsedAt`. Only the outer inventory envelope carries
redaction attestations; an item has no nested redaction object or flags.

Request proof, approved claim code, exchanged connector credential, and pending
rotation credential responses all require the top-level
`credentialDeliveredToAuthorizedRecipient=true`,
`rawCredentialPersisted=false`, and `showCredentialOnce=true`. Exchange and
rotation also retain `credentialDelivery`; the claim-code response does not add
a purpose-specific delivery object.

## Authority matrix

The active principal remains `credentialType=connector_agent`. Allowed actions
are exact self/workspace/status/inventory readback, exact self-registration
confirmation, public-safe memory submit, body-only read-only search, and
intrinsic activation/rotation/cancel/disconnect. Human APIs, access management,
invites, other agents, meetings/messages, audit/history, export/company
lifecycle, knowledge/external-link mutation, review, sync, and every unlisted
route fail with `403 connector_scope_forbidden` before body parsing or storage
dispatch. Rotation preserves the original scopes and digest.

## Recovery and lifecycle

Exact request, claim, exchange, activation, and lifecycle retries use the same
canonical body and idempotency key. No uncertain response authorizes creation
of a replacement workspace or credential. If secure storage fails before
activation, cancel with the pending credential when available or allow expiry.
Rotation is prepare/store/activate; the predecessor remains active until
successor activation. Company-master revocation, connector disconnect, and
pending cancellation are immediate and typed. Raw credentials are never
recoverable from metadata.

Connector-specific protected audit rows record the action with stable,
domain-separated HMAC correlation references. Their workspace foreign-key
field is null, and their actor, target, and details never contain raw human,
tenant, workspace, project, agent, request, pairing, rotation, credential, or
master-key identifiers. Public request references are pseudonymized as well.
If the credential pepper is unavailable, the row retains only an
uncorrelated event category.

`publicRequestRef` is the sole variable in the browser approval/wake surface.
No company, workspace, project, or agent identifier, scope, secret, code,
proof, or state enters a browser URL. Authenticated lifecycle API paths use
only non-secret, non-authorizing `pairingId` and `rotationId` recovery metadata
and still require the exact bearer authority.

General company agent names use the separate company-scoped normalization and
uniqueness policy. That policy does not loosen the byte-for-byte fixed v1
connector identity.

See [the threat model](connector-pairing-threat-model.md),
[the full API contract](api-contract.md), and
[the route inventory](route-inventory.md).
