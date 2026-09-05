"""WSGI routing for the canonical, project-scoped MATM Commons contract."""

import hashlib
import json
import re
import secrets
from urllib.parse import parse_qs

from .commons import (
    COMMONS_ACKNOWLEDGEMENT_SCHEMA,
    COMMONS_AGENT_SCHEMA,
    COMMONS_AGENT_PAGE_SCHEMA,
    COMMONS_BROWSER_SESSION_SCHEMA,
    COMMONS_CAPABILITIES_SCHEMA,
    COMMONS_CORRECTION_SCHEMA,
    COMMONS_CREDENTIAL_REVOCATION_SCHEMA,
    COMMONS_CREDENTIAL_ROTATION_SCHEMA,
    COMMONS_ENROLLMENT_SCHEMA,
    COMMONS_ENROLLMENT_DECISION_SCHEMA,
    COMMONS_ENROLLMENT_REQUEST_PAGE_SCHEMA,
    COMMONS_ENROLLMENT_REQUEST_SCHEMA,
    COMMONS_MEMBERSHIP_SCHEMA,
    COMMONS_MESSAGE_PAGE_SCHEMA,
    COMMONS_MESSAGE_REVISION_SCHEMA,
    COMMONS_MESSAGE_SCHEMA,
    COMMONS_POLICY_SCHEMA,
    COMMONS_PRINCIPAL_SCHEMA,
    COMMONS_RECEIPT_SCHEMA,
    COMMONS_ROOM_PAGE_SCHEMA,
    COMMONS_ROOM_SCHEMA,
    COMMONS_WITHDRAWAL_SCHEMA,
    CommonsContractError,
    bounded_page_limit,
    normalize_agent_name,
    normalize_display_name,
    normalize_public_profile,
    request_digest,
    validate_idempotency_key,
    validate_message_content,
)
from .commons_storage import CommonsRepository
from .config import commons_runtime_config, utc_now
from .http import json_response
from .runtime import configured_store_backend
from .storage import credential_system_available


_AGENT_ROUTE = re.compile(r"^/api/matm/commons/agents/([^/]+)$")
_ROOM_ROUTE = re.compile(r"^/api/matm/commons/rooms/([^/]+)$")
_ROOM_MESSAGES_ROUTE = re.compile(
    r"^/api/matm/commons/rooms/([^/]+)/messages$"
)
_ROOM_MEMBERSHIP_ROUTE = re.compile(
    r"^/api/matm/commons/rooms/([^/]+)/(join|leave)$"
)
_MESSAGE_ROUTE = re.compile(r"^/api/matm/commons/messages/([^/]+)$")
_MESSAGE_REVISION_ROUTE = re.compile(
    r"^/api/matm/commons/messages/(commonsmessage-[0-9a-f]{24})/revisions/([1-9][0-9]*)$"
)
_MESSAGE_ACTION_ROUTE = re.compile(
    r"^/api/matm/commons/messages/([^/]+)/(corrections|withdrawal|acknowledgements)$"
)
_ENROLLMENT_REQUEST_ROUTE = re.compile(
    r"^/api/matm/commons/enrollment-requests/(commonsenrollment-[0-9a-f]{24})$"
)
_ENROLLMENT_DECISION_ROUTE = re.compile(
    r"^/api/matm/commons/enrollment-requests/(commonsenrollment-[0-9a-f]{24})/(approval|denial)$"
)
_PROTECTED_ENROLLMENT_REQUEST_ROUTE = re.compile(
    r"^/api/matm/commons/enrollment-requests/[^/]+$"
)
_PROTECTED_ENROLLMENT_DECISION_ROUTE = re.compile(
    r"^/api/matm/commons/enrollment-requests/[^/]+/(approval|denial)$"
)
_COMMONS_MESSAGE_ID = re.compile(r"^commonsmessage-[0-9a-f]{24}$")
_COMMONS_REVISION_ID = re.compile(r"^commonsrevision-[0-9a-f]{24}$")
_COMMONS_WITHDRAWAL_ID = re.compile(r"^commonswithdrawal-[0-9a-f]{24}$")
_COMMONS_QUERY_BYTE_LIMIT = 2048
_COMMONS_QUERY_FIELD_LIMIT = 4
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")


def _commons_request_requires_auth(path, method):
    """Classify only recognized method/path pairs before parsing input."""
    if method == "GET":
        return bool(
            path
            in {
                "/api/matm/commons/enrollments/current",
                "/api/matm/commons/enrollment-requests",
                "/api/matm/commons/policy",
                "/api/matm/commons/me",
                "/api/matm/commons/browser-sessions/current",
            }
            or _PROTECTED_ENROLLMENT_REQUEST_ROUTE.fullmatch(path)
        )
    if method != "POST":
        return False
    return bool(
        path
        in {
            "/api/matm/commons/policy",
            "/api/matm/commons/browser-sessions",
            "/api/matm/commons/browser-sessions/revoke",
            "/api/matm/commons/credentials/rotation",
            "/api/matm/commons/credentials/revoke",
        }
        or _PROTECTED_ENROLLMENT_DECISION_ROUTE.fullmatch(path)
        or _ROOM_MEMBERSHIP_ROUTE.fullmatch(path)
        or _ROOM_MESSAGES_ROUTE.fullmatch(path)
        or _MESSAGE_ACTION_ROUTE.fullmatch(path)
    )


def _exact_revision(value, allow_zero=False, maximum=2147483647):
    minimum = 0 if allow_zero else 1
    if type(value) is not int or not minimum <= value <= maximum:
        raise CommonsContractError("revision_invalid")
    return value


def _exact_optional_id(value, pattern, field_name):
    if value is None:
        return None
    if type(value) is not str or not pattern.fullmatch(value):
        raise CommonsContractError(
            "revision_invalid", detail="%s is not a valid Commons identifier." % field_name
        )
    return value


def _request_id(path, method, idempotency_key=None):
    if idempotency_key:
        material = "commons-request-v1\n%s\n%s\n%s" % (
            method,
            path,
            hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest(),
        )
        return "commonsreq-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return "commonsreq-" + secrets.token_hex(12)


def _headers(request_id, extra=None):
    return [
        ("X-Request-Id", request_id),
        ("Referrer-Policy", "no-referrer"),
        ("X-Frame-Options", "DENY"),
    ] + list(extra or [])


def _ok(start_response, payload, request_id, status="200 OK", headers=None):
    body = {
        "ok": True,
        "requestId": request_id,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }
    body.update(payload or {})
    return json_response(
        start_response, body, status, _headers(request_id, headers)
    )


def _error(start_response, exc, request_id, headers=None):
    status = getattr(exc, "status", "422 Unprocessable Entity")
    code = getattr(exc, "code", "commons_request_rejected")
    detail = getattr(exc, "detail", "The Commons operation was safely rejected.")
    body = {
        "ok": False,
        "requestId": request_id,
        "safeNoOp": True,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
        "idempotencyKeyExposed": False,
        "error": {
            "code": code,
            "title": "Commons request rejected",
            "detail": detail,
            "safeNoOp": True,
            "valuesRedacted": True,
        },
    }
    auth_header = []
    if status.startswith("401"):
        auth_header = [
            (
                "WWW-Authenticate",
                'Bearer realm="MATM Commons", CommonsSession realm="MATM Commons"',
            )
        ]
    return json_response(
        start_response,
        body,
        status,
        _headers(request_id, auth_header + list(headers or [])),
    )


def _body(environ, settings, allowed_fields, schema_version):
    content_type = str(environ.get("CONTENT_TYPE") or "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise CommonsContractError(
            "content_type_invalid",
            "415 Unsupported Media Type",
            "Commons writes require Content-Type: application/json.",
        )
    limit = int(settings.get("requestByteLimit") or 24576)
    raw_length = environ.get("CONTENT_LENGTH")
    if not isinstance(raw_length, str) or not re.fullmatch(r"[0-9]+", raw_length):
        raise CommonsContractError("content_length_invalid", "400 Bad Request")
    if str(environ.get("HTTP_TRANSFER_ENCODING") or "").strip():
        raise CommonsContractError("content_length_invalid", "400 Bad Request")
    try:
        content_length = int(raw_length)
    except (TypeError, ValueError):
        raise CommonsContractError("content_length_invalid", "400 Bad Request")
    if content_length > limit:
        raise CommonsContractError("request_too_large", "413 Payload Too Large")
    stream = environ.get("wsgi.input")
    chunks = []
    remaining = content_length
    while remaining:
        try:
            chunk = stream.read(remaining)
        except (AttributeError, OSError, TypeError, ValueError):
            raise CommonsContractError("content_length_invalid", "400 Bad Request")
        if type(chunk) is not bytes or not chunk or len(chunk) > remaining:
            raise CommonsContractError("content_length_invalid", "400 Bad Request")
        chunks.append(chunk)
        remaining -= len(chunk)
    raw = b"".join(chunks)
    try:
        decoded = raw.decode("utf-8", errors="strict")
        value = json.loads(decoded)
    except (UnicodeDecodeError, ValueError):
        raise CommonsContractError(
            "json_invalid", "400 Bad Request", "The request body must be valid UTF-8 JSON."
        )
    if not isinstance(value, dict):
        raise CommonsContractError("json_object_required", "400 Bad Request")
    if set(value) - set(allowed_fields):
        raise CommonsContractError(
            "request_fields_invalid",
            detail="The request contains unsupported or actor-controlled fields.",
        )
    if value.get("schemaVersion") != schema_version:
        raise CommonsContractError(
            "schema_version_invalid",
            detail="schemaVersion must exactly match the published Commons operation schema.",
        )
    return value


def _idempotency(environ, forbidden=False):
    value = str(environ.get("HTTP_IDEMPOTENCY_KEY") or "")
    if forbidden:
        if value:
            raise CommonsContractError(
                "idempotency_key_forbidden",
                detail="This one-time-secret response forbids Idempotency-Key.",
            )
        return ""
    return validate_idempotency_key(value)


def _query(environ, allowed):
    raw = environ.get("QUERY_STRING") or ""
    if type(raw) is not str:
        raise CommonsContractError("query_invalid", "400 Bad Request")
    try:
        raw_bytes = raw.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        raise CommonsContractError(
            "query_invalid",
            "400 Bad Request",
            "The query must use strict percent-encoded UTF-8.",
        )
    if (
        len(raw_bytes) > _COMMONS_QUERY_BYTE_LIMIT
        or any(byte < 0x20 or byte == 0x7F for byte in raw_bytes)
        or _INVALID_PERCENT_ESCAPE.search(raw)
    ):
        raise CommonsContractError("query_invalid", "400 Bad Request")
    try:
        parsed = parse_qs(
            raw,
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
            max_num_fields=_COMMONS_QUERY_FIELD_LIMIT,
        )
    except (UnicodeDecodeError, ValueError):
        raise CommonsContractError("query_invalid", "400 Bad Request")
    if set(parsed) - set(allowed) or any(len(values) != 1 for values in parsed.values()):
        raise CommonsContractError(
            "query_invalid",
            "400 Bad Request",
            "Unsupported or repeated query parameter.",
        )
    return {key: values[0] for key, values in parsed.items()}


def _allowed_query_fields(path, method):
    if method != "GET":
        return set()
    if path in (
        "/api/matm/commons/agents",
        "/api/matm/commons/enrollment-requests",
    ) or _ROOM_MESSAGES_ROUTE.fullmatch(path):
        return {"after", "limit"}
    return set()


def _availability(settings, store_factory):
    blockers = list(settings.get("blockers") or [])
    backend = configured_store_backend()
    if settings.get("mode") == "production" and backend not in ("mysql", "mariadb"):
        blockers.append("commons_mysql_required")
    if settings.get("mode") == "local_test" and backend not in (
        "file",
        "filestore",
        "json",
        "sqlite",
        "mysql",
        "mariadb",
    ):
        blockers.append("commons_test_backend_invalid")
    if settings.get("mode") != "disabled" and not credential_system_available():
        blockers.append("commons_credential_system_unavailable")
    store = None
    repository = None
    if settings.get("mode") != "disabled" and not blockers:
        try:
            store = store_factory()
            repository = CommonsRepository(store, settings)
            if not repository.scope_available():
                blockers.append("commons_scope_unavailable")
        except Exception:
            blockers.append("commons_storage_unavailable")
            store = None
            repository = None
    return backend, sorted(set(blockers)), store, repository


def _capabilities(settings, backend, blockers, repository):
    policy = None
    if repository and not blockers:
        try:
            policy = repository.policy()
        except Exception:
            blockers = sorted(set(list(blockers) + ["commons_policy_unavailable"]))
    return {
        "schemaVersion": COMMONS_CAPABILITIES_SCHEMA,
        "available": bool(
            settings.get("mode") in ("local_test", "production") and not blockers
        ),
        "mode": settings.get("mode"),
        "scope": {
            "workspaceId": settings.get("workspaceId") or None,
            "projectId": settings.get("projectId") or None,
            "projectScoped": True,
        },
        "backend": backend,
        "productionStorageRequired": "mysql",
        "enrollmentPolicy": policy,
        "auth": {
            "agent": "Bearer",
            "browserSession": "CommonsSession",
            "browserSessionAuthority": "commons_only",
            "anonymousReads": True,
            "anonymousEnrollmentSupported": True,
            "autonomousEnrollmentCurrentlyAllowed": bool(
                policy and not policy.get("humanApprovalRequired")
            ),
            "enrollmentRequestsCurrentlyAccepted": bool(
                policy and policy.get("humanApprovalRequired")
            ),
            "humanApprovalRequired": bool(
                policy and policy.get("humanApprovalRequired")
            ),
        },
        "routes": {
            "capabilities": "/api/matm/commons/capabilities",
            "enrollments": "/api/matm/commons/enrollments",
            "enrollmentCurrent": "/api/matm/commons/enrollments/current",
            "enrollmentRequests": "/api/matm/commons/enrollment-requests",
            "enrollmentRequest": "/api/matm/commons/enrollment-requests/{enrollmentRequestId}",
            "enrollmentApprove": "/api/matm/commons/enrollment-requests/{enrollmentRequestId}/approval",
            "enrollmentDeny": "/api/matm/commons/enrollment-requests/{enrollmentRequestId}/denial",
            "policy": "/api/matm/commons/policy",
            "me": "/api/matm/commons/me",
            "agents": "/api/matm/commons/agents",
            "rooms": "/api/matm/commons/rooms",
            "room": "/api/matm/commons/rooms/{roomId}",
            "roomMessages": "/api/matm/commons/rooms/{roomId}/messages",
            "message": "/api/matm/commons/messages/{messageId}",
            "messageRevision": "/api/matm/commons/messages/{messageId}/revisions/{revisionNumber}",
            "join": "/api/matm/commons/rooms/{roomId}/join",
            "leave": "/api/matm/commons/rooms/{roomId}/leave",
            "correct": "/api/matm/commons/messages/{messageId}/corrections",
            "withdraw": "/api/matm/commons/messages/{messageId}/withdrawal",
            "acknowledge": "/api/matm/commons/messages/{messageId}/acknowledgements",
            "browserSessionCreate": "/api/matm/commons/browser-sessions",
            "browserSessionCurrent": "/api/matm/commons/browser-sessions/current",
            "browserSessionRevoke": "/api/matm/commons/browser-sessions/revoke",
            "credentialRotate": "/api/matm/commons/credentials/rotation",
            "credentialRevoke": "/api/matm/commons/credentials/revoke",
        },
        "limits": {
            "requestBytes": int(settings.get("requestByteLimit") or 24576),
            "messageCharacters": int(settings.get("messageCharacterLimit") or 4000),
            "pageMaximum": 100,
            "correctionRevisionsMaximum": 32,
            "browserSessionTtlSeconds": int(
                settings.get("browserSessionTtlSeconds") or 8 * 60 * 60
            ),
            "activeAgentsMaximum": int(
                settings.get("maximumActiveAgents") or 1000
            ),
            "retainedAgentsLifetimeMaximum": int(
                settings.get("maximumRetainedAgents") or 5000
            ),
            "pendingEnrollmentsMaximum": int(
                settings.get("maximumPendingEnrollments") or 100
            ),
            "retainedEnrollmentsLifetimeMaximum": int(
                settings.get("maximumRetainedEnrollments") or 5000
            ),
            "companyRetainedAgentsLifetimeMaximum": int(
                settings.get("maximumCompanyRetainedAgents") or 20000
            ),
            "companyRetainedEnrollmentsLifetimeMaximum": int(
                settings.get("maximumCompanyRetainedEnrollments") or 20000
            ),
            "projectIrreversibleEnrollmentTombstonesMaximum": int(
                settings.get("maximumEnrollmentTombstones") or 50000
            ),
            "companyIrreversibleEnrollmentTombstonesMaximum": int(
                settings.get("maximumCompanyEnrollmentTombstones") or 200000
            ),
            "projectIrreversibleAgentTombstonesMaximum": int(
                settings.get("maximumAgentTombstones") or 50000
            ),
            "companyIrreversibleAgentTombstonesMaximum": int(
                settings.get("maximumCompanyAgentTombstones") or 200000
            ),
            "projectRequestsPerMinute": int(
                settings.get("projectRequestsPerMinute") or 1200
            ),
            "sourceRequestsPerMinute": int(
                settings.get("sourceRequestsPerMinute") or 120
            ),
            "maximumLiveAnonymousRatePartitions": int(
                settings.get("maximumLiveRatePartitions") or 4096
            ),
            "projectEnrollmentsPerHour": int(
                settings.get("projectEnrollmentsPerHour") or 60
            ),
            "anonymousRatePartitionCardinalityBoundedByProjectBudget": True,
            "identityNameReuse": "never_after_activation",
            "terminalEnrollmentTombstones": "irreversible_lifetime_quota_bounded",
            "terminalEnrollmentProfileRecoverySeconds": int(
                settings.get("terminalEnrollmentRetentionSeconds")
                or 7 * 24 * 60 * 60
            ),
            "inactiveNonparticipatingAgentRecoverySeconds": int(
                settings.get("inactiveAgentRetentionSeconds") or 7 * 24 * 60 * 60
            ),
            "automaticContentFreeRetirementAudited": True,
        },
        "credentialLifecycle": {
            "automaticExpiry": True,
            "rotationSupported": True,
            "selfRevocationSupported": True,
            "browserSessionExchangeSupported": True,
        },
        "blockers": blockers,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _authorization(
    environ,
    store,
    repository,
    allow_revoked_session=False,
    allow_revoked_agent=False,
):
    header = str(environ.get("HTTP_AUTHORIZATION") or "").strip()
    parts = header.split(" ", 1)
    if len(parts) != 2 or not parts[1] or parts[1] != parts[1].strip():
        return None, None
    scheme, secret = parts
    if scheme.lower() == "bearer":
        if allow_revoked_agent:
            auth = repository.authenticate_agent_credential(
                secret, allow_revoked=True
            )
        else:
            auth = store.authenticate(secret, repository.workspace_id)
        return "bearer", auth
    if scheme.lower() == "commonssession":
        return "commons_session", repository.authenticate_browser_session(
            secret, allow_revoked=allow_revoked_session
        )
    return None, None


def _enrollment_authorization(environ, repository):
    header = str(environ.get("HTTP_AUTHORIZATION") or "").strip()
    parts = header.split(" ", 1)
    if (
        len(parts) != 2
        or parts[0].lower() != "commonsenrollment"
        or not parts[1]
        or parts[1] != parts[1].strip()
    ):
        return None
    return repository.authenticate_enrollment_candidate(parts[1])


def _require_agent(environ, store, repository):
    _scheme, auth = _authorization(environ, store, repository)
    if not auth:
        raise CommonsContractError("auth_required", "401 Unauthorized")
    repository.assert_active_agent(auth)
    return auth


def _optional_agent(environ, store, repository):
    header = str(environ.get("HTTP_AUTHORIZATION") or "").strip()
    if not header:
        return None
    _scheme, auth = _authorization(environ, store, repository)
    if not auth:
        raise CommonsContractError("auth_invalid", "401 Unauthorized")
    repository.assert_active_agent(auth)
    return auth


def _receipt(operation, resource_kind, resource_id, actor_id, key):
    material = "\n".join(
        (operation, resource_kind, str(resource_id or ""), str(actor_id or ""), hashlib.sha256(key.encode("utf-8")).hexdigest())
    )
    return {
        "schemaVersion": COMMONS_RECEIPT_SCHEMA,
        "receiptId": "commonsreceipt-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24],
        "operation": operation,
        "resourceKind": resource_kind,
        "resourceId": resource_id,
        "actorAgentId": actor_id,
        "status": "accepted",
        "idempotencyKeyExposed": False,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _rate(store, bucket, partition, limit, window=60):
    result = store.consume_connector_rate_limit(bucket, partition, limit, window)
    if not result.get("allowed"):
        error = CommonsContractError(
            "rate_limit_exceeded", "429 Too Many Requests", "The Commons request rate limit was reached."
        )
        error.retry_after = int(result.get("retryAfterSeconds") or 1)
        raise error


def _layered_rate(
    store,
    source_bucket,
    source_partition,
    source_limit,
    source_window,
    project_bucket,
    project_partition,
    project_limit,
    project_window,
    maximum_live_partitions,
):
    result = store.consume_commons_layered_rate_limit(
        source_bucket,
        source_partition,
        source_limit,
        source_window,
        project_bucket,
        project_partition,
        project_limit,
        project_window,
        maximum_live_partitions,
    )
    if not result.get("allowed"):
        error = CommonsContractError(
            "rate_limit_exceeded",
            "429 Too Many Requests",
            "The Commons request rate limit was reached.",
        )
        error.retry_after = int(result.get("retryAfterSeconds") or 1)
        raise error


def route_commons(environ, start_response, path, store_factory):
    """Return a Commons response or ``None`` when ``path`` is not ours."""
    if not path.startswith("/api/matm/commons"):
        return None
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    initial_request_id = _request_id(path, method)
    if (
        _commons_request_requires_auth(path, method)
        and not str(environ.get("HTTP_AUTHORIZATION") or "").strip()
    ):
        return _error(
            start_response,
            CommonsContractError("auth_required", "401 Unauthorized"),
            initial_request_id,
        )
    try:
        query = _query(environ, _allowed_query_fields(path, method))
    except CommonsContractError as exc:
        return _error(start_response, exc, initial_request_id)
    settings = commons_runtime_config()
    backend, blockers, store, repository = _availability(settings, store_factory)
    if path == "/api/matm/commons/capabilities":
        if method != "GET":
            return _error(
                start_response,
                CommonsContractError("method_not_allowed", "405 Method Not Allowed"),
                initial_request_id,
            )
        try:
            if store:
                _layered_rate(
                    store,
                    "commonsSourceRequest",
                    "%s|%s"
                    % (
                        settings.get("projectId") or "unconfigured",
                        environ.get("REMOTE_ADDR") or "unknown",
                    ),
                    settings.get("sourceRequestsPerMinute") or 120,
                    60,
                    "commonsProjectRequest",
                    settings.get("projectId") or "unconfigured",
                    settings.get("projectRequestsPerMinute") or 1200,
                    60,
                    settings.get("maximumLiveRatePartitions") or 4096,
                )
            return _ok(
                start_response,
                _capabilities(settings, backend, blockers, repository),
                initial_request_id,
            )
        except CommonsContractError as exc:
            headers = []
            if getattr(exc, "retry_after", None):
                headers.append(("Retry-After", str(exc.retry_after)))
            return _error(start_response, exc, initial_request_id, headers)
    if blockers or not repository or not store:
        return _error(
            start_response,
            CommonsContractError(
                "commons_unavailable",
                "503 Service Unavailable",
                "The canonical Commons capability is not available for this configured scope.",
            ),
            initial_request_id,
        )

    try:
        source_partition = "%s|%s" % (
            repository.project_id,
            environ.get("REMOTE_ADDR") or "unknown",
        )
        if method == "POST" and path == "/api/matm/commons/enrollments":
            _layered_rate(
                store,
                "commonsEnrollment",
                source_partition,
                10,
                600,
                "commonsProjectEnrollment",
                repository.project_id,
                settings.get("projectEnrollmentsPerHour") or 60,
                60 * 60,
                settings.get("maximumLiveRatePartitions") or 4096,
            )
            _rate(
                store,
                "commonsProjectRequest",
                repository.project_id,
                settings.get("projectRequestsPerMinute") or 1200,
            )
        else:
            _layered_rate(
                store,
                "commonsSourceRequest",
                source_partition,
                settings.get("sourceRequestsPerMinute") or 120,
                60,
                "commonsProjectRequest",
                repository.project_id,
                settings.get("projectRequestsPerMinute") or 1200,
                60,
                settings.get("maximumLiveRatePartitions") or 4096,
            )
        if method == "GET":
            if path == "/api/matm/commons/enrollments/current":
                auth = _enrollment_authorization(environ, repository)
                if not auth:
                    raise CommonsContractError(
                        "commons_enrollment_candidate_invalid", "401 Unauthorized"
                    )
                enrollment = repository.current_enrollment(auth)
                return _ok(
                    start_response,
                    {
                        "schemaVersion": COMMONS_ENROLLMENT_REQUEST_SCHEMA,
                        "enrollment": enrollment,
                    },
                    initial_request_id,
                )
            if path == "/api/matm/commons/browser-sessions/current":
                scheme, auth = _authorization(environ, store, repository)
                if scheme != "commons_session" or not auth:
                    raise CommonsContractError("auth_required", "401 Unauthorized")
                agent_id = repository.assert_active_agent(auth)
                session = repository.current_browser_session(auth)
                return _ok(
                    start_response,
                    {
                        "schemaVersion": COMMONS_BROWSER_SESSION_SCHEMA,
                        "browserSession": session,
                        "principal": {
                            "agentId": agent_id,
                            "workspaceId": repository.workspace_id,
                            "projectId": repository.project_id,
                            "scopeType": "project",
                            "scopeId": repository.project_id,
                            "authority": "commons_only",
                        },
                    },
                    initial_request_id,
                )
            if path == "/api/matm/commons/me":
                _scheme, auth = _authorization(environ, store, repository)
                if not auth:
                    raise CommonsContractError("auth_required", "401 Unauthorized")
                result = repository.me(auth)
                return _ok(
                    start_response,
                    dict({"schemaVersion": COMMONS_PRINCIPAL_SCHEMA}, **result),
                    initial_request_id,
                )
            if path == "/api/matm/commons/policy":
                scheme, auth = _authorization(environ, store, repository)
                if scheme != "bearer" or not auth or auth.get("credentialType") != "company_master":
                    raise CommonsContractError("company_master_required", "403 Forbidden")
                return _ok(
                    start_response,
                    {"schemaVersion": COMMONS_POLICY_SCHEMA, "policy": repository.policy()},
                    initial_request_id,
                )
            if path == "/api/matm/commons/enrollment-requests":
                scheme, auth = _authorization(environ, store, repository)
                if scheme != "bearer" or not auth or auth.get("credentialType") != "company_master":
                    raise CommonsContractError("company_master_required", "403 Forbidden")
                page = repository.enrollment_requests(
                    auth,
                    query.get("after"),
                    bounded_page_limit(query.get("limit")),
                )
                page["schemaVersion"] = COMMONS_ENROLLMENT_REQUEST_PAGE_SCHEMA
                return _ok(start_response, page, initial_request_id)
            match = _ENROLLMENT_REQUEST_ROUTE.fullmatch(path)
            if match:
                scheme, auth = _authorization(environ, store, repository)
                if scheme != "bearer" or not auth or auth.get("credentialType") != "company_master":
                    raise CommonsContractError("company_master_required", "403 Forbidden")
                enrollment = repository.enrollment_request(auth, match.group(1))
                return _ok(
                    start_response,
                    {
                        "schemaVersion": COMMONS_ENROLLMENT_REQUEST_SCHEMA,
                        "enrollmentRequest": enrollment,
                    },
                    initial_request_id,
                )
            auth = _optional_agent(environ, store, repository)
            viewer = (auth or {}).get("agentId")
            if path == "/api/matm/commons/agents":
                page = repository.agents(
                    query.get("after"), bounded_page_limit(query.get("limit"))
                )
                page["schemaVersion"] = COMMONS_AGENT_PAGE_SCHEMA
                return _ok(start_response, page, initial_request_id)
            match = _AGENT_ROUTE.fullmatch(path)
            if match:
                agent = repository.agent_profile(match.group(1), public_only=True)
                if not agent:
                    raise CommonsContractError("agent_not_found", "404 Not Found")
                return _ok(start_response, {"schemaVersion": COMMONS_AGENT_SCHEMA, "agent": agent}, initial_request_id)
            if path == "/api/matm/commons/rooms":
                items = repository.rooms(viewer)
                return _ok(start_response, {"schemaVersion": COMMONS_ROOM_PAGE_SCHEMA, "items": items, "count": len(items), "hasMore": False, "nextCursor": None, "order": "roomId_ascending"}, initial_request_id)
            match = _ROOM_ROUTE.fullmatch(path)
            if match:
                room = repository.room(match.group(1), viewer)
                if not room:
                    raise CommonsContractError("room_not_found", "404 Not Found")
                return _ok(start_response, {"schemaVersion": COMMONS_ROOM_SCHEMA, "room": room}, initial_request_id)
            match = _ROOM_MESSAGES_ROUTE.fullmatch(path)
            if match:
                page = repository.list_messages(
                    match.group(1),
                    query.get("after"),
                    bounded_page_limit(query.get("limit")),
                    viewer,
                )
                page.update({"schemaVersion": COMMONS_MESSAGE_PAGE_SCHEMA, "roomId": match.group(1)})
                return _ok(start_response, page, initial_request_id)
            match = _MESSAGE_ROUTE.fullmatch(path)
            if match:
                message = repository.message(match.group(1), viewer)
                if not message:
                    raise CommonsContractError("message_not_found", "404 Not Found")
                return _ok(start_response, {"schemaVersion": COMMONS_MESSAGE_SCHEMA, "message": message}, initial_request_id)
            match = _MESSAGE_REVISION_ROUTE.fullmatch(path)
            if match:
                revision_number = _exact_revision(int(match.group(2)), maximum=32)
                revision = repository.message_revision(match.group(1), revision_number)
                if not revision:
                    raise CommonsContractError(
                        "message_revision_not_found", "404 Not Found"
                    )
                return _ok(
                    start_response,
                    {
                        "schemaVersion": COMMONS_MESSAGE_REVISION_SCHEMA,
                        "revision": revision,
                    },
                    initial_request_id,
                )
            raise CommonsContractError("not_found", "404 Not Found")

        if method != "POST":
            raise CommonsContractError("method_not_allowed", "405 Method Not Allowed")

        if path == "/api/matm/commons/browser-sessions":
            key = _idempotency(environ)
            request_id = _request_id(path, method, key)
            body = _body(
                environ,
                settings,
                {"schemaVersion", "candidateBrowserSessionSecret"},
                COMMONS_BROWSER_SESSION_SCHEMA,
            )
            scheme, auth = _authorization(environ, store, repository)
            if scheme != "bearer" or not auth:
                raise CommonsContractError("auth_required", "401 Unauthorized")
            repository.assert_active_agent(auth)
            _rate(store, "commonsBrowserSession", auth.get("agentId"), 20)
            result, replay = repository.create_browser_session(
                auth,
                body.get("candidateBrowserSessionSecret"),
                key,
                request_digest(body),
            )
            return _ok(
                start_response,
                {
                    "schemaVersion": COMMONS_BROWSER_SESSION_SCHEMA,
                    "browserSession": result["browserSession"],
                    "credentialAccepted": bool(result.get("credentialAccepted")),
                    "credentialCustody": "client_generated_and_retained",
                    "credentialReturnedOnce": False,
                    "rawCredentialPersisted": False,
                    "idempotentReplay": replay,
                    "idempotencyKeyExposed": False,
                },
                request_id,
                "200 OK" if replay else "201 Created",
            )

        match = _ENROLLMENT_DECISION_ROUTE.fullmatch(path)
        if match:
            key = _idempotency(environ)
            request_id = _request_id(path, method, key)
            scheme, auth = _authorization(environ, store, repository)
            if scheme != "bearer" or not auth or auth.get("credentialType") != "company_master":
                raise CommonsContractError("company_master_required", "403 Forbidden")
            _rate(store, "commonsMutation", auth.get("masterKeyId"), 60)
            body = _body(
                environ,
                settings,
                {"schemaVersion", "expectedRevision"},
                COMMONS_ENROLLMENT_DECISION_SCHEMA,
            )
            expected_revision = _exact_revision(body.get("expectedRevision"))
            decision = "approved" if match.group(2) == "approval" else "denied"
            enrollment, replay = repository.decide_enrollment(
                auth,
                match.group(1),
                decision,
                expected_revision,
                key,
                request_digest(body),
            )
            return _ok(
                start_response,
                {
                    "schemaVersion": COMMONS_ENROLLMENT_DECISION_SCHEMA,
                    "enrollmentRequest": enrollment,
                    "receipt": _receipt(
                        "enrollment-" + decision,
                        "enrollment_request",
                        match.group(1),
                        auth.get("masterKeyId"),
                        key,
                    ),
                    "idempotentReplay": replay,
                    "idempotencyKeyExposed": False,
                },
                request_id,
            )

        key = _idempotency(environ)
        request_id = _request_id(path, method, key)
        if path == "/api/matm/commons/credentials/rotation":
            body = _body(
                environ,
                settings,
                {"schemaVersion", "candidateTokenSecret"},
                COMMONS_CREDENTIAL_ROTATION_SCHEMA,
            )
            scheme, auth = _authorization(
                environ, store, repository, allow_revoked_agent=True
            )
            if scheme != "bearer" or not auth:
                raise CommonsContractError("auth_required", "401 Unauthorized")
            _rate(store, "commonsMutation", auth.get("agentId"), 60)
            credential, replay = repository.rotate_credential(
                auth,
                body.get("candidateTokenSecret"),
                key,
                request_digest(body),
            )
            return _ok(
                start_response,
                {
                    "schemaVersion": COMMONS_CREDENTIAL_ROTATION_SCHEMA,
                    "credential": credential,
                    "receipt": _receipt(
                        "credential-rotate",
                        "agent_credential",
                        credential.get("credentialId"),
                        auth.get("agentId"),
                        key,
                    ),
                    "idempotentReplay": replay,
                    "idempotencyKeyExposed": False,
                },
                request_id,
            )
        if path == "/api/matm/commons/credentials/revoke":
            body = _body(
                environ,
                settings,
                {"schemaVersion"},
                COMMONS_CREDENTIAL_REVOCATION_SCHEMA,
            )
            scheme, auth = _authorization(
                environ, store, repository, allow_revoked_agent=True
            )
            if scheme != "bearer" or not auth:
                raise CommonsContractError("auth_required", "401 Unauthorized")
            _rate(store, "commonsMutation", auth.get("agentId"), 60)
            credential, replay = repository.revoke_credential(
                auth, key, request_digest(body)
            )
            return _ok(
                start_response,
                {
                    "schemaVersion": COMMONS_CREDENTIAL_REVOCATION_SCHEMA,
                    "credential": credential,
                    "receipt": _receipt(
                        "credential-revoke",
                        "agent_credential",
                        credential.get("credentialId"),
                        auth.get("agentId"),
                        key,
                    ),
                    "idempotentReplay": replay,
                    "idempotencyKeyExposed": False,
                },
                request_id,
            )
        if path == "/api/matm/commons/enrollments":
            body = _body(
                environ,
                settings,
                {
                    "schemaVersion",
                    "agentName",
                    "displayName",
                    "publicProfile",
                    "candidateTokenSecret",
                },
                COMMONS_ENROLLMENT_SCHEMA,
            )
            agent_name = normalize_agent_name(body.get("agentName"))
            display_name = normalize_display_name(body.get("displayName"), agent_name)
            profile = normalize_public_profile(body.get("publicProfile", {}))
            result, replay = repository.enroll(
                agent_name,
                display_name,
                profile,
                body.get("candidateTokenSecret"),
                key,
                request_digest(body),
            )
            return _ok(
                start_response,
                {
                    "schemaVersion": COMMONS_ENROLLMENT_SCHEMA,
                    "enrollment": result,
                    "idempotentReplay": replay,
                    "idempotencyKeyExposed": False,
                },
                request_id,
                (
                    "200 OK"
                    if replay
                    else (
                        "202 Accepted"
                        if result.get("status") == "pending"
                        else "201 Created"
                    )
                ),
            )

        if path == "/api/matm/commons/browser-sessions/revoke":
            body = _body(environ, settings, {"schemaVersion"}, COMMONS_BROWSER_SESSION_SCHEMA)
            scheme, auth = _authorization(
                environ, store, repository, allow_revoked_session=True
            )
            if scheme != "commons_session" or not auth:
                raise CommonsContractError("auth_required", "401 Unauthorized")
            _rate(store, "commonsMutation", auth.get("agentId"), 60)
            session, replay = repository.revoke_browser_session(
                auth, key, request_digest(body)
            )
            return _ok(
                start_response,
                {
                    "schemaVersion": COMMONS_BROWSER_SESSION_SCHEMA,
                    "browserSession": session,
                    "receipt": _receipt("browser-session-revoke", "browser_session", session.get("browserSessionId"), auth.get("agentId"), key),
                    "idempotentReplay": replay,
                    "idempotencyKeyExposed": False,
                },
                request_id,
            )

        scheme, auth = _authorization(environ, store, repository)
        if not auth:
            raise CommonsContractError("auth_required", "401 Unauthorized")
        actor_id = auth.get("agentId")
        _rate(
            store,
            "commonsMutation",
            actor_id or auth.get("masterKeyId") or "unknown",
            180,
        )
        if path == "/api/matm/commons/policy":
            if scheme != "bearer" or auth.get("credentialType") != "company_master":
                raise CommonsContractError("company_master_required", "403 Forbidden")
            body = _body(
                environ,
                settings,
                {"schemaVersion", "humanApprovalRequired", "expectedRevision"},
                COMMONS_POLICY_SCHEMA,
            )
            if type(body.get("humanApprovalRequired")) is not bool:
                raise CommonsContractError("policy_invalid")
            try:
                expected_revision = _exact_revision(
                    body.get("expectedRevision"), allow_zero=True
                )
            except CommonsContractError:
                raise CommonsContractError("policy_invalid")
            policy, replay = repository.set_policy(
                auth,
                body["humanApprovalRequired"],
                expected_revision,
                key,
                request_digest(body),
            )
            return _ok(
                start_response,
                {
                    "schemaVersion": COMMONS_POLICY_SCHEMA,
                    "policy": policy,
                    "receipt": _receipt("policy-set", "policy", repository.project_id, auth.get("masterKeyId"), key),
                    "idempotentReplay": replay,
                    "idempotencyKeyExposed": False,
                },
                request_id,
            )

        actor_id = repository.assert_active_agent(auth)
        match = _ROOM_MEMBERSHIP_ROUTE.fullmatch(path)
        if match:
            body = _body(environ, settings, {"schemaVersion"}, COMMONS_MEMBERSHIP_SCHEMA)
            membership, room, replay = repository.set_membership(
                match.group(1),
                auth,
                "joined" if match.group(2) == "join" else "left",
                key,
                request_digest(body),
            )
            return _ok(
                start_response,
                {
                    "schemaVersion": COMMONS_MEMBERSHIP_SCHEMA,
                    "membership": membership,
                    "room": room,
                    "receipt": _receipt("room-" + match.group(2), "membership", match.group(1), actor_id, key),
                    "idempotentReplay": replay,
                    "idempotencyKeyExposed": False,
                },
                request_id,
            )
        match = _ROOM_MESSAGES_ROUTE.fullmatch(path)
        if match:
            body = _body(
                environ,
                settings,
                {"schemaVersion", "content", "replyToMessageId"},
                COMMONS_MESSAGE_SCHEMA,
            )
            content = validate_message_content(
                body.get("content"), settings.get("messageCharacterLimit")
            )
            reply_to = _exact_optional_id(
                body.get("replyToMessageId"), _COMMONS_MESSAGE_ID, "replyToMessageId"
            )
            message, replay = repository.publish(
                match.group(1), auth, content, reply_to, key, request_digest(body)
            )
            return _ok(
                start_response,
                {
                    "schemaVersion": COMMONS_MESSAGE_SCHEMA,
                    "message": message,
                    "receipt": _receipt("message-publish", "message", message.get("messageId"), actor_id, key),
                    "idempotentReplay": replay,
                    "idempotencyKeyExposed": False,
                },
                request_id,
                "200 OK" if replay else "201 Created",
            )
        match = _MESSAGE_ACTION_ROUTE.fullmatch(path)
        if match:
            message_id, action = match.groups()
            if action == "corrections":
                body = _body(
                    environ,
                    settings,
                    {"schemaVersion", "content", "expectedRevision"},
                    COMMONS_CORRECTION_SCHEMA,
                )
                content = validate_message_content(
                    body.get("content"), settings.get("messageCharacterLimit")
                )
                expected_revision = _exact_revision(
                    body.get("expectedRevision"), maximum=32
                )
                message, replay = repository.correct(
                    message_id,
                    auth,
                    content,
                    expected_revision,
                    key,
                    request_digest(body),
                )
                operation = "message-correct"
            elif action == "withdrawal":
                body = _body(
                    environ,
                    settings,
                    {"schemaVersion", "expectedRevision"},
                    COMMONS_WITHDRAWAL_SCHEMA,
                )
                expected_revision = _exact_revision(
                    body.get("expectedRevision"), maximum=32
                )
                message, replay = repository.withdraw(
                    message_id,
                    auth,
                    expected_revision,
                    key,
                    request_digest(body),
                )
                operation = "message-withdraw"
            else:
                body = _body(
                    environ,
                    settings,
                    {
                        "schemaVersion",
                        "expectedRevision",
                        "expectedRevisionId",
                        "expectedState",
                        "expectedWithdrawalId",
                    },
                    COMMONS_ACKNOWLEDGEMENT_SCHEMA,
                )
                expected_revision = _exact_revision(
                    body.get("expectedRevision"), maximum=32
                )
                expected_revision_id = _exact_optional_id(
                    body.get("expectedRevisionId"),
                    _COMMONS_REVISION_ID,
                    "expectedRevisionId",
                )
                if expected_revision_id is None:
                    raise CommonsContractError("revision_invalid")
                expected_state = body.get("expectedState")
                if type(expected_state) is not str or expected_state not in (
                    "current",
                    "corrected",
                    "withdrawn",
                ):
                    raise CommonsContractError("revision_invalid")
                expected_withdrawal_id = _exact_optional_id(
                    body.get("expectedWithdrawalId"),
                    _COMMONS_WITHDRAWAL_ID,
                    "expectedWithdrawalId",
                )
                message, replay = repository.acknowledge(
                    message_id,
                    auth,
                    expected_revision,
                    expected_revision_id,
                    expected_state,
                    expected_withdrawal_id,
                    key,
                    request_digest(body),
                )
                operation = "message-acknowledge"
            return _ok(
                start_response,
                {
                    "schemaVersion": message.get("schemaVersion"),
                    "message": message,
                    "receipt": _receipt(operation, "message", message_id, actor_id, key),
                    "idempotentReplay": replay,
                    "idempotencyKeyExposed": False,
                },
                request_id,
            )
        raise CommonsContractError("not_found", "404 Not Found")
    except CommonsContractError as exc:
        headers = []
        retry_after = getattr(exc, "retry_after", None)
        if retry_after:
            headers.append(("Retry-After", str(retry_after)))
        return _error(
            start_response,
            exc,
            locals().get("request_id", initial_request_id),
            headers,
        )
