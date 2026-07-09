from . import __version__
from .config import COMPANION_DOCS_URL, GITHUB_REPO_URL, SITE_NAME, SITE_URL, utc_now
from .runtime import configured_store_backend, mysql_backend_name, store_backend_health


ROUTE_TABLE = [
    {"route": "/", "access": "public", "methods": ["GET"], "purpose": "Human home page."},
    {"route": "/docs", "access": "public", "methods": ["GET"], "purpose": "Human-readable documentation."},
    {"route": "/docs/", "access": "public", "methods": ["GET"], "purpose": "Trailing-slash documentation alias."},
    {"route": "/agent-setup", "access": "public", "methods": ["GET"], "purpose": "Agent setup instructions."},
    {"route": "/console", "access": "public", "methods": ["GET"], "purpose": "Human verification console for authenticated workspace keys."},
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
    {"route": "/api/matm/review-queue", "access": "protected", "methods": ["GET"], "purpose": "Memory review and promotion queue readback."},
    {"route": "/api/matm/review-queue/decide", "access": "protected", "methods": ["POST"], "purpose": "Idempotent memory promotion, rejection, or quarantine decision."},
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
            "fileBackedMemory": "live_local_and_first_deploy",
            "longTermMemorySource": "docs_folder_until_hosted_memory_promotion",
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
            {"level": "project", "status": "live", "storage": "docs/long-term-memory"},
            {"level": "workspace", "status": "live", "storage": "file store with memory firewall and review queue"},
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
            "idempotencyRequiredForDecision": True,
        },
        "storageBackends": [
            {"backend": "file", "status": "current" if backend == "file" else "available_local", "dependency": "python_stdlib"},
            {"backend": "sqlite", "status": "current" if backend == "sqlite" else "available_local_relational", "dependency": "python_stdlib_sqlite3"},
            {"backend": "mysql", "status": "current_verified" if mysql_active else "required_unverified", "dependency": "PyMySQL or mysql.connector"},
        ],
        "runtimeBackendHealth": health,
        "currentMessageLane": {
            "status": "live",
            "readRoute": "/api/matm/current-message",
            "ackRoute": "/api/matm/notifications/ack",
            "responseStates": ["required_response", "viewed_acknowledgement"],
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
