import re


UAIX_MEMORY_GUIDE_URL = "https://uaix.org/en-us/ai-memory/"
UAIX_PACKAGE_FORMAT_URL = "https://uaix.org/en-us/ai-memory/uaix-package-format/"
UAIX_UAI_FILES_URL = "https://uaix.org/en-us/ai-memory/uai-files/"
UAIX_WIZARD_URL = "https://uaix.org/en-us/tools/ai-memory-package-wizard/"
UAIX_MATM_MEMORYENDPOINTS_SETUP_URL = (
    "https://uaix.org/en-us/tools/ai-memory-package-wizard/"
    "#setup-MATM-MemoryEndpoints"
)
UAIX_MEMORYENDPOINTS_SETUP_URL = (
    "https://uaix.org/en-us/tools/ai-memory-package-wizard/"
    "#setup-file-handoff-MATM-MemoryEndpoints"
)

VIRTUAL_UAI_PROFILE = "uaix.accountless-browser-memory.v1"
VIRTUAL_UAI_PACKAGE_TYPE = "database_backed_uai_active_memory"
VIRTUAL_UAI_DURABLE_HOME_URL = "https://memoryendpoints.com"
MAX_UAI_RECORD_CONTENT_BYTES = 65536
MIN_UAI_EDIT_LEASE_SECONDS = 60
MAX_UAI_EDIT_LEASE_SECONDS = 1800
DEFAULT_UAI_EDIT_LEASE_SECONDS = 600

LOCAL_FORBIDDEN_UAI_FILENAMES = {
    "active-memory.uai",
    "current-state.uai",
    "project-state.uai",
    "short-term-memory.uai",
    "working-state.uai",
}

REQUIRED_UAI_FIELDS = (
    "Purpose:",
    "Verification status:",
    "Memory scope:",
    "Public-safe status:",
    "Update route:",
    "Source of truth:",
    "Next action",
    "Must not expose:",
)

UAI_ROLE_REQUIRED_FIELDS = {
    ".uai/identity.uai": (
        "Agent id:",
        "Agent name:",
        "Owner/steward:",
        "Declared profile:",
        "Namespace:",
        "Source authority:",
        "Sensitivity boundary:",
        "Actor boundary:",
    ),
    ".uai/startup-packet.uai": (
        "Required read order:",
        "First safe action:",
    ),
    ".uai/progress.uai": (
        "Completed work:",
        "Remaining work:",
        "Verification evidence:",
        "Blockers:",
    ),
    ".uai/short-term-memory.uai": (
        "Current working state:",
        "Newest accepted decisions:",
        "Active blockers:",
        "Next-read pointers:",
        "Review status:",
    ),
    ".uai/long-term-memory.uai": (
        "Stable id:",
        "Path:",
        "Label:",
        "Routing summary:",
        "Authority/source:",
        "Review status:",
        "Review evidence:",
    ),
}

VIRTUAL_UAI_RECORD_SPECS = (
    {
        "logicalPath": ".uai/startup-packet.uai",
        "role": "startup_packet",
        "purpose": "Deterministic active-record read order and first safe action for the virtual package.",
        "required": True,
        "requiredStatus": "universal_required",
        "startupOrder": 5,
    },
    {
        "logicalPath": ".uai/memory-maintenance.uai",
        "role": "memory_maintenance",
        "purpose": "Load, validate, reconcile, and maintain the active package before normal inference.",
        "required": True,
        "requiredStatus": "universal_required",
        "startupOrder": 10,
    },
    {
        "logicalPath": ".uai/identity.uai",
        "role": "identity",
        "purpose": "Stable registered-agent identity and product identity without credentials.",
        "required": True,
        "requiredStatus": "universal_required",
        "startupOrder": 20,
    },
    {
        "logicalPath": ".uai/world-context.uai",
        "role": "world_context",
        "purpose": "Current environment and external-system context needed to interpret active memory.",
        "required": True,
        "requiredStatus": "universal_required",
        "startupOrder": 30,
    },
    {
        "logicalPath": ".uai/totem.uai",
        "role": "totem",
        "purpose": "Non-negotiable positive invariants, including continuity behavior.",
        "required": True,
        "requiredStatus": "universal_required",
        "startupOrder": 40,
    },
    {
        "logicalPath": ".uai/taboo.uai",
        "role": "taboo",
        "purpose": "Hard negative boundaries and prohibited behavior.",
        "required": True,
        "requiredStatus": "universal_required",
        "startupOrder": 50,
    },
    {
        "logicalPath": ".uai/talisman.uai",
        "role": "talisman",
        "purpose": "Compact recovery cues and operational reminders.",
        "required": True,
        "requiredStatus": "universal_required",
        "startupOrder": 60,
    },
    {
        "logicalPath": ".uai/progress.uai",
        "role": "progress",
        "purpose": "Reviewed completion, remaining work, verification evidence, and current blockers.",
        "required": True,
        "requiredStatus": "universal_required",
        "startupOrder": 70,
    },
    {
        "logicalPath": ".uai/short-term-memory.uai",
        "role": "short_term_memory",
        "purpose": "Configuration-required hot working memory for an accountless browser agent with no durable local filesystem.",
        "required": True,
        "requiredStatus": "configuration_specific_required",
        "startupOrder": 80,
        "virtualOnly": True,
    },
    {
        "logicalPath": ".uai/system-profile.uai",
        "role": "system_profile",
        "purpose": "Runtime capability, browser, storage, and connector profile.",
        "required": True,
        "requiredStatus": "profile_required",
        "startupOrder": 90,
    },
    {
        "logicalPath": ".uai/receiver-brief.uai",
        "role": "receiver_brief",
        "purpose": "Bounded handoff instructions for the receiving agent instance.",
        "required": True,
        "requiredStatus": "profile_required",
        "startupOrder": 100,
    },
    {
        "logicalPath": ".uai/long-term-memory.uai",
        "role": "long_term_pointer_ledger",
        "purpose": "Pointers from active memory into protected MemoryEndpoints durable memory and knowledge routes.",
        "required": True,
        "requiredStatus": "configuration_specific_required",
        "startupOrder": 110,
    },
)

VIRTUAL_UAI_STARTUP_ORDER = tuple(
    item["logicalPath"] for item in sorted(VIRTUAL_UAI_RECORD_SPECS, key=lambda value: value["startupOrder"])
)
VIRTUAL_UAI_REQUIRED_PATHS = tuple(item["logicalPath"] for item in VIRTUAL_UAI_RECORD_SPECS if item["required"])
VIRTUAL_UAI_SPEC_BY_PATH = {item["logicalPath"]: item for item in VIRTUAL_UAI_RECORD_SPECS}

DATE_PATTERNS = (
    ("iso_date", re.compile(r"\b\d{4}-\d{2}-\d{2}\b")),
    ("iso_timestamp", re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", re.I)),
    ("compact_calendar_date", re.compile(r"\b20\d{6}\b")),
)


def normalize_uai_logical_path(value):
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return ""
    if not text.startswith(".uai/"):
        return ""
    if "//" in text or "/../" in text or text.endswith("/..") or "/./" in text:
        return ""
    if not re.fullmatch(r"\.uai/[a-z0-9][a-z0-9._/-]*\.uai", text):
        return ""
    return text


def normalize_local_uai_collaboration_path(value):
    text = normalize_uai_logical_path(value)
    if not text or text.rsplit("/", 1)[-1].lower() in LOCAL_FORBIDDEN_UAI_FILENAMES:
        return ""
    return text


def normalize_sha256(value):
    text = str(value or "").strip().lower()
    if text.startswith("sha256:"):
        text = text[7:]
    return text if re.fullmatch(r"[a-f0-9]{64}", text) else ""


def uai_record_spec(logical_path):
    return VIRTUAL_UAI_SPEC_BY_PATH.get(normalize_uai_logical_path(logical_path))


def uai_content_date_rules(content):
    text = str(content or "")
    return [name for name, pattern in DATE_PATTERNS if pattern.search(text)]


def missing_uai_content_fields(content):
    text = str(content or "")
    return [field for field in REQUIRED_UAI_FIELDS if field not in text]


def _field_value(content, field):
    match = re.search(r"(?im)^\s*%s\s*(.*?)\s*$" % re.escape(field), str(content or ""))
    return match.group(1).strip() if match else ""


def uai_content_role_errors(logical_path, content, agent_id="", agent_name=""):
    normalized_path = normalize_uai_logical_path(logical_path)
    text = str(content or "")
    missing_fields = [
        field
        for field in UAI_ROLE_REQUIRED_FIELDS.get(normalized_path, ())
        if not _field_value(text, field)
    ]
    details = {}
    if missing_fields:
        details["missingRoleFields"] = missing_fields
    if normalized_path == ".uai/startup-packet.uai":
        missing_paths = [path for path in VIRTUAL_UAI_REQUIRED_PATHS if path not in text]
        if missing_paths:
            details["missingStartupReadOrderPaths"] = missing_paths
    if normalized_path == ".uai/identity.uai" and not missing_fields:
        mismatched_fields = []
        if agent_id and _field_value(text, "Agent id:") != str(agent_id):
            mismatched_fields.append("Agent id:")
        if agent_name and _field_value(text, "Agent name:") != str(agent_name):
            mismatched_fields.append("Agent name:")
        if mismatched_fields:
            details["identityBindingMismatches"] = mismatched_fields
    if normalized_path == ".uai/long-term-memory.uai" and not missing_fields:
        if _field_value(text, "Path:").rstrip("/") != VIRTUAL_UAI_DURABLE_HOME_URL:
            details["durableHomePathRequired"] = True
    return details


def uai_collaboration_contract():
    return {
        "schemaVersion": "memoryendpoints.uai_collaboration_contract.v1",
        "mode": "local_uai_collaboration_overlay",
        "purpose": "Coordinate simultaneous local .uai edits without uploading or centralizing local active-memory contents.",
        "routes": {
            "fileHeads": "/api/matm/uai-memory/file-heads",
            "editClaims": "/api/matm/uai-memory/edit-claims",
            "heartbeat": "/api/matm/uai-memory/edit-claims/heartbeat",
            "complete": "/api/matm/uai-memory/edit-claims/complete",
            "release": "/api/matm/uai-memory/edit-claims/release",
            "projectMeetingRooms": "/api/matm/meeting-rooms",
        },
        "requiredAcquireFields": [
            "workspaceId",
            "projectId",
            "agentId",
            "logicalPath",
            "baseContentHash",
            "intentSummary",
        ],
        "requiredCompleteFields": ["workspaceId", "agentId", "claimId", "newContentHash", "completionSummary"],
        "leaseSeconds": {
            "default": DEFAULT_UAI_EDIT_LEASE_SECONDS,
            "minimum": MIN_UAI_EDIT_LEASE_SECONDS,
            "maximum": MAX_UAI_EDIT_LEASE_SECONDS,
        },
        "workflow": [
            "Read file heads and active claims for the project before editing local .uai.",
            "Hash the unchanged local file and acquire a short edit claim with that base hash.",
            "If a conflicting claim or newer head exists, do not edit; coordinate in the project meeting room.",
            "Heartbeat only while actively editing and within the bounded lease window.",
            "Complete with the new local content hash and a public-safe summary, or release without changing the head.",
            "Other agents re-read heads before touching the same local path and reconcile local content out of band.",
        ],
        "truthBoundary": {
            "localUaiContentsUploaded": False,
            "localUaiContentsStored": False,
            "automaticMerge": False,
            "automaticFileWrite": False,
            "conflictPrevention": "best_effort_claim_plus_compare_and_swap",
            "registeredAgentRequired": True,
            "realWorkspaceProjectRequired": True,
            "workspaceBearerKeyRequired": True,
            "hashesAreCoordinationMetadataNotMemoryContent": True,
            "sourceControlRemainsContentAuthority": True,
            "operatingSystemFileLock": False,
        },
        "storedFields": [
            "workspaceId",
            "projectId",
            "agentId",
            "logicalPath",
            "baseContentHash",
            "intentSummary",
            "lease metadata",
            "completionContentHash",
            "completionSummary",
            "status",
            "audit metadata",
        ],
        "forbiddenLocalFilenames": sorted(LOCAL_FORBIDDEN_UAI_FILENAMES),
        "confirmationFields": [
            "persisted",
            "visibleToSender",
            "claimAcquired",
            "canonicalClaimId",
            "canonicalHeadId",
            "headRevision",
            "claimQueryUrl",
            "headQueryUrl",
            "projectMeetingRoomQueryUrl",
        ],
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def virtual_uai_contract():
    return {
        "schemaVersion": "memoryendpoints.virtual_uai_contract.v1",
        "status": "implemented",
        "profile": VIRTUAL_UAI_PROFILE,
        "packageType": VIRTUAL_UAI_PACKAGE_TYPE,
        "durableHomePath": VIRTUAL_UAI_DURABLE_HOME_URL,
        "intendedClientClass": "accountless_browser_ai_without_durable_local_filesystem",
        "exceptionBoundary": {
            "normalRule": "Keep local .uai active memory on the client and use MemoryEndpoints for protected mid-to-long-term memory.",
            "exception": "An accountless browser AI with no durable local filesystem may keep its UAIX active-memory package in protected MemoryEndpoints database records.",
            "anonymousStorageAllowed": False,
            "workspaceBearerKeyRequired": True,
            "registeredStableAgentRequired": True,
            "rawBearerKeyStoredInPackage": False,
            "virtualLogicalPathsCreateLocalFiles": False,
        },
        "standardsPosture": {
            "model": "memoryendpoints_database_adaptation_of_typed_uai_active_memory",
            "uaixHostedImportClaimed": False,
            "uaixAutomaticSyncClaimed": False,
            "uaixCertificationClaimed": False,
            "uaixConformanceClaimed": False,
            "uaixPackageFileCreated": False,
            "closedRequiredFileStatesApplied": True,
        },
        "authentication": {
            "scheme": "bearer_workspace_key",
            "header": "Authorization: Bearer <workspace-key>",
            "agentBinding": "workspaceId + registered agentId",
            "browserStorageGuidance": "Default to an in-memory key that the user supplies per session. Persistent remember-me behavior requires explicit opt-in, encrypted browser storage, and a user-held unlock secret that is never persisted. Browser storage cannot defend against same-origin script compromise, so strict CSP, dependency integrity, and XSS prevention remain mandatory.",
            "forbiddenBrowserStorage": ["source code", "URL", "query string", "prompt", "virtual .uai record", "console log", "analytics", "plaintext localStorage", "WASM asset", "NuGet asset"],
        },
        "routes": {
            "contract": "/api/matm/uai-memory/contract",
            "packages": "/api/matm/uai-memory/packages",
            "records": "/api/matm/uai-memory/records",
            "startup": "/api/matm/uai-memory/startup",
            "durableSubmit": "/api/matm/memory-events/submit",
            "durableSearch": "/api/matm/search",
            "knowledgeDocuments": "/api/matm/knowledge-documents",
        },
        "requiredPackageCreateFields": ["workspaceId", "agentId", "clientClass", "localFilesystemAvailable"],
        "requiredRecordWriteFields": ["workspaceId", "agentId", "packageId", "logicalPath", "content"],
        "recordUpdateRequirement": "expectedRevision is required when replacing an existing logical record.",
        "postConfirmationFields": [
            "persisted",
            "visibleToSender",
            "canonicalPackageId",
            "canonicalRecordId",
            "logicalPath",
            "revision",
            "contentHash",
            "packageQueryUrl",
            "recordQueryUrl",
            "startupQueryUrl",
        ],
        "requiredContentFields": list(REQUIRED_UAI_FIELDS),
        "roleContentRequirements": {
            path: list(fields) for path, fields in UAI_ROLE_REQUIRED_FIELDS.items()
        },
        "validation": {
            "dateFreeContent": True,
            "publicSafeContentOnly": True,
            "secretLikeContentRejectedBeforePersistence": True,
            "promptInjectionMarkersRejectedBeforePersistence": True,
            "maximumContentBytes": MAX_UAI_RECORD_CONTENT_BYTES,
            "optimisticConcurrency": True,
            "immutableRevisionHistory": True,
            "oneLogicalRecordPerWrite": True,
            "bulkPackageImport": False,
            "identityBoundToRegisteredAgent": True,
            "startupPacketEnumeratesRequiredLogicalPaths": True,
        },
        "startupReadOrder": list(VIRTUAL_UAI_STARTUP_ORDER),
        "recordSpecs": [dict(item) for item in VIRTUAL_UAI_RECORD_SPECS],
        "memoryLevelMapping": {
            "hotActive": "The virtual UAIX package and startup route hold active working context for the narrow accountless-browser exception.",
            "midTerm": "Protected memory events, meeting transcripts, current messages, and sync revisions preserve reviewed operating continuity.",
            "longTerm": "Promoted memory plus protected company/workspace/project knowledge documents and external-link citations form durable recall.",
            "promotionRule": "Active records are never silently promoted into durable canonical memory; clients submit a separate public-safe durable memory event for review.",
        },
        "localCollaborationOverlay": uai_collaboration_contract(),
        "uaixReferences": [
            UAIX_MEMORY_GUIDE_URL,
            UAIX_PACKAGE_FORMAT_URL,
            UAIX_UAI_FILES_URL,
            UAIX_WIZARD_URL,
            UAIX_MATM_MEMORYENDPOINTS_SETUP_URL,
            UAIX_MEMORYENDPOINTS_SETUP_URL,
        ],
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }
