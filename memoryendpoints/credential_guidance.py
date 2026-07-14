"""Public-safe storage guidance for governed MemoryEndpoints credentials."""


COMPANY_MASTER_DEFAULT_SECRET_PATH = (
    ".local-secrets/memoryendpoints-company-master.json"
)
COMPANY_MASTER_SECRET_FIELDS = (
    "baseUrl",
    "companyId",
    "workspaceId",
    "companyMasterTokenSecret",
)


def company_master_storage_guidance():
    """Return a copy-safe contract that never contains a credential value."""

    return {
        "schemaVersion": "memoryendpoints.company_master_storage_guidance.v1",
        "issuedBy": "/api/matm/agent-setup/free-account",
        "issuedWhen": "The first company workspace is created.",
        "shownOnce": True,
        "defaultLocalSecretPath": COMPANY_MASTER_DEFAULT_SECRET_PATH,
        "pathBase": "project_root",
        "fileFormat": "json",
        "requiredFields": list(COMPANY_MASTER_SECRET_FIELDS),
        "gitignoreEntry": ".local-secrets/",
        "persistenceRequiredBeforeSetupComplete": True,
        "agentSetupHelper": "scripts/setup_memoryendpoints_company.py",
        "agentRecoveryHelper": "scripts/recover_memoryendpoints_company_master.py",
        "companyMasterDelegationRoute": "/api/matm/access/company-master-credentials",
        "topLevelAgentSchemaVersion": "memoryendpoints.top_level_agent_company_master.v1",
        "topLevelAgentSourceEnvironment": "MEMORYENDPOINTS_AGENT_TOKEN",
        "humanAdminSettingRoute": "/api/matm/human/companies/{companyId}/top-level-agent-master-credential-setting",
        "databaseSettingColumn": "matm_companies.top_level_agent_master_credential_enabled",
        "humanSaveAction": (
            "Use Save to project secret folder, select the project root, and let "
            "the page create the default JSON file before leaving setup."
        ),
        "browserWriteBoundary": (
            "A browser can create the default file only after the human grants "
            "folder access. If folder access is unavailable, the page downloads "
            "the exact JSON filename and the human must move it to the default path."
        ),
        "missingFileMeans": (
            "The credential was not persisted at the default path; guidance alone "
            "does not create a local file."
        ),
        "humanIfMissing": (
            "Ask your top-level AI agent to check the default project-relative path "
            "and run the recovery helper if it is missing. "
            "Do not paste the raw credential into chat."
        ),
        "agentIfMissing": (
            "A company-scoped top-level agent may use the recovery helper with "
            "MEMORYENDPOINTS_AGENT_TOKEN when the company setting is enabled. An "
            "existing company master may use MEMORYENDPOINTS_COMPANY_MASTER_TOKEN. "
            "Lower-scoped agents ask a top-level agent or human administrator. Do not "
            "scan outside configured paths or request, echo, or log a raw credential."
        ),
        "agentUse": (
            "Use a bound agent credential for normal agent work. Read the company "
            "master only for a company-administration operation allowed by the "
            "published agent policy."
        ),
        "localFileBoundary": (
            "Keep the file outside source control and unavailable to normal or disposable "
            "agents. Processes sharing one unrestricted OS identity cannot be separated "
            "by API policy; use distinct OS/vault identities or capability-aware secret "
            "mounts."
        ),
        "rawCredentialIncluded": False,
        "valuesRedacted": True,
    }
