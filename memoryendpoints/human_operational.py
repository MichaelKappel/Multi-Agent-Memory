"""Cookie-authenticated human operational API.

This controller deliberately stays separate from the bearer-token machine API.
It reuses the same storage-backed render data, but never accepts Authorization,
agent identity fields, inferred resource selection, or cross-origin requests.
"""

import hmac
import json
import re
from http.cookies import SimpleCookie
from urllib.parse import parse_qs

from .http import json_response, one_time_secret_response, problem
from .human_auth import human_browser_request_allowed


HUMAN_SESSION_COOKIE = "__Host-memoryendpoints-human"
HUMAN_SESSION_SECONDS = 30 * 60
RESOURCE_CONTEXT_PATH = "/api/matm/human/session/resource-context"
OPERATIONAL_PREFIX = "/api/matm/human/operational/"
MAX_JSON_BODY_BYTES = 32768
MAX_QUERY_BYTES = 4096

PRIVATE_HEADERS = (
    ("Cache-Control", "no-store, no-cache, must-revalidate, private"),
    ("Pragma", "no-cache"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
    ("Vary", "Cookie"),
)

ROUTES = {
    "/api/matm/human/operational/context-catalog": ("GET", "canReadContextCatalog"),
    "/api/matm/human/operational/workspace": ("GET", "canReadWorkspace"),
    "/api/matm/human/operational/search": ("GET", "canSearchMemory"),
    "/api/matm/human/operational/knowledge-tree": ("GET", "canReadKnowledgeTree"),
    "/api/matm/human/operational/knowledge-documents": ("GET", "canReadKnowledgeDocuments"),
    "/api/matm/human/operational/external-links": ("GET", "canReadExternalLinks"),
    "/api/matm/human/operational/internet-search": ("GET", "canSearchCuratedInternet"),
    "/api/matm/human/operational/memory-events/submit": ("POST", "canSubmitPublicSafeMemory"),
}

DENIED_OPERATION_SEGMENTS = frozenset(
    (
        "collaboration",
        "collaborations",
        "review",
        "reviews",
        "sync",
        "meeting",
        "meetings",
        "message",
        "messages",
    )
)


def _permissions(role):
    can_read = role in ("owner", "credential_admin")
    return {
        "canSelectResourceContext": can_read,
        "canReadContextCatalog": can_read,
        "canReadWorkspace": can_read,
        "canSearchMemory": can_read,
        "canReadKnowledgeTree": can_read,
        "canReadKnowledgeDocuments": can_read,
        "canReadExternalLinks": can_read,
        "canSearchCuratedInternet": can_read,
        "canSubmitPublicSafeMemory": role == "owner",
        "canUseCollaboration": False,
        "canReviewMemory": False,
        "canUseSync": False,
        "canUseMeetings": False,
        "canSendMessages": False,
    }


def _operations(permissions, resource_selected):
    def item(path, methods, permission, requires_resource=True):
        return {
            "path": path,
            "methods": list(methods),
            "permission": permission,
            "allowed": bool(
                permissions.get(permission)
                and (resource_selected or not requires_resource)
            ),
        }

    return {
        "resourceContext": item(
            RESOURCE_CONTEXT_PATH,
            ("POST",),
            "canSelectResourceContext",
            requires_resource=False,
        ),
        "contextCatalog": item(
            "/api/matm/human/operational/context-catalog",
            ("GET",),
            "canReadContextCatalog",
            requires_resource=False,
        ),
        "workspace": item(
            "/api/matm/human/operational/workspace",
            ("GET",),
            "canReadWorkspace",
        ),
        "search": item(
            "/api/matm/human/operational/search",
            ("GET",),
            "canSearchMemory",
        ),
        "knowledgeTree": item(
            "/api/matm/human/operational/knowledge-tree",
            ("GET",),
            "canReadKnowledgeTree",
        ),
        "knowledgeDocuments": item(
            "/api/matm/human/operational/knowledge-documents",
            ("GET",),
            "canReadKnowledgeDocuments",
        ),
        "externalLinks": item(
            "/api/matm/human/operational/external-links",
            ("GET",),
            "canReadExternalLinks",
        ),
        "internetSearch": item(
            "/api/matm/human/operational/internet-search",
            ("GET",),
            "canSearchCuratedInternet",
        ),
        "memorySubmit": item(
            "/api/matm/human/operational/memory-events/submit",
            ("POST",),
            "canSubmitPublicSafeMemory",
        ),
        "collaboration": item("", (), "canUseCollaboration"),
        "review": item("", (), "canReviewMemory"),
        "sync": item("", (), "canUseSync"),
        "meetings": item("", (), "canUseMeetings"),
        "messages": item("", (), "canSendMessages"),
    }


def _audit_actor(session, resource_context):
    return {
        "humanAccountId": session.get("humanAccountId"),
        "humanAccountSessionId": session.get("humanAccountSessionId"),
        "username": session.get("username"),
        "authorityId": resource_context.get("authorityId"),
        "companyId": resource_context.get("companyId"),
        "workspaceId": resource_context.get("workspaceId"),
        "projectId": resource_context.get("projectId"),
        "authMode": "human_account",
    }


def _envelope(session, resource_context, **extra):
    resource_context = {
        "authorityId": resource_context.get("authorityId"),
        "companyId": resource_context.get("companyId"),
        "workspaceId": resource_context.get("workspaceId"),
        "projectId": resource_context.get("projectId"),
        "contextVersion": resource_context.get("contextVersion"),
    }
    permissions = _permissions(session.get("role"))
    selected = bool(
        resource_context.get("workspaceId") and resource_context.get("projectId")
    )
    payload = {
        "ok": True,
        "resourceContext": resource_context,
        "contextVersion": resource_context.get("contextVersion"),
        "csrfTokenRotated": False,
        "permissions": permissions,
        "operations": _operations(permissions, selected),
        "auditActor": _audit_actor(session, resource_context),
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }
    payload.update(extra)
    return payload


def _private_json(start_response, payload, status="200 OK", headers=None):
    return json_response(
        start_response,
        payload,
        status,
        list(PRIVATE_HEADERS) + list(headers or ()),
    )


_ERROR_STATUS = {
    "human_authorization_forbidden": "403 Forbidden",
    "human_trusted_origin_required": "403 Forbidden",
    "human_operational_session_required": "401 Unauthorized",
    "human_selected_company_required": "409 Conflict",
    "human_csrf_required": "403 Forbidden",
    "human_csrf_invalid": "403 Forbidden",
    "human_resource_context_fields_required": "422 Unprocessable Entity",
    "human_resource_context_version_required": "428 Precondition Required",
    "human_resource_context_required": "409 Conflict",
    "human_resource_context_invalid": "409 Conflict",
    "human_resource_context_stale": "409 Conflict",
    "human_resource_context_cross_company": "403 Forbidden",
    "human_resource_context_project_invalid": "404 Not Found",
    "human_operation_not_permitted": "403 Forbidden",
    "human_operational_route_not_found": "404 Not Found",
    "human_operational_method_not_allowed": "405 Method Not Allowed",
    "human_json_content_type_required": "415 Unsupported Media Type",
    "human_json_body_too_large": "413 Payload Too Large",
    "human_json_body_invalid": "400 Bad Request",
    "human_memory_payload_invalid": "422 Unprocessable Entity",
    "human_idempotency_key_required": "422 Unprocessable Entity",
    "idempotency_conflict": "409 Conflict",
    "workspace_quota_exceeded": "409 Conflict",
    "human_operational_failure": "422 Unprocessable Entity",
}


def _error(start_response, code, detail=None, allow=None):
    headers = list(PRIVATE_HEADERS)
    if allow:
        headers.append(("Allow", allow))
    return problem(
        start_response,
        _ERROR_STATUS.get(code, "422 Unprocessable Entity"),
        "Human operational request rejected",
        detail or "The request was safely rejected without exposing protected data.",
        code,
        headers=headers,
    )


def _storage_error(start_response, result):
    code = (result or {}).get("status") or "human_operational_failure"
    aliases = {
        "human_account_session_required": "human_operational_session_required",
        "human_session_required": "human_operational_session_required",
    }
    return _error(start_response, aliases.get(code, code))


def _request_cookie(environ):
    raw = str(environ.get("HTTP_COOKIE") or "")
    if not raw:
        return ""
    cookie = SimpleCookie()
    try:
        cookie.load(raw)
    except Exception:
        return ""
    morsel = cookie.get(HUMAN_SESSION_COOKIE)
    return morsel.value if morsel else ""


def _session_cookie(secret):
    return "%s=%s; Path=/; Max-Age=%d; Secure; HttpOnly; SameSite=Strict" % (
        HUMAN_SESSION_COOKIE,
        secret,
        HUMAN_SESSION_SECONDS,
    )


def _read_json(environ):
    content_type = str(environ.get("CONTENT_TYPE") or "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return None, "human_json_content_type_required"
    length_value = str(environ.get("CONTENT_LENGTH") or "").strip()
    try:
        length = int(length_value) if length_value else None
    except ValueError:
        return None, "human_json_body_invalid"
    if length is not None and (length < 0 or length > MAX_JSON_BODY_BYTES):
        return None, "human_json_body_too_large"
    try:
        raw = environ["wsgi.input"].read(
            length if length is not None else MAX_JSON_BODY_BYTES + 1
        )
    except Exception:
        return None, "human_json_body_invalid"
    if len(raw) > MAX_JSON_BODY_BYTES:
        return None, "human_json_body_too_large"
    try:
        body = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, ValueError):
        return None, "human_json_body_invalid"
    if not isinstance(body, dict):
        return None, "human_json_body_invalid"
    return body, None


def _query(environ):
    raw = str(environ.get("QUERY_STRING") or "")
    if len(raw.encode("utf-8")) > MAX_QUERY_BYTES:
        return {}
    parsed = parse_qs(raw, keep_blank_values=False, strict_parsing=False)
    return {key: values[-1] for key, values in parsed.items() if values}


def _limit(value, default=50, maximum=200):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(maximum, parsed))


def _context_version(environ):
    return str(
        environ.get("HTTP_X_MEMORYENDPOINTS_CONTEXT_VERSION") or ""
    ).strip()


def _context_is_current(current, supplied):
    expected = str(
        (current or {}).get("resourceContext", {}).get("contextVersion") or ""
    )
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


def _selected_catalog_item(catalog, resource_context):
    workspace_id = resource_context.get("workspaceId")
    project_id = resource_context.get("projectId")
    for workspace in catalog.get("workspaces") or []:
        if workspace.get("workspaceId") != workspace_id:
            continue
        selected_project = next(
            (
                project
                for project in workspace.get("projects") or []
                if project.get("projectId") == project_id
            ),
            None,
        )
        if selected_project:
            return dict(workspace), dict(selected_project)
    return None, None


def _memory_payload(body, resource_context):
    allowed = {
        "title",
        "summary",
        "tags",
        "memoryType",
        "subject",
        "confidence",
        "scope",
        "scopeId",
    }
    if set(body) - allowed:
        return None
    if body.get("scope") not in (None, "project"):
        return None
    if body.get("scopeId") not in (None, resource_context.get("projectId")):
        return None
    summary = body.get("summary")
    title = body.get("title") or "Human-submitted memory"
    subject = body.get("subject") or title
    tags = body.get("tags") if body.get("tags") is not None else []
    if (
        not isinstance(summary, str)
        or not 1 <= len(summary.strip()) <= 4000
        or not isinstance(title, str)
        or not 1 <= len(title.strip()) <= 255
        or not isinstance(subject, str)
        or len(subject) > 255
        or not isinstance(tags, list)
        or len(tags) > 20
        or any(not isinstance(tag, str) or not 1 <= len(tag) <= 96 for tag in tags)
    ):
        return None
    payload = {
        "title": title,
        "summary": summary,
        "tags": tags,
        "memoryType": body.get("memoryType") or "note",
        "subject": subject,
    }
    if body.get("confidence") is not None:
        payload["confidence"] = body.get("confidence")
    return payload


def _denied_operation(path):
    if not path.startswith(OPERATIONAL_PREFIX):
        return False
    remainder = path[len(OPERATIONAL_PREFIX) :]
    first = remainder.split("/", 1)[0].strip().lower()
    return first in DENIED_OPERATION_SEGMENTS


def route_human_operational(environ, start_response, path, store, site_url):
    """Dispatch the isolated same-origin human operational surface."""
    if path != RESOURCE_CONTEXT_PATH and not path.startswith(OPERATIONAL_PREFIX):
        return None

    # This must stay first: bearer-shaped requests never parse a body or touch storage.
    if str(environ.get("HTTP_AUTHORIZATION") or "").strip():
        return _error(start_response, "human_authorization_forbidden")

    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    if not human_browser_request_allowed(
        method,
        environ.get("HTTP_ORIGIN"),
        site_url,
        environ.get("HTTP_SEC_FETCH_SITE"),
        environ.get("HTTP_SEC_FETCH_MODE"),
        environ.get("HTTP_SEC_FETCH_DEST"),
    ):
        return _error(start_response, "human_trusted_origin_required")

    session_secret = _request_cookie(environ)
    if not session_secret:
        return _error(start_response, "human_operational_session_required")
    csrf_token = str(environ.get("HTTP_X_CSRF_TOKEN") or "").strip()
    if not csrf_token:
        return _error(start_response, "human_csrf_required")
    session = store.authenticate_human_account_session(
        session_secret, csrf_token, require_csrf=True
    )
    if not session:
        return _error(start_response, "human_csrf_invalid")
    if not session.get("selectedAuthorityId") or not session.get("companyId"):
        return _error(start_response, "human_selected_company_required")

    if path == RESOURCE_CONTEXT_PATH:
        if method != "POST":
            return _error(
                start_response,
                "human_operational_method_not_allowed",
                allow="POST",
            )
        body, body_error = _read_json(environ)
        if body_error:
            return _error(start_response, body_error)
        if set(body) != {
            "authorityId",
            "workspaceId",
            "projectId",
            "contextVersion",
        }:
            return _error(
                start_response, "human_resource_context_fields_required"
            )
        result = store.transition_human_operational_context(
            session_secret,
            csrf_token,
            body.get("contextVersion"),
            body.get("authorityId"),
            body.get("workspaceId"),
            body.get("projectId"),
        )
        if not result.get("ok"):
            return _storage_error(start_response, result)
        rotated_secret = result.get("sessionSecret")
        rotated_csrf = result.get("csrfToken")
        rotated_session = result.get("session") or {}
        memberships = store.list_human_company_memberships(rotated_secret)
        if not memberships.get("ok"):
            return _storage_error(start_response, memberships)
        payload = _envelope(
            rotated_session,
            result["resourceContext"],
            account={
                "humanAccountId": rotated_session.get("humanAccountId"),
                "username": rotated_session.get("username"),
                "displayName": rotated_session.get("displayName")
                or rotated_session.get("username"),
            },
            memberships=memberships.get("items") or [],
            humanSession={
                "humanAccountSessionId": rotated_session.get(
                    "humanAccountSessionId"
                ),
                "humanAccountId": rotated_session.get("humanAccountId"),
                "username": rotated_session.get("username"),
                "selectedAuthorityId": rotated_session.get(
                    "selectedAuthorityId"
                ),
                "selectedCompanyId": rotated_session.get("companyId"),
                "role": rotated_session.get("role"),
                "expiresAt": rotated_session.get("expiresAt"),
                "passwordReauthenticatedAt": rotated_session.get(
                    "passwordReauthenticatedAt"
                ),
            },
            selectedCompanyId=rotated_session.get("companyId"),
            sessionRotated=True,
            csrfTokenRotated=True,
            csrfToken=rotated_csrf,
        )
        return one_time_secret_response(
            start_response,
            payload,
            "200 OK",
            headers=[
                ("Set-Cookie", _session_cookie(rotated_secret)),
                ("Vary", "Cookie"),
            ],
        )

    route = ROUTES.get(path)
    if not route:
        if _denied_operation(path):
            return _error(start_response, "human_operation_not_permitted")
        return _error(start_response, "human_operational_route_not_found")
    expected_method, permission_name = route
    if method != expected_method:
        return _error(
            start_response,
            "human_operational_method_not_allowed",
            allow=expected_method,
        )

    if path == "/api/matm/human/operational/context-catalog":
        catalog = store.human_operational_context_catalog(
            session_secret, csrf_token
        )
        if not catalog.get("ok"):
            return _storage_error(start_response, catalog)
        payload = _envelope(
            catalog["session"],
            catalog["resourceContext"],
            workspaces=catalog.get("workspaces") or [],
            items=catalog.get("items") or [],
            count=len(catalog.get("items") or []),
        )
        return _private_json(start_response, payload)

    supplied_context_version = _context_version(environ)
    if not supplied_context_version:
        return _error(
            start_response, "human_resource_context_version_required"
        )
    current = store.human_operational_context(
        session_secret, csrf_token, require_csrf=True
    )
    if not current.get("ok"):
        return _storage_error(start_response, current)
    if not _context_is_current(current, supplied_context_version):
        return _error(start_response, "human_resource_context_stale")
    resource_context = current["resourceContext"]
    if not resource_context.get("workspaceId") or not resource_context.get(
        "projectId"
    ):
        return _error(start_response, "human_resource_context_required")
    permissions = _permissions(current["session"].get("role"))
    if not permissions.get(permission_name):
        return _error(start_response, "human_operation_not_permitted")

    workspace_id = resource_context["workspaceId"]
    project_id = resource_context["projectId"]
    query = _query(environ)
    limit = _limit(query.get("limit"))

    if path == "/api/matm/human/operational/workspace":
        catalog = store.human_operational_context_catalog(
            session_secret, csrf_token
        )
        if not catalog.get("ok"):
            return _storage_error(start_response, catalog)
        workspace, project = _selected_catalog_item(catalog, resource_context)
        if not workspace or not project:
            return _error(start_response, "human_resource_context_invalid")
        payload = _envelope(
            current["session"],
            resource_context,
            workspace=workspace,
            project=project,
        )
        return _private_json(start_response, payload)

    if path == "/api/matm/human/operational/search":
        filters = {
            "scope": "project",
            "scopeId": project_id,
        }
        for key in ("memoryType", "tag", "sourcePrefix"):
            if query.get(key):
                filters[key] = query[key]
        items = store.search_memory(workspace_id, query.get("q") or "", filters)[
            :limit
        ]
        payload = _envelope(
            current["session"],
            resource_context,
            items=items,
            count=len(items),
            query=query.get("q") or "",
        )
        return _private_json(start_response, payload)

    if path == "/api/matm/human/operational/knowledge-tree":
        filters = {
            "scope": "project",
            "scopeId": project_id,
            "q": query.get("q") or "",
        }
        tree = store.knowledge_tree(workspace_id, filters)
        payload = _envelope(
            current["session"], resource_context, tree=tree
        )
        return _private_json(start_response, payload)

    if path == "/api/matm/human/operational/knowledge-documents":
        filters = {
            "scope": "project",
            "scopeId": project_id,
            "q": query.get("q") or "",
        }
        for key in ("category", "documentType", "knowledgeStatus", "authorityLevel"):
            if query.get(key):
                filters[key] = query[key]
        items = store.knowledge_documents(
            workspace_id, filters, limit=limit, include_text=False
        )
        payload = _envelope(
            current["session"],
            resource_context,
            items=items,
            count=len(items),
        )
        return _private_json(start_response, payload)

    if path in (
        "/api/matm/human/operational/external-links",
        "/api/matm/human/operational/internet-search",
    ):
        filters = {
            "scope": "project",
            "scopeId": project_id,
            "q": query.get("q") or "",
        }
        for key in ("host", "siteName", "reviewStatus", "relationshipType"):
            if query.get(key):
                filters[key] = query[key]
        items = store.external_links(workspace_id, filters, limit=limit)
        extra = {
            "items": items,
            "count": len(items),
            "query": query.get("q") or "",
        }
        if path.endswith("/internet-search"):
            extra.update(
                {
                    "curatedOnly": True,
                    "liveNetworkRequestMade": False,
                    "source": "stored-reviewed-external-links",
                }
            )
        payload = _envelope(
            current["session"], resource_context, **extra
        )
        return _private_json(start_response, payload)

    if path == "/api/matm/human/operational/memory-events/submit":
        body, body_error = _read_json(environ)
        if body_error:
            return _error(start_response, body_error)
        payload_input = _memory_payload(body, resource_context)
        if not payload_input:
            return _error(start_response, "human_memory_payload_invalid")
        idempotency_key = str(
            environ.get("HTTP_IDEMPOTENCY_KEY") or ""
        ).strip()
        if not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._:-]{7,199}", idempotency_key
        ):
            return _error(start_response, "human_idempotency_key_required")
        result = store.submit_human_operational_memory(
            session_secret,
            csrf_token,
            supplied_context_version,
            idempotency_key,
            payload_input,
        )
        if not result.get("ok"):
            return _storage_error(start_response, result)
        response_payload = _envelope(
            current["session"],
            result["resourceContext"],
            event=result.get("event"),
            idempotentReplay=bool(result.get("idempotentReplay")),
            safeNoOpOnRetry=True,
            csrfTokenRotated=False,
        )
        response_payload["auditActor"] = result["auditActor"]
        status = result.get("_httpStatus") or "201 Created"
        return _private_json(start_response, response_payload, status)

    return _error(start_response, "human_operational_route_not_found")

