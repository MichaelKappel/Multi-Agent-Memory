# Human operational API v1

The human operational API is a closed, same-origin, cookie-authenticated
surface. It is separate from the bearer-only machine API. A request carrying
any `Authorization` header is rejected before request-body parsing or storage
access.

## Browser authority

Every request requires all of the following:

- the `__Host-memoryendpoints-human` account-session cookie;
- `Sec-Fetch-Site: same-origin`, fetch mode `cors` or `same-origin`, and an
  empty fetch destination;
- the current in-memory `X-CSRF-Token` on reads and mutations;
- the exact trusted `Origin` on mutations;
- `Cache-Control: no-store, no-cache, must-revalidate, private` responses.

The existing `GET /api/matm/human/session` route can reissue an in-memory CSRF
token after a safe same-origin session revalidation. Neither bearer tokens nor
recovery-only closure sessions can use this API.

## Explicit resource selection

`GET /api/matm/human/operational/context-catalog` returns only workspaces and
projects belonging to the explicitly selected company. Its initial
`resourceContext` has `workspaceId` and `projectId` set to `null`; the server
does not infer either value.

Select a complete resource context with:

```http
POST /api/matm/human/session/resource-context
Content-Type: application/json
X-CSRF-Token: <in-memory token>

{
  "authorityId": "<selected authority>",
  "workspaceId": "<company workspace>",
  "projectId": "<workspace project>",
  "contextVersion": "<catalog version>"
}
```

The authority, workspace, and project are all mandatory and validated as one
company-owned chain. Success rotates the account-session cookie and CSRF token
and returns a new opaque `contextVersion`. Selecting a company also rotates the
session and therefore starts with an empty resource context. Reissuing only a
CSRF token does not change the resource context.

Every resource-bound request sends the selected version as:

```http
X-MemoryEndpoints-Context-Version: <opaque current version>
```

A missing version fails with `human_resource_context_version_required`; an old
version fails with `human_resource_context_stale` before protected operation
work begins.

The exact context object is:

```json
{
  "authorityId": "...",
  "companyId": "...",
  "workspaceId": "...",
  "projectId": "...",
  "contextVersion": "..."
}
```

## Operations

The closed route set is:

| Method | Path | Permission |
| --- | --- | --- |
| `POST` | `/api/matm/human/session/resource-context` | `canSelectResourceContext` |
| `GET` | `/api/matm/human/operational/context-catalog` | `canReadContextCatalog` |
| `GET` | `/api/matm/human/operational/workspace` | `canReadWorkspace` |
| `GET` | `/api/matm/human/operational/search` | `canSearchMemory` |
| `GET` | `/api/matm/human/operational/knowledge-tree` | `canReadKnowledgeTree` |
| `GET` | `/api/matm/human/operational/knowledge-documents` | `canReadKnowledgeDocuments` |
| `GET` | `/api/matm/human/operational/external-links` | `canReadExternalLinks` |
| `GET` | `/api/matm/human/operational/internet-search` | `canSearchCuratedInternet` |
| `POST` | `/api/matm/human/operational/memory-events/submit` | `canSubmitPublicSafeMemory` |

Owner and `credential_admin` roles can read. Only owners can submit public-safe
memory. Permission booleans and a complete operation map are returned by the
server; clients must not infer access from role names.

Collaboration, review, sync, meeting, and message operations are present in the
operation map with false permissions and no callable methods. Requests to those
categories return the typed `human_operation_not_permitted` 403 response until
genuine human-actor semantics exist.

The `internet-search` operation searches stored, reviewed external-link
metadata only. Its response includes `curatedOnly:true` and
`liveNetworkRequestMade:false`; it never performs a live network request.

## Response and audit identity

Every successful operation echoes `resourceContext`, its top-level
`contextVersion`, `permissions`, `operations`, and `csrfTokenRotated`. Ordinary
reads and idempotent mutations return `csrfTokenRotated:false` and do not return
a new CSRF token.

The server derives this exact audit actor from the authenticated session and
selected context:

```json
{
  "humanAccountId": "...",
  "humanAccountSessionId": "...",
  "username": "...",
  "authorityId": "...",
  "companyId": "...",
  "workspaceId": "...",
  "projectId": "...",
  "authMode": "human_account"
}
```

Caller-supplied agent actor fields are rejected. Human memory records persist
first-class human account, session, username, authority, company, and auth-mode
columns with a null agent actor. Search readback reconstructs the same human
audit actor and does not synthesize or expose `actorAgentId` for those records.
Existing agent memory records and bearer routes remain agent-shaped.

## Public-safe memory submission

Submission requires `Content-Type: application/json`, the current context
version, CSRF token, and an `Idempotency-Key` of 8–200 safe ASCII characters.
The accepted body fields are `title`, `summary`, `tags`, `memoryType`,
`subject`, `confidence`, and an optional exact project `scope`/`scopeId` pair.
The server fixes scope to the selected project and source to
`human-operational://public-safe-submit`, then applies the existing memory
firewall.

File and relational stores serialize context validation, human-attributed
memory persistence, review/outbox/ledger/audit creation, and idempotency receipt
creation in one lock/transaction. A lost response retried with the same key and
body returns the same event with `idempotentReplay:true`; reusing the key with a
different body is a safe no-op `idempotency_conflict`.

All errors use typed, redacted JSON with `safeNoOp:true`,
`rawCredentialExposed:false`, and `rawPayloadExposed:false`.

