# Route Inventory

The live route inventory is available at `/api/matm/route-inventory`.

Public routes are readable without credentials. Protected MATM routes require a workspace key and must use public-safe summaries.

Operator deployment is not exposed as a public web route.

Required public evidence routes:

- `/api/matm/live-capability-matrix`
- `/api/matm/connector-contract`
- `/api/matm/route-inventory`
- `/api/matm/readiness-result`
- `/ai-manifest.json`
- `/.well-known/mcp.json`
- `/.well-known/ai-agent.json`
- `/docs` and `/docs/`
- `/llms.txt`
- `/sitemap.xml`

Current protected MATM routes:

- `/api/matm/workspace`
- `/api/matm/agents/register`
- `/api/matm/memory-events/submit`
- `/api/matm/memory-events`
- `/api/matm/search`
- `/api/matm/review-queue`
- `/api/matm/review-queue/decide`
- `/api/matm/meeting-rooms`
- `/api/matm/meeting-messages`
- `/api/matm/meeting-rooms/read`
- `/api/matm/agent-messages`
- `/api/matm/current-message`
- `/api/matm/agent-inbox`
- `/api/matm/notifications/ack`
- `/api/matm/receipts`
- `/api/matm/audit-log`
