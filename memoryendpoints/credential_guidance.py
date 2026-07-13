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
            "Ask your AI agent to check the default project-relative path. "
            "Do not paste the raw credential into chat."
        ),
        "agentIfMissing": (
            "Stop safely and report that autonomous setup is incomplete. Check only "
            "an explicitly configured governed secret store; do not require a human, "
            "scan outside configured paths, or request, echo, or log the raw credential."
        ),
        "agentUse": (
            "Use a bound agent credential for normal agent work. Read the company "
            "master only for a company-administration operation allowed by the "
            "published agent policy."
        ),
        "localFileBoundary": (
            "Keep the file outside source control, restrict it to the owner and "
            "explicitly authorized local agents, and prefer a managed secret store "
            "when one is available."
        ),
        "rawCredentialIncluded": False,
        "valuesRedacted": True,
    }
