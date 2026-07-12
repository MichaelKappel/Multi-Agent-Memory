from . import __version__
from .config import COMPANION_DOCS_URL, GITHUB_REPO_URL, SITE_NAME, SITE_URL, utc_now
from .runtime import configured_store_backend, mysql_backend_name, store_backend_health
from .uai_memory import virtual_uai_contract


ROUTE_TABLE = [
    {"route": "/", "access": "public", "methods": ["GET"], "purpose": "Human home page."},
    {"route": "/docs", "access": "public", "methods": ["GET"], "purpose": "Human-readable documentation."},
    {"route": "/docs/", "access": "public", "methods": ["GET"], "purpose": "Trailing-slash documentation alias."},
    {"route": "/agent-setup", "access": "public", "methods": ["GET"], "purpose": "Agent setup instructions."},
    {"route": "/agent-coordination", "access": "public", "methods": ["GET"], "purpose": "Authenticated agent coordination quickstart with copy-safe examples."},
    {"route": "/console", "access": "public", "methods": ["GET"], "purpose": "Human verification console for authenticated workspace keys."},
    {"route": "/knowledge", "access": "public", "methods": ["GET"], "purpose": "Authenticated human wiki shell backed by protected database knowledge routes."},
    {"route": "/memory-lifecycle", "access": "public", "methods": ["GET"], "purpose": "Memory lifecycle explanation."},
    {"route": "/transparency", "access": "public", "methods": ["GET"], "purpose": "Support boundaries and no-op behavior."},
    {"route": "/api/version", "access": "public", "methods": ["GET"], "purpose": "Runtime version and dependency facts."},
    {"route": "/api/matm/live-capability-matrix", "access": "public", "methods": ["GET"], "purpose": "Current MATM capability state."},
    {"route": "/api/matm/agent-compatibility", "access": "public", "methods": ["GET"], "purpose": "L0-L7 agent ability contract, fallbacks, and route-record guidance."},
    {"route": "/api/matm/sync/capabilities", "access": "public", "methods": ["GET"], "purpose": "Public distributed-sync v1 capability negotiation."},
    {"route": "/api/matm/connector-contract", "access": "public", "methods": ["GET"], "purpose": "Public-safe optional connector integration contract for external agents and apps."},
    {"route": "/api/matm/uai-memory/contract", "access": "public", "methods": ["GET"], "purpose": "Public contract for protected database-backed UAIX active memory used by accountless browser agents."},
    {"route": "/api/matm/openapi.json", "access": "public", "methods": ["GET"], "purpose": "Bounded OpenAPI-style golden-path route schema."},
    {"route": "/api/matm/route-inventory", "access": "public", "methods": ["GET"], "purpose": "Route inventory with access boundaries."},
    {"route": "/api/matm/readiness-result", "access": "public", "methods": ["GET"], "purpose": "AI-ready web readiness evidence."},
    {"route": "/api/matm/redacted-example-receipts", "access": "public", "methods": ["GET"], "purpose": "Public-safe receipt examples."},
    {"route": "/api/matm/agent-setup/free-account", "access": "public", "methods": ["GET", "POST"], "purpose": "Free 200 MB workspace setup."},
    {"route": "/mcp/resources", "access": "public", "methods": ["GET"], "purpose": "MCP-style public resource list."},
    {"route": "/robots.txt", "access": "public", "methods": ["GET"], "purpose": "Crawler policy."},
    {"route": "/sitemap.xml", "access": "public", "methods": ["GET"], "purpose": "Human page sitemap."},
    {"route": "/llms.txt", "access": "public", "methods": ["GET"], "purpose": "Compact AI-readable site summary."},
    {"route": "/llms-full.txt", "access": "public", "methods": ["GET"], "purpose": "Full AI-readable public summary."},
    {"route": "/ai.txt", "access": "public", "methods": ["GET"], "purpose": "Plain-text agent discovery pointer."},
    {"route": "/ai-manifest.json", "access": "public", "methods": ["GET"], "purpose": "AI-ready site manifest."},
    {"route": "/.well-known/mcp.json", "access": "public", "methods": ["GET"], "purpose": "MCP discovery pointer."},
    {"route": "/.well-known/ai-agent.json", "access": "public", "methods": ["GET"], "purpose": "Agent discovery pointer."},
    {"route": "/api/matm/workspace", "access": "protected", "methods": ["GET"], "purpose": "Workspace quota and status."},
    {"route": "/api/matm/projects", "access": "protected", "methods": ["GET", "POST"], "purpose": "Workspace project list and project upsert for company/workspace/project hierarchy."},
    {"route": "/api/matm/knowledge-tree", "access": "protected", "methods": ["GET"], "purpose": "Database-backed company/workspace/project wiki tree for humans and agents."},
    {"route": "/api/matm/knowledge-documents", "access": "protected", "methods": ["GET", "POST"], "purpose": "Search, retrieve, and upsert protected knowledge documents from database search rows."},
    {"route": "/api/matm/knowledge-documents/upsert", "access": "protected", "methods": ["POST"], "purpose": "Idempotent protected knowledge document upsert alias."},
    {"route": "/api/matm/external-links", "access": "protected", "methods": ["GET", "POST"], "purpose": "Search and store first-class external links with site, page, description, crawl state, and knowledge citations."},
    {"route": "/api/matm/external-links/upsert", "access": "protected", "methods": ["POST"], "purpose": "Idempotent protected external-link and knowledge-citation upsert alias."},
    {"route": "/api/matm/internet-search", "access": "protected", "methods": ["GET"], "purpose": "Search the workspace's reviewed curated-web link index."},
    {"route": "/api/matm/agents/register", "access": "protected", "methods": ["POST"], "purpose": "Agent registration."},
    {"route": "/api/matm/uai-memory/packages", "access": "protected", "methods": ["GET", "POST"], "purpose": "Create or inspect a registered agent's protected virtual UAIX active-memory package."},
    {"route": "/api/matm/uai-memory/records", "access": "protected", "methods": ["GET", "POST"], "purpose": "Read or revision-safely write one date-free public-safe virtual UAIX record at a time."},
    {"route": "/api/matm/uai-memory/startup", "access": "protected", "methods": ["GET"], "purpose": "Read an agent-bound virtual UAIX package in deterministic startup order with readiness evidence."},
    {"route": "/api/matm/uai-memory/file-heads", "access": "protected", "methods": ["GET"], "purpose": "Read hash-only project file heads for local .uai multi-agent edit coordination without file content."},
    {"route": "/api/matm/uai-memory/edit-claims", "access": "protected", "methods": ["GET", "POST"], "purpose": "Inspect or acquire bounded project-scoped claims before editing a local .uai path."},
    {"route": "/api/matm/uai-memory/edit-claims/heartbeat", "access": "protected", "methods": ["POST"], "purpose": "Extend an owned active local .uai edit claim within the bounded lease window."},
    {"route": "/api/matm/uai-memory/edit-claims/complete", "access": "protected", "methods": ["POST"], "purpose": "Complete an owned claim and compare-and-swap the hash-only local .uai file head."},
    {"route": "/api/matm/uai-memory/edit-claims/release", "access": "protected", "methods": ["POST"], "purpose": "Release an owned local .uai edit claim without changing the observed file head."},
    {"route": "/api/matm/memory-events/submit", "access": "protected", "methods": ["POST"], "purpose": "Workspace memory summary write with hosted search and review-queue readback confirmation."},
    {"route": "/api/matm/memory-events", "access": "protected", "methods": ["GET"], "purpose": "Workspace memory event search."},
    {"route": "/api/matm/search", "access": "protected", "methods": ["GET"], "purpose": "Hosted workspace memory search."},
    {"route": "/api/matm/review-queue", "access": "protected", "methods": ["GET"], "purpose": "Memory review and promotion queue readback."},
    {"route": "/api/matm/review-queue/decide", "access": "protected", "methods": ["POST"], "purpose": "Idempotent memory promotion, rejection, or quarantine decision."},
    {"route": "/api/matm/meeting-rooms", "access": "protected", "methods": ["GET", "POST"], "purpose": "Always-present company, workspace, project room discovery plus goal/task room creation."},
    {"route": "/api/matm/meeting-messages", "access": "protected", "methods": ["GET", "POST"], "purpose": "Durable scoped meeting room transcript read and public-safe post creation."},
    {"route": "/api/matm/meeting-messages/promote", "access": "protected", "methods": ["POST"], "purpose": "Promote a public-safe meeting transcript message into hosted workspace memory with source linkage."},
    {"route": "/api/matm/meeting-rooms/read", "access": "protected", "methods": ["POST"], "purpose": "Meeting room read cursor update for an agent."},
    {"route": "/api/matm/routing-decisions", "access": "protected", "methods": ["GET", "POST"], "purpose": "Structured coordinator routing decisions with lane, destination room, goal, next action, and expected evidence."},
    {"route": "/api/matm/agent-messages", "access": "protected", "methods": ["POST"], "purpose": "Current-message creation."},
    {"route": "/api/matm/current-message", "access": "protected", "methods": ["GET"], "purpose": "Current-message lane readback."},
    {"route": "/api/matm/agent-inbox", "access": "protected", "methods": ["GET"], "purpose": "Unread inbox readback."},
    {"route": "/api/matm/notifications/ack", "access": "protected", "methods": ["POST"], "purpose": "Notification acknowledgement and receipt creation."},
    {"route": "/api/matm/receipts", "access": "protected", "methods": ["GET"], "purpose": "Redacted receipt readback."},
    {"route": "/api/matm/audit-log", "access": "protected", "methods": ["GET"], "purpose": "Redacted protected-operation audit log readback."},
    {"route": "/api/matm/sync/devices", "access": "protected", "methods": ["POST"], "purpose": "Register a public-safe distributed-sync device authority."},
    {"route": "/api/matm/sync/devices/rotate", "access": "protected", "methods": ["POST"], "purpose": "Rotate a sync device authority epoch."},
    {"route": "/api/matm/sync/devices/revoke", "access": "protected", "methods": ["POST"], "purpose": "Revoke a sync device authority epoch."},
    {"route": "/api/matm/sync/mutations", "access": "protected", "methods": ["POST"], "purpose": "Submit conflict-safe public-safe memory sync mutation."},
    {"route": "/api/matm/sync/receipts", "access": "protected", "methods": ["GET"], "purpose": "Read mutation receipt by idempotency key or receipt id."},
    {"route": "/api/matm/sync/changes", "access": "protected", "methods": ["GET"], "purpose": "Read monotonic sync revision changes after a checkpoint sequence."},
    {"route": "/api/matm/sync/heads", "access": "protected", "methods": ["GET"], "purpose": "Read authoritative sync memory heads."},
    {"route": "/api/matm/sync/retention", "access": "protected", "methods": ["GET"], "purpose": "Read sync tombstone and hard-forget retention policy."},
]


PUBLIC_ROUTES = [item["route"] for item in ROUTE_TABLE if item["access"] == "public"]


PROTECTED_ROUTES = [item["route"] for item in ROUTE_TABLE if item["access"] == "protected"]


def current_store_backend():
    return configured_store_backend()


UAIX_AI_READY_WEB_REFERENCES = [
    "https://uaix.org/en-us/ai-ready-web/",
    "https://uaix.org/en-us/agent-capability-framework/",
    "https://uaix.org/en-us/spec/capability-adaptive-agent-interoperability/",
    "https://uaix.org/en-us/spec/capability-surface-matrix/",
    "https://uaix.org/en-us/spec/agent-executability-matrix/",
]


AGENT_ABILITY_LEVELS = [
    {
        "level": "L0",
        "label": "URL-only static reader",
        "canUse": ["human pages", "sitemap", "llms.txt", "ai.txt"],
        "memoryAuthority": "none",
        "memoryEndpointsPath": ["/", "/docs", "/llms.txt", "/sitemap.xml", "/transparency"],
        "fallback": "Read /transparency and stop with human_review_required when action, auth, memory, or JSON parsing is required.",
    },
    {
        "level": "L1",
        "label": "URL synthesizer and compact JSON reader",
        "canUse": ["public JSON GET", "manifest", "route inventory", "readiness result"],
        "memoryAuthority": "none",
        "memoryEndpointsPath": ["/ai-manifest.json", "/api/matm/agent-compatibility", "/api/matm/route-inventory", "/api/matm/readiness-result"],
        "fallback": "Use public route records only; do not infer write permission from public discovery.",
    },
    {
        "level": "L2",
        "label": "Browser-assisted form operator",
        "canUse": ["visible setup page", "console-assisted flow", "authenticated wiki shell", "copy-safe examples"],
        "memoryAuthority": "human-supplied workspace key only",
        "memoryEndpointsPath": ["/agent-setup", "/agent-coordination", "/console", "/knowledge", "/api/matm/uai-memory/contract"],
        "fallback": "Ask the human to complete setup or provide a workspace key through a secure local setting.",
    },
    {
        "level": "L3",
        "label": "Schema-capable HTTP JSON agent",
        "canUse": ["OpenAPI-style JSON", "structured POST", "safe no-op errors"],
        "memoryAuthority": "workspace-key protected public-safe summaries and protected knowledge rows",
        "memoryEndpointsPath": ["/api/matm/openapi.json", "/api/matm/uai-memory/packages", "/api/matm/uai-memory/records", "/api/matm/uai-memory/startup", "/api/matm/memory-events/submit", "/api/matm/search", "/api/matm/knowledge-documents", "/api/matm/internet-search"],
        "fallback": "Use idempotent POST only when the workspace key and required fields are explicit; otherwise no-op.",
    },
    {
        "level": "L4",
        "label": "Authenticated owner agent",
        "canUse": ["workspace boundary", "protected mutations", "database wiki tree", "audit and receipts"],
        "memoryAuthority": "owned workspace scope with redaction and audit",
        "memoryEndpointsPath": ["/api/matm/workspace", "/api/matm/projects", "/api/matm/uai-memory/file-heads", "/api/matm/uai-memory/edit-claims", "/api/matm/knowledge-tree", "/api/matm/review-queue", "/api/matm/audit-log", "/api/matm/receipts"],
        "fallback": "If auth, scope, idempotency, or provenance is missing, return auth_required or human_review_required.",
    },
    {
        "level": "L5",
        "label": "Restore/readback verifier",
        "canUse": ["post confirmation fields", "readback URLs", "receipt verification"],
        "memoryAuthority": "verified writes only after readback proves visibility",
        "memoryEndpointsPath": ["/api/matm/search", "/api/matm/current-message", "/api/matm/sync/receipts", "/api/matm/sync/changes"],
        "fallback": "Treat a mutation as incomplete until persisted=true and the returned readback route proves visibility.",
    },
    {
        "level": "L6",
        "label": "Multi-agent coordinator",
        "canUse": ["meeting rooms", "routing decisions", "current-message fanout", "memory promotion"],
        "memoryAuthority": "public-safe coordination notes and promoted memory only",
        "memoryEndpointsPath": ["/api/matm/meeting-rooms", "/api/matm/meeting-messages", "/api/matm/routing-decisions", "/api/matm/agent-messages"],
        "fallback": "Start in the company room, record routing decisions, then route work to workspace, project, goal, or task rooms.",
    },
    {
        "level": "L7",
        "label": "Site-specific capability negotiator",
        "canUse": ["manifest negotiation", "connector contract", "sync capability contract"],
        "memoryAuthority": "site-specific only when advertised by public manifest and protected auth",
        "memoryEndpointsPath": ["/ai-manifest.json", "/api/matm/connector-contract", "/api/matm/uai-memory/contract", "/api/matm/live-capability-matrix", "/api/matm/sync/capabilities"],
        "fallback": "Downgrade to L0/L1 when a capability is not listed, auth is unavailable, or an unsupported operation is requested.",
    },
]


ROUTE_RECORD_CONTRACT_FIELDS = [
    "lowestSafeAbilityLevel",
    "highestSupportedAbilityLevel",
    "method",
    "contentType",
    "sideEffectStatus",
    "fetchExecutionClass",
    "requiredFields",
    "resultUrlField",
    "restoreReadbackUrlField",
    "writeCredentialResponsePath",
    "browserFormEquivalent",
    "getSafety",
    "postBlockedFallback",
    "liveGetBlockedFallback",
    "mcpUnavailableFallback",
    "authUnavailableFallback",
    "toolUnavailableFallback",
    "humanReviewUrl",
    "noOpBehavior",
]


def _route_agent_guidance(item):
    route = item["route"]
    methods = item.get("methods") or ["GET"]
    access = item.get("access") or "public"
    has_post = "POST" in methods
    is_public_api = route.startswith("/api/")
    is_static_discovery = route in ("/", "/docs", "/docs/", "/agent-setup", "/agent-coordination", "/console", "/knowledge", "/memory-lifecycle", "/transparency", "/robots.txt", "/sitemap.xml", "/llms.txt", "/llms-full.txt", "/ai.txt")
    is_json_discovery = route in ("/ai-manifest.json", "/.well-known/mcp.json", "/.well-known/ai-agent.json", "/mcp/resources", "/api/version", "/api/matm/live-capability-matrix", "/api/matm/agent-compatibility", "/api/matm/connector-contract", "/api/matm/uai-memory/contract", "/api/matm/openapi.json", "/api/matm/route-inventory", "/api/matm/readiness-result", "/api/matm/redacted-example-receipts", "/api/matm/sync/capabilities")

    if access == "public" and is_static_discovery:
        return {
            "lowestSafeAbilityLevel": "L0",
            "highestSupportedAbilityLevel": "L7",
            "sideEffectStatus": "safe_read",
            "fetchExecutionClass": "static_or_human_html" if route not in ("/robots.txt", "/sitemap.xml", "/llms.txt", "/llms-full.txt", "/ai.txt") else "text_or_xml_get",
            "contentType": "text/html" if route not in ("/robots.txt", "/sitemap.xml", "/llms.txt", "/llms-full.txt", "/ai.txt") else "text_or_xml",
            "requiredFields": [],
            "resultUrlField": "",
            "restoreReadbackUrlField": "",
            "writeCredentialResponsePath": "",
            "browserFormEquivalent": route if route in ("/agent-setup", "/agent-coordination", "/console") else "",
            "getSafety": "safe",
            "postBlockedFallback": "/agent-coordination",
            "liveGetBlockedFallback": "/llms.txt",
            "mcpUnavailableFallback": "/llms.txt",
            "authUnavailableFallback": "/agent-setup",
            "toolUnavailableFallback": "/docs",
            "humanReviewUrl": "/transparency",
            "noOpBehavior": "Read public guidance only; do not infer protected write authority.",
        }

    if access == "public" and is_json_discovery and not has_post:
        return {
            "lowestSafeAbilityLevel": "L1",
            "highestSupportedAbilityLevel": "L7",
            "sideEffectStatus": "safe_read",
            "fetchExecutionClass": "public_json_get",
            "contentType": "application/json",
            "requiredFields": [],
            "resultUrlField": "route_or_url",
            "restoreReadbackUrlField": "",
            "writeCredentialResponsePath": "",
            "browserFormEquivalent": "/docs",
            "getSafety": "safe",
            "postBlockedFallback": "/agent-coordination",
            "liveGetBlockedFallback": "/llms.txt",
            "mcpUnavailableFallback": "/api/matm/route-inventory",
            "authUnavailableFallback": "/agent-setup",
            "toolUnavailableFallback": "/docs",
            "humanReviewUrl": "/transparency",
            "noOpBehavior": "Use discovery as advisory public evidence only; protected actions still require workspace auth.",
        }

    if route == "/api/matm/agent-setup/free-account":
        return {
            "lowestSafeAbilityLevel": "L2",
            "highestSupportedAbilityLevel": "L7",
            "sideEffectStatus": "creates_workspace_on_post",
            "fetchExecutionClass": "browser_form_or_public_json_post",
            "contentType": "application/json",
            "requiredFields": ["companyLabel", "label", "projectLabel"],
            "resultUrlField": "workspaceId",
            "restoreReadbackUrlField": "/api/matm/workspace",
            "writeCredentialResponsePath": "workspaceKey returned once; raw key is not stored server-side",
            "browserFormEquivalent": "/agent-setup",
            "getSafety": "GET is safe; POST creates a workspace and one-time secret",
            "postBlockedFallback": "/agent-setup",
            "liveGetBlockedFallback": "/agent-setup",
            "mcpUnavailableFallback": "/agent-setup",
            "authUnavailableFallback": "not_required_for_setup",
            "toolUnavailableFallback": "/agent-setup",
            "humanReviewUrl": "/transparency",
            "noOpBehavior": "Do not create setup records unless the user explicitly requested workspace setup.",
        }

    if access == "protected":
        level = "L6" if any(fragment in route for fragment in ("meeting-", "routing-decisions", "agent-messages", "current-message", "notifications")) else "L4"
        if "/sync/" in route:
            level = "L7"
        side_effect = "authenticated_mutation" if has_post else "authenticated_read"
        return {
            "lowestSafeAbilityLevel": level,
            "highestSupportedAbilityLevel": "L7",
            "sideEffectStatus": side_effect,
            "fetchExecutionClass": "protected_json_post" if has_post else "protected_json_get",
            "contentType": "application/json",
            "requiredFields": ["workspaceId"] if has_post else ["workspace_id"],
            "resultUrlField": "messageId_or_memoryEventId_or_receiptId",
            "restoreReadbackUrlField": "memoryQueryUrl_or_transcriptQueryUrl_or_inboxQueryUrl_or_receiptQueryUrl",
            "writeCredentialResponsePath": "Authorization: Bearer <WORKSPACE_KEY> or X-MemoryEndpoints-Key; never echo raw key",
            "browserFormEquivalent": "/console",
            "getSafety": "GET is protected read; mutation requires POST and Idempotency-Key when advertised",
            "postBlockedFallback": "/agent-coordination",
            "liveGetBlockedFallback": "/agent-coordination",
            "mcpUnavailableFallback": "/api/matm/openapi.json",
            "authUnavailableFallback": "safeNoOp auth_required",
            "toolUnavailableFallback": "/agent-coordination",
            "humanReviewUrl": "/transparency",
            "noOpBehavior": "Return safe no-op when auth, scope, idempotency, authority, or provenance is missing.",
        }

    return {
        "lowestSafeAbilityLevel": "L1" if is_public_api else "L0",
        "highestSupportedAbilityLevel": "L7",
        "sideEffectStatus": "safe_read" if not has_post else "explicit_mutation",
        "fetchExecutionClass": "public_json_get" if is_public_api else "public_get",
        "contentType": "application/json" if is_public_api else "text/html",
        "requiredFields": [],
        "resultUrlField": "",
        "restoreReadbackUrlField": "",
        "writeCredentialResponsePath": "",
        "browserFormEquivalent": "/docs",
        "getSafety": "safe",
        "postBlockedFallback": "/agent-coordination",
        "liveGetBlockedFallback": "/llms.txt",
        "mcpUnavailableFallback": "/llms.txt",
        "authUnavailableFallback": "/agent-setup",
        "toolUnavailableFallback": "/docs",
        "humanReviewUrl": "/transparency",
        "noOpBehavior": "Use lowest safe public route and stop when authority is unclear.",
    }


def agent_compatibility_contract():
    return {
        "schemaVersion": "memoryendpoints.agent_compatibility.v1",
        "site": SITE_NAME,
        "baseUrl": SITE_URL,
        "generatedAt": utc_now(),
        "status": "public_safe_contract",
        "sourceReferences": UAIX_AI_READY_WEB_REFERENCES,
        "scope": "MemoryEndpoints applies UAIX AI-ready web and agent-compatibility guidance to this target site; this endpoint is implementation evidence, not a UAIX certification claim.",
        "unknownClientDefault": "downgrade_to_L0_or_L1",
        "supportedAbilityLevels": [item["level"] for item in AGENT_ABILITY_LEVELS],
        "abilityLevels": AGENT_ABILITY_LEVELS,
        "routeRecordContract": {
            "routeInventory": "/api/matm/route-inventory",
            "fields": ROUTE_RECORD_CONTRACT_FIELDS,
            "everyRouteIncludesAgentCompatibilityGuidance": True,
        },
        "surfaceMatrix": {
            "staticHtml": {"lowestLevel": "L0", "routes": ["/", "/docs", "/agent-setup", "/agent-coordination", "/console", "/knowledge", "/transparency"]},
            "llmsTxt": {"lowestLevel": "L0", "routes": ["/llms.txt", "/llms-full.txt", "/ai.txt"]},
            "sitemap": {"lowestLevel": "L0", "routes": ["/sitemap.xml"]},
            "jsonDiscovery": {"lowestLevel": "L1", "routes": ["/ai-manifest.json", "/api/matm/agent-compatibility", "/api/matm/uai-memory/contract", "/api/matm/route-inventory", "/api/matm/readiness-result"]},
            "browserForms": {"lowestLevel": "L2", "routes": ["/agent-setup", "/agent-coordination", "/console", "/knowledge"]},
            "postJson": {"lowestLevel": "L3", "routes": ["/api/matm/agents/register", "/api/matm/uai-memory/packages", "/api/matm/uai-memory/records", "/api/matm/memory-events/submit", "/api/matm/knowledge-documents", "/api/matm/external-links", "/api/matm/meeting-messages"]},
            "authenticatedOwner": {"lowestLevel": "L4", "routes": ["/api/matm/workspace", "/api/matm/projects", "/api/matm/uai-memory/file-heads", "/api/matm/uai-memory/edit-claims", "/api/matm/knowledge-tree", "/api/matm/review-queue", "/api/matm/audit-log"]},
            "restoreReadback": {"lowestLevel": "L5", "routes": ["/api/matm/search", "/api/matm/current-message", "/api/matm/sync/receipts", "/api/matm/sync/changes"]},
            "multiAgent": {"lowestLevel": "L6", "routes": ["/api/matm/meeting-rooms", "/api/matm/routing-decisions", "/api/matm/agent-messages"]},
            "siteSpecificNegotiation": {"lowestLevel": "L7", "routes": ["/api/matm/live-capability-matrix", "/api/matm/connector-contract", "/api/matm/uai-memory/contract", "/api/matm/sync/capabilities"]},
        },
        "fallbackPolicy": {
            "postUnavailable": "Use /agent-coordination or /console for browser-assisted flow; otherwise stop with human_review_required.",
            "authUnavailable": "Use public setup and discovery only; protected routes return safeNoOp auth_required.",
            "mcpUnavailable": "Use /api/matm/route-inventory, /api/matm/openapi.json, and /llms.txt.",
            "liveGetUnavailable": "Use cached public guidance only if provided by the operator; do not claim live verification.",
            "toolsUnavailable": "Use L0/L1 text and JSON routes, then ask for human review before action.",
            "memoryEndpointUnavailable": "Keep local .uai active startup memory usable; do not treat hosted memory outage as permission to forget active local instructions.",
        },
        "dogfoodFeedbackForUAIX": [
            "Publish one compact JSON companion that composes AI-Ready Web evidence requirements with L0-L7 agent compatibility so agents do not have to stitch separate standards pages together.",
            "Make route-record compatibility fields validator-addressable: lowest safe level, highest supported level, side-effect status, fetch class, required fields, readback URL, browser equivalent, fallbacks, human review URL, and no-op behavior.",
            "Make the wizard generate L0/L1 fallback routes beside OpenAPI or MCP output so low-capability agents are not stranded on POST-only or JavaScript-only flows.",
            "Require memory guidance to preserve local .uai active memory even when hosted memory endpoints are unavailable, then route public-safe durable memory to the hosted system.",
            "Document the narrow accountless-browser exception separately from normal local .uai guidance, and recommend hash-only edit claims for concurrent local agents instead of centralizing every active file.",
            "Warn when examples and real credentials share the same prompt block; require machine-readable auth blocks with placeholder-only examples.",
        ],
        "truthBoundary": {
            "publicDiscoveryGrantsWriteAuthority": False,
            "protectedWritesRequireWorkspaceKey": True,
            "rawWorkspaceKeysInPublicResponses": False,
            "rawPrivatePayloadsStored": False,
            "certificationClaimed": False,
            "unsupportedActionsReturnSafeNoOp": True,
        },
    }


def sync_capabilities():
    return {
        "schemaVersion": "memoryendpoints.distributed_sync_capabilities.v1",
        "status": "live",
        "protocol": "memoryendpoints-distributed-sync-v1",
        "capabilityRoute": "/api/matm/sync/capabilities",
        "routes": {
            "registerDevice": "/api/matm/sync/devices",
            "rotateDevice": "/api/matm/sync/devices/rotate",
            "revokeDevice": "/api/matm/sync/devices/revoke",
            "submitMutation": "/api/matm/sync/mutations",
            "lookupReceipt": "/api/matm/sync/receipts",
            "changes": "/api/matm/sync/changes",
            "heads": "/api/matm/sync/heads",
            "retention": "/api/matm/sync/retention",
        },
        "mutationContract": {
            "operations": ["upsert", "delete", "hard_forget"],
            "hardForgetSupported": False,
            "hardForgetBehavior": "safe_rejected_receipt",
            "idempotency": "Idempotency-Key is required for reliable offline retry; receipt lookup accepts the same key and never echoes it.",
            "revisionFields": ["logicalMemoryId", "parentRevisionId", "syncRevisionId", "serverSequence", "bodyHash", "conflict", "conflictCode"],
            "conflictSemantics": "When an existing head is updated without the current parent revision, the mutation is durably recorded as conflict and the head remains unchanged.",
            "tombstoneSemantics": "Delete creates a tombstoned head; later upsert is blocked unless a future explicit resurrection contract is advertised.",
        },
        "checkpointContract": {
            "changesQuery": ["workspace_id", "after_sequence", "limit", "logical_memory_id"],
            "monotonicServerSequence": True,
            "indexedThroughWatermark": True,
            "paginationFields": ["items", "hasMore", "nextAfterSequence", "indexedThroughSequence", "checkpoint"],
        },
        "deviceContract": {
            "authorityEpoch": True,
            "registerRotateRevoke": True,
            "revokedDeviceMutationBehavior": "safe_rejected_receipt",
            "secretMaterialStored": False,
        },
        "retention": {
            "tombstoneRetentionDays": 30,
            "hardForgetSupported": False,
            "rawPrivatePayloadStored": False,
            "valuesRedacted": True,
        },
        "publicSafeOnly": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
        "valuesRedacted": True,
    }


def capability_matrix():
    health = store_backend_health()
    backend = health["storeBackend"]
    configured_backend = health["configuredStoreBackend"]
    mysql_active = mysql_backend_name(configured_backend) and health["storeBackendVerified"]
    return {
        "schemaVersion": "memoryendpoints.capability_matrix.v1",
        "site": SITE_NAME,
        "version": __version__,
        "generatedAt": utc_now(),
        "truthBoundary": {
            "databasePersistence": "mysql_relational_backend_live" if mysql_active else "mysql_backend_required_not_verified",
            "fileBackedMemory": "local_bootstrap_and_export_artifacts_only",
            "longTermMemorySource": "hosted_memoryendpoints_workspace_memory",
            "rawSecretsInPublicSurfaces": False,
            "certificationClaimed": False,
        },
        "publicRoutes": PUBLIC_ROUTES,
        "protectedRoutes": PROTECTED_ROUTES,
        "companionDocumentation": {
            "site": COMPANION_DOCS_URL,
            "role": "GitHub companion documentation for MATM architecture, repository handoff, and memory boundary details.",
            "sourceRepository": GITHUB_REPO_URL,
        },
        "memoryLevels": [
            {"level": "active_startup_suite", "status": "live", "storage": ".uai/*.uai listed by .uai/startup-packet.uai"},
            {"level": "accountless_browser_active_memory", "status": "live", "storage": "registered-agent virtual UAIX records in protected database tables; narrow no-local-filesystem exception only"},
            {"level": "local_uai_collaboration_overlay", "status": "live", "storage": "project/path hashes, bounded edit claims, and public-safe summaries only; local .uai content remains local"},
            {"level": "account_company_membership", "status": "live", "storage": "account-company membership links; accounts and companies can be many-to-many"},
            {"level": "company", "status": "live", "storage": "company-owned workspaces"},
            {"level": "project", "status": "live", "storage": "hosted project-scoped MATM memory records"},
            {"level": "workspace", "status": "live", "storage": "hosted workspace MATM memory with firewall and review queue"},
            {"level": "company_workspace_project_wiki", "status": "live", "storage": "database-backed crawl sources and search documents; no filesystem knowledge tree"},
            {"level": "curated_external_web", "status": "live", "storage": "first-class external links and many-to-many knowledge citations"},
            {"level": "workspace_database", "status": "live_mysql" if mysql_active else "mysql_required_not_verified", "storage": "MySQL/MariaDB relational MATM tables"},
        ],
        "memoryFirewall": {
            "status": "live",
            "redactsBeforePersistence": True,
            "quarantineRoute": "/api/matm/review-queue",
            "rawPrivatePayloadStored": False,
        },
        "reviewPromotionQueue": {
            "status": "live",
            "readRoute": "/api/matm/review-queue",
            "decisionRoute": "/api/matm/review-queue/decide",
            "queryFilters": ["status", "source_prefix", "tag", "memory_type", "actor_agent_id"],
            "operatorSummaryFields": ["statusCounts", "visibleStatusCounts", "firewallDecisionCounts", "longTermMemoryReviews"],
            "longTermMemoryReviewHealth": "Review queue responses summarize canonical docs/long-term-memory source review health, duplicate records, and actionable counts.",
            "idempotencyRequiredForDecision": True,
        },
        "knowledgeWiki": {
            "status": "live",
            "humanRoute": "/knowledge",
            "authenticationRequired": True,
            "anonymousShellContainsKnowledge": False,
            "publicKnowledgeIndex": False,
            "projectRoute": "/api/matm/projects",
            "treeRoute": "/api/matm/knowledge-tree",
            "documentRoute": "/api/matm/knowledge-documents",
            "upsertRoute": "/api/matm/knowledge-documents/upsert",
            "supportedScopes": ["company", "workspace", "project"],
            "identityOwnedKnowledgeScopes": [],
            "accountCompanyMembership": "many_to_many",
            "taskLevelTreeSupported": False,
            "databaseSourceOfTruth": True,
            "filesystemKnowledgeTree": False,
            "firstClassStorage": ["matm_crawl_sources", "matm_search_documents", "matm_external_links", "matm_external_link_mentions", "matm_projects"],
            "humanAndAgentParity": "The authenticated wiki shell and swarm agents read the same protected database tree and document rows.",
            "queryFilters": ["q", "scope", "scope_id", "category", "taxonomy_path", "taxonomy_prefix", "document_type", "source_prefix", "document_id", "route_or_path", "include_text", "limit"],
            "postConfirmationFields": ["persisted", "visibleInSearch", "visibleInWikiTree", "visibleInAuditLog", "canonicalSearchDocumentId", "canonicalSourceId", "documentQueryUrl", "searchQueryUrl", "treeQueryUrl"],
            "requiredDocumentFields": ["title", "description", "keywords", "taxonomyPaths", "searchableText"],
            "multiHierarchyPlacement": True,
        },
        "externalLinkSearch": {
            "status": "live",
            "searchRoute": "/api/matm/internet-search",
            "linkRoute": "/api/matm/external-links",
            "upsertRoute": "/api/matm/external-links/upsert",
            "storageTables": ["matm_external_links", "matm_external_link_mentions"],
            "requiredLinkFields": ["url", "siteName", "pageTitle", "description", "keywords"],
            "citationFields": ["knowledgeDocumentId", "relationshipType", "anchorText", "contextDescription", "citationLabel", "citationOrder"],
            "queryFilters": ["q", "external_link_id", "document_id", "host", "site_name", "review_status", "crawl_status", "relationship_type", "scope", "scope_id", "taxonomy_path", "limit"],
            "publicInternetHostsOnly": True,
            "credentialBearingUrlsRejected": True,
            "automaticFetchOnUpsert": False,
            "searchMode": "reviewed_curated_web_index",
        },
        "storageBackends": [
            {"backend": "file", "status": "current" if backend == "file" else "available_local", "dependency": "python_stdlib"},
            {"backend": "sqlite", "status": "current" if backend == "sqlite" else "available_local_relational", "dependency": "python_stdlib_sqlite3"},
            {"backend": "mysql", "status": "current_verified" if mysql_active else "required_unverified", "dependency": "host_provided_mysql_python_driver_not_packaged"},
        ],
        "runtimeBackendHealth": health,
        "currentMessageLane": {
            "status": "live",
            "readRoute": "/api/matm/current-message",
            "sendRoute": "/api/matm/agent-messages",
            "ackRoute": "/api/matm/notifications/ack",
            "responseStates": ["required_response", "viewed_acknowledgement"],
            "queryFilters": ["agent_id", "message_id", "notification_id", "limit"],
            "broadcastFanout": "per_active_agent_notification",
            "ackIsolation": "per_recipient_notification",
            "broadcastInvariant": "Each broadcast recipient receives a distinct unread notification id so one agent acknowledgement does not clear the broadcast for other agents.",
            "postConfirmationFields": ["expectedRecipientCount", "visibleRecipientCount", "visibleToAgents", "notificationIds"],
        },
        "meetingRooms": {
            "status": "live",
            "roomListRoute": "/api/matm/meeting-rooms",
            "roomCreateRoute": "/api/matm/meeting-rooms",
            "messageRoute": "/api/matm/meeting-messages",
            "promoteMessageRoute": "/api/matm/meeting-messages/promote",
            "readCursorRoute": "/api/matm/meeting-rooms/read",
            "defaultScopes": ["company", "workspace", "project"],
            "customScopes": ["goal", "task"],
            "alwaysAvailable": True,
            "firstClassStorage": ["matm_meeting_rooms", "matm_meeting_messages", "matm_meeting_reads"],
        },
        "routingDecisions": {
            "status": "live",
            "route": "/api/matm/routing-decisions",
            "methods": ["GET", "POST"],
            "requiredPostFields": ["workspaceId", "sourceRoomId", "coordinatorAgentId", "routedAgentId", "lane", "specificGoal", "expectedEvidence", "nextAction", "supportPlan"],
            "destinationFields": ["destinationRoomId", "destinationScope", "destinationScopeId"],
            "queryFilters": ["room_id", "destination_room_id", "routed_agent_id", "coordinator_agent_id", "lane", "destination_scope", "destination_scope_id", "status"],
            "postConfirmationFields": ["persisted", "visibleToRoutedAgent", "canonicalRoutingDecisionId", "canonicalRoomId", "destinationRoomId", "messageId", "routingDecisionQueryUrl", "transcriptQueryUrl", "destinationTranscriptQueryUrl"],
            "firstClassStorage": ["matm_routing_decisions", "matm_meeting_messages"],
            "purpose": "Give new or redirected agents a machine-readable answer for chosen lane, chosen room, specific goal, evidence expected, and next action while still posting a human-readable meeting transcript note.",
        },
        "connectorContract": {
            "status": "live",
            "route": "/api/matm/connector-contract",
            "purpose": "Public-safe integration contract for optional app and agent connectors.",
            "credentialBoundary": "workspace keys are user-provided protected credentials; connector UIs must keep them in secure local settings and never print them back.",
            "browserCors": {
                "status": "live",
                "preflightWithoutWorkspaceKey": True,
                "allowedMethods": ["GET", "POST", "OPTIONS"],
                "allowedHeaders": ["Authorization", "Content-Type", "Idempotency-Key", "X-MemoryEndpoints-Key"],
            },
        },
        "virtualUaiMemory": virtual_uai_contract(),
        "agentCompatibility": {
            "status": "live",
            "route": "/api/matm/agent-compatibility",
            "supportedAbilityLevels": [item["level"] for item in AGENT_ABILITY_LEVELS],
            "unknownClientDefault": "downgrade_to_L0_or_L1",
            "routeInventoryIncludesCompatibilityGuidance": True,
            "lowestSafeFallback": "/transparency",
            "publicSafeOnly": True,
        },
        "distributedSync": sync_capabilities(),
        "auditTrail": {
            "status": "live",
            "readRoute": "/api/matm/audit-log",
            "protectedOperationsLogged": True,
            "valuesRedacted": True,
            "rawCredentialsExposed": False,
            "rawPayloadsExposed": False,
        },
        "freeAccount": {
            "status": "live",
            "storageLimitBytes": 200 * 1024 * 1024,
            "checkoutRequired": False,
            "keyReturnedOnce": True,
            "rawKeyStoredByServer": False,
            "hierarchy": "creates account -> company membership, company -> workspace, and workspace -> project records",
        },
        "fileHandoff": {
            "status": "live",
            "contentBucket": "agent-file-handoff/Content",
            "improvementBucket": "agent-file-handoff/Improvement",
            "outcomeLedger": ".uai/intake-outcome-ledger.uai",
        },
        "authorityGates": [
            "production_database_adapter",
            "external_authority_receipts",
            "reviewer_memory_promotion",
        ],
    }


def connector_contract():
    protected_headers = {
        "Authorization": "Bearer <WORKSPACE_KEY>",
        "Idempotency-Key": "<stable key for protected mutations>",
    }
    return {
        "schemaVersion": "memoryendpoints.connector_contract.v1",
        "site": SITE_NAME,
        "baseUrl": SITE_URL,
        "generatedAt": utc_now(),
        "status": "public_safe_contract",
        "purpose": "Stable public contract for optional MemoryEndpoints connectors in desktop apps, local runtimes, and agent tools.",
        "audience": ["external_agent", "desktop_app_plugin", "local_runtime_connector", "accountless_browser_ai", "operator_console"],
        "truthBoundary": {
            "protectedWritesRequireWorkspaceKey": True,
            "rawWorkspaceKeysInPublicResponses": False,
            "rawPrivatePayloadsAccepted": False,
            "rawPrivatePayloadsStored": False,
            "valuesRedacted": True,
            "certificationClaimed": False,
        },
        "requiredUserSettings": [
            {"name": "baseUrl", "example": SITE_URL, "storage": "plain setting"},
            {"name": "workspaceId", "example": "workspace-...", "storage": "plain setting"},
            {"name": "agentId", "example": "local-tool-agent", "storage": "plain setting"},
            {"name": "workspaceKey", "example": "me_live_...", "storage": "secure secret store; never echo or log"},
        ],
        "machineReadableAuthBlock": {
            "format": "json_or_env",
            "jsonFields": ["baseUrl", "workspaceId", "agentId", "workspaceKey"],
            "envFields": ["MEMORYENDPOINTS_BASE_URL", "MEMORYENDPOINTS_WORKSPACE_ID", "MEMORYENDPOINTS_AGENT_ID", "MEMORYENDPOINTS_WORKSPACE_KEY"],
            "examplePolicy": "Examples must use placeholder values only. Real workspace keys belong in a clearly named machine-readable auth block or secure local secret store.",
        },
        "authentication": {
            "scheme": "bearer_workspace_key",
            "header": protected_headers["Authorization"],
            "alternateHeader": "X-MemoryEndpoints-Key: <WORKSPACE_KEY>",
            "serverStoresRawKey": False,
            "connectorMustStoreRawKey": "only in a user-approved secure local secret store",
            "connectorMustNot": [
                "print the workspace key",
                "send raw credentials inside memory or meeting summaries",
                "persist raw private payloads as memory",
                "treat public discovery routes as proof of workspace authorization",
            ],
        },
        "browserCors": {
            "status": "live",
            "preflightRoutePattern": "/api/*",
            "preflightMethod": "OPTIONS",
            "preflightRequiresWorkspaceKey": False,
            "allowedMethods": ["GET", "POST", "OPTIONS"],
            "allowedHeaders": ["Authorization", "Content-Type", "Idempotency-Key", "X-MemoryEndpoints-Key"],
            "defaultAllowedOrigins": "*",
            "credentialMode": "omit_or_same_origin_cookie_free; send workspace key in Authorization or X-MemoryEndpoints-Key, not browser cookies",
            "connectorGuidance": "Browser connectors should preflight /api/matm routes, keep the workspace key out of localStorage, and use explicit user opt-in before calling protected routes.",
        },
        "manifestFields": [
            {"name": "id", "required": True, "example": "tiny-rust-lm-memoryendpoints"},
            {"name": "label", "required": True, "example": "MemoryEndpoints.com"},
            {"name": "kind", "required": True, "example": "optional_memory_connector"},
            {"name": "baseUrl", "required": True, "example": SITE_URL},
            {"name": "capabilities", "required": True, "example": ["save_memory", "search_memory", "virtual_uai_active_memory", "local_uai_edit_claims", "knowledge_wiki", "meeting_rooms", "current_messages"]},
            {"name": "publicSafeOnly", "required": True, "example": True},
            {"name": "requiresUserWorkspaceKey", "required": True, "example": True},
            {"name": "secretStorage", "required": True, "example": "os_credential_vault_or_user_approved_secret_store"},
            {"name": "forbiddenPayloads", "required": True, "example": ["raw_credentials", "private_keys", "hidden_prompts", "model_weights"]},
        ],
        "setupFlow": [
            {
                "step": "inspect_setup",
                "route": "/api/matm/agent-setup/free-account",
                "method": "GET",
                "auth": "public",
                "result": "storage limit, checkout state, hierarchy fields, and POST instructions",
            },
            {
                "step": "create_or_enter_workspace",
                "route": "/api/matm/agent-setup/free-account",
                "method": "POST",
                "auth": "public",
                "result": "one-time workspace key plus account/company/workspace/project ids",
                "warning": "The workspace key is returned once; connector UIs must mask it immediately and never print it back",
            },
            {
                "step": "register_agent",
                "route": "/api/matm/agents/register",
                "method": "POST",
                "auth": "workspace_key",
                "headers": protected_headers,
                "required": ["workspaceId", "agentId"],
            },
            {
                "step": "load_workspace",
                "route": "/api/matm/workspace",
                "method": "GET",
                "auth": "workspace_key",
                "query": ["workspace_id"],
            },
            {
                "step": "choose_active_memory_mode",
                "route": "/api/matm/uai-memory/contract",
                "method": "GET",
                "auth": "public",
                "result": "Choose the full virtual package only for an accountless browser AI with no durable local filesystem; normal local agents use the hash-only collaboration overlay.",
            },
        ],
        "uaiMemoryFlow": virtual_uai_contract(),
        "memoryFlow": {
            "submitRoute": "/api/matm/memory-events/submit",
            "searchRoute": "/api/matm/search",
            "promoteMeetingMessageRoute": "/api/matm/meeting-messages/promote",
            "reviewQueueRoute": "/api/matm/review-queue",
            "decisionRoute": "/api/matm/review-queue/decide",
            "summaryMaxCharacters": 4000,
            "supportedScopes": ["company", "workspace", "project", "goal", "task"],
            "supportedMemoryTypes": ["fact", "decision", "status", "procedure", "risk", "evidence", "handoff", "note"],
            "requiredSubmitFields": ["workspaceId", "actorAgentId", "summary"],
            "recommendedSubmitFields": ["scope", "scopeId", "title", "memoryType", "subject", "tags", "source", "confidence"],
            "sourceReferenceFields": ["source", "subject", "tags"],
            "publicSafeRule": "submit summaries only; do not send raw logs, source secrets, full files, or private prompt payloads",
            "updateRule": "Submit a new reviewed public-safe memory event with the same subject/source and an explicit update tag; do not overwrite history until a dedicated revision route is advertised.",
            "submitConfirmationRule": "Treat memory save as successful only when persisted=true and the response confirms visibleInSearch or visibleInReviewQueue plus visibleInAuditLog with memoryQueryUrl, reviewQueueUrl, and auditLogUrl.",
            "searchQueryFilters": ["q", "scope", "scope_id", "source_prefix", "tag", "actor_agent_id", "memory_type", "review_status", "promotion_state", "event_id"],
            "retrieveByScope": "Use /api/matm/search with scope, source_prefix, tag, actor_agent_id, memory_type, review_status, promotion_state, and event_id filters. For deterministic post-submit readback, set event_id to the returned memory event id. For goal or task retrieval, set scope to goal or task and use a stable scopeId chosen by the connector.",
            "reviewQueueFilters": ["status", "source_prefix", "tag", "memory_type", "actor_agent_id"],
            "reviewQueueOperatorSummary": "Use operatorSummary.longTermMemoryReviews to monitor hosted long-term memory promotion health without parsing raw review JSON.",
            "meetingPromotionRule": "Use POST /api/matm/meeting-messages/promote to turn a public-safe meeting transcript note into a durable memory event while preserving the source meeting message id.",
        },
        "knowledgeWikiFlow": {
            "humanRoute": "/knowledge",
            "authenticationRequired": True,
            "anonymousShellContainsKnowledge": False,
            "publicKnowledgeIndex": False,
            "projectRoute": "/api/matm/projects",
            "treeRoute": "/api/matm/knowledge-tree",
            "documentRoute": "/api/matm/knowledge-documents",
            "upsertRoute": "/api/matm/knowledge-documents/upsert",
            "storageTables": ["matm_projects", "matm_crawl_sources", "matm_search_documents"],
            "databaseSourceOfTruth": True,
            "filesystemKnowledgeTree": False,
            "supportedScopes": ["company", "workspace", "project"],
            "forbiddenScopes": ["account", "user", "goal", "task"],
            "identityRule": "Accounts and users are many-to-many company members, not knowledge ownership scopes.",
            "queryFilters": ["q", "scope", "scope_id", "category", "taxonomy_path", "taxonomy_prefix", "document_type", "knowledge_status", "authority_level", "source_prefix", "document_id", "route_or_path", "include_text", "limit"],
            "requiredUpsertFields": ["workspaceId", "actorAgentId", "scope", "title", "description", "keywords", "taxonomyPaths", "searchableText"],
            "recommendedUpsertFields": ["scopeId", "projectId", "projectLabel", "category", "documentType", "knowledgeStatus", "authorityLevel", "statusReason", "supersededByDocumentId", "sourceUri", "sourceType", "routeOrPath", "metadata", "tags"],
            "projectRule": "Project-scoped documents require a real workspace project. Create or discover the project with /api/matm/projects, or include projectLabel during document upsert so the project row is created before indexing.",
            "taxonomyRule": "Each knowledge document requires one or more taxonomyPaths. A single canonical document can appear under multiple hierarchy paths without duplicating the stored report body.",
            "lifecycleRule": "knowledgeStatus is current, proposed, historical, superseded, or archived. Non-current pages require statusReason; superseded pages also require supersededByDocumentId pointing to the current replacement. authorityLevel is canonical, reviewed, reference, community, or unverified.",
            "rankingRule": "Search returns relevance and lifecycle ranking separately, boosts current canonical knowledge, and exposes warnings and replacement links on non-current pages.",
            "exampleTaxonomyPaths": [["AI infrastructure", "tokenization", "prompt optimization"], ["AI infrastructure", "cost governance", "inference budgets"], ["agent operations", "context management", "prompt budgets"]],
            "humanAndAgentParity": "The authenticated human wiki and agent swarm routes read the same protected database documents and canonical tree links.",
            "postConfirmationRule": "Treat a document upsert as successful only when persisted=true and the response confirms visibleInSearch, visibleInWikiTree, and visibleInAuditLog with documentQueryUrl, searchQueryUrl, and treeQueryUrl.",
        },
        "externalLinkFlow": {
            "searchRoute": "/api/matm/internet-search",
            "linkRoute": "/api/matm/external-links",
            "upsertRoute": "/api/matm/external-links/upsert",
            "storageTables": ["matm_external_links", "matm_external_link_mentions"],
            "requiredUpsertFields": ["workspaceId", "actorAgentId", "url", "siteName", "pageTitle", "description", "keywords"],
            "citationRule": "When a wiki page cites the link, also send knowledgeDocumentId and contextDescription. The canonical link is deduplicated while each page keeps its own relationship, anchor, citation label, order, and context.",
            "keywordRule": "Canonical search keywords are a case-insensitive monotonic union across reviewed upserts, so a later citation can add vocabulary without erasing terms learned from earlier reports.",
            "securityRule": "Only public HTTP(S) URLs are accepted. URLs containing userinfo, credential-like query parameters, localhost, private IPs, or internal host suffixes are rejected.",
            "fetchRule": "Upsert indexes reviewed metadata only; it does not automatically fetch or execute the target URL.",
            "postConfirmationRule": "Treat an external-link upsert as successful only when persisted=true and visibleInInternetSearch, visibleOnKnowledgeDocument when cited, and visibleInAuditLog are confirmed.",
        },
        "memoryClassificationRules": [
            "Active startup memory stays local in .uai and must remain usable when MemoryEndpoints.com is unreachable.",
            "Narrow exception: an accountless browser AI with no durable local filesystem may bind a complete virtual UAIX active-memory package to its registered agent id and protected workspace key.",
            "Normal local agents never upload .uai bodies for collaboration; they coordinate project/path hashes, edit intent, short leases, and completion hashes through the local .uai collaboration overlay.",
            "Short-term operational notes can be posted to meeting rooms or current messages when they are coordination, not durable memory.",
            "Short-term memory worth future retrieval should be submitted as memoryType=status or note with tags such as short-term, goal:<id>, or task:<id>.",
            "Long-term decisions, procedures, evidence, risks, and handoffs should be submitted as protected memory events and promoted through review.",
            "Expiration is connector-managed until a dedicated expiration route is advertised: submit only public-safe summaries, include retention tags, and distribute durable outcomes into project, goal, or task scope.",
        ],
        "publicSafeExclusions": [
            "raw credentials",
            "private keys",
            "bearer tokens",
            "model weights",
            "proprietary training data",
            "private optimization logic",
            "license-server internals",
            "hidden prompts",
            "raw prompt payloads",
            "full private source files",
        ],
        "coordinationFlow": {
            "meetingRoomsRoute": "/api/matm/meeting-rooms",
            "meetingRoomCreateRoute": "/api/matm/meeting-rooms",
            "meetingMessagesRoute": "/api/matm/meeting-messages",
            "meetingMessagePromoteRoute": "/api/matm/meeting-messages/promote",
            "meetingReadRoute": "/api/matm/meeting-rooms/read",
            "routingDecisionRoute": "/api/matm/routing-decisions",
            "currentMessageRoute": "/api/matm/current-message",
            "sendCurrentMessageRoute": "/api/matm/agent-messages",
            "ackRoute": "/api/matm/notifications/ack",
            "broadcastFanout": "per_active_agent_notification",
            "ackIsolation": "per_recipient_notification",
            "broadcastInvariant": "Blank targetAgentId means broadcast to active registered agents with a distinct notification per recipient; acknowledgements are scoped to the recipient notification.",
            "currentMessageQueryFilters": ["agent_id", "message_id", "notification_id", "limit"],
            "supportedMeetingRoomScopes": ["company", "workspace", "project", "goal", "task"],
            "meetingRoomQueryFilters": ["agent_id", "scope", "scope_id"],
            "routingDecisionQueryFilters": ["room_id", "destination_room_id", "routed_agent_id", "coordinator_agent_id", "lane", "destination_scope", "destination_scope_id", "status"],
            "requiredRoutingDecisionFields": ["workspaceId", "sourceRoomId", "coordinatorAgentId", "routedAgentId", "lane", "specificGoal", "expectedEvidence", "nextAction", "supportPlan"],
            "requiredMeetingRoomCreateFields": ["workspaceId", "creatorAgentId", "scope", "scopeId"],
            "customMeetingRoomCreateScopes": ["goal", "task"],
            "meetingSummaryMaxCharacters": 2000,
            "currentMessageMaxCharacters": 1000,
            "routingPolicy": [
                "Start in the company welcome/routing room when the connector agent is new or unsure where work belongs.",
                "Coordinators should answer intake with POST /api/matm/routing-decisions so lane, destination room, goal, expected evidence, and next action are machine-readable.",
                "Use the workspace room for cross-project operating context.",
                "Use the project room for assigned implementation work, decisions, blockers, and handoff.",
                "Create goal or task rooms with POST /api/matm/meeting-rooms when work needs a narrower durable transcript.",
                "Use targeted current messages for urgent lane-specific notices; use meeting rooms for durable coordination transcripts.",
            ],
        },
        "recommendedConnectorUi": [
            "Settings: base URL, workspace id, agent id, masked workspace key, and a test-connection action.",
            "Active memory: show either virtual UAIX startup readiness for the accountless-browser exception or local .uai file-head and edit-claim status for filesystem agents; never silently switch modes.",
            "Memory: save public-safe summary, search hosted workspace memory, and show review status.",
            "Meetings: list company/workspace/project/goal/task rooms, create goal or task rooms, post public-safe room notes, promote durable evidence to memory, and mark room read.",
            "Inbox: read current messages for the configured agent and acknowledge notifications.",
            "Receipts/Audit: show redacted receipts and audit summaries for operator trust.",
        ],
        "evidenceToPostBack": [
            "After setup, post a company-room intake note with connector name, agent id, user-visible purpose, and requested route.",
            "After implementation, post a project-room status note with routes exercised, tests run, redaction result, and remaining blocker.",
            "Store durable public-safe status memory with scope project when the connector is verified.",
        ],
        "responseContract": {
            "successEnvelope": ["ok", "valuesRedacted", "rawCredentialExposed", "rawPayloadExposed"],
            "postConfirmationFields": ["persisted", "visibleToSender", "visibleToTarget", "visibleToRoutedAgent", "visibleToAgent", "visibleToAgents", "visibleInSearch", "visibleInReviewQueue", "visibleInAuditLog", "expectedRecipientCount", "visibleRecipientCount", "canonicalRoomId", "canonicalTargetAgentId", "canonicalRoutingDecisionId", "canonicalMemoryEventId", "canonicalPackageId", "canonicalRecordId", "canonicalClaimId", "canonicalHeadId", "messageId", "notificationId", "notificationIds", "roomQueryUrl", "routingDecisionQueryUrl", "transcriptQueryUrl", "destinationTranscriptQueryUrl", "memoryQueryUrl", "reviewQueueUrl", "auditLogUrl", "inboxQueryUrl", "packageQueryUrl", "recordQueryUrl", "startupQueryUrl", "claimQueryUrl", "headQueryUrl"],
            "safeFailureEnvelope": ["ok=false", "safeNoOp=true", "valuesRedacted=true", "rawCredentialExposed=false", "rawPayloadExposed=false"],
            "operatorSummaries": "Protected API responses include compact operatorSummary objects where useful so connector UIs do not need to parse raw debug JSON.",
            "idempotency": "Protected mutation routes support Idempotency-Key except one-time setup.",
        },
        "publicDiscovery": {
            "capabilityMatrix": "/api/matm/live-capability-matrix",
            "agentCompatibility": "/api/matm/agent-compatibility",
            "uaiMemoryContract": "/api/matm/uai-memory/contract",
            "openApi": "/api/matm/openapi.json",
            "routeInventory": "/api/matm/route-inventory",
            "readiness": "/api/matm/readiness-result",
            "mcpResources": "/mcp/resources",
            "aiManifest": "/ai-manifest.json",
            "companionDocs": COMPANION_DOCS_URL,
            "sourceRepository": GITHUB_REPO_URL,
        },
    }


def openapi_spec():
    json_type = {"application/json": {"schema": {"type": "object"}}}
    safe_problem = {
        "description": "Safe no-op error. Raw credentials and raw private payloads are not echoed.",
        "content": json_type,
    }
    protected_security = [{"workspaceBearer": []}, {"workspaceHeader": []}]

    def public_operation(summary, description):
        return {
            "summary": summary,
            "description": description,
            "responses": {
                "200": {"description": "Public-safe response.", "content": json_type},
                "400": safe_problem,
            },
        }

    def protected_operation(summary, description, method="get", mutation=False):
        operation = {
            "summary": summary,
            "description": description,
            "security": protected_security,
            "responses": {
                "200": {"description": "Protected redacted response.", "content": json_type},
                "201": {"description": "Protected redacted creation response.", "content": json_type},
                "202": {"description": "Protected redacted accepted response.", "content": json_type},
                "400": safe_problem,
                "401": safe_problem,
                "404": safe_problem,
                "409": safe_problem,
                "422": safe_problem,
            },
        }
        if method.lower() == "get":
            operation["parameters"] = [
                {"name": "workspace_id", "in": "query", "required": True, "schema": {"type": "string"}, "description": "Authorized workspace id."}
            ]
        else:
            operation["requestBody"] = {"required": True, "content": json_type}
        if mutation:
            operation["parameters"] = [
                {
                    "name": "Idempotency-Key",
                    "in": "header",
                    "required": True,
                    "schema": {"type": "string"},
                    "description": "Stable idempotency key for exact retries. Never include secrets.",
                }
            ]
        return operation

    paths = {
        "/api/matm/connector-contract": {"get": public_operation("Read connector contract", "Public-safe integration contract, browser key guidance, CORS boundary, and UI expectations.")},
        "/api/matm/uai-memory/contract": {"get": public_operation("Read UAIX active-memory contract", "Read the narrow accountless-browser virtual-package exception and hash-only local .uai collaboration-overlay contract.")},
        "/api/matm/live-capability-matrix": {"get": public_operation("Read capability matrix", "Current public capability state and truth boundaries.")},
        "/api/matm/agent-compatibility": {"get": public_operation("Read agent compatibility contract", "L0-L7 agent ability levels, route-record guidance, fallback policy, and UAIX dogfood feedback.")},
        "/api/matm/sync/capabilities": {"get": public_operation("Read distributed sync capabilities", "Public-safe distributed-sync v1 routes, revision/conflict semantics, checkpoint fields, and retention policy.")},
        "/api/matm/readiness-result": {"get": public_operation("Read readiness result", "Current readiness evidence without certification overclaim.")},
        "/api/matm/route-inventory": {"get": public_operation("Read route inventory", "Public and protected route inventory with access boundaries.")},
        "/api/matm/agent-setup/free-account": {
            "get": public_operation("Inspect free workspace setup", "Read quota, hierarchy, and one-time key handling rules."),
            "post": {
                "summary": "Create free workspace",
                "description": "Returns a one-time workspace key. Clients must mask it immediately and store it only in a user-approved secret store.",
                "requestBody": {"required": False, "content": json_type},
                "responses": {
                    "201": {"description": "Workspace created; one-time workspace key returned once.", "content": json_type},
                    "400": safe_problem,
                },
            },
        },
        "/api/matm/workspace": {"get": protected_operation("Load workspace boundary", "Read account, company, workspace, project, storage, and redaction operator summary.")},
        "/api/matm/projects": {
            "get": protected_operation("List projects", "List project records in the authenticated workspace hierarchy."),
            "post": protected_operation("Upsert project", "Create or update a real project record before project-scoped wiki indexing.", "post", True),
        },
        "/api/matm/knowledge-tree": {"get": protected_operation("Read knowledge tree", "Read the lifecycle-aware database-backed company/workspace/project wiki tree. Task-level durable trees are not supported.")},
        "/api/matm/knowledge-documents": {
            "get": protected_operation("Search knowledge documents", "Search or retrieve lifecycle-aware protected database wiki documents by text, scope, category, type, status, authority, source prefix, or exact document id."),
            "post": protected_operation("Upsert knowledge document", "Store a protected database wiki document with first-class lifecycle, authority, and supersession fields.", "post", True),
        },
        "/api/matm/knowledge-documents/upsert": {"post": protected_operation("Upsert knowledge document", "Idempotent protected alias for lifecycle-aware database wiki document upsert.", "post", True)},
        "/api/matm/external-links": {
            "get": protected_operation("Search external links", "Search first-class reviewed external links and their knowledge-document citations."),
            "post": protected_operation("Upsert external link", "Store one canonical external link and optionally attach one contextual knowledge-document citation.", "post", True),
        },
        "/api/matm/external-links/upsert": {"post": protected_operation("Upsert external link", "Idempotent protected alias for external-link and citation upsert.", "post", True)},
        "/api/matm/internet-search": {"get": protected_operation("Search curated web", "Search reviewed URL, site, page title, description, keywords, and citation context as an authenticated internet-search index.")},
        "/api/matm/agents/register": {"post": protected_operation("Register agent", "Register or refresh a stable public-safe agent id.", "post", True)},
        "/api/matm/uai-memory/packages": {
            "get": protected_operation("Read virtual UAIX packages", "Inspect registered-agent virtual UAIX package readiness without exposing a workspace key."),
            "post": protected_operation("Create virtual UAIX package", "Create the full database-backed active-memory exception only for an accountless browser AI without durable local filesystem access.", "post", True),
        },
        "/api/matm/uai-memory/records": {
            "get": protected_operation("Read virtual UAIX records", "Read protected date-free public-safe records or immutable revision history for one registered agent package."),
            "post": protected_operation("Write one virtual UAIX record", "Create or compare-and-swap one supported logical UAIX record with exact protected readback.", "post", True),
        },
        "/api/matm/uai-memory/startup": {"get": protected_operation("Read virtual UAIX startup", "Return the protected virtual package in deterministic startup order with missing-record and readiness evidence.")},
        "/api/matm/uai-memory/file-heads": {"get": protected_operation("Read local .uai file heads", "Read project/path SHA-256 heads and active claim metadata; local file contents are never stored.")},
        "/api/matm/uai-memory/edit-claims": {
            "get": protected_operation("Read local .uai edit claims", "Inspect project-scoped active, completed, released, and expired hash-only edit claims."),
            "post": protected_operation("Acquire local .uai edit claim", "Acquire a bounded project/path lease only when the caller's local base hash matches the latest observed head.", "post", True),
        },
        "/api/matm/uai-memory/edit-claims/heartbeat": {"post": protected_operation("Heartbeat local .uai edit claim", "Extend an owned active claim within the bounded lease window.", "post", True)},
        "/api/matm/uai-memory/edit-claims/complete": {"post": protected_operation("Complete local .uai edit claim", "Advance the hash-only file head using compare-and-swap and retain public-safe completion evidence.", "post", True)},
        "/api/matm/uai-memory/edit-claims/release": {"post": protected_operation("Release local .uai edit claim", "Release an owned active claim without advancing the observed file hash.", "post", True)},
        "/api/matm/memory-events/submit": {"post": protected_operation("Submit memory event", "Save a public-safe hosted memory summary; raw private payloads and credentials are rejected/redacted.", "post", True)},
        "/api/matm/search": {"get": protected_operation("Search hosted memory", "Search scoped hosted workspace memory using query, exact event id, scope, source prefix, tag, memory type, review status, and promotion filters.")},
        "/api/matm/review-queue": {"get": protected_operation("Read review queue", "Read memory review and long-term-memory promotion health without parsing raw debug JSON.")},
        "/api/matm/review-queue/decide": {"post": protected_operation("Decide review", "Promote, reject, or quarantine a review-pending memory item with idempotent reviewer action.", "post", True)},
        "/api/matm/meeting-rooms": {
            "get": protected_operation("List meeting rooms", "List always-present company/workspace/project rooms plus goal/task rooms."),
            "post": protected_operation("Create goal or task room", "Create first-class goal/task coordination room.", "post", True),
        },
        "/api/matm/meeting-messages": {
            "get": protected_operation("Read meeting transcript", "Read durable room transcript and read-state summary."),
            "post": protected_operation("Post meeting message", "Post a public-safe coordination note to a room.", "post", True),
        },
        "/api/matm/meeting-messages/promote": {"post": protected_operation("Promote meeting message", "Promote a public-safe meeting note into hosted memory while preserving source linkage.", "post", True)},
        "/api/matm/meeting-rooms/read": {"post": protected_operation("Mark meeting room read", "Advance an agent read cursor for a room.", "post", True)},
        "/api/matm/routing-decisions": {
            "get": protected_operation("Read routing decisions", "Read machine-readable coordinator routing decisions by room, lane, agent, destination, or status."),
            "post": protected_operation("Create routing decision", "Persist lane, destination room, specific goal, expected evidence, next action, and support plan.", "post", True),
        },
        "/api/matm/agent-messages": {"post": protected_operation("Send current message", "Send broadcast or targeted current-message notification with recipient-specific acknowledgement isolation.", "post", True)},
        "/api/matm/current-message": {"get": protected_operation("Read current messages", "Read current-message inbox with agent_id, message_id, and notification_id filters.")},
        "/api/matm/notifications/ack": {"post": protected_operation("Acknowledge notification", "Mark a notification read and create a redacted receipt.", "post", True)},
        "/api/matm/receipts": {"get": protected_operation("Read receipts", "Read redacted acknowledgement receipts for an agent.")},
        "/api/matm/audit-log": {"get": protected_operation("Read audit log", "Read redacted protected-operation audit events.")},
        "/api/matm/sync/devices": {"post": protected_operation("Register sync device", "Register a public-safe device authority for distributed sync.", "post", True)},
        "/api/matm/sync/devices/rotate": {"post": protected_operation("Rotate sync device", "Increment device authority epoch for distributed sync.", "post", True)},
        "/api/matm/sync/devices/revoke": {"post": protected_operation("Revoke sync device", "Revoke a device authority so future mutations are rejected with durable receipts.", "post", True)},
        "/api/matm/sync/mutations": {"post": protected_operation("Submit sync mutation", "Submit a public-safe conflict-aware memory sync mutation with durable idempotent receipt.", "post", True)},
        "/api/matm/sync/receipts": {"get": protected_operation("Read sync receipt", "Read mutation receipt by Idempotency-Key header, idempotency_key query, or receipt_id query.")},
        "/api/matm/sync/changes": {"get": protected_operation("Read sync changes", "Read monotonic server-sequence revisions after a checkpoint.")},
        "/api/matm/sync/heads": {"get": protected_operation("Read sync heads", "Read authoritative logical memory heads.")},
        "/api/matm/sync/retention": {"get": protected_operation("Read sync retention", "Read tombstone retention and hard-forget support policy.")},
    }
    paths["/api/matm/search"]["get"]["parameters"] = [
        {"name": "workspace_id", "in": "query", "required": True, "schema": {"type": "string"}, "description": "Authorized workspace id."},
        {"name": "q", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Public-safe text query. Leave blank when using an exact event_id readback."},
        {"name": "event_id", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Exact memory event id for deterministic post-submit readback."},
        {"name": "scope", "in": "query", "required": False, "schema": {"type": "string", "enum": ["company", "workspace", "project", "goal", "task"]}, "description": "Exact memory scope filter."},
        {"name": "scope_id", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Exact scope id filter."},
        {"name": "source_prefix", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Source URI prefix filter."},
        {"name": "tag", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Exact tag filter."},
        {"name": "actor_agent_id", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Exact actor agent id filter."},
        {"name": "memory_type", "in": "query", "required": False, "schema": {"type": "string", "enum": ["fact", "decision", "status", "procedure", "risk", "evidence", "handoff", "note"]}, "description": "Exact memory type filter."},
        {"name": "review_status", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Review status filter."},
        {"name": "promotion_state", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Promotion state filter."},
    ]
    knowledge_params = [
        {"name": "workspace_id", "in": "query", "required": True, "schema": {"type": "string"}, "description": "Authorized workspace id."},
        {"name": "q", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Protected text query over database wiki rows."},
        {"name": "scope", "in": "query", "required": False, "schema": {"type": "string", "enum": ["company", "workspace", "project"]}, "description": "Durable wiki scope filter. Task scope is intentionally unsupported."},
        {"name": "scope_id", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Exact company, workspace, or project scope id."},
        {"name": "category", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Knowledge category filter."},
        {"name": "taxonomy_path", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Hierarchy path prefix filter, such as AI infrastructure > tokenization."},
        {"name": "document_type", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Knowledge document type filter."},
        {"name": "source_prefix", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Source URI prefix filter."},
        {"name": "document_id", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Exact search document id for deterministic page retrieval."},
        {"name": "route_or_path", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Exact private wiki route for deterministic internal-link traversal."},
        {"name": "include_text", "in": "query", "required": False, "schema": {"type": "boolean"}, "description": "When true, include protected stored document text."},
        {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer"}, "description": "Result limit, capped by the server."},
    ]
    paths["/api/matm/knowledge-tree"]["get"]["parameters"] = knowledge_params[:8]
    paths["/api/matm/knowledge-documents"]["get"]["parameters"] = knowledge_params
    external_link_params = [
        {"name": "workspace_id", "in": "query", "required": True, "schema": {"type": "string"}, "description": "Authorized workspace id."},
        {"name": "q", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Contextual query over URL, host, site, page title, description, keywords, and citation context."},
        {"name": "external_link_id", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Exact canonical external link id."},
        {"name": "document_id", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Only links cited by this knowledge document."},
        {"name": "host", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Exact normalized public host."},
        {"name": "site_name", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Human-readable site name filter."},
        {"name": "review_status", "in": "query", "required": False, "schema": {"type": "string"}, "description": "External-link review status."},
        {"name": "crawl_status", "in": "query", "required": False, "schema": {"type": "string"}, "description": "External-link crawl status."},
        {"name": "relationship_type", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Citation relationship type."},
        {"name": "scope", "in": "query", "required": False, "schema": {"type": "string", "enum": ["company", "workspace", "project"]}, "description": "Scope of citing knowledge pages."},
        {"name": "scope_id", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Exact scope id of citing knowledge pages."},
        {"name": "taxonomy_path", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Taxonomy prefix of citing knowledge pages."},
        {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer"}, "description": "Result limit, capped by the server."},
    ]
    paths["/api/matm/external-links"]["get"]["parameters"] = external_link_params
    paths["/api/matm/internet-search"]["get"]["parameters"] = external_link_params
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "MemoryEndpoints MATM Golden Path API",
            "version": __version__,
            "summary": "Bounded public-safe OpenAPI-style schema for setup, hosted memory, coordination, receipts, audit, and discovery.",
        },
        "servers": [{"url": SITE_URL}],
        "tags": [
            {"name": "discovery", "description": "Public-safe discovery and readiness routes."},
            {"name": "setup", "description": "Workspace setup and agent registration."},
            {"name": "memory", "description": "Hosted public-safe memory and review promotion."},
            {"name": "knowledge", "description": "Database-backed authenticated wiki tree and protected searchable documents."},
            {"name": "web", "description": "First-class reviewed external links, citations, and curated internet search."},
            {"name": "coordination", "description": "Meeting rooms, routing, and current messages."},
            {"name": "evidence", "description": "Receipts and audit evidence."},
        ],
        "x-memoryendpoints-goldenPath": [
            "create_or_enter_workspace",
            "register_agent",
            "load_workspace",
            "create_or_discover_project",
            "index_knowledge_document",
            "crawl_knowledge_tree",
            "index_external_link_citation",
            "search_curated_web",
            "save_memory",
            "search_memory",
            "create_or_read_meeting_room",
            "send_current_message",
            "acknowledge_notification",
            "read_receipts_and_audit",
        ],
        "x-truthBoundary": {
            "notFullGeneratedSpec": True,
            "protectedWritesRequireWorkspaceKey": True,
            "rawWorkspaceKeysInPublicResponses": False,
            "rawPrivatePayloadsStored": False,
            "valuesRedacted": True,
            "examplesUsePlaceholdersOnly": True,
        },
        "x-agentCompatibility": {
            "contract": "/api/matm/agent-compatibility",
            "supportedAbilityLevels": [item["level"] for item in AGENT_ABILITY_LEVELS],
            "unknownClientDefault": "downgrade_to_L0_or_L1",
            "routeInventoryIncludesCompatibilityGuidance": True,
        },
        "paths": paths,
        "components": {
            "securitySchemes": {
                "workspaceBearer": {"type": "http", "scheme": "bearer", "description": "Workspace key supplied by the user; never echo or log."},
                "workspaceHeader": {"type": "apiKey", "in": "header", "name": "X-MemoryEndpoints-Key", "description": "Alternate workspace key header for browser connectors."},
            },
            "schemas": {
                "SafeEnvelope": {
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean"},
                        "valuesRedacted": {"type": "boolean"},
                        "rawCredentialExposed": {"type": "boolean"},
                        "rawPayloadExposed": {"type": "boolean"},
                    },
                }
            },
        },
    }


def manifest():
    return {
        "schemaVersion": "memoryendpoints.ai_manifest.v1",
        "name": SITE_NAME,
        "url": SITE_URL,
        "description": "Pure Python/TypeScript/HTML5 MATM endpoint reference implementation.",
        "version": __version__,
        "companionDocumentation": {
            "site": COMPANION_DOCS_URL,
            "role": "GitHub companion documentation site for the repository, MATM setup, and public memory model.",
            "sourceRepository": GITHUB_REPO_URL,
        },
        "aiReadyWeb": {
            "humanFirst": True,
            "deterministicDiscovery": True,
            "boundedCapabilities": True,
            "privacyPreservingReceipts": True,
            "hiddenBotOnlyContent": False,
            "agentAbilityLevels": [item["level"] for item in AGENT_ABILITY_LEVELS],
            "agentCompatibilityRoute": "%s/api/matm/agent-compatibility" % SITE_URL,
        },
        "evidence": {
            "routeInventory": "%s/api/matm/route-inventory" % SITE_URL,
            "readinessResult": "%s/api/matm/readiness-result" % SITE_URL,
            "capabilityMatrix": "%s/api/matm/live-capability-matrix" % SITE_URL,
            "agentCompatibility": "%s/api/matm/agent-compatibility" % SITE_URL,
            "connectorContract": "%s/api/matm/connector-contract" % SITE_URL,
            "uaiMemoryContract": "%s/api/matm/uai-memory/contract" % SITE_URL,
            "openApi": "%s/api/matm/openapi.json" % SITE_URL,
            "sitemap": "%s/sitemap.xml" % SITE_URL,
            "llmsTxt": "%s/llms.txt" % SITE_URL,
            "companionDocs": COMPANION_DOCS_URL,
            "sourceRepository": GITHUB_REPO_URL,
        },
        "supportBoundary": {
            "noCertificationClaimed": True,
            "noHiddenCredentialValidation": True,
            "protectedWritesRequireWorkspaceKey": True,
            "unsupportedActionsReturnSafeNoOp": True,
        },
        "routes": {"public": PUBLIC_ROUTES, "protected": PROTECTED_ROUTES},
        "mcp": {"resources": "%s/mcp/resources" % SITE_URL, "wellKnown": "%s/.well-known/mcp.json" % SITE_URL},
        "agentCompatibility": {
            "contract": "%s/api/matm/agent-compatibility" % SITE_URL,
            "supportedAbilityLevels": [item["level"] for item in AGENT_ABILITY_LEVELS],
            "unknownClientDefault": "downgrade_to_L0_or_L1",
        },
        "uaiMemory": {
            "contract": "%s/api/matm/uai-memory/contract" % SITE_URL,
            "fullVirtualPackageException": "accountless_browser_ai_without_durable_local_filesystem",
            "localCollaborationOverlayStoresFileContent": False,
            "registeredAgentAndWorkspaceKeyRequired": True,
        },
    }


def readiness_result():
    health = store_backend_health()
    backend = health["storeBackend"]
    configured_backend = health["configuredStoreBackend"]
    mysql_active = mysql_backend_name(configured_backend) and health["storeBackendVerified"]
    return {
        "schemaVersion": "memoryendpoints.readiness_result.v1",
        "site": SITE_NAME,
        "generatedAt": utc_now(),
        "overallStatus": "live_mysql_verified" if mysql_active else "mysql_required_not_verified",
        "completionClaimAllowed": mysql_active,
        "certificationClaimed": False,
        "runtimeBackendHealth": health,
        "sourceReferences": [
            "https://uaix.org/en-us/ai-ready-web/",
            "https://uaix.org/en-us/agent-capability-framework/",
            "https://uaix.org/en-us/spec/capability-adaptive-agent-interoperability/",
            "https://uaix.org/en-us/spec/capability-surface-matrix/",
            "https://uaix.org/en-us/spec/agent-executability-matrix/",
            "https://uaix.org/en-us/tools/ai-memory-package-wizard/#setup-MATM-MemoryEndpoints",
            COMPANION_DOCS_URL,
            GITHUB_REPO_URL,
        ],
        "checks": [
            {
                "id": "human_public_pages",
                "status": "pass_local",
                "evidence": ["/", "/docs", "/docs/", "/agent-setup", "/console", "/memory-lifecycle", "/transparency"],
            },
            {
                "id": "deterministic_discovery",
                "status": "pass_local",
                "evidence": ["/robots.txt", "/sitemap.xml", "/llms.txt", "/ai-manifest.json", "/.well-known/mcp.json", "/api/matm/connector-contract"],
            },
            {
                "id": "route_inventory",
                "status": "pass_local",
                "evidence": ["/api/matm/route-inventory", "docs/route-inventory.md", "every route includes agentCompatibility guidance"],
            },
            {
                "id": "agent_ability_compatibility",
                "status": "pass_local",
                "evidence": ["/api/matm/agent-compatibility", "L0-L7 ability levels", "fallback policy", "route-record contract fields"],
            },
            {
                "id": "safe_api_boundaries",
                "status": "pass_local",
                "evidence": ["protected routes require workspace key", "errors return safeNoOp"],
            },
            {
                "id": "account_company_workspace_project_hierarchy",
                "status": "pass_local",
                "evidence": ["account-company membership", "company-owned workspace", "workspace-owned project", "tests/test_app.py"],
            },
            {
                "id": "privacy_and_secret_handling",
                "status": "pass_local",
                "evidence": ["one-time key return", "token hash storage", "redacted receipts", "memory firewall redacts secret-like input before persistence"],
            },
            {
                "id": "review_promotion_queue",
                "status": "pass_local",
                "evidence": ["/api/matm/review-queue", "/api/matm/review-queue/decide", "idempotent promotion decisions"],
            },
            {
                "id": "meeting_rooms",
                "status": "pass_local",
                "evidence": ["/api/matm/meeting-rooms", "/api/matm/meeting-messages", "/api/matm/meeting-rooms/read", "default company/workspace/project rooms plus custom goal/task rooms"],
            },
            {
                "id": "optional_connector_contract",
                "status": "pass_local",
                "evidence": ["/api/matm/connector-contract", "public-safe connector setup, memory, meeting, inbox, receipt, and audit guidance"],
            },
            {
                "id": "uaix_active_memory_modes",
                "status": "pass_local",
                "evidence": [
                    "/api/matm/uai-memory/contract",
                    "registered-agent accountless-browser virtual package with immutable record revisions",
                    "hash-only project/path collaboration heads and bounded edit claims",
                    "tests/test_uai_memory.py",
                ],
            },
            {
                "id": "protected_operation_audit_trail",
                "status": "pass_local",
                "evidence": ["/api/matm/audit-log", "redacted protected-operation readback", "tests/test_app.py"],
            },
            {
                "id": "agent_file_handoff",
                "status": "pass_local",
                "evidence": ["agent-file-handoff/Content", "agent-file-handoff/Improvement", ".uai/intake-outcome-ledger.uai"],
            },
            {
                "id": "local_dogfood",
                "status": "pass_local",
                "evidence": ["scripts/dogfood_memoryendpoints.py", "docs/reports/dogfood-memory-run.json"],
            },
            {
                "id": "live_deployment",
                "status": "pass_live",
                "evidence": [
                    "scripts/ftp_deploy_memoryendpoints.py",
                    "docs/reports/deploy-attempt-20260709.json",
                    "docs/reports/live-route-verification.json",
                    "Live public route verifier returns zero failures for the deployed public surface.",
                    "Live /api/version source SHA verification is the current post-deploy proof.",
                ],
            },
            {
                "id": "live_dogfood",
                "status": "pass_live",
                "evidence": [
                    "docs/reports/dogfood-memory-run.json",
                    "Live authenticated MATM dogfood verifies workspace setup, memory, current-message, receipt, and audit-log readback.",
                ],
            },
            {
                "id": "human_verifier_console",
                "status": "pass_local",
                "evidence": ["/console", "static/js/site.js", "scripts/create_human_verifier_account.py"],
            },
            {
                "id": "mysql_runtime_backend",
                "status": "pass_live" if mysql_active else "blocked",
                "evidence": ["/api/version storeBackendVerified", "MEMORYENDPOINTS_STORE_BACKEND", "memoryendpoints.storage.MySQLStore"],
            },
            {
                "id": "production_database_adapter",
                "status": "pass_live" if mysql_active else "blocked",
                "evidence": ["docs/database-schema-canonical.sql", "docs/database-structure.md", "docs/long-term-memory/architecture-notes.md"],
            },
        ],
        "blockers": []
        if mysql_active
        else [
            {
                "id": "mysql_runtime_backend",
                "detail": "The runtime is not verified against MySQL/MariaDB. /api/version must report storeBackend mysql or mariadb and storeBackendVerified true before completion can be claimed.",
                "configuredStoreBackend": configured_backend,
                "observedStoreBackend": backend,
                "storeBackendStatus": health["storeBackendStatus"],
                "safeNoOp": True,
            },
        ],
        "gatedCapabilities": [],
    }


def route_inventory():
    routes = []
    for item in ROUTE_TABLE:
        out = dict(item)
        out["agentCompatibility"] = _route_agent_guidance(item)
        out["valuesRedacted"] = True
        routes.append(out)
    return {
        "schemaVersion": "memoryendpoints.route_inventory.v1",
        "site": SITE_NAME,
        "generatedAt": utc_now(),
        "routeCount": len(routes),
        "routes": routes,
        "truthBoundary": {
            "publicRoutesRequireNoCredential": True,
            "protectedRoutesRequireWorkspaceKey": True,
            "operatorDeployRoutesExposed": False,
            "rawSecretsExposed": False,
        },
    }
