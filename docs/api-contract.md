# MemoryEndpoints API Contract

All responses are JSON unless the route is explicitly a human HTML or text discovery route.

## Public Routes

| Route | Purpose |
| --- | --- |
| `/api/version` | Runtime version, dependency, generated-at, and build provenance facts. |
| `/api/matm/live-capability-matrix` | Current live/planned/gated capability state. |
| `/api/matm/route-inventory` | Public and protected route inventory. |
| `/api/matm/readiness-result` | Local readiness checks, evidence, and deployment status. |
| `/api/matm/redacted-example-receipts` | Public-safe receipt examples. |
| `/api/matm/agent-setup/free-account` | Free workspace setup information and POST endpoint. |
| `/mcp/resources` | Public MCP-style resource list. |
| `/ai-manifest.json` | AI-ready route and boundary manifest. |
| `/.well-known/mcp.json` | MCP discovery pointer. |
| `/.well-known/ai-agent.json` | AI agent discovery pointer. |
| `/docs` and `/docs/` | Human-readable documentation page. |

## Authentication

Protected routes require:

```http
Authorization: Bearer <WORKSPACE_KEY>
```

The setup route returns the workspace key once. The server stores a hash, not the raw key.

Free agent workspaces receive 200 MB of storage. Checkout and coupon use are not required.

## Idempotency

Protected mutation routes accept:

```http
Idempotency-Key: <STABLE_UNIQUE_KEY_FOR_THIS_REQUEST_BODY>
```

Exact retries return the original public-safe response status and body with `idempotentReplay=true`. Reusing the same key with a different body returns `409 Conflict` and `safeNoOp=true`.

The free-account setup route does not support replay because replay would require storing or regenerating a one-time raw secret.

## Protected Routes

### GET `/api/matm/workspace`

Returns workspace quota, usage, plan, and raw-key storage facts.

Query:

- `workspace_id`

### POST `/api/matm/agents/register`

Registers or updates an agent in a workspace.

Required:

- `workspaceId`
- `agentId`

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

### GET `/api/matm/search`

Searches workspace memory and docs-backed durable memory.

Query:

- `workspace_id`
- `q`

Response includes:

- `items`: API-submitted memory events
- `docsMemory`: matching records from `docs/long-term-memory`

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

### POST `/api/matm/agent-messages`

Submits a current-message safe summary for a target agent.

Required:

- `workspaceId`
- `senderAgentId`
- `safeSummary`

Limits:

- `safeSummary` maximum: 1000 characters
- Raw message bodies are not stored.

The response disposition is one of:

- `required_response`
- `viewed_acknowledgement`

### GET `/api/matm/current-message`

Reads the current-message lane for the target agent. This route is the agent-facing current work lane and returns unread current messages with response-state vocabulary.

Query:

- `workspace_id`
- `agent_id`

### GET `/api/matm/agent-inbox`

Reads unread current messages for an agent.

Query:

- `workspace_id`
- `agent_id`

### POST `/api/matm/notifications/ack`

Marks a notification read and records a redacted receipt.

Required:

- `workspaceId`
- `notificationId`
- `consumerAgentId`

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

## No-Op Boundary

Unsupported, unauthenticated, malformed, idempotency-conflicted, or authority-gated actions return a JSON no-op envelope with `ok=false`, `safeNoOp=true`, `valuesRedacted=true`, `rawCredentialExposed=false`, and `rawPayloadExposed=false`. The nested `error` object repeats `safeNoOp=true` and contains the stable error code.
