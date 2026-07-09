from . import __version__
from .config import SITE_NAME, SITE_URL, utc_now


ROUTE_TABLE = [
    {"route": "/", "access": "public", "methods": ["GET"], "purpose": "Human home page."},
    {"route": "/docs", "access": "public", "methods": ["GET"], "purpose": "Human-readable documentation."},
    {"route": "/docs/", "access": "public", "methods": ["GET"], "purpose": "Trailing-slash documentation alias."},
    {"route": "/agent-setup", "access": "public", "methods": ["GET"], "purpose": "Agent setup instructions."},
    {"route": "/memory-lifecycle", "access": "public", "methods": ["GET"], "purpose": "Memory lifecycle explanation."},
    {"route": "/transparency", "access": "public", "methods": ["GET"], "purpose": "Support boundaries and no-op behavior."},
    {"route": "/api/version", "access": "public", "methods": ["GET"], "purpose": "Runtime version and dependency facts."},
    {"route": "/api/matm/live-capability-matrix", "access": "public", "methods": ["GET"], "purpose": "Current MATM capability state."},
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
    {"route": "/api/matm/memory-events/submit", "access": "protected", "methods": ["POST"], "purpose": "Workspace memory summary write."},
    {"route": "/api/matm/memory-events", "access": "protected", "methods": ["GET"], "purpose": "Workspace memory event search."},
    {"route": "/api/matm/search", "access": "protected", "methods": ["GET"], "purpose": "Workspace and docs-backed memory search."},
    {"route": "/api/matm/agent-messages", "access": "protected", "methods": ["POST"], "purpose": "Current-message creation."},
    {"route": "/api/matm/current-message", "access": "protected", "methods": ["GET"], "purpose": "Current-message lane readback."},
    {"route": "/api/matm/agent-inbox", "access": "protected", "methods": ["GET"], "purpose": "Unread inbox readback."},
    {"route": "/api/matm/notifications/ack", "access": "protected", "methods": ["POST"], "purpose": "Notification acknowledgement and receipt creation."},
    {"route": "/api/matm/receipts", "access": "protected", "methods": ["GET"], "purpose": "Redacted receipt readback."},
]


PUBLIC_ROUTES = [item["route"] for item in ROUTE_TABLE if item["access"] == "public"]


PROTECTED_ROUTES = [item["route"] for item in ROUTE_TABLE if item["access"] == "protected"]


def capability_matrix():
    return {
        "schemaVersion": "memoryendpoints.capability_matrix.v1",
        "site": SITE_NAME,
        "version": __version__,
        "generatedAt": utc_now(),
        "truthBoundary": {
            "databasePersistence": "stdlib_sqlite_backend_live_optional_mysql_adapter_gated",
            "fileBackedMemory": "live_local_and_first_deploy",
            "longTermMemorySource": "docs_folder_until_hosted_memory_promotion",
            "rawSecretsInPublicSurfaces": False,
            "certificationClaimed": False,
        },
        "publicRoutes": PUBLIC_ROUTES,
        "protectedRoutes": PROTECTED_ROUTES,
        "memoryLevels": [
            {"level": "session", "status": "live", "storage": ".uai/short-term-memory.uai"},
            {"level": "project", "status": "live", "storage": "docs/long-term-memory"},
            {"level": "workspace", "status": "live", "storage": "file store"},
            {"level": "workspace_database", "status": "live_optional", "storage": "stdlib sqlite"},
            {"level": "client", "status": "planned", "storage": "review-gated durable memory"},
        ],
        "storageBackends": [
            {"backend": "file", "status": "live", "dependency": "python_stdlib"},
            {"backend": "sqlite", "status": "live_optional", "dependency": "python_stdlib_sqlite3"},
            {"backend": "mysql", "status": "adapter_gated", "dependency": "requires_explicit_no_third_party_compatible_adapter"},
        ],
        "currentMessageLane": {
            "status": "live",
            "readRoute": "/api/matm/current-message",
            "ackRoute": "/api/matm/notifications/ack",
            "responseStates": ["required_response", "viewed_acknowledgement"],
        },
        "freeAccount": {
            "status": "live",
            "storageLimitBytes": 200 * 1024 * 1024,
            "checkoutRequired": False,
            "keyReturnedOnce": True,
            "rawKeyStoredByServer": False,
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


def manifest():
    return {
        "schemaVersion": "memoryendpoints.ai_manifest.v1",
        "name": SITE_NAME,
        "url": SITE_URL,
        "description": "Pure Python/TypeScript/HTML5 MATM endpoint reference implementation.",
        "version": __version__,
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
            "sitemap": "%s/sitemap.xml" % SITE_URL,
            "llmsTxt": "%s/llms.txt" % SITE_URL,
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
    return {
        "schemaVersion": "memoryendpoints.readiness_result.v1",
        "site": SITE_NAME,
        "generatedAt": utc_now(),
        "overallStatus": "live_verified",
        "certificationClaimed": False,
        "sourceReferences": [
            "https://uaix.org/en-us/ai-ready-web/",
            "https://uaix.org/en-us/tools/ai-memory-package-wizard/#setup-file-handoff",
        ],
        "checks": [
            {
                "id": "human_public_pages",
                "status": "pass_local",
                "evidence": ["/", "/docs", "/docs/", "/agent-setup", "/memory-lifecycle", "/transparency"],
            },
            {
                "id": "deterministic_discovery",
                "status": "pass_local",
                "evidence": ["/robots.txt", "/sitemap.xml", "/llms.txt", "/ai-manifest.json", "/.well-known/mcp.json"],
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
                "id": "privacy_and_secret_handling",
                "status": "pass_local",
                "evidence": ["one-time key return", "token hash storage", "redacted receipts"],
            },
            {
                "id": "agent_file_handoff",
                "status": "pass_local",
                "evidence": ["agent-file-handoff/Content", "agent-file-handoff/Improvement", ".uai/intake-outcome-ledger.uai"],
            },
            {
                "id": "live_deployment",
                "status": "pass_live",
                "evidence": [
                    "scripts/ftp_deploy_memoryendpoints.py",
                    "docs/reports/live-route-verification.json",
                    "FTP login directory is the deployment root; deployed with --remote-dir .",
                    "Live route verifier returned zero failures.",
                ],
            },
            {
                "id": "production_database_adapter",
                "status": "partial_pass_sqlite_live_mysql_adapter_gated",
                "evidence": ["docs/database-schema-canonical.sql", "docs/database-structure.md", "docs/long-term-memory/architecture-notes.md"],
            },
        ],
        "blockers": [],
        "gatedCapabilities": [
            {
                "id": "mysql_runtime_adapter",
                "detail": "Stdlib SQLite is available for durable database-backed storage; MySQL activation still requires an explicit no-third-party-compatible adapter path.",
                "safeNoOp": True,
            },
        ],
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
