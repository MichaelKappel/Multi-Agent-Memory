from . import __version__
from .config import COMPANION_DOCS_URL, GITHUB_REPO_URL, SITE_NAME, SITE_URL, utc_now
from .runtime import configured_store_backend, mysql_backend_name, store_backend_health


ROUTE_TABLE = [
    {"route": "/", "access": "public", "methods": ["GET"], "purpose": "Human home page."},
    {"route": "/docs", "access": "public", "methods": ["GET"], "purpose": "Human-readable documentation."},
    {"route": "/docs/", "access": "public", "methods": ["GET"], "purpose": "Trailing-slash documentation alias."},
    {"route": "/agent-setup", "access": "public", "methods": ["GET"], "purpose": "Agent setup instructions."},
    {"route": "/agent-coordination", "access": "public", "methods": ["GET"], "purpose": "Authenticated agent coordination quickstart with copy-safe examples."},
    {"route": "/console", "access": "public", "methods": ["GET"], "purpose": "Human verification console for authenticated workspace keys."},
    {"route": "/memory-lifecycle", "access": "public", "methods": ["GET"], "purpose": "Memory lifecycle explanation."},
    {"route": "/transparency", "access": "public", "methods": ["GET"], "purpose": "Support boundaries and no-op behavior."},
    {"route": "/api/version", "access": "public", "methods": ["GET"], "purpose": "Runtime version and dependency facts."},
    {"route": "/api/matm/live-capability-matrix", "access": "public", "methods": ["GET"], "purpose": "Current MATM capability state."},
    {"route": "/api/matm/connector-contract", "access": "public", "methods": ["GET"], "purpose": "Public-safe optional connector integration contract for external agents and apps."},
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
    {"route": "/api/matm/agents/register", "access": "protected", "methods": ["POST"], "purpose": "Agent registration."},
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
]


PUBLIC_ROUTES = [item["route"] for item in ROUTE_TABLE if item["access"] == "public"]


PROTECTED_ROUTES = [item["route"] for item in ROUTE_TABLE if item["access"] == "protected"]


def current_store_backend():
    return configured_store_backend()


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
            {"level": "account_company_membership", "status": "live", "storage": "account-company membership links; accounts and companies can be many-to-many"},
            {"level": "company", "status": "live", "storage": "company-owned workspaces"},
            {"level": "project", "status": "live", "storage": "hosted project-scoped MATM memory records"},
            {"level": "workspace", "status": "live", "storage": "hosted workspace MATM memory with firewall and review queue"},
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
        "audience": ["external_agent", "desktop_app_plugin", "local_runtime_connector", "operator_console"],
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
            {"name": "capabilities", "required": True, "example": ["save_memory", "search_memory", "meeting_rooms", "current_messages"]},
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
        ],
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
            "retrieveByScope": "Use /api/matm/search with scope, source_prefix, tag, actor_agent_id, memory_type, review_status, and promotion_state filters. For goal or task retrieval, set scope to goal or task and use a stable scopeId chosen by the connector.",
            "reviewQueueFilters": ["status", "source_prefix", "tag", "memory_type", "actor_agent_id"],
            "reviewQueueOperatorSummary": "Use operatorSummary.longTermMemoryReviews to monitor hosted long-term memory promotion health without parsing raw review JSON.",
            "meetingPromotionRule": "Use POST /api/matm/meeting-messages/promote to turn a public-safe meeting transcript note into a durable memory event while preserving the source meeting message id.",
        },
        "memoryClassificationRules": [
            "Active startup memory stays local in .uai and must remain usable when MemoryEndpoints.com is unreachable.",
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
            "postConfirmationFields": ["persisted", "visibleToSender", "visibleToTarget", "visibleToRoutedAgent", "visibleToAgent", "visibleToAgents", "visibleInSearch", "visibleInReviewQueue", "visibleInAuditLog", "expectedRecipientCount", "visibleRecipientCount", "canonicalRoomId", "canonicalTargetAgentId", "canonicalRoutingDecisionId", "canonicalMemoryEventId", "messageId", "notificationId", "notificationIds", "roomQueryUrl", "routingDecisionQueryUrl", "transcriptQueryUrl", "destinationTranscriptQueryUrl", "memoryQueryUrl", "reviewQueueUrl", "auditLogUrl", "inboxQueryUrl"],
            "safeFailureEnvelope": ["ok=false", "safeNoOp=true", "valuesRedacted=true", "rawCredentialExposed=false", "rawPayloadExposed=false"],
            "operatorSummaries": "Protected API responses include compact operatorSummary objects where useful so connector UIs do not need to parse raw debug JSON.",
            "idempotency": "Protected mutation routes support Idempotency-Key except one-time setup.",
        },
        "publicDiscovery": {
            "capabilityMatrix": "/api/matm/live-capability-matrix",
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
        "/api/matm/live-capability-matrix": {"get": public_operation("Read capability matrix", "Current public capability state and truth boundaries.")},
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
        "/api/matm/agents/register": {"post": protected_operation("Register agent", "Register or refresh a stable public-safe agent id.", "post", True)},
        "/api/matm/memory-events/submit": {"post": protected_operation("Submit memory event", "Save a public-safe hosted memory summary; raw private payloads and credentials are rejected/redacted.", "post", True)},
        "/api/matm/search": {"get": protected_operation("Search hosted memory", "Search scoped hosted workspace memory using query, scope, source prefix, tag, memory type, review status, and promotion filters.")},
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
    }
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
            {"name": "coordination", "description": "Meeting rooms, routing, and current messages."},
            {"name": "evidence", "description": "Receipts and audit evidence."},
        ],
        "x-memoryendpoints-goldenPath": [
            "create_or_enter_workspace",
            "register_agent",
            "load_workspace",
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
        },
        "evidence": {
            "routeInventory": "%s/api/matm/route-inventory" % SITE_URL,
            "readinessResult": "%s/api/matm/readiness-result" % SITE_URL,
            "capabilityMatrix": "%s/api/matm/live-capability-matrix" % SITE_URL,
            "connectorContract": "%s/api/matm/connector-contract" % SITE_URL,
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
                "evidence": ["/api/matm/route-inventory", "docs/route-inventory.md"],
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
