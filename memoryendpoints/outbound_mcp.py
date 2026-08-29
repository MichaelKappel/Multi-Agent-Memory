"""Policy and validation core for outbound MCP server configuration.

This module deliberately performs no network I/O.  Callers must obtain an
authorization decision immediately before a future executor connects, then
apply TLS, DNS, redirect, size, and timeout controls independently.
"""

from __future__ import annotations

import hashlib
import ipaddress
import io
import json
import re
from urllib.parse import urlsplit, urlunsplit

from .http import json_response, problem


SERVER_SCHEMA = "multiagentmemory.outbound_mcp_server.v1"
PROJECT_POLICY_SCHEMA = "multiagentmemory.outbound_mcp_project_policy.v1"
# Temporary internal compatibility for storage code being reconciled separately.
POLICY_SCHEMA = PROJECT_POLICY_SCHEMA
TRANSPORT = "streamable_http"
POLICY_MODES = ("autonomous", "human_required", "blocked")
REQUESTED_MODES = ("inherit", "human_required")
AUTH_MODES = ("none", "credential_slot")
APPROVAL_STATUSES = ("approved", "denied", "revoked")
MAX_ENDPOINT_LENGTH = 2048
MAX_LABEL_LENGTH = 120
_SLOT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_BOUND_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_SERVER_ROUTE_RE = re.compile(
    r"^/api/matm/outbound-mcp/servers/([^/]+)(?:/(disable|authorization-checks))?$"
)
_SERVER_ID_RE = re.compile(r"^omcp-[a-f0-9]{32}$")
_IDEMPOTENCY_RE = re.compile(r"^[\x21-\x7e]{16,200}$")
_MAX_JSON_BODY_BYTES = 32768
_RATE_POLICIES = {
    "outboundMcpRead": (240, 60),
    "outboundMcpMutation": (60, 60),
    "outboundMcpAuthorization": (300, 60),
}


class OutboundMcpValidationError(ValueError):
    """Public-safe validation failure identified by a stable error code."""


def _error(code: str) -> OutboundMcpValidationError:
    return OutboundMcpValidationError(code)


def normalize_endpoint(value: object) -> str:
    endpoint = str(value or "").strip()
    if not endpoint or len(endpoint) > MAX_ENDPOINT_LENGTH:
        raise _error("outbound_mcp_endpoint_invalid")
    if "\\" in endpoint or any(
        character.isspace() or ord(character) == 127 for character in endpoint
    ):
        raise _error("outbound_mcp_endpoint_invalid")
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError as exc:
        raise _error("outbound_mcp_endpoint_invalid") from exc
    if parsed.scheme.lower() != "https":
        raise _error("outbound_mcp_https_required")
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise _error("outbound_mcp_endpoint_invalid")
    if port is not None and not 1 <= port <= 65535:
        raise _error("outbound_mcp_endpoint_invalid")
    if parsed.query or parsed.fragment:
        raise _error("outbound_mcp_endpoint_query_forbidden")
    raw_hostname = parsed.hostname
    if "%" in raw_hostname:
        raise _error("outbound_mcp_endpoint_invalid")
    try:
        address = ipaddress.ip_address(raw_hostname)
    except ValueError:
        if re.fullmatch(r"[0-9.]+", raw_hostname):
            raise _error("outbound_mcp_endpoint_invalid")
        try:
            hostname = raw_hostname.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise _error("outbound_mcp_endpoint_invalid") from exc
        labels = hostname.split(".")
        if (
            not hostname
            or len(hostname) > 253
            or hostname.endswith(".")
            or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in labels
            )
        ):
            raise _error("outbound_mcp_endpoint_invalid")
        host = hostname
    else:
        hostname = address.compressed.lower()
        host = "[%s]" % hostname if address.version == 6 else hostname
    netloc = host if port is None else "%s:%d" % (host, port)
    path = parsed.path or "/"
    return urlunsplit(("https", netloc, path, "", ""))


def validate_server_config(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise _error("outbound_mcp_server_invalid")
    allowed = {
        "schemaVersion",
        "label",
        "endpoint",
        "transport",
        "authMode",
        "credentialSlotId",
        "requestedMode",
        "toolAllowlist",
    }
    if set(payload) - allowed:
        raise _error("outbound_mcp_server_unknown_field")
    if payload.get("schemaVersion") != SERVER_SCHEMA:
        raise _error("outbound_mcp_server_schema_invalid")
    label = " ".join(str(payload.get("label") or "").split())
    if not label or len(label) > MAX_LABEL_LENGTH:
        raise _error("outbound_mcp_label_invalid")
    transport = str(payload.get("transport") or TRANSPORT)
    if transport != TRANSPORT:
        raise _error("outbound_mcp_transport_invalid")
    auth_mode = str(payload.get("authMode") or "none")
    if auth_mode not in AUTH_MODES:
        raise _error("outbound_mcp_auth_mode_invalid")
    slot = str(payload.get("credentialSlotId") or "").strip()
    if auth_mode == "credential_slot":
        if not _SLOT_RE.fullmatch(slot):
            raise _error("outbound_mcp_credential_slot_invalid")
    elif slot:
        raise _error("outbound_mcp_credential_slot_forbidden")
    requested_mode = str(payload.get("requestedMode") or "inherit")
    if requested_mode not in REQUESTED_MODES:
        raise _error("outbound_mcp_requested_mode_invalid")
    if "toolAllowlist" not in payload or not isinstance(
        payload.get("toolAllowlist"), list
    ):
        raise _error("outbound_mcp_tool_allowlist_invalid")
    tool_allowlist = []
    for value in payload["toolAllowlist"]:
        if not isinstance(value, str):
            raise _error("outbound_mcp_tool_allowlist_invalid")
        tool_name = value.strip()
        if not _TOOL_NAME_RE.fullmatch(tool_name):
            raise _error("outbound_mcp_tool_allowlist_invalid")
        tool_allowlist.append(tool_name)
    tool_allowlist = sorted(set(tool_allowlist))
    if not tool_allowlist or len(tool_allowlist) > 256:
        raise _error("outbound_mcp_tool_allowlist_invalid")
    return {
        "schemaVersion": SERVER_SCHEMA,
        "label": label,
        "endpoint": normalize_endpoint(payload.get("endpoint")),
        "transport": TRANSPORT,
        "authMode": auth_mode,
        "credentialSlotId": slot or None,
        "requestedMode": requested_mode,
        "toolAllowlist": tool_allowlist,
    }


def config_digest(config: object) -> str:
    canonical = validate_server_config(config)
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_project_policy(policy: object | None = None) -> dict:
    if policy is None:
        return {
            "schemaVersion": POLICY_SCHEMA,
            "mode": "autonomous",
            "forcedByHuman": False,
            "revision": 0,
        }
    if not isinstance(policy, dict):
        raise _error("outbound_mcp_policy_invalid")
    mode = str(policy.get("mode") or "")
    if mode not in POLICY_MODES:
        raise _error("outbound_mcp_policy_mode_invalid")
    revision = policy.get("revision", 0)
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        raise _error("outbound_mcp_policy_revision_invalid")
    return {
        "schemaVersion": POLICY_SCHEMA,
        "mode": mode,
        "forcedByHuman": bool(policy.get("forcedByHuman")),
        "revision": revision,
    }


def agent_policy_update_allowed(current: object | None, requested_mode: object) -> bool:
    policy = normalize_project_policy(current)
    requested = str(requested_mode or "")
    if requested not in POLICY_MODES:
        raise _error("outbound_mcp_policy_mode_invalid")
    if policy["forcedByHuman"]:
        return requested == policy["mode"]
    strictness = {"autonomous": 0, "human_required": 1, "blocked": 2}
    return strictness[requested] >= strictness[policy["mode"]]


def authorization_decision(
    server_config: object,
    project_policy: object | None = None,
    approval: object | None = None,
    *,
    server_id: object = "",
    server_revision: object = 0,
    project_id: object = "",
    expected_server_revision: object = 0,
    expected_config_digest: object = "",
    expected_policy_revision: object = -1,
    tool_name: object = "",
    arguments_digest: object = "",
) -> dict:
    server = validate_server_config(server_config)
    policy = normalize_project_policy(project_policy)
    digest = config_digest(server)
    bound_server_id = str(server_id or "").strip()
    bound_project_id = str(project_id or "").strip()
    bound_tool_name = str(tool_name or "").strip()
    bound_arguments_digest = str(arguments_digest or "").strip()
    valid_revision = (
        isinstance(server_revision, int)
        and not isinstance(server_revision, bool)
        and server_revision >= 1
    )
    expected_revision_valid = (
        isinstance(expected_server_revision, int)
        and not isinstance(expected_server_revision, bool)
        and expected_server_revision >= 1
    )
    expected_policy_revision_valid = (
        isinstance(expected_policy_revision, int)
        and not isinstance(expected_policy_revision, bool)
        and expected_policy_revision >= 0
    )
    bound_expected_config_digest = str(expected_config_digest or "").strip()
    context_valid = bool(
        _BOUND_ID_RE.fullmatch(bound_server_id)
        and _BOUND_ID_RE.fullmatch(bound_project_id)
        and valid_revision
        and expected_revision_valid
        and expected_policy_revision_valid
        and _SHA256_RE.fullmatch(bound_expected_config_digest)
        and _TOOL_NAME_RE.fullmatch(bound_tool_name)
        and _SHA256_RE.fullmatch(bound_arguments_digest)
    )
    if not context_valid:
        state = "blocked"
        reason = "authorization_context_invalid"
    elif expected_server_revision != server_revision:
        state = "blocked"
        reason = "server_revision_mismatch"
    elif bound_expected_config_digest != digest:
        state = "blocked"
        reason = "config_digest_mismatch"
    elif expected_policy_revision != policy["revision"]:
        state = "blocked"
        reason = "project_policy_revision_mismatch"
    elif policy["mode"] == "blocked":
        state = "blocked"
        reason = "project_policy_blocked"
    elif bound_tool_name not in server["toolAllowlist"]:
        state = "blocked"
        reason = "tool_not_allowlisted"
    else:
        approval_required = (
            policy["mode"] == "human_required"
            or server["requestedMode"] == "human_required"
        )
        approved = bool(
            isinstance(approval, dict)
            and approval.get("status") == "approved"
            and approval.get("serverId") == bound_server_id
            and approval.get("serverRevision") == server_revision
            and approval.get("configDigest") == digest
            and approval.get("policyRevision") == policy["revision"]
        )
        if approval_required and not approved:
            state = "approval_required"
            reason = "exact_config_approval_required"
        else:
            state = "allowed"
            reason = "exact_config_approved" if approval_required else "autonomous_default"
    return {
        "schemaVersion": "multiagentmemory.outbound_mcp_authorization.v1",
        "state": state,
        "reason": reason,
        "configDigest": digest,
        "expectedConfigDigest": bound_expected_config_digest,
        "serverId": bound_server_id,
        "serverRevision": server_revision if valid_revision else 0,
        "expectedServerRevision": (
            expected_server_revision if expected_revision_valid else 0
        ),
        "projectId": bound_project_id,
        "toolName": bound_tool_name,
        "argumentsDigest": bound_arguments_digest,
        "projectPolicyMode": policy["mode"],
        "projectPolicyRevision": policy["revision"],
        "expectedPolicyRevision": (
            expected_policy_revision if expected_policy_revision_valid else -1
        ),
        "networkRequestPerformed": False,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _read_json(environ: dict) -> dict:
    content_type = str(environ.get("CONTENT_TYPE") or "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise _error("outbound_mcp_json_required")
    try:
        size = int(environ.get("CONTENT_LENGTH") or "0")
    except (TypeError, ValueError) as exc:
        raise _error("outbound_mcp_body_invalid") from exc
    if size < 0 or size > _MAX_JSON_BODY_BYTES:
        raise _error("outbound_mcp_body_too_large")
    raw = environ.get("wsgi.input", io.BytesIO()).read(size + 1)
    if len(raw) > _MAX_JSON_BODY_BYTES:
        raise _error("outbound_mcp_body_too_large")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise _error("outbound_mcp_body_invalid") from exc
    if not isinstance(value, dict):
        raise _error("outbound_mcp_body_invalid")
    return value


def _query(environ: dict) -> dict:
    from urllib.parse import parse_qs

    raw = str(environ.get("QUERY_STRING") or "")
    if len(raw) > 4096:
        raise _error("outbound_mcp_query_invalid")
    return {key: values[-1] for key, values in parse_qs(raw, keep_blank_values=True).items()}


def _bearer(environ: dict) -> str:
    value = str(environ.get("HTTP_AUTHORIZATION") or "")
    if not value.startswith("Bearer ") or value.count(" ") != 1:
        return ""
    return value[7:].strip()


def _problem(
    start_response,
    code: str,
    status: str = "422 Unprocessable Entity",
    headers=None,
):
    statuses = {
        "outbound_mcp_auth_required": "401 Unauthorized",
        "outbound_mcp_agent_required": "403 Forbidden",
        "outbound_mcp_scope_forbidden": "403 Forbidden",
        "outbound_mcp_project_required": "422 Unprocessable Entity",
        "outbound_mcp_owner_forbidden": "403 Forbidden",
        "outbound_mcp_server_not_found": "404 Not Found",
        "outbound_mcp_revision_conflict": "409 Conflict",
        "outbound_mcp_idempotency_conflict": "409 Conflict",
        "idempotency_conflict": "409 Conflict",
        "idempotency_in_progress": "409 Conflict",
        "outbound_mcp_method_not_allowed": "405 Method Not Allowed",
        "outbound_mcp_body_too_large": "413 Payload Too Large",
        "outbound_mcp_json_required": "415 Unsupported Media Type",
        "outbound_mcp_rate_limited": "429 Too Many Requests",
        "outbound_mcp_service_unavailable": "503 Service Unavailable",
    }
    return problem(
        start_response,
        statuses.get(code, status),
        "Outbound MCP request rejected",
        "The outbound MCP registry rejected this request.",
        code,
        headers=headers,
    )


def _principal_key(auth: dict, client_key: str) -> str:
    material = json.dumps(
        {
            "credentialType": auth.get("credentialType"),
            "credentialId": auth.get("agentTokenId") or auth.get("credentialId"),
            "agentId": auth.get("agentId"),
            "companyId": auth.get("companyId"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "outbound-mcp-v1-" + hashlib.sha256(
        (material + "\n" + client_key).encode("utf-8")
    ).hexdigest()


def _claim_idempotency(
    store,
    environ,
    workspace_id,
    auth,
    operation,
    body,
    start_response,
    defer_committed_replay=False,
):
    client_key = str(environ.get("HTTP_IDEMPOTENCY_KEY") or "")
    if not _IDEMPOTENCY_RE.fullmatch(client_key):
        return None, _problem(start_response, "outbound_mcp_idempotency_key_invalid")
    key = _principal_key(auth, client_key)
    replay = store.claim_idempotency(workspace_id, key, operation, body)
    if replay and replay.pop("_idempotencyClaimed", False):
        claim = {
            "store": store,
            "workspaceId": workspace_id,
            "key": key,
            "operation": operation,
            "claimId": replay.get("_claimId"),
            "mutationStarted": False,
            "finalized": False,
        }
        environ.setdefault("memoryendpoints.idempotencyClaims", []).append(claim)
        return claim, None
    if replay:
        replay_status = replay.pop("_httpStatus", "200 OK")
        if defer_committed_replay and replay.get("idempotentReplay"):
            return None, {"payload": replay, "httpStatus": replay_status}
        return None, json_response(start_response, replay, replay_status)
    return None, _problem(start_response, "outbound_mcp_idempotency_key_invalid")


def _finalize_idempotency(claim, body, payload, http_status):
    if not claim["store"].record_idempotency(
        claim["workspaceId"],
        claim["key"],
        claim["operation"],
        body,
        payload,
        http_status,
        claim_id=claim["claimId"],
    ):
        raise RuntimeError("outbound_mcp_idempotency_finalization_failed")
    claim["finalized"] = True


def _cancel_idempotency(claim):
    claim["store"].release_idempotency_claim(
        claim["workspaceId"], claim["key"], claim["operation"], claim["claimId"]
    )
    claim["mutationStarted"] = False
    claim["finalized"] = True


def _rate_limit_rejection(
    store, auth, workspace_id, project_id, bucket, start_response
):
    limit, window_seconds = _RATE_POLICIES[bucket]
    partition = json.dumps(
        {
            "credentialId": auth.get("agentTokenId") or auth.get("credentialId"),
            "agentId": auth.get("agentId"),
            "workspaceId": workspace_id,
            "projectId": project_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    try:
        result = store.consume_connector_rate_limit(
            bucket, partition, limit, window_seconds
        )
    except (OSError, RuntimeError, ValueError):
        return _problem(
            start_response,
            "outbound_mcp_service_unavailable",
            headers=[("Retry-After", "5")],
        )
    if result.get("allowed"):
        return None
    retry_after = max(1, int(result.get("retryAfterSeconds") or 1))
    return _problem(
        start_response,
        "outbound_mcp_rate_limited",
        headers=[("Retry-After", str(retry_after))],
    )


def _authenticate_agent(store, environ, workspace_id, project_id, start_response):
    token = _bearer(environ)
    if not token:
        return None, _problem(start_response, "outbound_mcp_auth_required")
    auth = store.authenticate(token, workspace_id)
    if not auth:
        return None, _problem(start_response, "outbound_mcp_auth_required")
    if (
        auth.get("credentialType") != "agent"
        or auth.get("publicCredentialType") == "connector_agent"
        or str(auth.get("agentId") or "").lower().startswith("npc-")
    ):
        return None, _problem(start_response, "outbound_mcp_agent_required")
    if not store.auth_allows_scope(auth, "project", project_id):
        return None, _problem(start_response, "outbound_mcp_scope_forbidden")
    if not store.outbound_mcp_project_active(workspace_id, project_id):
        return None, _problem(start_response, "outbound_mcp_scope_forbidden")
    return auth, None


def _authorization_payload(
    store,
    workspace_id,
    project_id,
    owner_agent_id,
    server_id,
    body,
):
    record = store.outbound_mcp_server(
        workspace_id, project_id, owner_agent_id, server_id
    )
    if not record:
        return None, "outbound_mcp_server_not_found"
    policy = store.outbound_mcp_project_policy(workspace_id, project_id)
    if not policy:
        return None, "outbound_mcp_scope_forbidden"
    decision = authorization_decision(
        record["config"],
        policy,
        record.get("approvalBinding"),
        server_id=server_id,
        server_revision=record.get("revision"),
        project_id=project_id,
        expected_server_revision=body.get("expectedServerRevision"),
        expected_config_digest=body.get("expectedConfigDigest"),
        expected_policy_revision=body.get("expectedPolicyRevision"),
        tool_name=body.get("toolName"),
        arguments_digest=body.get("argumentsDigest"),
    )
    server_enabled = record.get("status") == "active"
    decision.update({"serverEnabled": server_enabled})
    if not server_enabled:
        decision.update({"state": "blocked", "reason": "server_disabled"})
    recorded = store.record_outbound_mcp_authorization_decision(
        workspace_id,
        project_id,
        owner_agent_id,
        server_id,
        record.get("revision"),
        record.get("configDigest"),
        policy.get("revision"),
        body.get("toolName"),
        body.get("argumentsDigest"),
        decision.get("state"),
        decision.get("reason"),
        server_enabled,
    )
    if not recorded:
        return None, "outbound_mcp_revision_conflict"
    return {
        "ok": True,
        "authorization": decision,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }, None


def route_outbound_mcp(environ, start_response, path, store_factory):
    """Dispatch the protected agent-owned outbound registry; perform no I/O."""
    if not path.startswith("/api/matm/outbound-mcp/"):
        return None
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    try:
        match = _SERVER_ROUTE_RE.fullmatch(path)
        if path == "/api/matm/outbound-mcp/policy":
            if method != "GET":
                return _problem(start_response, "outbound_mcp_method_not_allowed")
            query = _query(environ)
            workspace_id = str(query.get("workspace_id") or query.get("workspaceId") or "").strip()
            project_id = str(query.get("project_id") or query.get("projectId") or "").strip()
            if not project_id:
                return _problem(start_response, "outbound_mcp_project_required")
            store = store_factory()
            auth, rejected = _authenticate_agent(
                store, environ, workspace_id, project_id, start_response
            )
            if rejected:
                return rejected
            rate_rejection = _rate_limit_rejection(
                store,
                auth,
                workspace_id,
                project_id,
                "outboundMcpRead",
                start_response,
            )
            if rate_rejection:
                return rate_rejection
            return json_response(start_response, {
                "ok": True,
                "policy": store.outbound_mcp_project_policy(workspace_id, project_id),
                "agentId": auth.get("agentId"),
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            })
        if path == "/api/matm/outbound-mcp/servers":
            if method == "GET":
                query = _query(environ)
                workspace_id = str(query.get("workspace_id") or query.get("workspaceId") or "").strip()
                project_id = str(query.get("project_id") or query.get("projectId") or "").strip()
                if not project_id:
                    return _problem(start_response, "outbound_mcp_project_required")
                store = store_factory()
                auth, rejected = _authenticate_agent(
                    store, environ, workspace_id, project_id, start_response
                )
                if rejected:
                    return rejected
                rate_rejection = _rate_limit_rejection(
                    store,
                    auth,
                    workspace_id,
                    project_id,
                    "outboundMcpRead",
                    start_response,
                )
                if rate_rejection:
                    return rate_rejection
                items = store.outbound_mcp_servers(
                    workspace_id, project_id, auth.get("agentId")
                )
                return json_response(start_response, {
                    "ok": True, "items": items, "count": len(items),
                    "valuesRedacted": True, "rawCredentialExposed": False,
                    "rawPayloadExposed": False,
                })
            if method != "POST":
                return _problem(start_response, "outbound_mcp_method_not_allowed")
            body = _read_json(environ)
            if not str(body.get("projectId") or "").strip():
                return _problem(start_response, "outbound_mcp_project_required")
            if set(body) != {"workspaceId", "projectId", "server"}:
                raise _error("outbound_mcp_body_fields_invalid")
            workspace_id = str(body.get("workspaceId") or "").strip()
            project_id = str(body.get("projectId") or "").strip()
            config = validate_server_config(body.get("server"))
            store = store_factory()
            auth, rejected = _authenticate_agent(
                store, environ, workspace_id, project_id, start_response
            )
            if rejected:
                return rejected
            rate_rejection = _rate_limit_rejection(
                store,
                auth,
                workspace_id,
                project_id,
                "outboundMcpMutation",
                start_response,
            )
            if rate_rejection:
                return rate_rejection
            claim, replay = _claim_idempotency(store, environ, workspace_id, auth, "outbound-mcp-server-create", body, start_response)
            if replay:
                return replay
            claim["mutationStarted"] = True
            record, error = store.create_outbound_mcp_server(
                workspace_id, project_id, auth.get("agentId"), config
            )
            if error:
                _cancel_idempotency(claim)
                return _problem(start_response, error)
            payload = {"ok": True, "server": record, "valuesRedacted": True, "rawCredentialExposed": False, "rawPayloadExposed": False}
            _finalize_idempotency(claim, body, payload, "201 Created")
            return json_response(start_response, payload, "201 Created")
        if not match:
            return _problem(start_response, "outbound_mcp_server_not_found")
        server_id, action = match.groups()
        if not _SERVER_ID_RE.fullmatch(server_id):
            return _problem(start_response, "outbound_mcp_server_not_found")
        if method == "GET" and action is None:
            query = _query(environ)
            workspace_id = str(query.get("workspace_id") or query.get("workspaceId") or "").strip()
            project_id = str(query.get("project_id") or query.get("projectId") or "").strip()
            if not project_id:
                return _problem(start_response, "outbound_mcp_project_required")
            store = store_factory()
            auth, rejected = _authenticate_agent(
                store, environ, workspace_id, project_id, start_response
            )
            if rejected:
                return rejected
            rate_rejection = _rate_limit_rejection(
                store,
                auth,
                workspace_id,
                project_id,
                "outboundMcpRead",
                start_response,
            )
            if rate_rejection:
                return rate_rejection
            record = store.outbound_mcp_server(
                workspace_id, project_id, auth.get("agentId"), server_id
            )
            return json_response(start_response, {"ok": True, "server": record, "valuesRedacted": True, "rawCredentialExposed": False, "rawPayloadExposed": False}) if record else _problem(start_response, "outbound_mcp_server_not_found")
        if method != "POST":
            return _problem(start_response, "outbound_mcp_method_not_allowed")
        body = _read_json(environ)
        if action == "authorization-checks":
            expected = {
                "workspaceId",
                "projectId",
                "expectedServerRevision",
                "expectedConfigDigest",
                "expectedPolicyRevision",
                "toolName",
                "argumentsDigest",
            }
        else:
            expected = {"workspaceId", "projectId", "expectedRevision"}
            if action is None:
                expected.add("server")
        if not str(body.get("projectId") or "").strip():
            return _problem(start_response, "outbound_mcp_project_required")
        if set(body) != expected:
            raise _error("outbound_mcp_body_fields_invalid")
        revision = body.get(
            "expectedServerRevision"
            if action == "authorization-checks"
            else "expectedRevision"
        )
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise _error("outbound_mcp_revision_invalid")
        workspace_id = str(body.get("workspaceId") or "").strip()
        project_id = str(body.get("projectId") or "").strip()
        store = store_factory()
        auth, rejected = _authenticate_agent(
            store, environ, workspace_id, project_id, start_response
        )
        if rejected:
            return rejected
        rate_bucket = (
            "outboundMcpAuthorization"
            if action == "authorization-checks"
            else "outboundMcpMutation"
        )
        rate_rejection = _rate_limit_rejection(
            store,
            auth,
            workspace_id,
            project_id,
            rate_bucket,
            start_response,
        )
        if rate_rejection:
            return rate_rejection
        operation = "outbound-mcp-server-%s-%s" % (server_id, action or "update")
        claim, replay = _claim_idempotency(
            store,
            environ,
            workspace_id,
            auth,
            operation,
            body,
            start_response,
            defer_committed_replay=action == "authorization-checks",
        )
        if replay:
            if action != "authorization-checks" or not isinstance(replay, dict):
                return replay
            payload, error = _authorization_payload(
                store,
                workspace_id,
                project_id,
                auth.get("agentId"),
                server_id,
                body,
            )
            if error:
                return _problem(start_response, error)
            payload.update(
                {
                    "idempotentReplay": True,
                    "authorizationRevalidated": True,
                }
            )
            return json_response(start_response, payload, replay["httpStatus"])
        claim["mutationStarted"] = True
        if action == "disable":
            record, error = store.disable_outbound_mcp_server(
                workspace_id,
                project_id,
                auth.get("agentId"),
                server_id,
                revision,
            )
        elif action == "authorization-checks":
            payload, error = _authorization_payload(
                store,
                workspace_id,
                project_id,
                auth.get("agentId"),
                server_id,
                body,
            )
            if not error:
                _finalize_idempotency(claim, body, payload, "200 OK")
                return json_response(start_response, payload)
        else:
            config = validate_server_config(body.get("server"))
            record, error = store.update_outbound_mcp_server(
                workspace_id,
                project_id,
                auth.get("agentId"),
                server_id,
                revision,
                config,
            )
        if error:
            _cancel_idempotency(claim)
            return _problem(start_response, error)
        payload = {"ok": True, "server": record, "valuesRedacted": True, "rawCredentialExposed": False, "rawPayloadExposed": False}
        _finalize_idempotency(claim, body, payload, "200 OK")
        return json_response(start_response, payload)
    except OutboundMcpValidationError as exc:
        return _problem(start_response, str(exc))
