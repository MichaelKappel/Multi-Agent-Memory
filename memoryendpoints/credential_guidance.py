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
        "humanIfMissing": (
            "Ask your AI agent to check the default project-relative path. "
            "Do not paste the raw credential into chat."
        ),
        "agentIfMissing": (
            "Stop safely and tell the human that the default file was not found. "
            "Ask which governed secret store was used; do not scan outside the "
            "project or request, echo, or log the raw credential."
        ),
        "agentUse": (
            "Use a bound agent credential for normal agent work. Read the company "
            "master only for an explicit owner-authorized company operation."
        ),
        "localFileBoundary": (
            "Keep the file outside source control, restrict it to the owner and "
            "explicitly authorized local agents, and prefer a managed secret store "
            "when one is available."
        ),
        "rawCredentialIncluded": False,
        "valuesRedacted": True,
    }
