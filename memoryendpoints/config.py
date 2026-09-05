import os
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
SITE_NAME = os.environ.get("MEMORYENDPOINTS_SITE_NAME", "Private MATM Intranet")
SITE_URL = os.environ.get("MEMORYENDPOINTS_SITE_URL", "https://matm-intranet.local")
SITE_DESCRIPTION = os.environ.get(
    "MEMORYENDPOINTS_SITE_DESCRIPTION",
    "Free private-network MATM hive for one company, local agents, and internal memory coordination.",
)
COMPANION_DOCS_URL = os.environ.get("MEMORYENDPOINTS_COMPANION_DOCS_URL", "https://multiagentmemory.com")
GITHUB_REPO_URL = os.environ.get(
    "MEMORYENDPOINTS_GITHUB_REPO_URL",
    "https://github.com/MichaelKappel/Multi-Agent-Memory",
)
DATA_DIR = Path(os.environ.get("MEMORYENDPOINTS_DATA_DIR", str(ROOT / "var")))
DOCS_DIR = Path(os.environ.get("MEMORYENDPOINTS_DOCS_DIR", str(ROOT / "docs")))
STORE_PATH = Path(os.environ.get("MEMORYENDPOINTS_STORE_PATH", str(DATA_DIR / "matm_store.json")))
SQLITE_PATH = Path(os.environ.get("MEMORYENDPOINTS_SQLITE_PATH", str(DATA_DIR / "matm_store.sqlite3")))
STORE_BACKEND = os.environ.get("MEMORYENDPOINTS_STORE_BACKEND", "sqlite").strip().lower() or "sqlite"
PUBLIC_STORAGE_BYTES = 200 * 1024 * 1024


def _strict_boolean_environment(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return bool(default), True
    normalized = str(value).strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True, True
    if normalized in ("0", "false", "no", "off"):
        return False, True
    return bool(default), False


def _strict_bounded_int_environment(name, default, minimum, maximum):
    value = os.environ.get(name)
    if value is None:
        return int(default), True
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return int(default), False
    if not minimum <= parsed <= maximum:
        return int(default), False
    return parsed, True


def commons_runtime_config():
    """Return the explicit, project-bound Commons activation contract.

    ``production`` is deliberately MySQL-only at the request boundary. The
    ``local_test`` mode exists only for isolated loopback/.local verification
    of the FileStore and SQLite parity implementations; it is never an
    implicit production fallback.
    """
    mode = str(os.environ.get("MEMORYENDPOINTS_COMMONS_MODE") or "disabled").strip().lower()
    workspace_id = str(os.environ.get("MEMORYENDPOINTS_COMMONS_WORKSPACE_ID") or "").strip()
    project_id = str(os.environ.get("MEMORYENDPOINTS_COMMONS_PROJECT_ID") or "").strip()
    site_url = os.environ.get("MEMORYENDPOINTS_SITE_URL", SITE_URL)
    site_host = (urlsplit(site_url).hostname or "").strip().lower()
    local_host = (
        site_host in ("localhost", "127.0.0.1", "::1")
        or site_host.endswith(".local")
    )
    human_approval_required, approval_valid = _strict_boolean_environment(
        "MEMORYENDPOINTS_COMMONS_HUMAN_APPROVAL_REQUIRED", False
    )
    credential_ttl, credential_ttl_valid = _strict_bounded_int_environment(
        "MEMORYENDPOINTS_COMMONS_CREDENTIAL_TTL_SECONDS",
        30 * 24 * 60 * 60,
        60 * 60,
        365 * 24 * 60 * 60,
    )
    browser_ttl, browser_ttl_valid = _strict_bounded_int_environment(
        "MEMORYENDPOINTS_COMMONS_BROWSER_SESSION_TTL_SECONDS",
        8 * 60 * 60,
        5 * 60,
        24 * 60 * 60,
    )
    enrollment_ttl, enrollment_ttl_valid = _strict_bounded_int_environment(
        "MEMORYENDPOINTS_COMMONS_ENROLLMENT_REQUEST_TTL_SECONDS",
        24 * 60 * 60,
        15 * 60,
        7 * 24 * 60 * 60,
    )
    maximum_agents, maximum_agents_valid = _strict_bounded_int_environment(
        "MEMORYENDPOINTS_COMMONS_MAXIMUM_ACTIVE_AGENTS", 1000, 2, 10000
    )
    maximum_pending, maximum_pending_valid = _strict_bounded_int_environment(
        "MEMORYENDPOINTS_COMMONS_MAXIMUM_PENDING_ENROLLMENTS", 100, 1, 1000
    )
    maximum_retained_agents, maximum_retained_agents_valid = (
        _strict_bounded_int_environment(
            "MEMORYENDPOINTS_COMMONS_MAXIMUM_RETAINED_AGENTS", 5000, 2, 50000
        )
    )
    maximum_retained_enrollments, maximum_retained_enrollments_valid = (
        _strict_bounded_int_environment(
            "MEMORYENDPOINTS_COMMONS_MAXIMUM_RETAINED_ENROLLMENTS",
            5000,
            1,
            50000,
        )
    )
    maximum_company_retained_agents, maximum_company_retained_agents_valid = (
        _strict_bounded_int_environment(
            "MEMORYENDPOINTS_COMMONS_MAXIMUM_COMPANY_RETAINED_AGENTS",
            20000,
            2,
            100000,
        )
    )
    maximum_company_retained_enrollments, maximum_company_retained_enrollments_valid = (
        _strict_bounded_int_environment(
            "MEMORYENDPOINTS_COMMONS_MAXIMUM_COMPANY_RETAINED_ENROLLMENTS",
            20000,
            1,
            100000,
        )
    )
    maximum_enrollment_tombstones, maximum_enrollment_tombstones_valid = (
        _strict_bounded_int_environment(
            "MEMORYENDPOINTS_COMMONS_MAXIMUM_ENROLLMENT_TOMBSTONES",
            50000,
            1,
            500000,
        )
    )
    maximum_company_enrollment_tombstones, maximum_company_enrollment_tombstones_valid = (
        _strict_bounded_int_environment(
            "MEMORYENDPOINTS_COMMONS_MAXIMUM_COMPANY_ENROLLMENT_TOMBSTONES",
            200000,
            1,
            1000000,
        )
    )
    maximum_retired_agent_tombstones, maximum_retired_agent_tombstones_valid = (
        _strict_bounded_int_environment(
            "MEMORYENDPOINTS_COMMONS_MAXIMUM_AGENT_TOMBSTONES",
            50000,
            2,
            500000,
        )
    )
    maximum_company_retired_agent_tombstones, maximum_company_retired_agent_tombstones_valid = (
        _strict_bounded_int_environment(
            "MEMORYENDPOINTS_COMMONS_MAXIMUM_COMPANY_AGENT_TOMBSTONES",
            200000,
            2,
            1000000,
        )
    )
    project_requests_per_minute, project_requests_valid = (
        _strict_bounded_int_environment(
            "MEMORYENDPOINTS_COMMONS_PROJECT_REQUESTS_PER_MINUTE",
            1200,
            60,
            10000,
        )
    )
    source_requests_per_minute, source_requests_valid = (
        _strict_bounded_int_environment(
            "MEMORYENDPOINTS_COMMONS_SOURCE_REQUESTS_PER_MINUTE",
            120,
            10,
            1000,
        )
    )
    maximum_live_rate_partitions, maximum_live_rate_partitions_valid = (
        _strict_bounded_int_environment(
            "MEMORYENDPOINTS_COMMONS_MAXIMUM_LIVE_RATE_PARTITIONS",
            4096,
            64,
            50000,
        )
    )
    project_enrollments_per_hour, project_enrollments_valid = (
        _strict_bounded_int_environment(
            "MEMORYENDPOINTS_COMMONS_PROJECT_ENROLLMENTS_PER_HOUR",
            60,
            2,
            1000,
        )
    )
    inactive_agent_retention, inactive_agent_retention_valid = (
        _strict_bounded_int_environment(
            "MEMORYENDPOINTS_COMMONS_INACTIVE_AGENT_RETENTION_SECONDS",
            7 * 24 * 60 * 60,
            60 * 60,
            90 * 24 * 60 * 60,
        )
    )
    terminal_enrollment_retention, terminal_enrollment_retention_valid = (
        _strict_bounded_int_environment(
            "MEMORYENDPOINTS_COMMONS_TERMINAL_ENROLLMENT_RETENTION_SECONDS",
            7 * 24 * 60 * 60,
            60 * 60,
            90 * 24 * 60 * 60,
        )
    )
    message_limit, message_limit_valid = _strict_bounded_int_environment(
        "MEMORYENDPOINTS_COMMONS_MESSAGE_CHARACTER_LIMIT", 4000, 256, 16000
    )
    request_limit, request_limit_valid = _strict_bounded_int_environment(
        "MEMORYENDPOINTS_COMMONS_REQUEST_BYTE_LIMIT", 24576, 4096, 65536
    )
    blockers = []
    if mode not in ("disabled", "local_test", "production"):
        blockers.append("commons_mode_invalid")
    if mode != "disabled" and not workspace_id:
        blockers.append("commons_workspace_not_configured")
    if mode != "disabled" and not project_id:
        blockers.append("commons_project_not_configured")
    if mode == "local_test" and not local_host:
        blockers.append("commons_local_test_origin_required")
    if not approval_valid:
        blockers.append("commons_human_approval_config_invalid")
    for valid, blocker in (
        (credential_ttl_valid, "commons_credential_ttl_config_invalid"),
        (browser_ttl_valid, "commons_browser_session_ttl_config_invalid"),
        (enrollment_ttl_valid, "commons_enrollment_ttl_config_invalid"),
        (maximum_agents_valid, "commons_agent_capacity_config_invalid"),
        (maximum_pending_valid, "commons_enrollment_capacity_config_invalid"),
        (maximum_retained_agents_valid, "commons_agent_retention_config_invalid"),
        (
            maximum_retained_enrollments_valid,
            "commons_enrollment_retention_config_invalid",
        ),
        (
            maximum_company_retained_agents_valid,
            "commons_company_agent_retention_config_invalid",
        ),
        (
            maximum_company_retained_enrollments_valid,
            "commons_company_enrollment_retention_config_invalid",
        ),
        (
            maximum_enrollment_tombstones_valid,
            "commons_enrollment_tombstone_capacity_config_invalid",
        ),
        (
            maximum_company_enrollment_tombstones_valid,
            "commons_company_enrollment_tombstone_capacity_config_invalid",
        ),
        (
            maximum_retired_agent_tombstones_valid,
            "commons_agent_tombstone_capacity_config_invalid",
        ),
        (
            maximum_company_retired_agent_tombstones_valid,
            "commons_company_agent_tombstone_capacity_config_invalid",
        ),
        (project_requests_valid, "commons_project_request_rate_config_invalid"),
        (source_requests_valid, "commons_source_request_rate_config_invalid"),
        (
            maximum_live_rate_partitions_valid,
            "commons_rate_partition_capacity_config_invalid",
        ),
        (
            project_enrollments_valid,
            "commons_project_enrollment_rate_config_invalid",
        ),
        (
            inactive_agent_retention_valid,
            "commons_inactive_agent_retention_config_invalid",
        ),
        (
            terminal_enrollment_retention_valid,
            "commons_terminal_enrollment_retention_config_invalid",
        ),
        (message_limit_valid, "commons_message_limit_config_invalid"),
        (request_limit_valid, "commons_request_limit_config_invalid"),
    ):
        if not valid:
            blockers.append(blocker)
    return {
        "schemaVersion": "memoryendpoints.commons_runtime_config.v1",
        "mode": mode,
        "enabled": mode in ("local_test", "production") and not blockers,
        "workspaceId": workspace_id,
        "projectId": project_id,
        "humanApprovalRequiredByDefault": human_approval_required,
        "credentialTtlSeconds": credential_ttl,
        "browserSessionTtlSeconds": browser_ttl,
        "enrollmentRequestTtlSeconds": enrollment_ttl,
        "maximumActiveAgents": maximum_agents,
        "maximumPendingEnrollments": maximum_pending,
        "maximumRetainedAgents": maximum_retained_agents,
        "maximumRetainedEnrollments": maximum_retained_enrollments,
        "maximumCompanyRetainedAgents": maximum_company_retained_agents,
        "maximumCompanyRetainedEnrollments": maximum_company_retained_enrollments,
        "maximumEnrollmentTombstones": maximum_enrollment_tombstones,
        "maximumCompanyEnrollmentTombstones": maximum_company_enrollment_tombstones,
        "maximumAgentTombstones": maximum_retired_agent_tombstones,
        "maximumCompanyAgentTombstones": maximum_company_retired_agent_tombstones,
        "projectRequestsPerMinute": project_requests_per_minute,
        "sourceRequestsPerMinute": source_requests_per_minute,
        "maximumLiveRatePartitions": maximum_live_rate_partitions,
        "projectEnrollmentsPerHour": project_enrollments_per_hour,
        "inactiveAgentRetentionSeconds": inactive_agent_retention,
        "terminalEnrollmentRetentionSeconds": terminal_enrollment_retention,
        "messageCharacterLimit": message_limit,
        "requestByteLimit": request_limit,
        "blockers": blockers,
        "valuesRedacted": True,
    }


def utc_now():
    import datetime

    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
