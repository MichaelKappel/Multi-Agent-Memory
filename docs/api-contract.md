# MemoryEndpoints API Contract

All responses are JSON unless the route is explicitly a human HTML or text discovery route.

## Public Routes

| Route | Purpose |
| --- | --- |
| `/api/version` | Runtime version, dependency, and generated-at facts. |
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

Writes a public-safe memory summary.

Required:

- `workspaceId`
- `actorAgentId`
- `summary`

Limits:

- `summary` maximum: 4000 characters
- Raw private payloads are not accepted.

### GET `/api/matm/search`

Searches workspace memory and docs-backed durable memory.

Query:

- `workspace_id`
- `q`

Response includes:

- `items`: API-submitted memory events
- `docsMemory`: matching records from `docs/long-term-memory`

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

## No-Op Boundary

Unsupported, unauthenticated, malformed, or authority-gated actions return an error object with `safeNoOp=true`.
