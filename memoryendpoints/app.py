import datetime
import hashlib
import hmac
import json
import os
import re
import secrets
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlsplit

from . import __version__
from .build import build_provenance
from .company_export import CompanyExportError, assemble_company_export
from .connector_authorize_ui import (
    ApprovalResultDisplay,
    CompanyOption,
    PairingRequestDisplay,
    WorkspaceOption,
    demo_authorization_view,
    production_authorization_view,
    render_connector_authorization,
)
from .connector_pairing import (
    AUTHORIZATION_CODE_TTL_SECONDS,
    AUTHORIZE_PATH as CONNECTOR_AUTHORIZE_PATH,
    CANONICAL_AGENT_DISPLAY_NAME as CONNECTOR_AGENT_DISPLAY_NAME,
    CANONICAL_AGENT_ID as CONNECTOR_AGENT_ID,
    CLIENT_ID as CONNECTOR_CLIENT_ID,
    ISSUER as CONNECTOR_ISSUER,
    MAX_DISCOVERY_RESPONSE_BYTES,
    PAIRING_REQUEST_TTL_SECONDS,
    PENDING_ACTIVATION_TTL_SECONDS,
    PKCE_METHOD as CONNECTOR_PKCE_METHOD,
    RATE_LIMIT_POLICIES as CONNECTOR_RATE_LIMIT_POLICIES,
    SCHEMA as CONNECTOR_PAIRING_SCHEMA,
    V1_REQUESTED_SCOPES as CONNECTOR_V1_REQUESTED_SCOPES,
    PairingPolicyError,
    build_authorization_url,
    build_discovery_document,
    build_wake_up_url,
    exact_request_digest,
    normalize_connector_agent_name,
    connector_scope_digest,
    validate_client_id,
    validate_idempotency_key,
    validate_requested_scopes,
    validate_redirect_uri,
)
from .config import COMPANION_DOCS_URL, GITHUB_REPO_URL, PUBLIC_STORAGE_BYTES, ROOT, SITE_DESCRIPTION, SITE_NAME, SITE_URL, utc_now
from .credential_guidance import (
    COMPANY_MASTER_DEFAULT_SECRET_PATH,
    company_master_storage_guidance,
)
from .http import (
    json_response,
    one_time_secret_payload,
    one_time_secret_response,
    problem,
    response,
)
from .human_access_ui import render_human_access_main
from .human_operational import route_human_operational
from .runtime import backend_error_code, configured_store_backend, store_backend_health
from .security import evaluate_memory_firewall, governed_bearer_token, redact_text
from .site_data import PUBLIC_ROUTES, agent_compatibility_contract, capability_matrix, connector_contract, manifest, openapi_spec, readiness_result, route_inventory, sync_capabilities
from .storage import (
    _knowledge_tree_from_documents,
    _normalize_taxonomy_path,
    _parse_limit,
    _public_external_link,
    FileStore,
    MySQLStore,
    NPC_MEETING_SCOPE_TYPES,
    SQLiteStore,
    credential_system_available,
    mysql_config_diagnostics,
    mysql_connection_stage_diagnostics,
    normalize_project_id,
)
from .uai_memory import virtual_uai_contract


STATIC_ROOT = ROOT / "static"
LONG_TERM_MEMORY_TAG = "long-term-memory-migration"
LONG_TERM_MEMORY_SOURCE_PREFIX = "docs/long-term-memory/"
DEFAULT_CORS_ALLOWED_HEADERS = "Authorization, Content-Type, Idempotency-Key, X-CSRF-Token, X-MemoryEndpoints-Key"
DEFAULT_CORS_ALLOWED_METHODS = "GET, POST, OPTIONS"
_ROUTE_PROTECTED_POST_MUTATIONS = frozenset(
    {
        "/api/matm/projects",
        "/api/matm/knowledge-documents",
        "/api/matm/knowledge-documents/upsert",
        "/api/matm/external-links",
        "/api/matm/external-links/upsert",
        "/api/matm/agents/register",
        "/api/matm/uai-memory/packages",
        "/api/matm/uai-memory/records",
        "/api/matm/uai-memory/edit-claims",
        "/api/matm/uai-memory/edit-claims/heartbeat",
        "/api/matm/uai-memory/edit-claims/complete",
        "/api/matm/uai-memory/edit-claims/release",
        "/api/matm/memory-events/submit",
        "/api/matm/review-queue/decide",
        "/api/matm/meeting-rooms",
        "/api/matm/meeting-messages",
        "/api/matm/meeting-messages/promote",
        "/api/matm/meeting-rooms/read",
        "/api/matm/routing-decisions",
        "/api/matm/agent-messages",
        "/api/matm/notifications/ack",
        "/api/matm/sync/devices",
        "/api/matm/sync/devices/rotate",
        "/api/matm/sync/devices/revoke",
        "/api/matm/sync/mutations",
    }
)
_IDEMPOTENCY_OPTIONAL_PROTECTED_POST_MUTATIONS = frozenset(
    {
        # Deprecated exact company-master LocalEndpoint transition. Connector
        # self-registration is dispatched earlier and still requires a key.
        "/api/matm/agents/register",
    }
)
_IDEMPOTENCY_REQUIRED_PROTECTED_POST_MUTATIONS = (
    _ROUTE_PROTECTED_POST_MUTATIONS
    - _IDEMPOTENCY_OPTIONAL_PROTECTED_POST_MUTATIONS
)
KNOWLEDGE_PAGE_ROUTE = re.compile(r"^/knowledge/(?:company|workspace|project)/(?:[a-z0-9]+(?:-[a-z0-9]+)*/)*[a-z0-9]+(?:-[a-z0-9]+)*$")
TOUR_KNOWLEDGE_PAGE_ROUTE = re.compile(r"^/tour/knowledge/(?:company|workspace|project)/(?:[a-z0-9]+(?:-[a-z0-9]+)*/)*[a-z0-9]+(?:-[a-z0-9]+)*$")
HUMAN_SESSION_COOKIE = "__Host-memoryendpoints-human"
HUMAN_SESSION_SECONDS = 15 * 60
HUMAN_REAUTH_SECONDS = 5 * 60
_CONNECTOR_REQUEST_HANDLE_ROUTE = re.compile(
    r"^/connect/authorize/(pairref_[A-Za-z0-9_-]{43})$"
)
_CONNECTOR_DEMO_AUTHORIZE_ROUTE = re.compile(
    r"^/tour/connect/authorize/(signed_out|login_failed|company_selection|reauth_required|reauthentication_failed|pending|approved|authorization_issued|credential_prepared|activated|authorization_received|credential_delivered|connected|error|expired|canceled|replay|permission_denied)$"
)
_CONNECTOR_PAIRING_ROUTE = re.compile(r"^/api/matm/connector-pairings/([^/]+)$")
_CONNECTOR_CREDENTIALS_ROUTE = re.compile(
    r"^/api/matm/connector-pairings/([^/]+)/credentials$"
)
_CONNECTOR_PAIRING_ACTION_ROUTE = re.compile(
    r"^/api/matm/connector-pairings/([^/]+)/(activate|rotations|revoke|disconnect|cancel)$"
)
_CONNECTOR_ROTATION_ACTIVATION_ROUTE = re.compile(
    r"^/api/matm/connector-pairings/([^/]+)/rotations/([^/]+)/activate$"
)
_CONNECTOR_HUMAN_APPROVAL_ROUTE = re.compile(
    r"^/api/matm/human/connector-pairings/([^/]+)/approve$"
)
_CONNECTOR_HUMAN_COMPANY_SELECTION_ROUTE = re.compile(
    r"^/api/matm/human/connector-pairings/([^/]+)/company-selection$"
)
_CONNECTOR_HUMAN_CANCEL_ROUTE = re.compile(
    r"^/api/matm/human/connector-pairings/([^/]+)/cancel$"
)
_CONNECTOR_MAX_JSON_RESPONSE_BYTES = 65536
_CONNECTOR_MAX_JSON_REQUEST_BYTES = 32768
_CONNECTOR_JSON_HEADERS = (
    ("Cache-Control", "no-store, no-cache, must-revalidate, private"),
    ("Pragma", "no-cache"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
)


def _connector_authorize_headers(script_nonce):
    nonce = str(script_nonce or "")
    return list(_CONNECTOR_JSON_HEADERS) + [
        (
            "Content-Security-Policy",
            "default-src 'none'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; "
            "form-action 'self'; script-src 'self' 'nonce-%s'; style-src 'self'; "
            "img-src 'self'; font-src 'self'; connect-src 'self'" % nonce,
        ),
        ("Cross-Origin-Opener-Policy", "same-origin"),
        ("Cross-Origin-Resource-Policy", "same-origin"),
        ("Vary", "Cookie"),
        (
            "Permissions-Policy",
            "camera=(), geolocation=(), microphone=(), payment=(), usb=()",
        ),
    ]


def _sensitive_html_headers(script_nonce):
    nonce = str(script_nonce or "")
    return list(_CONNECTOR_JSON_HEADERS) + [
        (
            "Content-Security-Policy",
            "default-src 'none'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; "
            "form-action 'self'; script-src 'self' 'nonce-%s'; script-src-attr 'none'; "
            "style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'" % nonce,
        ),
        ("Cross-Origin-Opener-Policy", "same-origin"),
        ("Cross-Origin-Resource-Policy", "same-origin"),
        ("Strict-Transport-Security", "max-age=31536000"),
        ("X-Content-Type-Options", "nosniff"),
        ("Vary", "Cookie"),
        (
            "Permissions-Policy",
            "camera=(), geolocation=(), microphone=(), payment=(), usb=()",
        ),
    ]


def _read_body(environ):
    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError:
        length = 0
    raw = environ["wsgi.input"].read(length) if length else b""
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        return None


def _query(environ):
    return {k: v[0] if v else "" for k, v in parse_qs(environ.get("QUERY_STRING", "")).items()}


def _is_knowledge_page_route(path):
    return bool(KNOWLEDGE_PAGE_ROUTE.fullmatch(path or "")) and "//" not in path and not path.endswith("/")


def _is_tour_knowledge_page_route(path):
    return bool(TOUR_KNOWLEDGE_PAGE_ROUTE.fullmatch(path or "")) and "//" not in path and not path.endswith("/")


def _token(environ):
    auth = environ.get("HTTP_AUTHORIZATION", "")
    governed = governed_bearer_token(auth)
    if governed:
        return governed
    if str(auth or "").lower().startswith("bearer "):
        bearer = str(auth).split(" ", 1)[1].strip()
        if bearer.startswith("me_live_"):
            return bearer
    header_key = environ.get("HTTP_X_MEMORYENDPOINTS_KEY", "").strip()
    if header_key.startswith("me_live_"):
        return header_key
    return ""


def _idempotency_key(environ):
    return environ.get("HTTP_IDEMPOTENCY_KEY", "").strip()


def _validated_idempotency_key_or_problem(environ, start_response, required=True):
    raw_key = environ.get("HTTP_IDEMPOTENCY_KEY", "")
    if not raw_key:
        if not required:
            return "", None
        return "", problem(
            start_response,
            "422 Unprocessable Entity",
            "Idempotency key required",
            "Protected mutations require Idempotency-Key so exact retries cannot create duplicate effects.",
            "idempotency_key_required",
        )
    try:
        return validate_idempotency_key(raw_key), None
    except PairingPolicyError:
        return "", problem(
            start_response,
            "422 Unprocessable Entity",
            "Invalid idempotency key",
            "Idempotency-Key must be 16 to 200 visible ASCII characters with no surrounding whitespace.",
            "idempotency_key_invalid",
        )


def _principal_scoped_idempotency_key(auth, key):
    """Hide the caller key and isolate reservations between principals."""
    if not key:
        return ""
    credential_type = str((auth or {}).get("credentialType") or "unknown")
    if credential_type == "company_master":
        principal_id = (auth or {}).get("masterKeyId")
    elif credential_type == "agent":
        principal_id = (
            (auth or {}).get("agentIdentityId")
            or (auth or {}).get("agentTokenId")
            or (auth or {}).get("credentialId")
            or (auth or {}).get("agentId")
        )
    else:
        principal_id = (
            (auth or {}).get("connectorCredentialId")
            or (auth or {}).get("credentialId")
            or (auth or {}).get("pairingId")
            or (auth or {}).get("agentId")
        )
    namespace = {
        "credentialType": credential_type,
        "principalId": principal_id or (auth or {}).get("principalName") or "",
        "companyId": (auth or {}).get("companyId") or "",
        "workspaceId": (auth or {}).get("workspaceId") or "",
    }
    material = "%s\n%s" % (
        json.dumps(namespace, sort_keys=True, separators=(",", ":")),
        key,
    )
    return "principal-v2-" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def _connector_json(start_response, data, status="200 OK", headers=None):
    encoded = json.dumps(data, indent=2, sort_keys=True).encode("utf-8")
    if len(encoded) > _CONNECTOR_MAX_JSON_RESPONSE_BYTES:
        return problem(
            start_response,
            "503 Service Unavailable",
            "Connector pairing unavailable",
            "The connector response could not be returned within the published size bound.",
            "connector_service_unavailable",
            headers=list(_CONNECTOR_JSON_HEADERS) + [("Retry-After", "5")],
        )
    return json_response(
        start_response,
        data,
        status,
        list(_CONNECTOR_JSON_HEADERS) + list(headers or []),
    )


def _connector_one_time_secret(start_response, data, status="201 Created", headers=None):
    public_payload = one_time_secret_payload(data)
    encoded = json.dumps(public_payload, indent=2, sort_keys=True).encode("utf-8")
    if len(encoded) > _CONNECTOR_MAX_JSON_RESPONSE_BYTES:
        return problem(
            start_response,
            "503 Service Unavailable",
            "Connector pairing unavailable",
            "The connector response could not be returned within the published size bound.",
            "connector_service_unavailable",
            headers=list(_CONNECTOR_JSON_HEADERS) + [("Retry-After", "5")],
        )
    return one_time_secret_response(
        start_response, public_payload, status, list(headers or [])
    )


def _connector_problem(start_response, code, detail=None, headers=None):
    statuses = {
        "invalid_token": "401 Unauthorized",
        "pkce_verification_failed": "401 Unauthorized",
        "authorization_code_invalid": "401 Unauthorized",
        "authorization_claim_invalid": "401 Unauthorized",
        "workspace_ref_invalid": "401 Unauthorized",
        "company_ref_invalid": "401 Unauthorized",
        "pending_credential_not_active": "401 Unauthorized",
        "company_master_required": "403 Forbidden",
        "insufficient_scope": "403 Forbidden",
        "connector_scope_forbidden": "403 Forbidden",
        "pairing_not_found": "404 Not Found",
        "pairing_request_not_found": "404 Not Found",
        "workspace_not_found": "404 Not Found",
        "rotation_not_found": "404 Not Found",
        "idempotency_conflict": "409 Conflict",
        "authorization_code_already_exchanged": "409 Conflict",
        "agent_name_unavailable": "409 Conflict",
        "pairing_request_unavailable": "409 Conflict",
        "pairing_unavailable": "409 Conflict",
        "pairing_not_pending_activation": "409 Conflict",
        "rotation_unavailable": "409 Conflict",
        "rotation_pending": "409 Conflict",
        "grant_not_active": "409 Conflict",
        "pairing_verification_failed": "409 Conflict",
        "pairing_request_expired": "410 Gone",
        "authorization_code_expired": "410 Gone",
        "authorization_code_redeemed": "410 Gone",
        "pairing_request_canceled": "410 Gone",
        "pending_grant_expired": "410 Gone",
        "pairing_canceled": "410 Gone",
        "pairing_revoked": "410 Gone",
        "pairing_disconnected": "410 Gone",
        "workspace_ref_expired": "410 Gone",
        "company_ref_expired": "410 Gone",
        "request_body_too_large": "413 Content Too Large",
        "json_content_type_required": "415 Unsupported Media Type",
        "idempotency_key_required": "422 Unprocessable Entity",
        "idempotency_key_invalid": "422 Unprocessable Entity",
        "schema_version_unsupported": "422 Unprocessable Entity",
        "connector_client_unsupported": "422 Unprocessable Entity",
        "redirect_uri_not_allowed": "422 Unprocessable Entity",
        "state_invalid": "422 Unprocessable Entity",
        "pkce_method_unsupported": "422 Unprocessable Entity",
        "pkce_challenge_invalid": "422 Unprocessable Entity",
        "connector_agent_identity_invalid": "422 Unprocessable Entity",
        "approved_agent_mismatch": "422 Unprocessable Entity",
        "workspace_selection_invalid": "422 Unprocessable Entity",
        "connector_scopes_invalid": "422 Unprocessable Entity",
        "connector_public_safe_payload_required": "422 Unprocessable Entity",
        "idempotency_key_not_allowed": "422 Unprocessable Entity",
        "invalid_request": "422 Unprocessable Entity",
        "rate_limited": "429 Too Many Requests",
        "credential_system_not_configured": "503 Service Unavailable",
        "connector_service_unavailable": "503 Service Unavailable",
    }
    fixed_details = {
        "invalid_token": "A valid connector or company-master bearer credential is required.",
        "pkce_verification_failed": "PKCE verification failed.",
        "authorization_code_invalid": "The authorization code is invalid.",
        "authorization_claim_invalid": "The authorization claim binding is invalid.",
        "workspace_ref_invalid": "The workspace selection reference is invalid for this approval session.",
        "company_ref_invalid": "The company selection reference is invalid for this approval session.",
        "pending_credential_not_active": "The connector credential has not been activated.",
        "company_master_required": "A company master credential is required for this operation.",
        "insufficient_scope": "This connector credential is not authorized for that route or action.",
        "connector_scope_forbidden": "This route or action is outside the immutable connector grant.",
        "pairing_not_found": "The pairing resource was not found.",
        "pairing_request_not_found": "The pairing request was not found.",
        "workspace_not_found": "The selected workspace was not found in the authenticated company.",
        "rotation_not_found": "The connector rotation was not found.",
        "idempotency_conflict": "The idempotency key was already used for a different request.",
        "authorization_code_already_exchanged": "The authorization code was already exchanged by another request.",
        "agent_name_unavailable": "That human-readable agent name is already in use in this company.",
        "pairing_request_unavailable": "The pairing request is no longer awaiting approval.",
        "pairing_unavailable": "A different terminal connector action already completed.",
        "pairing_not_pending_activation": "The pairing is not awaiting activation.",
        "rotation_unavailable": "The credential rotation is no longer available.",
        "rotation_pending": "A credential rotation is already awaiting activation.",
        "grant_not_active": "The connector grant is not active.",
        "pairing_verification_failed": "The active grant could not prove its exact workspace and agent registration.",
        "pairing_request_expired": "The pairing request expired.",
        "authorization_code_expired": "The authorization code expired.",
        "authorization_code_redeemed": "The authorization code is no longer available.",
        "pairing_request_canceled": "The pairing request was canceled before connector claim.",
        "pending_grant_expired": "The pending connector grant expired without activation.",
        "pairing_canceled": "The pending pairing was canceled.",
        "pairing_revoked": "The connector grant was revoked.",
        "pairing_disconnected": "The connector was disconnected.",
        "workspace_ref_expired": "The workspace selection reference expired.",
        "company_ref_expired": "The company selection reference expired.",
        "request_body_too_large": "The connector request exceeds the published JSON size limit.",
        "json_content_type_required": "This operation requires application/json.",
        "idempotency_key_required": "A high-entropy Idempotency-Key header is required.",
        "idempotency_key_invalid": "The Idempotency-Key header is invalid.",
        "schema_version_unsupported": "The requested connector pairing schema is not supported.",
        "connector_client_unsupported": "The connector client is not supported.",
        "redirect_uri_not_allowed": "The redirect URI is not registered for this connector.",
        "state_invalid": "The desktop state value is invalid.",
        "pkce_method_unsupported": "Only PKCE S256 is supported.",
        "pkce_challenge_invalid": "The PKCE S256 challenge is invalid.",
        "connector_agent_identity_invalid": "The requested identity must be the exact canonical LocalEndpoint connector agent.",
        "approved_agent_mismatch": "The approved identity must exactly match the normalized requested agent identity.",
        "workspace_selection_invalid": "Select an authorized existing workspace or provide labels for a new workspace.",
        "connector_scopes_invalid": "The connector scope set does not exactly match the required ordered v1 scope contract.",
        "connector_public_safe_payload_required": "The connector accepts only the exact public-safe memory schema and content.",
        "idempotency_key_not_allowed": "This read-only connector operation does not accept an idempotency key.",
        "invalid_request": "The request body does not match the connector operation schema.",
        "rate_limited": "Too many pairing requests were made.",
        "credential_system_not_configured": "The protected credential service is temporarily unavailable.",
        "connector_service_unavailable": "The connector pairing service is temporarily unavailable.",
    }
    status = statuses.get(code, "422 Unprocessable Entity")
    response_headers = list(_CONNECTOR_JSON_HEADERS) + list(headers or [])
    if status.startswith("401"):
        response_headers.append(("WWW-Authenticate", 'Bearer realm="MemoryEndpoints", error="invalid_token"'))
    return problem(
        start_response,
        status,
        "Connector pairing rejected",
        detail or fixed_details.get(code, "The connector pairing operation was safely rejected."),
        code,
        headers=response_headers,
    )


def _connector_content_type_is_json(environ):
    return str(environ.get("CONTENT_TYPE") or "").split(";", 1)[0].strip().lower() == "application/json"


def _connector_request_digest(method, path, body):
    try:
        return exact_request_digest(method, path, body)
    except PairingPolicyError:
        return ""


def _connector_source_client_partition(environ):
    return "%s|%s" % (environ.get("REMOTE_ADDR") or "unknown", CONNECTOR_CLIENT_ID)


def _connector_rate_partition(environ, bucket, partition=""):
    if bucket == "discovery":
        return str(environ.get("REMOTE_ADDR") or "unknown")
    if bucket in (
        "authorize",
        "pairingRequest",
        "authorizationCodeClaim",
        "tokenExchange",
    ):
        # These public/pre-credential operations must never partition on an
        # attacker-selected code, request handle, state, or idempotency key.
        return _connector_source_client_partition(environ)
    return str(partition or "unknown")


def _connector_rate_policy(bucket):
    policy = CONNECTOR_RATE_LIMIT_POLICIES.get(bucket) or {}
    limit = int(policy.get("limit") or 10)
    window = int(policy.get("windowSeconds") or 600)
    if bucket == "pairingRequest":
        try:
            override = int(os.environ.get("MEMORYENDPOINTS_CONNECTOR_PAIRING_RATE_LIMIT") or limit)
        except ValueError:
            override = limit
        limit = max(1, min(override, 10000))
    return limit, window


def _connector_operation_rate_limited(environ, bucket, partition="", store=None):
    limit, window = _connector_rate_policy(bucket)
    try:
        result = (store or _store()).consume_connector_rate_limit(
            bucket,
            _connector_rate_partition(environ, bucket, partition),
            limit,
            window,
        )
    except (OSError, RuntimeError, ValueError):
        return {
            "allowed": False,
            "unavailable": True,
            "retryAfterSeconds": 5,
            "valuesRedacted": True,
        }
    return result


def _connector_rate_rejection(start_response, result):
    if result.get("allowed"):
        return None
    retry_after = max(1, int(result.get("retryAfterSeconds") or 1))
    if result.get("unavailable"):
        return _connector_problem(
            start_response,
            "connector_service_unavailable",
            headers=[("Retry-After", str(retry_after))],
        )
    return _connector_problem(
        start_response,
        "rate_limited",
        headers=[("Retry-After", str(retry_after))],
    )


def _connector_discovery():
    core = build_discovery_document()
    return {
        "schemaVersion": CONNECTOR_PAIRING_SCHEMA,
        "supportedSchemaVersions": [CONNECTOR_PAIRING_SCHEMA],
        "issuer": CONNECTOR_ISSUER,
        "serviceRoot": {
            "exact": CONNECTOR_ISSUER,
            "userinfoAllowed": False,
            "nonDefaultPortAllowed": False,
            "queryAllowed": False,
            "fragmentAllowed": False,
        },
        "clients": [
            {
                "clientId": CONNECTOR_CLIENT_ID,
                "canonicalAgentId": core["canonicalAgentIdentity"]["agentId"],
                "redirectUris": core["redirectUris"],
                "requestedScopes": list(CONNECTOR_V1_REQUESTED_SCOPES),
                "scopeDigest": connector_scope_digest(
                    CONNECTOR_V1_REQUESTED_SCOPES
                ),
            }
        ],
        "endpoints": {
            "pairingRequest": "/api/matm/connector-pairings/requests",
            "authorization": "/connect/authorize/{publicRequestRef}",
            "authorizationCodeClaim": "/api/matm/connector-pairings/authorization-code-claims",
            "token": "/api/matm/connector-pairings/token",
            "activation": "/api/matm/connector-pairings/{pairingId}/activate",
            "status": "/api/matm/connector-pairings/{pairingId}",
            "rotation": "/api/matm/connector-pairings/{pairingId}/rotations",
            "rotationActivation": "/api/matm/connector-pairings/{pairingId}/rotations/{rotationId}/activate",
            "credentialList": "/api/matm/connector-pairings/{pairingId}/credentials",
            "revocation": "/api/matm/connector-pairings/{pairingId}/revoke",
            "disconnect": "/api/matm/connector-pairings/{pairingId}/disconnect",
            "cancellation": "/api/matm/connector-pairings/{pairingId}/cancel",
        },
        "security": {
            "pkceMethods": [CONNECTOR_PKCE_METHOD],
            "stateRequired": True,
            "requestTtlSeconds": PAIRING_REQUEST_TTL_SECONDS,
            "authorizationCodeTtlSeconds": AUTHORIZATION_CODE_TTL_SECONDS,
            "pendingGrantTtlSeconds": PENDING_ACTIVATION_TTL_SECONDS,
            "authorizationCodeOneUse": True,
            "activationRequired": True,
            "authorizationCallbackParametersAllowed": False,
            "authorizationCodeDelivery": "body_only_claim",
        },
        "transport": {
            "tlsValidation": "operating_system_default",
            "sameOriginEndpoints": True,
            "noRedirectsForApiEndpoints": True,
            "jsonContentTypeRequired": True,
            "maximumJsonRequestBytes": _CONNECTOR_MAX_JSON_REQUEST_BYTES,
            "maximumJsonResponseBytes": 65536,
            "maximumDiscoveryResponseBytes": MAX_DISCOVERY_RESPONSE_BYTES,
            "credentialsInUrlsAllowed": False,
        },
        "agentNamePolicy": core["agentNamePolicy"],
        "requestedScopes": list(CONNECTOR_V1_REQUESTED_SCOPES),
        "scopeDigest": connector_scope_digest(CONNECTOR_V1_REQUESTED_SCOPES),
        "authorization": core["authorizationCode"],
        "rateLimits": core["rateLimits"],
        "publicResponse": core["publicResponse"],
    }


def _connector_result_error(start_response, result):
    code = str((result or {}).get("status") or "connector_service_unavailable")
    aliases = {
        "pending_credential_invalid": "invalid_token",
        "human_credential_authority_required": "human_reauthentication_required",
        "company_unavailable": "workspace_not_found",
        "provisional_workspace_collision": "idempotency_conflict",
        "pairing_request_redeemed": "authorization_code_redeemed",
        "authorization_claim_binding_invalid": "authorization_claim_invalid",
    }
    code = aliases.get(code, code)
    if code == "human_reauthentication_required":
        return _human_problem(start_response, code)
    headers = None
    if code == "rate_limited":
        headers = [("Retry-After", str(int((result or {}).get("retryAfterSeconds") or 60)))]
    elif code in ("credential_system_not_configured", "connector_service_unavailable"):
        headers = [("Retry-After", "5")]
    return _connector_problem(start_response, code, headers=headers)


def _connector_public_pairing_request(pairing_request, expires_in_seconds=None):
    """Return the exact tenant-neutral public pairing-request summary."""
    source = pairing_request or {}
    public = {
        "publicRequestRef": source.get("publicRequestRef"),
        "status": source.get("status"),
        "clientDisplayName": source.get("clientDisplayName"),
        "agentDisplayName": source.get("agentDisplayName"),
        "requestedScopes": list(source.get("requestedScopes") or ()),
        "approvedScopes": list(source.get("approvedScopes") or ()),
        "scopeDigest": source.get("scopeDigest"),
        "scopeImpacts": [
            {
                "scope": item.get("scope"),
                "impact": item.get("impact"),
            }
            for item in (source.get("scopeImpacts") or ())
            if isinstance(item, dict)
        ],
        "expiresAt": source.get("expiresAt"),
        "claimExpiresAt": source.get("claimExpiresAt"),
    }
    if expires_in_seconds is not None:
        public["expiresInSeconds"] = int(expires_in_seconds)
    return public


def _connector_public_pairing(pairing, verification=None):
    """Return the exact public pairing summary; never copy storage records."""
    source = pairing or {}
    source_grant = source.get("grant") or {}
    scopes = list(source.get("approvedScopes") or source_grant.get("approvedScopes") or ())
    scope_digest = source.get("scopeDigest") or source_grant.get("scopeDigest")
    status = source.get("status")
    workspace_id = source.get("workspaceId") or source_grant.get("workspaceId")
    agent_id = source.get("agentId") or source_grant.get("agentId")
    public = {
        "pairingId": source.get("pairingId"),
        "status": status,
        "workspaceId": workspace_id,
        "agentId": agent_id,
        "credentialId": source.get("credentialId"),
        "approvedScopes": scopes,
        "scopeDigest": scope_digest,
        "grant": {
            "credentialType": source_grant.get("credentialType")
            or "connector_agent",
            "scopeType": source_grant.get("scopeType") or "agent",
            "scopeId": source_grant.get("scopeId") or agent_id,
            "workspaceId": workspace_id,
            "agentId": agent_id,
            "approvedScopes": list(source_grant.get("approvedScopes") or scopes),
            "scopeDigest": source_grant.get("scopeDigest") or scope_digest,
            "active": source_grant.get("active") is True,
            "revoked": source_grant.get("revoked") is True,
            "canInvite": source_grant.get("canInvite") is True,
            "canRevoke": source_grant.get("canRevoke") is True,
        },
    }
    if status == "pending_activation":
        public["activationExpiresInSeconds"] = PENDING_ACTIVATION_TTL_SECONDS
    if verification is not None:
        public["workspace"] = {
            "workspaceId": workspace_id,
            "readable": verification.get("canonicalWorkspaceReadable") is True,
        }
        public["agent"] = {
            "agentId": agent_id,
            "readable": verification.get("exactAgentReadable") is True,
        }
    return public


def _connector_public_rotation(rotation):
    """Return the exact public rotation summary without linkage or reason data."""
    source = rotation or {}
    public = {
        "rotationId": source.get("rotationId"),
        "status": source.get("status"),
        "credentialId": source.get("credentialId"),
        "approvedScopes": list(source.get("approvedScopes") or ()),
        "scopeDigest": source.get("scopeDigest"),
    }
    if source.get("status") == "pending_activation":
        public["activationExpiresInSeconds"] = PENDING_ACTIVATION_TTL_SECONDS
    return public


def _connector_public_credential(credential):
    """Return exact credential inventory metadata without nested boilerplate."""
    source = credential or {}
    return {
        "credentialId": source.get("credentialId"),
        "status": source.get("status"),
        "isCurrent": source.get("isCurrent") is True,
        "approvedScopes": list(source.get("approvedScopes") or ()),
        "scopeDigest": source.get("scopeDigest"),
        "createdAt": source.get("createdAt"),
        "activatedAt": source.get("activatedAt"),
        "revokedAt": source.get("revokedAt"),
        "lastUsedAt": source.get("lastUsedAt"),
    }


def _connector_scope_binding(record):
    record = record or {}
    scopes = record.get("approvedScopes") or record.get("requestedScopes")
    scopes = list(validate_requested_scopes(scopes))
    expected_digest = connector_scope_digest(scopes)
    if not hmac.compare_digest(str(record.get("scopeDigest") or ""), expected_digest):
        raise PairingPolicyError("scope_digest_invalid")
    return scopes, expected_digest


def _connector_verification(pairing):
    facts = dict(pairing or {})
    return {
        "canonicalWorkspaceReadable": facts.get("canonicalWorkspaceReadable") is True,
        "canonicalWorkspaceIdMatches": facts.get("canonicalWorkspaceIdMatches") is True,
        "exactAgentReadable": facts.get("exactAgentReadable") is True,
        "exactAgentIdMatches": facts.get("exactAgentIdMatches") is True,
        "credentialScopedToConnectorAndAgent": facts.get("credentialScopedToConnectorAndAgent") is True,
        "grantActive": facts.get("grantActive") is True,
        "grantRevoked": facts.get("grantRevoked") is True,
        "rawCredentialExposed": False,
        "privatePayloadExposed": False,
        "valuesRedacted": True,
    }


def _connector_verification_passed(verification):
    return bool(
        verification.get("canonicalWorkspaceReadable")
        and verification.get("canonicalWorkspaceIdMatches")
        and verification.get("exactAgentReadable")
        and verification.get("exactAgentIdMatches")
        and verification.get("credentialScopedToConnectorAndAgent")
        and verification.get("grantActive")
        and not verification.get("grantRevoked")
    )


def _connector_receipt(
    action,
    resource_id,
    status,
    idempotent_replay=False,
    actor_master_key_id=None,
    scope_digest=None,
):
    binding = str(scope_digest or "")
    receipt = {
        "receiptId": "connector-" + hashlib.sha256(
            (str(action) + "|" + str(resource_id) + "|" + binding).encode("utf-8")
        ).hexdigest()[:24],
        "action": str(action),
        "status": str(status),
        "idempotentReplay": bool(idempotent_replay),
        "rawCredentialExposed": False,
        "privatePayloadExposed": False,
    }
    if actor_master_key_id:
        receipt["actorMasterKeyId"] = actor_master_key_id
    if scope_digest:
        receipt["scopeDigest"] = str(scope_digest)
    return receipt


def _connector_exact_body_or_problem(environ, start_response, required, optional=()):
    body, rejected = _connector_body_or_problem(environ, start_response)
    if rejected:
        return None, rejected
    required = frozenset(required)
    allowed = required | frozenset(optional)
    if set(body) - allowed or not required.issubset(body):
        return None, _connector_problem(start_response, "invalid_request")
    return body, None


def _connector_valid_reason(body):
    reason = body.get("reason")
    if not isinstance(reason, str) or reason != reason.strip() or not 1 <= len(reason) <= 255:
        return None
    if any(ord(character) < 32 or ord(character) == 127 for character in reason):
        return None
    return reason


def _connector_lifecycle_authority_or_problem(
    store, environ, start_response, pairing_id, action, rotation_id=None
):
    """Authenticate lifecycle authority before reading a mutation body."""
    token = _token(environ)
    if not token:
        return None, _connector_problem(start_response, "invalid_token")

    if action == "revoke":
        master = store.authenticate_company_master(token)
        if master:
            inventory = store.list_connector_credentials(pairing_id, token)
            if not inventory.get("ok"):
                return None, _connector_result_error(start_response, inventory)
            return {"credentialType": "company_master", "token": token}, None
        connector = store.authenticate_connector_token(
            token,
            pairing_id=pairing_id,
            allow_pending=True,
            allow_lifecycle_terminal=True,
        )
        if connector:
            return None, _connector_problem(start_response, "company_master_required")
        return None, _connector_problem(start_response, "invalid_token")

    allow_terminal = action == "disconnect"
    connector = store.authenticate_connector_token(
        token,
        pairing_id=pairing_id,
        allow_pending=True,
        allow_lifecycle_terminal=allow_terminal,
    )
    if connector:
        return connector, None

    if action in ("activate", "rotation_activate"):
        terminal_error = store.connector_lifecycle_terminal_error(
            token, pairing_id, rotation_id=rotation_id
        )
        if terminal_error:
            return None, _connector_problem(start_response, terminal_error)

    wrong_connector = store.authenticate_connector_token(
        token,
        allow_pending=True,
        allow_lifecycle_terminal=allow_terminal,
    )
    if wrong_connector or store.authenticate_company_master(token):
        return None, _connector_problem(start_response, "connector_scope_forbidden")
    return None, _connector_problem(start_response, "invalid_token")


def _connector_idempotency_or_problem(environ, start_response):
    key = environ.get("HTTP_IDEMPOTENCY_KEY", "")
    if not key:
        return None, _connector_problem(start_response, "idempotency_key_required")
    try:
        key = validate_idempotency_key(key)
    except PairingPolicyError:
        return None, _connector_problem(start_response, "idempotency_key_invalid")
    return key, None


def _connector_body_or_problem(environ, start_response):
    if not _connector_content_type_is_json(environ):
        return None, _connector_problem(start_response, "json_content_type_required")
    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except (TypeError, ValueError):
        return None, _connector_problem(start_response, "invalid_request")
    if length < 0 or length > _CONNECTOR_MAX_JSON_REQUEST_BYTES:
        return None, _connector_problem(start_response, "request_body_too_large")
    raw = environ["wsgi.input"].read(length) if length else b""
    if len(raw) > _CONNECTOR_MAX_JSON_REQUEST_BYTES:
        return None, _connector_problem(start_response, "request_body_too_large")
    try:
        body = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeError, ValueError, RecursionError):
        body = None
    if not isinstance(body, dict):
        return None, _connector_problem(start_response, "invalid_request")
    return body, None


def _cors_allowed_origin(environ):
    allowed = os.environ.get("MEMORYENDPOINTS_CORS_ALLOWED_ORIGINS", "*").strip() or "*"
    origin = (environ.get("HTTP_ORIGIN") or "").strip()
    if allowed == "*":
        return "*"
    allowed_origins = [item.strip() for item in allowed.split(",") if item.strip()]
    if origin and origin in allowed_origins:
        return origin
    if not origin:
        return ""
    return None


def _cors_headers(environ):
    origin = _cors_allowed_origin(environ)
    if origin is None:
        return []
    request_headers = (environ.get("HTTP_ACCESS_CONTROL_REQUEST_HEADERS") or "").strip()
    configured_headers = [item.strip() for item in DEFAULT_CORS_ALLOWED_HEADERS.split(",") if item.strip()]
    requested = {item.strip().lower() for item in request_headers.split(",") if item.strip()}
    allowed_headers = ", ".join(
        item for item in configured_headers if not requested or item.lower() in requested
    )
    headers = [
        ("Access-Control-Allow-Origin", origin or "*"),
        ("Access-Control-Allow-Methods", DEFAULT_CORS_ALLOWED_METHODS),
        ("Access-Control-Allow-Headers", allowed_headers),
        ("Access-Control-Max-Age", "600"),
        ("Access-Control-Expose-Headers", "Content-Length, Content-Type"),
    ]
    if origin and origin != "*":
        headers.append(("Vary", "Origin"))
    return headers


def _cors_start_response(environ, start_response):
    cors_headers = _cors_headers(environ)

    def wrapped(status, response_headers, exc_info=None):
        existing = {key.lower() for key, _value in response_headers}
        merged = list(response_headers)
        for key, value in cors_headers:
            if key.lower() not in existing:
                merged.append((key, value))
        if exc_info is None:
            return start_response(status, merged)
        return start_response(status, merged, exc_info)

    return wrapped


def _route_cors_preflight(environ, start_response):
    if _cors_allowed_origin(environ) is None:
        return problem(start_response, "403 Forbidden", "CORS origin not allowed", "This origin is not allowed to call the MemoryEndpoints API.", "cors_origin_not_allowed")
    return response(
        start_response,
        "204 No Content",
        b"",
        "text/plain; charset=utf-8",
        headers=[("Allow", DEFAULT_CORS_ALLOWED_METHODS)],
    )


def _protected_query_url(route, params):
    active = {}
    for key, value in (params or {}).items():
        if value is not None and value != "":
            active[key] = value
    return route + ("?" + urlencode(active) if active else "")


def _meeting_post_confirmation(store, workspace_id, room, message):
    room = room or {}
    message = message or {}
    room_id = room.get("roomId") or message.get("roomId")
    sender_agent_id = message.get("senderAgentId") or ""
    _room, messages, _read_state = store.meeting_messages(workspace_id, room_id, sender_agent_id, 200)
    visible = any(item.get("meetingMessageId") == message.get("meetingMessageId") for item in messages)
    return {
        "persisted": visible,
        "visibleToSender": visible,
        "canonicalRoomId": room_id,
        "messageId": message.get("meetingMessageId"),
        "transcriptQueryUrl": _protected_query_url(
            "/api/matm/meeting-messages",
            {
                "workspace_id": workspace_id,
                "room_id": room_id,
                "agent_id": sender_agent_id,
            },
        ),
        "valuesRedacted": True,
    }


def _memory_submission_confirmation(store, workspace_id, event):
    event = event or {}
    filters = {
        "scope": event.get("scope") or "",
        "scopeId": event.get("scopeId") or "",
        "memoryType": event.get("memoryType") or "",
        "eventId": event.get("eventId") or "",
    }
    search_items = store.search_memory(workspace_id, "", filters)
    visible_in_search = any(item.get("eventId") == event.get("eventId") for item in search_items)
    review_items = store.review_queue(workspace_id, "")
    visible_in_review_queue = any(item.get("memoryEventId") == event.get("eventId") for item in review_items)
    audit_items = store.audit_log(workspace_id, 50, "memory.submit")
    visible_in_audit_log = any(item.get("target") == event.get("eventId") for item in audit_items)
    return {
        "persisted": bool(event.get("eventId") and (visible_in_search or visible_in_review_queue) and visible_in_audit_log),
        "visibleInSearch": visible_in_search,
        "visibleInReviewQueue": visible_in_review_queue,
        "canonicalMemoryEventId": event.get("eventId"),
        "reviewId": event.get("reviewId"),
        "memoryQueryUrl": _protected_query_url(
            "/api/matm/search",
            {
                "workspace_id": workspace_id,
                "q": "",
                "event_id": event.get("eventId"),
                "scope": event.get("scope"),
                "scope_id": event.get("scopeId"),
                "memory_type": event.get("memoryType"),
            },
        ),
        "reviewQueueUrl": _protected_query_url(
            "/api/matm/review-queue",
            {
                "workspace_id": workspace_id,
                "status": event.get("reviewStatus") or "pending",
            },
        ),
        "valuesRedacted": True,
    }


def _knowledge_document_confirmation(store, workspace_id, document):
    document = document or {}
    document_id = document.get("searchDocumentId") or ""
    filters = {"documentId": document_id}
    search_items = store.knowledge_documents(workspace_id, filters, limit=10, include_text=False)
    visible_in_search = any(item.get("searchDocumentId") == document_id for item in search_items)
    tree = store.knowledge_tree(
        workspace_id,
        {
            "scope": document.get("scope") or "",
            "scopeId": document.get("scopeId") or "",
            "category": document.get("category") or "",
        },
    )
    visible_in_tree = any(
        item.get("searchDocumentId") == document_id
        for level in tree.get("levels", [])
        for category in level.get("categories", [])
        for item in category.get("documents", [])
    )
    audit_items = store.audit_log(workspace_id, 50, "knowledge_document.upsert")
    visible_in_audit = any(item.get("target") == document_id for item in audit_items)
    return {
        "persisted": bool(document_id and visible_in_search and visible_in_tree and visible_in_audit),
        "visibleInSearch": visible_in_search,
        "visibleInWikiTree": visible_in_tree,
        "canonicalSearchDocumentId": document_id,
        "canonicalSourceId": document.get("sourceId"),
        "documentQueryUrl": _protected_query_url(
            "/api/matm/knowledge-documents",
            {
                "workspace_id": workspace_id,
                "document_id": document_id,
                "include_text": "1",
            },
        ),
        "searchQueryUrl": _protected_query_url(
            "/api/matm/knowledge-documents",
            {
                "workspace_id": workspace_id,
                "q": document.get("title"),
                "scope": document.get("scope"),
                "scope_id": document.get("scopeId"),
                "category": document.get("category"),
            },
        ),
        "treeQueryUrl": _protected_query_url(
            "/api/matm/knowledge-tree",
            {
                "workspace_id": workspace_id,
                "scope": document.get("scope"),
                "scope_id": document.get("scopeId"),
            },
        ),
        "valuesRedacted": True,
    }


def _external_link_confirmation(store, workspace_id, link, document_id=""):
    link = link or {}
    external_link_id = link.get("externalLinkId") or ""
    items = store.external_links(workspace_id, {"externalLinkId": external_link_id}, limit=10)
    persisted_link = next((item for item in items if item.get("externalLinkId") == external_link_id), None)
    visible_on_document = not document_id or any(
        mention.get("knowledgeDocumentId") == document_id
        for mention in (persisted_link or {}).get("mentions", [])
    )
    audit_items = store.audit_log(workspace_id, 50, "external_link.upsert")
    visible_in_audit = any(item.get("target") == external_link_id for item in audit_items)
    return {
        "persisted": bool(external_link_id and persisted_link and visible_on_document and visible_in_audit),
        "visibleInInternetSearch": bool(persisted_link),
        "visibleOnKnowledgeDocument": visible_on_document,
        "canonicalExternalLinkId": external_link_id,
        "linkQueryUrl": _protected_query_url(
            "/api/matm/external-links",
            {"workspace_id": workspace_id, "external_link_id": external_link_id},
        ),
        "internetSearchQueryUrl": _protected_query_url(
            "/api/matm/internet-search",
            {
                "workspace_id": workspace_id,
                "q": link.get("pageTitle") or link.get("siteName"),
            },
        ),
        "knowledgeDocumentLinksQueryUrl": (
            _protected_query_url(
                "/api/matm/external-links",
                {"workspace_id": workspace_id, "document_id": document_id},
            )
            if document_id
            else None
        ),
        "valuesRedacted": True,
    }


def _knowledge_filters(query):
    return {
        "q": query.get("q") or query.get("query") or "",
        "scope": query.get("scope") or "",
        "scopeId": query.get("scope_id") or query.get("scopeId") or "",
        "category": query.get("category") or "",
        "documentType": query.get("document_type") or query.get("documentType") or "",
        "knowledgeStatus": query.get("knowledge_status") or query.get("knowledgeStatus") or "",
        "authorityLevel": query.get("authority_level") or query.get("authorityLevel") or "",
        "taxonomyPath": query.get("taxonomy_path") or query.get("taxonomyPath") or query.get("taxonomy_prefix") or query.get("taxonomyPrefix") or "",
        "sourcePrefix": query.get("source_prefix") or query.get("sourcePrefix") or "",
        "documentId": query.get("document_id") or query.get("documentId") or query.get("search_document_id") or query.get("searchDocumentId") or "",
        "routeOrPath": query.get("route_or_path") or query.get("routeOrPath") or "",
    }


def _external_link_filters(query):
    return {
        "q": query.get("q") or query.get("query") or "",
        "externalLinkId": query.get("external_link_id") or query.get("externalLinkId") or "",
        "documentId": query.get("document_id") or query.get("documentId") or query.get("knowledge_document_id") or query.get("knowledgeDocumentId") or "",
        "host": query.get("host") or "",
        "siteName": query.get("site_name") or query.get("siteName") or "",
        "reviewStatus": query.get("review_status") or query.get("reviewStatus") or "",
        "crawlStatus": query.get("crawl_status") or query.get("crawlStatus") or "",
        "relationshipType": query.get("relationship_type") or query.get("relationshipType") or "",
        "scope": query.get("scope") or "",
        "scopeId": query.get("scope_id") or query.get("scopeId") or "",
        "taxonomyPath": query.get("taxonomy_path") or query.get("taxonomyPath") or query.get("taxonomy_prefix") or query.get("taxonomyPrefix") or "",
    }


def _scope_allowed_cached(store, auth, cache, scope, scope_id):
    key = (str(scope or "").strip().lower(), str(scope_id or "").strip())
    if key not in cache:
        cache[key] = store.auth_allows_scope(auth, key[0], key[1])
    return cache[key]


def _authorized_scope_items(store, auth, items):
    scope_cache = {}
    return [
        item
        for item in items
        if _scope_allowed_cached(
            store, auth, scope_cache, item.get("scope"), item.get("scopeId")
        )
    ]


def _authorized_external_link_items(store, workspace_id, auth, filters, limit):
    """Authorize links and their mentions before ranking and pagination."""
    storage_filters = dict(filters or {})
    query_text = storage_filters.pop("q", "") or ""
    # These filters depend on mentions. Applying them in storage before scope
    # filtering can reveal a link because of a hidden sibling mention.
    for key in ("documentId", "relationshipType", "scope", "scopeId", "taxonomyPath"):
        storage_filters.pop(key, None)
    candidates = store.external_links(
        workspace_id, storage_filters, limit=limit, _all=True
    )
    requested_document_id = (filters or {}).get("documentId") or ""
    requested_relationship = str(
        (filters or {}).get("relationshipType") or ""
    ).strip().lower()
    requested_scope = str((filters or {}).get("scope") or "").strip().lower()
    requested_scope_id = (filters or {}).get("scopeId") or ""
    requested_taxonomy = (filters or {}).get("taxonomyPath") or ""
    wanted_taxonomy = [
        segment.lower() for segment in _normalize_taxonomy_path(requested_taxonomy)
    ]
    visible_items = []
    scope_cache = {}
    for item in candidates:
        mentions = item.get("mentions") or []
        visible_mentions = [
            mention
            for mention in mentions
            if _scope_allowed_cached(
                store,
                auth,
                scope_cache,
                mention.get("scope"),
                mention.get("scopeId"),
            )
        ]
        if mentions and not visible_mentions:
            continue
        if not mentions and not _scope_allowed_cached(
            store, auth, scope_cache, "workspace", workspace_id
        ):
            continue
        if requested_document_id and not any(
            mention.get("knowledgeDocumentId") == requested_document_id
            for mention in visible_mentions
        ):
            continue
        if requested_relationship and not any(
            str(mention.get("relationshipType") or "").lower()
            == requested_relationship
            for mention in visible_mentions
        ):
            continue
        if requested_scope and not any(
            str(mention.get("scope") or "").lower() == requested_scope
            for mention in visible_mentions
        ):
            continue
        if requested_scope_id and not any(
            mention.get("scopeId") == requested_scope_id
            for mention in visible_mentions
        ):
            continue
        if wanted_taxonomy and not any(
            any(
                [
                    segment.lower()
                    for segment in _normalize_taxonomy_path(path_label)
                ][: len(wanted_taxonomy)]
                == wanted_taxonomy
                for path_label in mention.get("taxonomyPathLabels") or []
            )
            for mention in visible_mentions
        ):
            continue
        visible_item = _public_external_link(item, visible_mentions, query_text)
        if query_text and not visible_item.get("matchScore"):
            continue
        visible_items.append(visible_item)
    visible_items.sort(
        key=lambda item: (
            -int(item.get("matchScore") or 0),
            item.get("siteName") or "",
            item.get("pageTitle") or "",
            item.get("externalLinkId") or "",
        )
    )
    return visible_items[: _parse_limit(limit, 50, 500)]


def _external_link_operator_summary(items, filters):
    hosts = {}
    sites = {}
    for item in items or []:
        host = item.get("host") or "unknown"
        site = item.get("siteName") or host
        hosts[host] = hosts.get(host, 0) + 1
        sites[site] = sites.get(site, 0) + 1
    return {
        "schemaVersion": "memoryendpoints.external_link_search_operator_summary.v1",
        "resultCount": len(items or []),
        "hostCounts": hosts,
        "siteCounts": sites,
        "activeFilters": sorted(key for key, value in (filters or {}).items() if value),
        "searchMode": "curated_external_links",
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _listish_values(value):
    if isinstance(value, str):
        return [item.strip() for item in value.replace("|", ",").replace(";", ",").split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _knowledge_taxonomy_values(body):
    value = body.get("taxonomyPaths") or body.get("taxonomy_paths") or body.get("taxonomyPath") or body.get("taxonomy_path")
    if isinstance(value, list):
        return [item for item in value if item]
    if isinstance(value, str):
        return [item.strip() for item in value.split(";") if item.strip()]
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    value = metadata.get("taxonomyPaths") or metadata.get("taxonomyPath")
    if isinstance(value, list):
        return [item for item in value if item]
    if isinstance(value, str):
        return [item.strip() for item in value.split(";") if item.strip()]
    return []


def _resolve_knowledge_scope(store, workspace_id, body):
    status = store.workspace_status(workspace_id)
    if not status:
        return None, "workspace_not_found"
    scope = str(body.get("scope") or "workspace").strip().lower()
    if scope not in ("company", "workspace", "project"):
        return None, "unsupported_scope"
    payload = dict(body)
    if scope == "company":
        company_id = status.get("companyId") or ""
        requested = body.get("scopeId") or body.get("scope_id") or company_id
        if requested != company_id:
            return None, "scope_not_authorized"
        payload["scope"] = "company"
        payload["scopeId"] = company_id
        payload["projectId"] = None
        return payload, None
    if scope == "workspace":
        requested = body.get("scopeId") or body.get("scope_id") or workspace_id
        if requested != workspace_id:
            return None, "scope_not_authorized"
        payload["scope"] = "workspace"
        payload["scopeId"] = workspace_id
        payload["projectId"] = None
        return payload, None
    project_id = body.get("projectId") or body.get("project_id") or body.get("scopeId") or body.get("scope_id") or ""
    project_id = str(project_id).strip()
    if not project_id:
        return None, "project_id_required"
    projects = {project.get("projectId"): project for project in status.get("projects", [])}
    if project_id not in projects:
        # Project creation is a separate workspace-authorized mutation. Keeping
        # scope resolution read-only prevents a knowledge write from creating a
        # sibling project before its idempotency reservation and authority check.
        return None, "project_not_found"
    payload["scope"] = "project"
    payload["scopeId"] = project_id
    payload["projectId"] = project_id
    return payload, None


def _knowledge_operator_summary(items, filters):
    scope_counts = {}
    category_counts = {}
    status_counts = {}
    authority_counts = {}
    for item in items:
        scope = item.get("scope") or "unknown"
        category = item.get("category") or "uncategorized"
        scope_counts[scope] = scope_counts.get(scope, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1
        status = item.get("knowledgeStatus") or "current"
        authority = item.get("authorityLevel") or "reviewed"
        status_counts[status] = status_counts.get(status, 0) + 1
        authority_counts[authority] = authority_counts.get(authority, 0) + 1
    return {
        "schemaVersion": "memoryendpoints.knowledge_operator_summary.v2",
        "documentCount": len(items),
        "scopeCounts": dict(sorted(scope_counts.items())),
        "categoryCounts": dict(sorted(category_counts.items())),
        "knowledgeStatusCounts": dict(sorted(status_counts.items())),
        "authorityLevelCounts": dict(sorted(authority_counts.items())),
        "filters": {key: value for key, value in (filters or {}).items() if value},
        "databaseSourceOfTruth": True,
        "filesystemDocsIncluded": False,
        "taskLevelTreeSupported": False,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _current_message_confirmation(store, workspace_id, message, notes):
    message = message or {}
    notes = notes if isinstance(notes, list) else ([notes] if notes else [])
    notification_ids = [note.get("notificationId") for note in notes if note and note.get("notificationId")]
    message_target = message.get("targetAgentId") or ""
    recipient_agent_ids = []
    for note in notes:
        recipient = (note or {}).get("targetAgentId") or message_target or message.get("senderAgentId") or ""
        if recipient and recipient not in recipient_agent_ids:
            recipient_agent_ids.append(recipient)
    if not recipient_agent_ids:
        recipient_agent_ids = [message_target or message.get("senderAgentId") or ""]
    visible_agents = []
    for recipient_agent_id in recipient_agent_ids:
        inbox_items = store.inbox(workspace_id, recipient_agent_id, message.get("messageId"))
        visible = any(
            ((item.get("notification") or {}).get("notificationId") in notification_ids)
            or ((item.get("message") or {}).get("messageId") == message.get("messageId"))
            for item in inbox_items
        )
        if visible:
            visible_agents.append(recipient_agent_id)
    persisted = bool(recipient_agent_ids) and len(visible_agents) == len(recipient_agent_ids)
    first_recipient = recipient_agent_ids[0] if recipient_agent_ids else ""
    return {
        "persisted": persisted,
        "visibleToTarget": persisted,
        "visibleToAgents": visible_agents,
        "visibleRecipientCount": len(visible_agents),
        "expectedRecipientCount": len(recipient_agent_ids),
        "canonicalTargetAgentId": message_target,
        "messageId": message.get("messageId"),
        "notificationId": notification_ids[0] if notification_ids else "",
        "notificationIds": notification_ids,
        "inboxQueryUrl": _protected_query_url(
            "/api/matm/current-message",
            {
                "workspace_id": workspace_id,
                "agent_id": message_target or first_recipient,
                "message_id": message.get("messageId"),
                "notification_id": notification_ids[0] if len(notification_ids) == 1 else "",
            },
        ),
        "valuesRedacted": True,
    }


def _sync_retention_policy():
    return {
        "schemaVersion": "memoryendpoints.sync_retention.v1",
        "tombstoneRetentionDays": 30,
        "hardForgetSupported": False,
        "hardForgetBehavior": "safe_rejected_receipt",
        "rawPrivatePayloadStored": False,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _sync_operator_summary(action, payload=None):
    payload = payload or {}
    receipt = payload.get("receipt") or {}
    return {
        "schemaVersion": "memoryendpoints.sync_operator_summary.v1",
        "action": action,
        "status": payload.get("status") or receipt.get("status") or "unknown",
        "serverSequence": payload.get("serverSequence") or receipt.get("serverSequence") or 0,
        "conflict": bool(payload.get("conflict") or receipt.get("conflict")),
        "conflictCode": receipt.get("conflictCode") or "",
        "persisted": bool(payload.get("persisted")),
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _sync_mutation_confirmation(store, workspace_id, payload):
    receipt = payload.get("receipt") or {}
    revision = payload.get("revision") or {}
    receipt_id = receipt.get("receiptId") or ""
    revision_id = revision.get("syncRevisionId") or ""
    logical_memory_id = receipt.get("logicalMemoryId") or revision.get("logicalMemoryId") or ""
    try:
        visible_receipt = store.sync_receipt(workspace_id, receipt_id=receipt_id) if receipt_id else None
        changes = {"items": [], "count": 0, "indexedThroughSequence": 0}
        revision_visible_in_changes = True
        if revision_id:
            after_sequence = max(0, int(payload.get("serverSequence") or revision.get("serverSequence") or 0) - 1)
            changes = store.sync_changes(workspace_id, after_sequence, 50, logical_memory_id)
            revision_visible_in_changes = any(item.get("syncRevisionId") == revision_id for item in changes.get("items") or [])
        heads = []
        head_visible = True
        if payload.get("status") == "applied" and revision_id:
            heads = store.sync_heads(workspace_id, logical_memory_id)
            head_visible = any(item.get("headRevisionId") == revision_id for item in heads)
        persisted = bool(visible_receipt and revision_visible_in_changes and head_visible)
        return {
            "schemaVersion": "memoryendpoints.sync_mutation_confirmation.v1",
            "persisted": persisted,
            "receiptVisible": bool(visible_receipt),
            "revisionVisibleInChanges": bool(revision_visible_in_changes),
            "headVisible": bool(head_visible),
            "changesCount": changes.get("count", 0),
            "headsCount": len(heads),
            "receiptId": receipt_id,
            "revisionId": revision_id,
            "logicalMemoryId": logical_memory_id,
            "indexedThroughSequence": changes.get("indexedThroughSequence", 0),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
    except Exception as exc:
        return {
            "schemaVersion": "memoryendpoints.sync_mutation_confirmation.v1",
            "persisted": False,
            "receiptVisible": False,
            "revisionVisibleInChanges": False,
            "headVisible": False,
            "errorFingerprint": _diagnostic_fingerprint(str(exc)),
            "errorType": exc.__class__.__name__,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }


def _sync_query_url(route, workspace_id, params=None):
    active = {"workspace_id": workspace_id}
    active.update(params or {})
    return _protected_query_url(route, active)


def _admin_diagnostics_path():
    return Path(
        os.environ.get(
            "MEMORYENDPOINTS_ADMIN_DIAGNOSTICS_PATH",
            str(ROOT / ".local-secrets" / "admin-diagnostics.json"),
        )
    )


def _admin_diagnostics_authorized(environ):
    path = _admin_diagnostics_path()
    if not path.exists():
        return False, "not_configured"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return False, "invalid_config"
    expected_hash = str(payload.get("tokenHash") or "").strip().lower()
    if not expected_hash:
        return False, "missing_token_hash"
    auth = str(environ.get("HTTP_AUTHORIZATION") or "").strip()
    token = auth.split(" ", 1)[1].strip() if auth.lower().startswith("bearer ") and " " in auth else ""
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return hmac.compare_digest(token_hash, expected_hash), "configured"


def _diagnostic_fingerprint(value):
    if value is None:
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]


def _store():
    backend = configured_store_backend()
    if backend in ("mysql", "mariadb"):
        return MySQLStore()
    if backend == "sqlite":
        return SQLiteStore()
    return FileStore()


def _require_auth(environ, workspace_id):
    token = _token(environ)
    if not token:
        return None
    auth = _store().authenticate(token, workspace_id)
    return auth


def _anonymous_auth_required(start_response):
    return problem(
        start_response,
        "401 Unauthorized",
        "Authentication required",
        "A valid governed bearer credential is required.",
        "auth_required",
        headers=[("WWW-Authenticate", 'Bearer realm="MemoryEndpoints"')],
    )


MASTER_CAPABILITIES = (
    "company:read",
    "company:write",
    "workspace:read",
    "workspace:write",
    "project:read",
    "project:write",
    "access:manage",
    "agent_credentials:revoke",
    "company_master_credentials:delegate",
)
AGENT_CAPABILITIES = (
    "scope:read",
    "scope:write",
    "self:memory",
    "self:message",
)

AGENT_NAME_POLICY = {
    "scope": "company",
    "uniqueness": "normalized_name_within_company",
    "normalization": "lowercase",
    "minLength": 3,
    "maxLength": 64,
    "pattern": r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    "guidance": "Choose a short, meaningful name that humans can recognize in rooms and audit history.",
    "displayName": {
        "minLength": 1,
        "maxLength": 80,
        "normalization": "trim_and_collapse_whitespace",
        "controlCharactersAllowed": False,
    },
}


def _is_connector_principal(auth):
    auth = auth or {}
    return bool(
        auth.get("publicCredentialType") == "connector_agent"
        or auth.get("credentialType") == "connector_agent"
        or auth.get("authType") == "connector_agent"
    )


def _principal_scope_type(auth):
    auth = auth or {}
    grant = auth.get("grant") if isinstance(auth.get("grant"), dict) else {}
    return str(
        auth.get("scopeType")
        or grant.get("scopeType")
        or ("company" if auth.get("credentialType") == "company_master" else "")
    ).strip().lower()


def _connector_principal_scopes(auth):
    if not _is_connector_principal(auth):
        return []
    scopes = (auth or {}).get("approvedScopes") or (auth or {}).get("requestedScopes")
    try:
        scopes = list(validate_requested_scopes(scopes))
        expected_digest = connector_scope_digest(scopes)
        if not hmac.compare_digest(
            str((auth or {}).get("scopeDigest") or ""), expected_digest
        ):
            return []
        return scopes
    except PairingPolicyError:
        return []


def _auth_capabilities(auth):
    if _is_connector_principal(auth):
        return _connector_principal_scopes(auth)
    if (auth or {}).get("credentialType") == "company_master":
        return list(MASTER_CAPABILITIES)
    if (auth or {}).get("credentialType") == "agent":
        return list(AGENT_CAPABILITIES)
    return []


def _auth_permissions(auth):
    if _is_connector_principal(auth):
        scopes = frozenset(_connector_principal_scopes(auth))
        return {
            "canRead": "connector:self:readback" in scopes,
            "canWrite": bool(
                {"agent:self:register", "memory:public-safe:submit"} & scopes
            ),
            "canApproveAgentAccess": False,
            "canIssueAgentInvites": False,
            "canListAgentTokens": False,
            "canRevokeAgentTokens": False,
            "canDelegateCompanyMasterCredentials": False,
            "canManageCompany": False,
            "canAccessWorkspaceOperations": False,
            "canReadConnectorSelf": "connector:self:readback" in scopes,
            "canConfirmConnectorAgentRegistration": "agent:self:register" in scopes,
            "canSubmitPublicSafeMemory": "memory:public-safe:submit" in scopes,
            "canSearchMemory": "memory:search:read" in scopes,
        }
    company_master = (auth or {}).get("credentialType") == "company_master"
    governed = company_master or (auth or {}).get("credentialType") == "agent"
    return {
        "canRead": governed,
        "canWrite": governed,
        "canApproveAgentAccess": company_master,
        "canIssueAgentInvites": company_master,
        "canListAgentTokens": company_master,
        "canRevokeAgentTokens": company_master,
        "canDelegateCompanyMasterCredentials": company_master,
        "canManageCompany": company_master,
        "canAccessWorkspaceOperations": governed,
    }


def _auth_actor_id(auth):
    if (auth or {}).get("credentialType") == "agent":
        return auth.get("agentId") or ""
    return (auth or {}).get("principalName") or ""


def _is_npc_principal(auth):
    return (
        (auth or {}).get("credentialType") == "agent"
        and str((auth or {}).get("agentId") or "").strip().lower().startswith("npc-")
    )


def _npc_meeting_scope_allowed(auth, scope):
    if not _is_npc_principal(auth):
        return True
    return str(scope or "").strip().lower() in NPC_MEETING_SCOPE_TYPES


def _npc_room_allowed(auth, room):
    return _npc_meeting_scope_allowed(auth, (room or {}).get("scope"))


def _public_auth_principal(auth):
    internal_credential_type = (auth or {}).get("credentialType")
    credential_type = (auth or {}).get("publicCredentialType") or (
        "agent_token" if internal_credential_type == "agent" else internal_credential_type
    )
    scope_type = (auth or {}).get("scopeType") or ("company" if internal_credential_type == "company_master" else None)
    scope_id = (auth or {}).get("scopeId") or ((auth or {}).get("companyId") if scope_type == "company" else None)
    credential_id = (
        (auth or {}).get("masterKeyId")
        or (auth or {}).get("connectorCredentialId")
        or (auth or {}).get("agentTokenId")
    )
    connector = _is_connector_principal(auth)
    approved_scopes = _connector_principal_scopes(auth) if connector else None
    approved_scope_digest = (
        (auth or {}).get("scopeDigest")
        or (connector_scope_digest(approved_scopes) if approved_scopes else None)
    )
    return {
        "credentialId": credential_id,
        "credentialType": credential_type,
        "ordinaryAgentCredential": internal_credential_type == "agent",
        "masterCompanyAgentCredential": internal_credential_type == "company_master",
        "companyId": (auth or {}).get("companyId"),
        "agentIdentityId": (auth or {}).get("agentIdentityId"),
        "agentId": (auth or {}).get("agentId")
        if internal_credential_type == "agent" or connector
        else None,
        "displayName": (auth or {}).get("agentName") or (auth or {}).get("principalName"),
        "grantId": (auth or {}).get("grantId"),
        "resourceContext": {
            "workspaceId": (auth or {}).get("workspaceId"),
            "projectId": (auth or {}).get("projectId"),
        },
        "grant": {
            "grantId": (auth or {}).get("grantId"),
            "scopeType": scope_type,
            "scopeId": scope_id,
            "accessRule": "exact_connector_and_agent" if connector else "scope_and_descendants",
            "immutable": True,
            **(
                {
                    "approvedScopes": approved_scopes,
                    "scopeDigest": approved_scope_digest,
                }
                if connector
                else {}
            ),
            "supersedesCredentialId": (auth or {}).get("supersedesCredentialId") or (auth or {}).get("supersedesTokenId"),
            "memoryTransferFromCredentialId": (auth or {}).get("memoryTransferFromCredentialId") or (auth or {}).get("memoryTransferFromTokenId"),
        },
        "capabilities": _auth_capabilities(auth),
        "permissions": _auth_permissions(auth),
        **(
            {
                "approvedScopes": approved_scopes,
                "scopeDigest": approved_scope_digest,
            }
            if connector
            else {}
        ),
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _access_problem(start_response, code, detail=None):
    statuses = {
        "invalid_token": "401 Unauthorized",
        "company_master_required": "403 Forbidden",
        "top_level_agent_required": "403 Forbidden",
        "top_level_agent_master_credential_disabled": "403 Forbidden",
        "capability_required": "403 Forbidden",
        "principal_mismatch": "403 Forbidden",
        "agent_identity_mismatch": "403 Forbidden",
        "insufficient_scope": "403 Forbidden",
        "npc_scope_forbidden": "403 Forbidden",
        "npc_game_scope_required": "403 Forbidden",
        "resource_not_found": "404 Not Found",
        "access_request_not_found": "404 Not Found",
        "invite_not_found": "404 Not Found",
        "agent_token_not_found": "404 Not Found",
        "workspace_not_found": "404 Not Found",
        "agent_name_invalid": "422 Unprocessable Entity",
        "access_decision_invalid": "422 Unprocessable Entity",
        "scope_invalid": "422 Unprocessable Entity",
        "scope_not_in_company": "422 Unprocessable Entity",
        "idempotency_key_required": "422 Unprocessable Entity",
        "idempotency_key_invalid": "422 Unprocessable Entity",
        "idempotency_key_not_allowed": "422 Unprocessable Entity",
        "company_master_candidate_invalid": "422 Unprocessable Entity",
        "company_master_metadata_invalid": "422 Unprocessable Entity",
        "company_master_delegation_invalid": "422 Unprocessable Entity",
        "top_level_agent_master_credential_request_invalid": "422 Unprocessable Entity",
        "referenced_agent_token_invalid": "422 Unprocessable Entity",
        "agent_name_unavailable": "409 Conflict",
        "approval_already_final": "409 Conflict",
        "agent_name_request_not_approved": "409 Conflict",
        "access_request_not_pending": "409 Conflict",
        "invite_already_active": "409 Conflict",
        "one_time_secret_already_delivered": "409 Conflict",
        "invite_not_revocable": "409 Conflict",
        "agent_token_already_revoked": "409 Conflict",
        "idempotency_conflict": "409 Conflict",
        "company_master_credential_exists": "409 Conflict",
        "company_master_credential_limit": "409 Conflict",
        "invite_expired": "410 Gone",
        "invite_redeemed": "410 Gone",
        "invite_revoked": "410 Gone",
        "invalid_invite": "401 Unauthorized",
        "invite_unavailable": "401 Unauthorized",
        "rate_limited": "429 Too Many Requests",
        "credential_system_not_configured": "503 Service Unavailable",
    }
    defaults = {
        "invalid_token": "A valid governed bearer credential is required.",
        "company_master_required": "A company master credential is required for this access-management operation.",
        "top_level_agent_required": "An active company-scoped top-level agent credential is required for this operation.",
        "top_level_agent_master_credential_disabled": "An authenticated human administrator has disabled top-level-agent company-master issuance for this company.",
        "capability_required": "The authenticated credential does not have the required capability.",
        "principal_mismatch": "The requested acting identity does not match the authenticated principal.",
        "agent_identity_mismatch": "The requested agent identity does not match the connector credential's exact agent grant.",
        "insufficient_scope": "The requested resource is outside the credential's immutable grant scope.",
        "npc_scope_forbidden": "NPC credentials may only be issued at project, game, or session scope.",
        "npc_game_scope_required": "NPC-to-NPC communication is allowed only inside game or session meeting rooms.",
        "resource_not_found": "No matching resource is visible to the authenticated principal.",
        "invalid_invite": "The one-time invitation is invalid.",
        "invite_unavailable": "The one-time invitation is unavailable.",
        "invite_expired": "The one-time invitation has expired and cannot be reopened.",
        "invite_redeemed": "The one-time invitation has already been redeemed.",
        "invite_revoked": "The one-time invitation has been revoked.",
        "credential_system_not_configured": "Governed credential verification is not configured.",
        "workspace_not_found": "The selected workspace was not found in the authenticated company.",
        "idempotency_key_required": "A high-entropy Idempotency-Key header is required.",
        "idempotency_key_invalid": "The Idempotency-Key header is invalid.",
        "idempotency_key_not_allowed": "One-time invitation issue and redemption operations do not accept Idempotency-Key because their raw secret responses are never persisted or replayed.",
        "idempotency_conflict": "The Idempotency-Key was already used for a different company-master credential request.",
        "company_master_candidate_invalid": "The candidate must be a newly generated company-master credential in the published v1 format.",
        "company_master_metadata_invalid": "The company-master label and principal name must be printable text from 1 through 80 characters.",
        "company_master_delegation_invalid": "The request must match the published company-master delegation v1 schema exactly.",
        "top_level_agent_master_credential_request_invalid": "The request must match the published top-level-agent company-master v1 schema exactly.",
        "company_master_credential_exists": "The candidate company-master credential is already registered or unavailable.",
        "company_master_credential_limit": "The company has reached the active company-master credential safety limit.",
    }
    status = statuses.get(code, "422 Unprocessable Entity")
    headers = list(_CONNECTOR_JSON_HEADERS)
    if status.startswith("401"):
        headers.append(("WWW-Authenticate", 'Bearer realm="MemoryEndpoints", error="invalid_token"'))
    if code == "agent_name_invalid":
        return json_response(
            start_response,
            {
                "ok": False,
                "safeNoOp": True,
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
                "error": {
                    "code": code,
                    "title": "Access operation rejected",
                    "detail": detail or "The requested agent name does not satisfy the human-readable company name policy.",
                    "safeNoOp": True,
                    "valuesRedacted": True,
                    "details": {"namePolicy": AGENT_NAME_POLICY},
                },
            },
            status,
            headers,
        )
    return problem(start_response, status, "Access operation rejected", detail or defaults.get(code, "The access operation was safely rejected."), code, headers=headers)


def _company_master_or_problem(auth, start_response):
    if (auth or {}).get("credentialType") != "company_master":
        return _access_problem(start_response, "company_master_required")
    return None


def _bound_agent_id_or_problem(auth, start_response, *candidate_ids):
    actor_id = _auth_actor_id(auth)
    if not actor_id:
        return None, _access_problem(start_response, "principal_mismatch")
    for candidate in candidate_ids:
        if candidate is not None and str(candidate).strip() and str(candidate).strip() != actor_id:
            code = "agent_identity_mismatch" if (auth or {}).get("publicCredentialType") == "connector_agent" else "principal_mismatch"
            return None, _access_problem(start_response, code)
    return actor_id, None


def _request_cookie(environ, name):
    raw = environ.get("HTTP_COOKIE") or ""
    if not raw:
        return ""
    cookie = SimpleCookie()
    try:
        cookie.load(raw)
    except Exception:
        return ""
    morsel = cookie.get(name)
    return morsel.value if morsel else ""


def _site_origin():
    parsed = urlsplit(SITE_URL)
    return "%s://%s" % (parsed.scheme.lower(), parsed.netloc.lower())


def _human_same_origin(environ):
    if str(environ.get("HTTP_SEC_FETCH_SITE") or "").strip().lower() != "same-origin":
        return False
    origin = str(environ.get("HTTP_ORIGIN") or "").strip().rstrip("/").lower()
    if origin:
        return origin == _site_origin()
    referer = str(environ.get("HTTP_REFERER") or "").strip()
    if not referer:
        return False
    parsed = urlsplit(referer)
    return "%s://%s" % (parsed.scheme.lower(), parsed.netloc.lower()) == _site_origin()


def _human_fetch_same_origin(environ):
    """Accept browser-generated Fetch Metadata for a same-origin read fetch."""
    return (
        str(environ.get("HTTP_SEC_FETCH_SITE") or "").strip().lower() == "same-origin"
        and str(environ.get("HTTP_SEC_FETCH_MODE") or "").strip().lower() in ("cors", "same-origin")
        and str(environ.get("HTTP_SEC_FETCH_DEST") or "").strip().lower() in ("", "empty")
    )


def _human_problem(start_response, code, detail=None):
    statuses = {
        "human_session_required": "401 Unauthorized",
        "human_account_session_required": "401 Unauthorized",
        "human_login_failed": "401 Unauthorized",
        "human_owner_recovery_required": "401 Unauthorized",
        "human_owner_required": "403 Forbidden",
        "human_credential_authority_required": "403 Forbidden",
        "recovery_session_restricted": "403 Forbidden",
        "trusted_origin_required": "403 Forbidden",
        "csrf_required": "403 Forbidden",
        "csrf_invalid": "403 Forbidden",
        "human_reauthentication_failed": "403 Forbidden",
        "human_reauthentication_required": "403 Forbidden",
        "recent_reauthentication_required": "403 Forbidden",
        "human_username_invalid": "422 Unprocessable Entity",
        "human_display_name_invalid": "422 Unprocessable Entity",
        "username_password_required": "400 Bad Request",
        "human_username_unavailable": "409 Conflict",
        "human_password_invalid": "422 Unprocessable Entity",
        "human_company_authority_exists": "409 Conflict",
        "human_company_authority_not_found": "404 Not Found",
        "company_master_proof_invalid": "401 Unauthorized",
        "company_master_proof_required": "422 Unprocessable Entity",
        "company_master_proof_expired": "410 Gone",
        "company_master_proof_used": "410 Gone",
        "selected_company_required": "409 Conflict",
        "human_company_not_found": "404 Not Found",
        "top_level_agent_master_credential_setting_invalid": "422 Unprocessable Entity",
        "replacement_not_found": "404 Not Found",
        "replacement_predecessor_inactive": "409 Conflict",
        "replacement_pending": "409 Conflict",
        "replacement_unavailable": "409 Conflict",
        "replacement_binding_invalid": "422 Unprocessable Entity",
        "successor_token_proof_required": "403 Forbidden",
        "idempotency_key_required": "422 Unprocessable Entity",
        "idempotency_key_invalid": "422 Unprocessable Entity",
        "idempotency_conflict": "409 Conflict",
        "replacement_expired": "410 Gone",
        "company_not_found": "404 Not Found",
        "export_opportunity_acknowledgement_required": "422 Unprocessable Entity",
        "closure_purpose_invalid": "422 Unprocessable Entity",
        "typed_confirmation_mismatch": "422 Unprocessable Entity",
        "company_label_confirmation_mismatch": "422 Unprocessable Entity",
        "company_must_be_closed": "409 Conflict",
        "company_must_be_soft_deleted": "409 Conflict",
        "export_receipt_or_no_export_acknowledgement_required": "422 Unprocessable Entity",
        "export_receipt_or_deletion_acknowledgement_required": "422 Unprocessable Entity",
        "closure_intent_invalid": "410 Gone",
        "closure_intent_unavailable": "410 Gone",
        "lifecycle_intent_invalid": "410 Gone",
        "lifecycle_intent_expired": "410 Gone",
        "lifecycle_intent_used": "410 Gone",
    }
    defaults = {
        "human_session_required": "A valid short-lived human-owner session is required.",
        "human_login_failed": (
            "Sign-in failed. The username or password was not accepted, or the account is "
            "unavailable. Check both and try again. For security, MemoryEndpoints does not "
            "reveal which condition occurred."
        ),
        "human_owner_required": "Agent and company-master credentials cannot use the human-owner control plane.",
        "trusted_origin_required": "Human account actions require the trusted same-origin browser context and Fetch Metadata.",
        "csrf_required": "The human session requires its in-memory CSRF token.",
        "csrf_invalid": "The CSRF token does not match the human session.",
        "human_reauthentication_failed": (
            "The password was not accepted for the signed-in account. "
            "Enter the current account password and try again."
        ),
        "recent_reauthentication_required": "Re-enter the account password before this sensitive action.",
        "top_level_agent_master_credential_setting_invalid": "The setting payload must contain exactly one boolean enabled value.",
        "export_opportunity_acknowledgement_required": "Review the company export opportunity before continuing.",
    }
    titles = {
        "human_login_failed": "Sign-in not completed",
        "human_reauthentication_failed": "Password confirmation failed",
    }
    return problem(
        start_response,
        statuses.get(code, "422 Unprocessable Entity"),
        titles.get(code, "Human-owner operation rejected"),
        detail or defaults.get(code, "The human-owner operation was safely rejected."),
        code,
        headers=list(_CONNECTOR_JSON_HEADERS),
    )


def _human_storage_error(start_response, result):
    code = (result or {}).get("status") or "human_operation_failed"
    aliases = {
        "human_account_session_required": "human_session_required",
        "company_master_proof_consumed": "company_master_proof_used",
        "company_master_proof_unavailable": "company_master_proof_used",
        "human_company_authority_not_found": "human_company_not_found",
        "agent_token_replacement_expired": "replacement_expired",
        "human_reauthentication_required": "recent_reauthentication_required",
    }
    return _human_problem(start_response, aliases.get(code, code))


def _human_session_auth(store, environ, start_response, company_id=None, mutation=False, allow_recovery=False):
    if str(environ.get("HTTP_AUTHORIZATION") or "").strip():
        return None, None, _human_problem(start_response, "human_owner_required")
    session_secret = _request_cookie(environ, HUMAN_SESSION_COOKIE)
    if not session_secret:
        return None, None, _human_problem(start_response, "human_session_required")
    if mutation and not _human_same_origin(environ):
        return None, None, _human_problem(start_response, "trusted_origin_required")
    csrf_token = str(environ.get("HTTP_X_CSRF_TOKEN") or "").strip()
    session = store.authenticate_human_account_session(session_secret)
    recovery_session = False
    if not session:
        recovered = store.authenticate_human_session(session_secret)
        if recovered:
            recovery_session = True
            session = {
                "credentialType": "recovery_closure_session",
                "authMode": "recovery_closure",
                "humanSessionId": recovered.get("humanSessionId"),
                "humanAccountSessionId": recovered.get("humanSessionId"),
                "humanAccountId": None,
                "username": None,
                "selectedAuthorityId": None,
                "companyId": recovered.get("companyId"),
                "role": "recovery_closure",
                "reauthenticatedAt": recovered.get("reauthenticatedAt"),
                "passwordReauthenticatedAt": recovered.get("reauthenticatedAt"),
                "expiresAt": recovered.get("expiresAt"),
            }
    if not session:
        return None, None, _human_problem(start_response, "human_session_required")
    if recovery_session and not allow_recovery:
        return None, None, _human_problem(start_response, "recovery_session_restricted")
    if company_id and not session.get("companyId"):
        return None, None, _human_problem(start_response, "selected_company_required")
    if company_id and session.get("companyId") != company_id:
        return None, None, _human_problem(start_response, "human_company_not_found")
    if mutation:
        if not csrf_token:
            return None, None, _human_problem(start_response, "csrf_required")
        valid_csrf_session = (
            store.authenticate_human_session(session_secret, csrf_token, require_csrf=True)
            if recovery_session
            else store.authenticate_human_account_session(session_secret, csrf_token, require_csrf=True)
        )
        if not valid_csrf_session:
            return None, None, _human_problem(start_response, "csrf_invalid")
    return session, session_secret, None


def _human_complete_session_payload(store, session_secret, csrf_token=None):
    session = store.authenticate_human_account_session(session_secret)
    if not session:
        return None
    memberships = store.list_human_company_memberships(session_secret)
    if not memberships.get("ok"):
        return None
    payload = {
        "ok": True,
        "account": {
            "humanAccountId": session.get("humanAccountId"),
            "username": session.get("username"),
            "displayName": session.get("displayName") or session.get("username"),
        },
        "memberships": memberships.get("items") or [],
        "humanSession": {
            "humanAccountSessionId": session.get("humanAccountSessionId"),
            "humanAccountId": session.get("humanAccountId"),
            "username": session.get("username"),
            "selectedAuthorityId": session.get("selectedAuthorityId"),
            "selectedCompanyId": session.get("companyId"),
            "role": session.get("role"),
            "expiresAt": session.get("expiresAt"),
            "passwordReauthenticatedAt": session.get("passwordReauthenticatedAt"),
        },
        "selectedCompanyId": session.get("companyId"),
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }
    if csrf_token:
        payload["csrfToken"] = csrf_token
    return payload


def _human_audit_actor(session):
    session = session or {}
    actor = {
        "humanAccountId": session.get("humanAccountId"),
        "username": session.get("username"),
        "authorityId": session.get("selectedAuthorityId"),
        "authMode": session.get("authMode") or "human_account",
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }
    return actor


def _human_recently_reauthenticated(session):
    value = (session or {}).get("passwordReauthenticatedAt") or (session or {}).get("reauthenticatedAt")
    if not value:
        return False
    try:
        timestamp = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    now = datetime.datetime.now(datetime.timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=datetime.timezone.utc)
    age = (now - timestamp.astimezone(datetime.timezone.utc)).total_seconds()
    return 0 <= age <= HUMAN_REAUTH_SECONDS


def _human_session_cookie(secret, max_age=HUMAN_SESSION_SECONDS):
    return "%s=%s; Path=/; Max-Age=%d; Secure; HttpOnly; SameSite=Strict" % (
        HUMAN_SESSION_COOKIE,
        secret,
        max_age,
    )


def _asset_version(*relative_paths):
    digest = hashlib.sha256()
    for relative_path in relative_paths:
        path = STATIC_ROOT / relative_path
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(str(relative_path).encode("utf-8"))
    source_version = build_provenance().get("sourceShaShort") or __version__
    return "%s-%s" % (source_version, digest.hexdigest()[:12])


def html_page(title, main, extra_head="", extra_scripts="", script_nonce=""):
    asset_version = _asset_version("css/site.css", "js/site.js")
    json_ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": SITE_NAME,
            "url": SITE_URL,
            "description": SITE_DESCRIPTION,
            "version": __version__,
        },
        sort_keys=True,
    ).replace("<", "\\u003c")
    nonce_attribute = (
        ' nonce="%s"' % escape_html(script_nonce) if script_nonce else ""
    )
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} | {site_name}</title>
  <meta name="description" content="{site_description}">
  <link rel="stylesheet" href="/static/css/site.css?v={asset_version}">
  {extra_head}
  <script type="application/ld+json"{nonce_attribute}>{json_ld}</script>
</head>
<body>
  <a class="skip-link" href="#main-content">Skip to main content</a>
  <header class="topbar">
    <a class="brand" href="/" aria-label="{site_name} home">
      <img src="/static/img/memory-endpoints-mark.svg" alt="" width="36" height="36">
      <span class="brand-name"><strong>{site_name}</strong></span>
    </a>
    <button class="site-nav-toggle" type="button" aria-expanded="false" aria-controls="site-navigation" data-site-nav-toggle>
      <span class="site-nav-toggle-icon" aria-hidden="true"><i></i><i></i><i></i></span>
      <span>Menu</span>
    </button>
    <nav class="site-nav" id="site-navigation" aria-label="Primary" data-site-nav>
      <a class="site-nav-demo" href="/tour">Demo</a>
      <a href="/docs">Docs</a>
      <a href="/human">Human Access</a>
      <a href="/agent-setup">Agent Setup</a>
      <a href="/agent-coordination">Agent Coordination</a>
      <a href="/console">Console</a>
      <a href="/knowledge">Knowledge</a>
      <a href="/memory-lifecycle">Memory</a>
      <a href="/transparency">Transparency</a>
      <details class="ecosystem-menu">
        <summary>Ecosystem</summary>
        <div class="ecosystem-links">
          <a href="https://localendpoints.com"><strong>LocalEndpoints.com</strong><span>Local execution boundaries</span></a>
          <a href="https://uaix.org"><strong>UAIX.org</strong><span>Portable agent guidance</span></a>
          <a href="https://llmwikis.org"><strong>LLMWikis.org</strong><span>Knowledge interfaces</span></a>
          <a href="{companion_docs_url}"><strong>MultiAgentMemory.com</strong><span>Repository companion</span></a>
        </div>
      </details>
    </nav>
  </header>
  <main id="main-content">{main}</main>
  <footer>
    <p>Free private-intranet MATM hive reference. No resale, certification, endorsement, or hidden authority claim is implied.</p>
  </footer>
  <script src="/static/js/site.js?v={asset_version}"></script>
  {extra_scripts}
</body>
</html>""".format(
        title=escape_html(title),
        site_name=escape_html(SITE_NAME),
        site_description=escape_html(SITE_DESCRIPTION),
        main=main,
        json_ld=json_ld,
        nonce_attribute=nonce_attribute,
        companion_docs_url=COMPANION_DOCS_URL,
        asset_version=escape_html(asset_version),
        extra_head=extra_head,
        extra_scripts=extra_scripts,
    )


def escape_html(value):
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _delivery_metadata(message, notification=None, inbox_agent_id=""):
    message = message or {}
    notification = notification or {}
    message_target_agent_id = message.get("targetAgentId") or ""
    notification_target_agent_id = notification.get("targetAgentId") or ""
    message_type = "targeted" if message_target_agent_id else "broadcast"
    response_disposition = notification.get("responseDisposition") or (
        "required_response" if message.get("responseRequired") else "viewed_acknowledgement"
    )
    return {
        "messageType": message_type,
        "broadcast": not bool(message_target_agent_id),
        "targetAgentId": message_target_agent_id,
        "recipientAgentId": notification_target_agent_id,
        "inboxAgentId": inbox_agent_id or notification_target_agent_id or message_target_agent_id or "",
        "responseDisposition": response_disposition,
        "valuesRedacted": True,
        "rawPayloadExposed": False,
    }


def _message_delivery_operator_summary(delivery, delivery_counts):
    delivery = delivery or {}
    delivery_counts = dict(delivery_counts or {})
    message_type = delivery.get("messageType") or ("targeted" if delivery.get("targetAgentId") else "broadcast")
    broadcast = delivery.get("broadcast")
    if broadcast is None:
        broadcast = message_type == "broadcast"
    response_disposition = delivery.get("responseDisposition") or "viewed_acknowledgement"
    response_counts = {"required_response": 0, "viewed_acknowledgement": 0}
    response_counts[response_disposition] = response_counts.get(response_disposition, 0) + 1
    return {
        "schemaVersion": "memoryendpoints.message_delivery_operator_summary.v1",
        "messageType": message_type,
        "broadcast": bool(broadcast),
        "targetAgentId": delivery.get("targetAgentId") or "",
        "inboxAgentId": delivery.get("inboxAgentId") or delivery.get("targetAgentId") or "",
        "recipientAgentId": delivery.get("recipientAgentId") or "",
        "recipientCount": delivery.get("recipientCount") or 1,
        "responseDisposition": response_disposition,
        "deliveryCounts": delivery_counts,
        "responseDispositionCounts": response_counts,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _agent_registration_operator_summary(agent):
    agent = agent or {}
    return {
        "schemaVersion": "memoryendpoints.agent_registration_operator_summary.v1",
        "agentId": agent.get("agentId") or "",
        "displayName": redact_text(agent.get("displayName") or ""),
        "status": agent.get("status") or "",
        "registered": bool(agent.get("agentId")),
        "currentMessageLaneReady": bool(agent.get("agentId")),
        "registeredAt": agent.get("registeredAt") or "",
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _memory_submission_metadata(event):
    event = event or {}
    firewall = event.get("firewall") or {}
    return {
        "memoryEventId": event.get("eventId") or "",
        "reviewId": event.get("reviewId") or "",
        "scope": event.get("scope") or "",
        "memoryType": event.get("memoryType") or "",
        "reviewStatus": event.get("reviewStatus") or "",
        "promotionState": event.get("promotionState") or "",
        "firewallDecision": firewall.get("decision") or "",
        "redactionApplied": bool(firewall.get("redactionApplied")),
        "valuesRedacted": True,
        "rawPayloadExposed": False,
    }


def _memory_submission_operator_summary(event):
    event = event or {}
    summary = _memory_submission_metadata(event)
    summary.update(
        {
            "schemaVersion": "memoryendpoints.memory_submission_operator_summary.v1",
            "actorAgentId": event.get("actorAgentId") or "",
            "scopeId": event.get("scopeId") or "",
            "subject": redact_text(event.get("subject") or ""),
            "tagCount": len(event.get("tags") or []),
            "rawCredentialExposed": False,
        }
    )
    return summary


def _review_status_counts(items):
    counts = {"pending": 0, "quarantined": 0, "promoted": 0, "rejected": 0}
    for item in items or []:
        status = item.get("status") or "unknown"
        counts[status] = counts.get(status, 0) + 1
    return counts


def _count_by(items, key, defaults=None):
    counts = dict(defaults or {})
    for item in items or []:
        value = item.get(key) or "unknown"
        counts[value] = counts.get(value, 0) + 1
    return counts


def _is_long_term_memory_item(item):
    source = item.get("source") or ""
    return source.startswith(LONG_TERM_MEMORY_SOURCE_PREFIX)


def _requests_long_term_memory_summary(items, query_text, filters):
    query_value = (query_text or "").lower()
    if filters.get("tag") == LONG_TERM_MEMORY_TAG or LONG_TERM_MEMORY_TAG in query_value:
        return True
    for item in items or []:
        tags = item.get("tags") or []
        if LONG_TERM_MEMORY_TAG in tags or _is_long_term_memory_item(item):
            return True
    return False


def _long_term_memory_operator_summary(items, query_text, filters):
    items = items or []
    filters = filters or {}
    relevant_items = [item for item in items if _is_long_term_memory_item(item)]
    related_items = [item for item in items if not _is_long_term_memory_item(item)]
    if not _requests_long_term_memory_summary(items, query_text, filters):
        return None
    source_paths = sorted({item.get("source") for item in relevant_items if (item.get("source") or "").startswith(LONG_TERM_MEMORY_SOURCE_PREFIX)})
    promoted_count = sum(1 for item in relevant_items if item.get("reviewStatus") == "promoted" or item.get("promotionState") == "promoted")
    raw_private_payload_count = sum(1 for item in relevant_items if item.get("rawPrivatePayloadStored"))
    all_values_redacted = all(item.get("valuesRedacted") is not False for item in relevant_items)
    status = "promoted" if relevant_items and promoted_count == len(relevant_items) else ("hosted_pending_review" if relevant_items else "not_found")
    duplicate_record_count = max(0, len(relevant_items) - len(source_paths))
    return {
        "schemaVersion": "memoryendpoints.long_term_memory_operator_summary.v1",
        "migrationTag": LONG_TERM_MEMORY_TAG,
        "status": status,
        "searchResultCount": len(items),
        "count": len(source_paths),
        "canonicalSourceCount": len(source_paths),
        "recordCount": len(relevant_items),
        "canonicalRecordCount": len(relevant_items),
        "duplicateRecordCount": duplicate_record_count,
        "sourcePathCount": len(source_paths),
        "sourcePathSamples": source_paths[:8],
        "relatedRecordCount": len(related_items),
        "relatedRecordsExcludedFromCanonical": bool(related_items),
        "memorySource": "hosted_workspace_store",
        "filesystemDocsIncluded": False,
        "scopeCounts": _count_by(relevant_items, "scope", {"account": 0, "company": 0, "workspace": 0, "project": 0}),
        "memoryTypeCounts": _count_by(relevant_items, "memoryType"),
        "reviewStatusCounts": _count_by(relevant_items, "reviewStatus", {"pending": 0, "quarantined": 0, "promoted": 0, "rejected": 0}),
        "promotionStateCounts": _count_by(relevant_items, "promotionState", {"review_pending": 0, "quarantined": 0, "promoted": 0, "rejected": 0}),
        "relatedScopeCounts": _count_by(related_items, "scope", {"account": 0, "company": 0, "workspace": 0, "project": 0}),
        "relatedMemoryTypeCounts": _count_by(related_items, "memoryType"),
        "relatedReviewStatusCounts": _count_by(related_items, "reviewStatus", {"pending": 0, "quarantined": 0, "promoted": 0, "rejected": 0}),
        "relatedPromotionStateCounts": _count_by(related_items, "promotionState", {"review_pending": 0, "quarantined": 0, "promoted": 0, "rejected": 0}),
        "allPromoted": bool(relevant_items) and promoted_count == len(relevant_items),
        "allValuesRedacted": all_values_redacted,
        "rawPrivatePayloadStoredCount": raw_private_payload_count,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _long_term_review_operator_summary(visible_reviews, all_reviews, memory_items):
    visible_reviews = visible_reviews or []
    all_reviews = all_reviews or []
    memory_by_id = {item.get("eventId"): item for item in (memory_items or []) if item.get("eventId")}

    def source_for(review):
        event = memory_by_id.get(review.get("memoryEventId")) or {}
        source = event.get("source") or ""
        return source if source.startswith(LONG_TERM_MEMORY_SOURCE_PREFIX) else ""

    all_long_term = [(review, source_for(review)) for review in all_reviews]
    all_long_term = [(review, source) for review, source in all_long_term if source]
    visible_ids = {review.get("reviewId") for review in visible_reviews if review.get("reviewId")}
    visible_long_term = [(review, source) for review, source in all_long_term if review.get("reviewId") in visible_ids]
    if not all_long_term:
        return None
    source_paths = sorted({source for _review, source in all_long_term})
    status_counts = _count_by([review for review, _source in all_long_term], "status", {"pending": 0, "quarantined": 0, "promoted": 0, "rejected": 0})
    visible_status_counts = _count_by([review for review, _source in visible_long_term], "status", {"pending": 0, "quarantined": 0, "promoted": 0, "rejected": 0})
    actionable_count = (status_counts.get("pending") or 0) + (status_counts.get("quarantined") or 0)
    all_promoted = bool(all_long_term) and status_counts.get("promoted") == len(all_long_term)
    status = "promoted" if all_promoted else ("action_required" if actionable_count else "reviewed")
    return {
        "schemaVersion": "memoryendpoints.long_term_memory_review_operator_summary.v1",
        "status": status,
        "count": len(source_paths),
        "visibleCount": len(visible_long_term),
        "recordCount": len(all_long_term),
        "visibleRecordCount": len(visible_long_term),
        "duplicateRecordCount": max(0, len(all_long_term) - len(source_paths)),
        "sourcePathCount": len(source_paths),
        "sourcePathSamples": source_paths[:8],
        "statusCounts": status_counts,
        "visibleStatusCounts": visible_status_counts,
        "actionableCount": actionable_count,
        "allPromoted": all_promoted,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _review_memory_metadata(review, memory_by_id):
    event = memory_by_id.get((review or {}).get("memoryEventId")) or {}
    if not event:
        return {}
    return {
        "eventId": event.get("eventId") or "",
        "source": event.get("source") or "",
        "memoryType": event.get("memoryType") or "",
        "scope": event.get("scope") or "",
        "scopeId": event.get("scopeId") or "",
        "actorAgentId": event.get("actorAgentId") or "",
        "tags": list(event.get("tags") or []),
        "valuesRedacted": True,
    }


def _review_matches_memory_filters(review, memory_by_id, filters):
    filters = filters or {}
    metadata = _review_memory_metadata(review, memory_by_id)
    source_prefix = (filters.get("sourcePrefix") or "").strip()
    if source_prefix and not (metadata.get("source") or "").startswith(source_prefix):
        return False
    tag_filter = (filters.get("tag") or "").strip().lower()
    if tag_filter and tag_filter not in [str(tag).lower() for tag in metadata.get("tags") or []]:
        return False
    memory_type = (filters.get("memoryType") or "").strip().lower()
    if memory_type and (metadata.get("memoryType") or "").lower() != memory_type:
        return False
    actor_agent_id = (filters.get("actorAgentId") or "").strip().lower()
    if actor_agent_id and (metadata.get("actorAgentId") or "").lower() != actor_agent_id:
        return False
    return True


def _review_public_item(review, memory_by_id):
    item = dict(review or {})
    metadata = _review_memory_metadata(item, memory_by_id)
    if metadata:
        item["memory"] = metadata
    return item


def _memory_search_operator_summary(items, query_text, filters):
    items = items or []
    summary = {
        "schemaVersion": "memoryendpoints.memory_search_operator_summary.v1",
        "query": redact_text(query_text or ""),
        "count": len(items),
        "filters": dict(filters or {}),
        "memorySource": "hosted_workspace_store",
        "filesystemDocsIncluded": False,
        "scopeCounts": _count_by(items, "scope", {"account": 0, "company": 0, "workspace": 0, "project": 0}),
        "memoryTypeCounts": _count_by(items, "memoryType"),
        "reviewStatusCounts": _count_by(items, "reviewStatus", {"pending": 0, "quarantined": 0, "promoted": 0, "rejected": 0}),
        "promotionStateCounts": _count_by(items, "promotionState", {"review_pending": 0, "quarantined": 0, "promoted": 0, "rejected": 0}),
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }
    long_term_memory = _long_term_memory_operator_summary(items, query_text, filters)
    if long_term_memory:
        summary["longTermMemoryMigration"] = long_term_memory
    return summary


def _current_message_attention_ordering_summary():
    return {
        "schemaVersion": "memoryendpoints.current_message_attention_ordering.v1",
        "priority": ["required_response", "viewed_acknowledgement"],
        "withinPriority": "newest_notification_first",
        "cursorField": "notification.notificationId",
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _inbox_operator_summary(items, filters, delivery_counts, current_message_lane, total_unread_count=None, pagination=None):
    response_counts = {"required_response": 0, "viewed_acknowledgement": 0}
    for item in items or []:
        delivery = item.get("delivery") or {}
        disposition = delivery.get("responseDisposition") or "viewed_acknowledgement"
        response_counts[disposition] = response_counts.get(disposition, 0) + 1
    return {
        "schemaVersion": "memoryendpoints.inbox_operator_summary.v1",
        "agentId": (filters or {}).get("agentId") or "",
        "unreadCount": len(items or []),
        "visibleUnreadCount": len(items or []),
        "totalUnreadCount": len(items or []) if total_unread_count is None else int(total_unread_count or 0),
        "currentMessageLane": bool(current_message_lane),
        "deliveryCounts": dict(delivery_counts or {}),
        "responseDispositionCounts": response_counts,
        "pagination": dict(pagination or {}),
        "attentionOrdering": _current_message_attention_ordering_summary(),
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _receipts_operator_summary(items, filters):
    items = items or []
    status_counts = _count_by(items, "status", {"read": 0})
    consumer_counts = _count_by(items, "consumerAgentId")
    raw_payload_exposed_count = sum(1 for item in items if item.get("rawPayloadExposed"))
    return {
        "schemaVersion": "memoryendpoints.receipts_operator_summary.v1",
        "count": len(items),
        "filters": dict(filters or {}),
        "statusCounts": status_counts,
        "consumerAgentCounts": consumer_counts,
        "rawPayloadExposedCount": raw_payload_exposed_count,
        "allPayloadsHidden": raw_payload_exposed_count == 0,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _acknowledgement_operator_summary(receipt):
    receipt = receipt or {}
    status = receipt.get("status") or "read"
    raw_payload_exposed = bool(receipt.get("rawPayloadExposed"))
    return {
        "schemaVersion": "memoryendpoints.acknowledgement_operator_summary.v1",
        "count": 1 if receipt else 0,
        "receiptId": receipt.get("receiptId") or "",
        "notificationId": receipt.get("notificationId") or "",
        "consumerAgentId": receipt.get("consumerAgentId") or "",
        "status": status,
        "statusCounts": {status: 1} if receipt else {},
        "rawPayloadExposedCount": 1 if raw_payload_exposed else 0,
        "allPayloadsHidden": not raw_payload_exposed,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _meeting_rooms_operator_summary(rooms, filters):
    rooms = rooms or []
    room_flow = {
        "entryRoomScope": "company",
        "entryProtocol": [
            "state agent identity",
            "state why the agent is here",
            "state current work or requested assignment",
            "wait for coordinator routing to workspace, project, goal, or task room",
        ],
        "routingOrder": ["company", "workspace", "project", "goal", "task"],
        "customGoalTaskRoomsSupported": True,
        "roomCreationRoute": "/api/matm/meeting-rooms",
        "valuesRedacted": True,
    }
    return {
        "schemaVersion": "memoryendpoints.meeting_rooms_operator_summary.v1",
        "count": len(rooms),
        "filters": dict(filters or {}),
        "scopeCounts": _count_by(rooms, "scope", {"company": 0, "workspace": 0, "project": 0, "goal": 0, "task": 0}),
        "alwaysAvailableCount": sum(1 for room in rooms if room.get("alwaysAvailable")),
        "defaultRoomCount": sum(1 for room in rooms if room.get("defaultRoom")),
        "messageCount": sum(int(room.get("messageCount") or 0) for room in rooms),
        "unreadCount": sum(int(room.get("unreadCount") or 0) for room in rooms),
        "readStateCount": sum(1 for room in rooms if room.get("readState")),
        "roomFlow": room_flow,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _meeting_room_create_operator_summary(room, created, creator_agent_id):
    room = room or {}
    return {
        "schemaVersion": "memoryendpoints.meeting_room_create_operator_summary.v1",
        "roomId": room.get("roomId") or "",
        "scope": room.get("scope") or "",
        "scopeId": room.get("scopeId") or "",
        "creatorAgentId": creator_agent_id or "",
        "created": bool(created),
        "reusedExistingRoom": not bool(created),
        "alwaysAvailable": bool(room.get("alwaysAvailable")),
        "defaultRoom": bool(room.get("defaultRoom")),
        "roomCreationRoute": "/api/matm/meeting-rooms",
        "transcriptRoute": "/api/matm/meeting-messages",
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _meeting_transcript_ordering_summary():
    return {
        "schemaVersion": "memoryendpoints.meeting_transcript_ordering.v1",
        "window": "latest_messages",
        "displayOrder": "oldest_to_newest_within_visible_window",
        "cursorDirection": "older",
        "cursorField": "items[0].meetingMessageId",
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _meeting_messages_operator_summary(room, messages, read_state, filters, unread_count=0, total_message_count=None, pagination=None):
    room = room or {}
    messages = messages or []
    return {
        "schemaVersion": "memoryendpoints.meeting_messages_operator_summary.v1",
        "roomId": room.get("roomId") or "",
        "scope": room.get("scope") or "",
        "scopeId": room.get("scopeId") or "",
        "count": len(messages),
        "visibleMessageCount": len(messages),
        "totalMessageCount": len(messages) if total_message_count is None else int(total_message_count or 0),
        "filters": dict(filters or {}),
        "senderAgentCounts": _count_by(messages, "senderAgentId"),
        "unreadCount": int(unread_count or 0),
        "pagination": dict(pagination or {}),
        "transcriptOrdering": _meeting_transcript_ordering_summary(),
        "readStatePresent": bool(read_state),
        "alwaysAvailable": bool(room.get("alwaysAvailable")),
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _meeting_post_operator_summary(room, message):
    room = room or {}
    message = message or {}
    return {
        "schemaVersion": "memoryendpoints.meeting_post_operator_summary.v1",
        "roomId": room.get("roomId") or "",
        "meetingMessageId": message.get("meetingMessageId") or "",
        "scope": room.get("scope") or message.get("scope") or "",
        "scopeId": room.get("scopeId") or message.get("scopeId") or "",
        "senderAgentId": message.get("senderAgentId") or "",
        "messageCount": 1 if message else 0,
        "alwaysAvailable": bool(room.get("alwaysAvailable")),
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _meeting_memory_promotion_operator_summary(message, room, event, promoted_by_agent_id):
    message = message or {}
    room = room or {}
    event = event or {}
    return {
        "schemaVersion": "memoryendpoints.meeting_memory_promotion_operator_summary.v1",
        "meetingMessageId": message.get("meetingMessageId") or "",
        "roomId": message.get("roomId") or room.get("roomId") or "",
        "sourceSenderAgentId": message.get("senderAgentId") or "",
        "promotedByAgentId": promoted_by_agent_id or "",
        "memoryEventId": event.get("eventId") or "",
        "reviewId": event.get("reviewId") or "",
        "scope": event.get("scope") or message.get("scope") or room.get("scope") or "",
        "scopeId": event.get("scopeId") or message.get("scopeId") or room.get("scopeId") or "",
        "memoryType": event.get("memoryType") or "",
        "firewallDecision": (event.get("firewall") or {}).get("decision") or "",
        "reviewStatus": event.get("reviewStatus") or "",
        "promotionState": event.get("promotionState") or "",
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _meeting_read_operator_summary(read_state, room):
    read_state = read_state or {}
    room = room or {}
    return {
        "schemaVersion": "memoryendpoints.meeting_read_operator_summary.v1",
        "roomId": room.get("roomId") or read_state.get("roomId") or "",
        "scope": room.get("scope") or "",
        "agentId": read_state.get("agentId") or "",
        "lastMeetingMessageId": read_state.get("lastMeetingMessageId") or "",
        "readMessageCount": int(read_state.get("readMessageCount") or 0),
        "status": read_state.get("status") or "read",
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _string_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = value.splitlines() if "\n" in value else value.split(",")
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []
    items = []
    for item in raw_items:
        text = redact_text(str(item).strip())
        if text:
            items.append(text[:240])
    return items[:10]


def _routing_decision_summary(fields, destination_room):
    evidence = fields.get("expectedEvidence") or []
    evidence_text = "; ".join(evidence[:5])
    parts = [
        "Routing decision for %s: lane=%s" % (fields.get("routedAgentId") or "agent", fields.get("lane") or "unassigned"),
        "destination=%s room %s" % (destination_room.get("scope") or fields.get("destinationScope") or "room", fields.get("destinationRoomId") or ""),
        "scopeId=%s" % (destination_room.get("scopeId") or fields.get("destinationScopeId") or ""),
        "goal=%s" % (fields.get("specificGoal") or ""),
        "nextAction=%s" % (fields.get("nextAction") or ""),
    ]
    if fields.get("supportPlan"):
        parts.append("coordination=%s" % fields.get("supportPlan"))
    if evidence_text:
        parts.append("expectedEvidence=%s" % evidence_text)
    return redact_text(". ".join(part for part in parts if part).strip())


def _routing_decision_operator_summary(decision, source_room, destination_room):
    decision = decision or {}
    source_room = source_room or {}
    destination_room = destination_room or {}
    return {
        "schemaVersion": "memoryendpoints.routing_decision_operator_summary.v1",
        "routingDecisionId": decision.get("routingDecisionId") or "",
        "meetingMessageId": decision.get("meetingMessageId") or "",
        "sourceRoomId": decision.get("sourceRoomId") or source_room.get("roomId") or "",
        "destinationRoomId": decision.get("destinationRoomId") or destination_room.get("roomId") or "",
        "destinationScope": decision.get("destinationScope") or destination_room.get("scope") or "",
        "destinationScopeId": decision.get("destinationScopeId") or destination_room.get("scopeId") or "",
        "coordinatorAgentId": decision.get("coordinatorAgentId") or "",
        "routedAgentId": decision.get("routedAgentId") or "",
        "lane": decision.get("lane") or "",
        "expectedEvidenceCount": len(decision.get("expectedEvidence") or []),
        "status": decision.get("status") or "",
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": bool(decision.get("rawPayloadExposed")),
    }


def _routing_decisions_operator_summary(items, filters):
    items = items or []
    return {
        "schemaVersion": "memoryendpoints.routing_decisions_operator_summary.v1",
        "count": len(items),
        "filters": dict(filters or {}),
        "routedAgentCounts": _count_by(items, "routedAgentId"),
        "laneCounts": _count_by(items, "lane"),
        "destinationScopeCounts": _count_by(items, "destinationScope", {"company": 0, "workspace": 0, "project": 0, "goal": 0, "task": 0}),
        "activeCount": sum(1 for item in items if item.get("status") == "active"),
        "allValuesRedacted": all(item.get("valuesRedacted") for item in items) if items else True,
        "rawPayloadExposedCount": sum(1 for item in items if item.get("rawPayloadExposed")),
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _routing_decision_confirmation(store, workspace_id, decision, message, source_room):
    decision = decision or {}
    message = message or {}
    source_room = source_room or {}
    room_id = decision.get("sourceRoomId") or source_room.get("roomId") or message.get("roomId")
    coordinator_agent_id = decision.get("coordinatorAgentId") or ""
    routed_agent_id = decision.get("routedAgentId") or ""
    decisions = store.routing_decisions(workspace_id, {"routedAgentId": routed_agent_id, "destinationRoomId": decision.get("destinationRoomId")}, 200)
    routed_agent_authorized = store.agent_has_scope(
        workspace_id,
        routed_agent_id,
        decision.get("destinationScope"),
        decision.get("destinationScopeId"),
    )
    visible_decision = routed_agent_authorized and any(
        item.get("routingDecisionId") == decision.get("routingDecisionId")
        for item in decisions
    )
    _room, messages, _read_state = store.meeting_messages(workspace_id, room_id, coordinator_agent_id, 200)
    visible_source_message = any(item.get("meetingMessageId") == message.get("meetingMessageId") for item in messages)
    return {
        "persisted": visible_decision and visible_source_message,
        "visibleToRoutedAgent": visible_decision,
        "canonicalRoutingDecisionId": decision.get("routingDecisionId"),
        "canonicalRoomId": room_id,
        "destinationRoomId": decision.get("destinationRoomId"),
        "messageId": message.get("meetingMessageId"),
        "routingDecisionQueryUrl": _protected_query_url(
            "/api/matm/routing-decisions",
            {
                "workspace_id": workspace_id,
                "routed_agent_id": routed_agent_id,
                "destination_room_id": decision.get("destinationRoomId"),
            },
        ),
        "transcriptQueryUrl": _protected_query_url(
            "/api/matm/meeting-messages",
            {
                "workspace_id": workspace_id,
                "room_id": room_id,
                "agent_id": coordinator_agent_id,
            },
        ),
        "destinationTranscriptQueryUrl": _protected_query_url(
            "/api/matm/meeting-messages",
            {
                "workspace_id": workspace_id,
                "room_id": decision.get("destinationRoomId"),
                "agent_id": routed_agent_id,
            },
        ),
        "valuesRedacted": True,
    }


def _routing_decision_visible_to_auth(store, workspace_id, auth, decision, rooms):
    source_room = rooms.get(decision.get("sourceRoomId")) or {}
    destination_room = rooms.get(decision.get("destinationRoomId")) or {}
    return bool(
        (
            source_room
            and store.auth_allows_scope(
                auth, source_room.get("scope"), source_room.get("scopeId")
            )
        )
        or (
            destination_room
            and store.auth_allows_scope(
                auth,
                destination_room.get("scope"),
                destination_room.get("scopeId"),
            )
        )
    )


def _audit_log_operator_summary(items, filters):
    items = items or []
    raw_credential_exposed_count = sum(1 for item in items if item.get("rawCredentialExposed"))
    raw_payload_exposed_count = sum(1 for item in items if item.get("rawPayloadExposed"))
    return {
        "schemaVersion": "memoryendpoints.audit_log_operator_summary.v1",
        "count": len(items),
        "filters": dict(filters or {}),
        "actionCounts": _count_by(items, "action"),
        "redactedCount": sum(1 for item in items if item.get("valuesRedacted")),
        "rawCredentialExposedCount": raw_credential_exposed_count,
        "rawPayloadExposedCount": raw_payload_exposed_count,
        "allCredentialsHidden": raw_credential_exposed_count == 0,
        "allPayloadsHidden": raw_payload_exposed_count == 0,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _review_queue_operator_summary(items, all_items, filters, status_counts, memory_items=None):
    items = items or []
    threat_count = sum(len(item.get("detectedThreats") or []) for item in items)
    risk_scores = [item.get("riskScore") or 0 for item in items]
    summary = {
        "schemaVersion": "memoryendpoints.review_queue_operator_summary.v1",
        "count": len(items),
        "filters": dict(filters or {}),
        "statusCounts": dict(status_counts or {}),
        "visibleStatusCounts": _count_by(items, "status", {"pending": 0, "quarantined": 0, "promoted": 0, "rejected": 0}),
        "firewallDecisionCounts": _count_by(items, "firewallDecision"),
        "itemsWithDetectedThreats": sum(1 for item in items if item.get("detectedThreats")),
        "detectedThreatCount": threat_count,
        "highestRiskScore": max(risk_scores) if risk_scores else 0,
        "totalQueueCount": len(all_items or []),
        "promotionRoute": "/api/matm/review-queue/decide",
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }
    long_term_reviews = _long_term_review_operator_summary(items, all_items, memory_items or [])
    if long_term_reviews:
        summary["longTermMemoryReviews"] = long_term_reviews
    return summary


def _review_decision_operator_summary(review):
    review = review or {}
    status = review.get("status") or "recorded"
    return {
        "schemaVersion": "memoryendpoints.review_decision_operator_summary.v1",
        "reviewId": review.get("reviewId") or "",
        "memoryEventId": review.get("memoryEventId") or "",
        "status": status,
        "statusCounts": {status: 1} if review else {},
        "reviewerAgentId": review.get("reviewerAgentId") or "",
        "decidedAt": review.get("decidedAt") or review.get("updatedAt") or "",
        "reviewNoteExposed": False,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _workspace_status_for_auth(store, auth, workspace):
    """Remove hierarchy and sibling resources from lower-scoped readback."""
    if not workspace or _principal_scope_type(auth) not in ("project", "game", "session", "goal", "task"):
        return workspace

    visible_projects = [
        dict(project)
        for project in workspace.get("projects") or []
        if store.auth_allows_scope(auth, "project", project.get("projectId"))
    ]
    visible_rooms = [
        dict(room)
        for room in workspace.get("meetingRooms") or []
        if store.auth_allows_scope(auth, room.get("scope"), room.get("scopeId"))
        and _npc_room_allowed(auth, room)
    ]
    scope_type = _principal_scope_type(auth)
    grant = auth.get("grant") if isinstance(auth.get("grant"), dict) else {}
    return {
        "workspaceId": workspace.get("workspaceId"),
        "label": workspace.get("label"),
        "primaryProjectId": (
            visible_projects[0].get("projectId") if len(visible_projects) == 1 else None
        ),
        "meetingRooms": visible_rooms,
        "projects": visible_projects,
        "plan": workspace.get("plan"),
        "status": workspace.get("status"),
        "billingStatus": workspace.get("billingStatus"),
        "checkoutRequired": bool(workspace.get("checkoutRequired")),
        "storageLimitBytes": workspace.get("storageLimitBytes") or 0,
        "storageLimitDisplay": workspace.get("storageLimitDisplay") or "",
        "storageUsedBytes": workspace.get("storageUsedBytes") or 0,
        "storageRemainingBytes": workspace.get("storageRemainingBytes"),
        "storageRemainingDisplay": workspace.get("storageRemainingDisplay") or "",
        "storageUnlimited": bool(workspace.get("storageUnlimited")),
        "storageQuotaEnforced": bool(workspace.get("storageQuotaEnforced")),
        "quotaExceeded": bool(workspace.get("quotaExceeded")),
        "npcMemoryUnlimited": bool(workspace.get("npcMemoryUnlimited")),
        "planEntitlement": workspace.get("planEntitlement") or {},
        "rawKeyStoredByServer": bool(workspace.get("rawKeyStoredByServer")),
        "hierarchyRedacted": True,
        "authorizedScope": {
            "scopeType": scope_type,
            "scopeId": auth.get("scopeId") or grant.get("scopeId") or "",
        },
    }


def _workspace_operator_summary(workspace):
    workspace = workspace or {}
    projects = workspace.get("projects") or []
    meeting_rooms = workspace.get("meetingRooms") or []
    hierarchy_redacted = bool(workspace.get("hierarchyRedacted"))
    if hierarchy_redacted:
        hierarchy = [
            {
                "level": "workspace",
                "id": workspace.get("workspaceId") or "",
                "label": workspace.get("label") or workspace.get("workspaceId") or "",
                "status": workspace.get("status") or "active",
                "plan": workspace.get("plan") or "",
            }
        ]
        hierarchy.extend(
            {
                "level": "project",
                "id": project.get("projectId") or "",
                "label": project.get("label") or project.get("projectId") or "",
                "status": project.get("status") or "active",
            }
            for project in projects
        )
    else:
        accounts = workspace.get("accounts") or []
        account = accounts[0] if accounts else {}
        company = workspace.get("company") or {}
        project = projects[0] if projects else {}
        hierarchy = [
            {
                "level": "account",
                "id": account.get("accountId") or workspace.get("accountId") or "",
                "label": account.get("label") or workspace.get("accountId") or "",
                "status": account.get("status") or "active",
                "role": account.get("role") or "owner",
            },
            {
                "level": "company",
                "id": company.get("companyId") or workspace.get("companyId") or "",
                "label": company.get("label") or workspace.get("companyId") or "",
                "status": company.get("status") or "active",
            },
            {
                "level": "workspace",
                "id": workspace.get("workspaceId") or "",
                "label": workspace.get("label") or workspace.get("workspaceId") or "",
                "status": workspace.get("status") or "active",
                "plan": workspace.get("plan") or "",
            },
            {
                "level": "project",
                "id": project.get("projectId") or workspace.get("primaryProjectId") or "",
                "label": project.get("label") or workspace.get("primaryProjectId") or "",
                "status": project.get("status") or "active",
            },
        ]
    summary = {
        "schemaVersion": "memoryendpoints.workspace_operator_summary.v1",
        "hierarchy": hierarchy,
        "hierarchyReady": all(item.get("id") for item in hierarchy),
        "storage": {
            "limitBytes": workspace.get("storageLimitBytes") or 0,
            "limitDisplay": workspace.get("storageLimitDisplay") or "",
            "usedBytes": workspace.get("storageUsedBytes") or 0,
            "remainingBytes": workspace.get("storageRemainingBytes"),
            "remainingDisplay": workspace.get("storageRemainingDisplay") or "",
            "unlimited": bool(workspace.get("storageUnlimited")),
            "quotaEnforced": bool(workspace.get("storageQuotaEnforced")),
            "quotaExceeded": bool(workspace.get("quotaExceeded")),
            "billingStatus": workspace.get("billingStatus") or "",
            "npcMemoryUnlimited": bool(workspace.get("npcMemoryUnlimited")),
        },
        "privacy": {
            "workspaceKeyEchoed": False,
            "rawKeyStoredByServer": bool(workspace.get("rawKeyStoredByServer")),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        },
        "meetingRooms": {
            "count": len(meeting_rooms),
            "scopeCounts": _count_by(meeting_rooms, "scope", {"company": 0, "workspace": 0, "project": 0, "goal": 0, "task": 0}),
            "alwaysAvailableCount": sum(1 for room in meeting_rooms if room.get("alwaysAvailable")),
            "entryRoomScope": "company",
            "routingOrder": ["company", "workspace", "project", "goal", "task"],
        },
        "copySafeIds": True,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }
    if hierarchy_redacted:
        summary["hierarchyRedacted"] = True
        summary["authorizedScope"] = workspace.get("authorizedScope") or {}
    return summary


def _free_account_setup_operator_summary(account_id, company_id, workspace_id, project_id):
    return {
        "schemaVersion": "memoryendpoints.free_account_setup_operator_summary.v1",
        "hierarchy": [
            {"level": "account", "id": account_id or "", "copySafe": True},
            {"level": "company", "id": company_id or "", "copySafe": True},
            {"level": "workspace", "id": workspace_id or "", "copySafe": True},
            {"level": "project", "id": project_id or "", "copySafe": True},
        ],
        "hierarchyReady": all([account_id, company_id, workspace_id, project_id]),
        "storage": {
            "limitBytes": PUBLIC_STORAGE_BYTES,
            "checkoutRequired": False,
        },
        "keyHandling": {
            "oneTimeWorkspaceKeyReturned": True,
            "saveRequired": True,
            "rawKeyStoredByServer": False,
            "idempotencySupported": False,
        },
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def route_home(start_response):
    body = """
<section class="hero">
  <div>
    <p class="eyebrow">Private-network memory for AI teams</p>
    <h1>Run a single-company MATM hive inside your own boundary.</h1>
    <p class="lead">A free intranet reference for durable workspace memory, current messages, redacted receipts, and AI-ready knowledge without public hosted sales features.</p>
    <div class="actions">
      <a class="button primary" href="/tour">Try the interactive demo</a>
      <a class="button" href="/agent-setup">Create agent workspace</a>
      <a class="button" href="/console">Open human console</a>
    </div>
    <p class="hero-note"><strong>No sign-in needed for the demo.</strong> It uses the real authenticated interface with clearly labeled, session-only mock data. Production use is intended for a trusted private network.</p>
  </div>
  <aside class="home-status" aria-label="Operational entry points">
    <p class="eyebrow">Operational Surface</p>
    <h2>Start where you work</h2>
    <a href="/agent-coordination"><strong>Agent coordination</strong><span>register, rooms, memory, inbox, ack</span></a>
    <a href="/console"><strong>Console</strong><span>workspace, memory, messages, receipts</span></a>
    <a href="/tour"><strong>Interactive demo</strong><span>real interface, clearly labeled mock data</span></a>
    <a href="/api/matm/connector-contract"><strong>Connector contract</strong><span>settings, routes, redaction, routing</span></a>
    <a href="/api/matm/uai-memory/contract"><strong>UAIX active memory</strong><span>browser exception and local edit claims</span></a>
    <a href="/api/matm/agent-compatibility"><strong>Agent compatibility</strong><span>L0-L7 ability paths and fallbacks</span></a>
    <a href="/api/matm/readiness-result"><strong>Readiness</strong><span>deployment and capability evidence</span></a>
    <a href="/memory-lifecycle"><strong>Memory lifecycle</strong><span>review, promotion, acknowledgement</span></a>
    <a href="/transparency"><strong>Transparency</strong><span>claims, redaction, unsupported areas</span></a>
  </aside>
</section>
<section class="grid">
  <article><h2>For humans</h2><p>Readable pages explain what is live, planned, gated, and unsupported.</p></article>
  <article><h2>For agents</h2><p>Deterministic JSON and text routes define setup, memory, inbox, and acknowledgement flows.</p></article>
  <article><h2>For operators</h2><p>Secrets stay outside the repo; deployment and database use require explicit proof.</p></article>
  <article><h2>For implementers</h2><p><a href="{companion_docs_url}">MultiAgentMemory.com</a> explains the repository, GitHub handoff, and MATM memory boundary.</p></article>
</section>
<section class="home-explainer" aria-label="Product model">
  <article>
    <p class="eyebrow">Ownership hierarchy</p>
    <h2>One account can work across durable team boundaries</h2>
    <p>People belong to one internal account and company. That company owns workspaces; each workspace owns projects. Durable knowledge and memory stay inside the authorized company, workspace, or project boundary.</p>
    <ol class="hierarchy-list">
      <li><strong>Account</strong><span>human membership</span></li>
      <li><strong>Company</strong><span>organization boundary</span></li>
      <li><strong>Workspace</strong><span>key and storage boundary</span></li>
      <li><strong>Project</strong><span>implementation scope</span></li>
    </ol>
  </article>
  <article>
    <p class="eyebrow">Memory boundary</p>
    <h2>Local continuity plus protected durable memory</h2>
    <p>Local <code>.uai</code> files remain the agent's active startup memory. The intranet MATM service adds protected mid- and long-term memory, review, meetings, current messages, receipts, and searchable wiki knowledge. Routine audit logs remain human-only for seven days and never enter agent context. Hosted memory augments local continuity; it never silently replaces it.</p>
    <p><a href="https://uaix.org">UAIX.org</a> provides portable setup guidance. <a href="{companion_docs_url}">MultiAgentMemory.com</a> and the <a href="{github_repo_url}">GitHub companion repository</a> explain this implementation.</p>
  </article>
</section>
""".format(companion_docs_url=COMPANION_DOCS_URL, github_repo_url=GITHUB_REPO_URL)
    return response(start_response, "200 OK", html_page("Home", body), "text/html; charset=utf-8")


def route_docs(start_response):
    body = """
<section class="page">
  <h1>Documentation</h1>
  <p>This private MATM intranet follows an AI-ready web model: human-first pages, deterministic discovery files, safe APIs, bounded capability claims, privacy-preserving receipts, and validation evidence.</p>
  <h2>Companion documentation</h2>
  <p><a href="{companion_docs_url}">MultiAgentMemory.com</a> is the public GitHub companion documentation site. It explains how the repository, `.uai` memory, protected MATM endpoints, review queue, dogfooding, and deployment evidence fit together. The source repository is <a href="{github_repo_url}">MichaelKappel/Multi-Agent-Memory</a>.</p>
  <h2>Discovery routes</h2>
  <ul class="route-list">
    <li><a href="/llms.txt"><code>/llms.txt</code></a> and <a href="/llms-full.txt"><code>/llms-full.txt</code></a> summarize public agent guidance.</li>
    <li><a href="/ai-manifest.json"><code>/ai-manifest.json</code></a> exposes route inventory and support boundaries.</li>
    <li><a href="/api/matm/agent-compatibility"><code>/api/matm/agent-compatibility</code></a> maps L0-L7 agent ability levels to safe routes, fallbacks, and no-op behavior.</li>
    <li><a href="/api/matm/connector-contract"><code>/api/matm/connector-contract</code></a> gives optional connectors one stable setup, API, UI, and routing contract.</li>
    <li><a href="/api/matm/uai-memory/contract"><code>/api/matm/uai-memory/contract</code></a> separates the accountless-browser virtual package from hash-only local <code>.uai</code> edit coordination.</li>
    <li><a href="/api/matm/openapi.json"><code>/api/matm/openapi.json</code></a> gives agents and connectors a bounded OpenAPI-style golden path.</li>
    <li><a href="/agent-coordination"><code>/agent-coordination</code></a> gives authenticated agents one copy-safe coordination quickstart.</li>
    <li><a href="/api/matm/readiness-result"><code>/api/matm/readiness-result</code></a> exposes current local readiness and deployment blockers.</li>
    <li><a href="/.well-known/mcp.json"><code>/.well-known/mcp.json</code></a> and <a href="/mcp/resources"><code>/mcp/resources</code></a> expose resource discovery.</li>
  </ul>
</section>
""".format(companion_docs_url=COMPANION_DOCS_URL, github_repo_url=GITHUB_REPO_URL)
    return response(start_response, "200 OK", html_page("Docs", body), "text/html; charset=utf-8")


def route_connector_authorize(
    environ, start_response, public_request_ref="", demo_state=""
):
    """Render one fail-closed human approval surface or explicit mock state."""
    if environ.get("QUERY_STRING"):
        return _connector_problem(start_response, "invalid_request")
    if demo_state:
        legacy_demo_states = {
            "authorization_received": "authorization_issued",
            "credential_delivered": "credential_prepared",
            "connected": "activated",
        }
        view = demo_authorization_view(legacy_demo_states.get(demo_state, demo_state))
    else:
        canonical_scope_digest = connector_scope_digest(CONNECTOR_V1_REQUESTED_SCOPES)

        def terminal_view(status):
            if status in ("pairing_request_expired", "authorization_code_expired", "expired"):
                return production_authorization_view(authenticated=True, state="expired")
            if status in ("pairing_canceled", "pairing_request_canceled", "canceled"):
                return production_authorization_view(authenticated=True, state="canceled")
            if status in (
                "human_credential_authority_required",
                "human_owner_required",
                "company_unavailable",
            ):
                return production_authorization_view(
                    authenticated=True, state="permission_denied"
                )
            if status == "human_account_session_required":
                return production_authorization_view(authenticated=False)
            return production_authorization_view(
                authenticated=True,
                state="error",
                error_code="service_error",
            )

        rate_rejection = _connector_rate_rejection(start_response, _connector_operation_rate_limited(
            environ,
            "authorize",
            "%s|%s" % (environ.get("REMOTE_ADDR") or "unknown", CONNECTOR_CLIENT_ID),
        ))
        if rate_rejection:
            return rate_rejection
        store = _store()
        session_secret = _request_cookie(environ, HUMAN_SESSION_COOKIE)
        session = store.authenticate_human_account_session(session_secret) if session_secret else None
        if not session:
            view = production_authorization_view(authenticated=False)
        elif not session.get("companyId"):
            catalog = store.human_connector_company_catalog(
                session_secret, public_request_ref
            )
            items = catalog.get("companies") or [] if catalog.get("ok") else []
            if not catalog.get("ok"):
                view = terminal_view(catalog.get("status"))
            elif items:
                view = production_authorization_view(
                    authenticated=True,
                    state="company_selection",
                    request=PairingRequestDisplay(
                        public_request_ref=public_request_ref,
                        client_name="LocalEndpoint Connect",
                        agent_display_name=CONNECTOR_AGENT_DISPLAY_NAME,
                        status_label="Pending approval",
                        expires_at_label="Approval remains subject to its published deadline",
                        scope_digest=canonical_scope_digest,
                    ),
                    companies=tuple(
                        CompanyOption(
                            item.get("companyRef") or "",
                            item.get("companyLabel") or item.get("label") or "Company",
                        )
                        for item in items
                    ),
                )
            else:
                view = production_authorization_view(authenticated=True, state="permission_denied")
        else:
            catalog = store.human_connector_scope_catalog(
                session_secret, public_request_ref
            )
            if not catalog.get("ok"):
                view = terminal_view(catalog.get("status"))
            else:
                context_result = store.connector_pairing_authorization_context(
                    session_secret, public_request_ref
                )
                if not context_result.get("ok"):
                    view = terminal_view(context_result.get("status"))
                else:
                    context = context_result.get("authorizationContext") or {}
                    requested_scopes = context.get("requestedScopes")
                    scope_digest = context.get("scopeDigest")
                    binding_valid = (
                        requested_scopes == list(CONNECTOR_V1_REQUESTED_SCOPES)
                        and isinstance(scope_digest, str)
                        and hmac.compare_digest(scope_digest, canonical_scope_digest)
                    )
                    if not binding_valid:
                        view = production_authorization_view(
                            authenticated=True,
                            state="error",
                            error_code="service_error",
                        )
                    else:
                        request_status = context.get("status") or ""
                        status_labels = {
                            "pending_human_approval": "Pending approval",
                            "approved": "Approved - awaiting LocalEndpoint",
                            "authorization_code_issued": "Authorization code issued",
                            "exchanged": "Credential prepared - awaiting activation",
                            "active": "Activated - verify in LocalEndpoint",
                            "canceled": "Canceled",
                            "expired": "Expired",
                            "authorization_code_expired": "Expired",
                        }
                        request_display = PairingRequestDisplay(
                            public_request_ref=public_request_ref,
                            client_name="LocalEndpoint Connect",
                            agent_display_name=CONNECTOR_AGENT_DISPLAY_NAME,
                            status_label=status_labels.get(request_status, "Unavailable"),
                            expires_at_label="Approval expires at %s"
                            % (
                                context.get("claimExpiresAt")
                                or context.get("expiresAt")
                                or "the published deadline"
                            ),
                            scope_digest=canonical_scope_digest,
                        )
                        workspaces = tuple(
                            WorkspaceOption(
                                item.get("workspaceRef") or "",
                                item.get("label") or "Workspace",
                            )
                            for item in (catalog.get("workspaces") or [])
                        )
                        company = catalog.get("company") or {}
                        common = {
                            "authenticated": True,
                            "request": request_display,
                            "company_label": company.get("label") or "Selected company",
                            "workspaces": workspaces,
                        }
                        if request_status == "pending_human_approval":
                            if _human_recently_reauthenticated(session):
                                view = production_authorization_view(**common)
                            else:
                                view = production_authorization_view(
                                    state="reauth_required", **common
                                )
                        elif request_status == "approved":
                            workspace_label = context.get("workspaceLabel")
                            workspace_label_valid = (
                                isinstance(workspace_label, str)
                                and 1 <= len(workspace_label) <= 96
                                and workspace_label == workspace_label.strip()
                                and not any(
                                    ord(character) < 32 or ord(character) == 127
                                    for character in workspace_label
                                )
                            )
                            if not workspace_label_valid:
                                view = production_authorization_view(
                                    authenticated=True,
                                    state="error",
                                    error_code="service_error",
                                )
                            else:
                                try:
                                    wake_up_url = build_wake_up_url(
                                        context.get("wakeUpUrl")
                                    )
                                except PairingPolicyError:
                                    view = production_authorization_view(
                                        authenticated=True,
                                        state="error",
                                        error_code="service_error",
                                    )
                                else:
                                    view = production_authorization_view(
                                        state="approved",
                                        result=ApprovalResultDisplay(
                                            workspace_label=workspace_label,
                                            agent_display_name=CONNECTOR_AGENT_DISPLAY_NAME,
                                            wake_up_url=wake_up_url,
                                            scope_digest=canonical_scope_digest,
                                        ),
                                        **common,
                                    )
                        elif request_status == "canceled":
                            view = production_authorization_view(
                                authenticated=True, state="canceled"
                            )
                        elif request_status in (
                            "expired",
                            "authorization_code_expired",
                        ):
                            view = production_authorization_view(
                                authenticated=True, state="expired"
                            )
                        elif request_status in (
                            "authorization_code_issued",
                            "exchanged",
                            "active",
                        ):
                            post_approval_states = {
                                "authorization_code_issued": "authorization_issued",
                                "exchanged": "credential_prepared",
                                "active": "activated",
                            }
                            view = production_authorization_view(
                                authenticated=True,
                                state=post_approval_states[request_status],
                            )
                        else:
                            view = production_authorization_view(
                                authenticated=True,
                                state="error",
                                error_code="service_error",
                            )
    fragment = render_connector_authorization(view)
    connector_style = _asset_version("css/connector-authorize.css")
    connector_asset = _asset_version("js/connector-authorize.js")
    script_nonce = secrets.token_urlsafe(18)
    page = html_page(
        "Connector authorization",
        fragment
        + '<script src="/static/js/connector-authorize.js?v=%s" defer></script>'
        % escape_html(connector_asset),
        extra_head='<link rel="stylesheet" href="/static/css/connector-authorize.css?v=%s">'
        % escape_html(connector_style),
        script_nonce=script_nonce,
    )
    return response(
        start_response,
        "200 OK",
        page,
        "text/html; charset=utf-8",
        headers=_connector_authorize_headers(script_nonce),
    )


def route_agent_setup(start_response):
    setup_available = credential_system_available()
    if setup_available:
        setup_form = """
        <form class="setup-form" method="post" action="/api/matm/agent-setup/free-account" data-agent-setup-form>
          <label>
            Company name
            <input name="companyLabel" autocomplete="organization" maxlength="120" placeholder="Example Company" required>
          </label>
          <label>
            Workspace name
            <input name="label" autocomplete="off" maxlength="120" placeholder="Agent Operations" required>
          </label>
          <label>
            First project
            <input name="projectLabel" autocomplete="off" maxlength="120" placeholder="Memory Integration" required>
          </label>
          <button class="button primary" type="submit" data-agent-setup-submit>Create workspace</button>
        </form>
        <noscript><p class="setup-noscript">JavaScript is required for the interactive form. Use the copy-safe API examples below; this form never sends labels in a URL.</p></noscript>
        """
        setup_status = "Enter labels to create your workspace. No checkout is required."
    else:
        setup_form = """
        <div class="setup-boundary-note setup-unavailable" role="alert" data-agent-setup-unavailable>
          <strong>Workspace setup is temporarily unavailable</strong>
          <span>Governed credential verification is not configured, so no workspace can be created safely. No setup request was sent. Ask the operator to restore credential service, then reload this page.</span>
        </div>
        """
        setup_status = "Workspace creation is unavailable. No workspace was created and no one-time credential was issued."
    body = """
<section class="page">
  <header class="setup-heading">
    <p class="eyebrow">Secure workspace onboarding</p>
    <h1>Start using the private MATM intranet</h1>
    <p class="lead">Autonomous agents can create a bounded Account, Company, Workspace, and Project with no human interaction. Optional human access and governed invitation flows remain available for human-only controls.</p>
  </header>
  <section class="setup-onboarding" data-agent-setup data-agent-setup-available="__SETUP_AVAILABLE__" data-company-master-default-path="__COMPANY_MASTER_DEFAULT_SECRET_PATH__">
    <div class="setup-choice-grid">
      <article class="setup-card setup-card-primary">
        <p class="setup-step">New workspace</p>
        <h2>Create a free 200 MB workspace</h2>
        <p>The intranet service returns one company master credential. It stays on this page only until you leave or refresh, and the server stores only a verifier. Setup is not complete until the credential file exists.</p>
        <div class="setup-boundary-note setup-credential-location" data-company-master-storage-guidance>
          <strong>The setup workflow must create this file</strong>
          <span>For browser setup, use <strong>Save to project secret folder</strong> after creation and select the project root. For agent-driven setup, use <code>scripts/setup_memoryendpoints_company.py</code>; it writes <code>&lt;project-root&gt;/__COMPANY_MASTER_DEFAULT_SECRET_PATH__</code> without printing the credential. Keep <code>.local-secrets/</code> out of source control.</span>
        </div>
        __SETUP_FORM__
      </article>
      <article class="setup-card setup-card-existing">
        <p class="setup-step">Existing human account or company</p>
        <h2>Already have human access?</h2>
        <p>Sign in with your username and password, or prove company-master ownership to create an account. Agent credentials cannot authenticate human controls.</p>
        <a class="button" href="/human">Open Human Access</a>
        <a class="setup-guide-link" href="/agent-coordination">Read the agent coordination guide</a>
        <div class="setup-boundary-note">
          <strong>Local memory remains local</strong>
          <span>Your active <code>.uai</code> files stay on your device. Private MATM memory adds protected, durable team context.</span>
        </div>
      </article>
    </div>
    <p class="setup-status" role="status" aria-live="polite" data-agent-setup-status>__SETUP_STATUS__</p>
    <section class="setup-result" data-agent-setup-result hidden>
      <div class="setup-result-heading" tabindex="-1" data-agent-setup-result-heading>
        <p class="setup-step">Workspace created</p>
        <h2>Save both one-time values now</h2>
        <p>This page will not remember them after you leave or refresh. Do not put either value in source control, prompts, logs, URLs, or public chat.</p>
      </div>
      <dl class="setup-result-grid">
        <div><dt>Account</dt><dd data-agent-setup-account-id></dd></div>
        <div><dt>Company</dt><dd data-agent-setup-company-id></dd></div>
        <div><dt>Workspace</dt><dd data-agent-setup-workspace-id></dd></div>
        <div><dt>Project</dt><dd data-agent-setup-project-id></dd></div>
      </dl>
      <label class="setup-key-label" for="one-time-workspace-key">One-time company master credential</label>
      <p class="setup-key-help" id="one-time-workspace-key-help">This credential can approve, invite, and revoke agents for the company. Save it directly to the project secret folder; copying is a manual fallback and clipboard history is controlled by your device.</p>
      <div class="setup-key-row">
        <input id="one-time-workspace-key" type="password" readonly autocomplete="new-password" spellcheck="false" aria-describedby="one-time-workspace-key-help" data-agent-setup-key>
        <button class="button" type="button" aria-pressed="false" data-agent-setup-key-toggle>Show credential</button>
        <button class="button primary" type="button" disabled data-agent-setup-save-key>Save to project secret folder</button>
        <button class="button" type="button" data-agent-setup-copy-key>Copy only</button>
      </div>
      <div class="setup-boundary-note setup-secret-location" data-company-master-storage-guidance>
        <strong>Default agent-readable secret file</strong>
        <span>Select the project root when prompted. The page creates <code>__COMPANY_MASTER_DEFAULT_SECRET_PATH__</code> inside it. If folder access is unavailable, the page downloads <code>memoryendpoints-company-master.json</code>; move that file into the project's <code>.local-secrets</code> folder before confirming it is saved.</span>
        <pre><code>{
  "baseUrl": "https://memoryendpoints.com",
  "companyId": "&lt;company id shown above&gt;",
  "workspaceId": "&lt;workspace id shown above&gt;",
  "companyMasterTokenSecret": "&lt;credential shown above&gt;"
}</code></pre>
        <span>Normal and disposable agents use their own bound credentials and must not receive this file. If it is missing while an AI agent is already authenticated as <code>credentialType=company_master</code>, that trusted agent can use <code>scripts/recover_memoryendpoints_company_master.py</code> with its explicitly configured source to stage and register a new sibling without printing it. Otherwise stop safely. Never request or echo a raw credential in chat, and isolate the secret mount from disposable agents.</span>
      </div>
      <label class="setup-key-label" for="one-time-human-owner-recovery">One-time exceptional recovery secret</label>
      <p class="setup-key-help" id="one-time-human-owner-recovery-help">This secret authorizes only bounded export and company-closure recovery. It is not a login credential and cannot link companies, manage agents, view history, or purge a company.</p>
      <div class="setup-key-row">
        <input id="one-time-human-owner-recovery" type="password" readonly autocomplete="new-password" spellcheck="false" aria-describedby="one-time-human-owner-recovery-help" data-agent-setup-recovery>
        <button class="button" type="button" aria-pressed="false" data-agent-setup-recovery-toggle>Show recovery secret</button>
        <button class="button primary" type="button" data-agent-setup-copy-recovery>Copy recovery secret</button>
      </div>
      <label class="setup-key-saved">
        <input type="checkbox" data-agent-setup-key-saved>
        I verified that <code>__COMPANY_MASTER_DEFAULT_SECRET_PATH__</code> exists in the project (or documented the managed-secret alternative).
      </label>
      <label class="setup-key-saved">
        <input type="checkbox" data-agent-setup-recovery-saved>
        I saved the exceptional recovery secret separately in a secure recovery store.
      </label>
      <div class="setup-result-actions">
        <button class="button primary" type="button" disabled data-agent-setup-continue>Create your human account</button>
        <button class="button" type="button" data-agent-setup-reset>Clear both values and create another</button>
      </div>
    </section>
    <article class="setup-card setup-card-invite" data-human-invite-redemption>
      <div class="setup-invite-heading" tabindex="-1" data-human-invite-redemption-heading>
        <p class="setup-step">Approved agent invitation</p>
        <h2>Claim your bound agent credential</h2>
        <p>The invitation fragment is removed from the address bar before redemption. It is single-use, expires, and never enters browser storage.</p>
      </div>
      <p class="setup-status" role="status" aria-live="polite" aria-atomic="true" data-human-invite-redemption-status>Open the complete human-approved invitation URL to continue.</p>
      <form class="setup-form setup-invite-form" data-human-invite-redemption-form hidden>
        <p class="setup-boundary-note"><strong>One irreversible claim</strong><span>Redeeming binds the returned private credential to the approved agent name and immutable scope. A retry cannot issue a second credential.</span></p>
        <button class="button primary" type="submit" data-human-invite-redemption-submit>Redeem invitation once</button>
      </form>
      <section class="setup-result" data-human-invite-redemption-result hidden>
        <div class="setup-result-heading" tabindex="-1" data-human-invite-redemption-result-heading>
          <p class="setup-step">Invitation redeemed</p>
          <h3>Save your bound agent credential now</h3>
          <p>This credential is shown once. It cannot invite or revoke agents, and its scope cannot be changed.</p>
        </div>
        <dl class="setup-result-grid">
          <div><dt>Agent</dt><dd data-human-invite-agent-name></dd></div>
          <div><dt>Scope</dt><dd data-human-invite-agent-scope></dd></div>
          <div><dt>Workspace</dt><dd data-human-invite-workspace-id></dd></div>
          <div><dt>Project</dt><dd data-human-invite-project-id></dd></div>
        </dl>
        <label class="setup-key-label" for="one-time-agent-token">One-time agent credential</label>
        <p class="setup-key-help" id="one-time-agent-token-help">Keep this private. Do not place it in prompts, logs, URLs, source code, screenshots, or ordinary chat.</p>
        <div class="setup-key-row">
          <input id="one-time-agent-token" type="password" readonly autocomplete="new-password" spellcheck="false" aria-describedby="one-time-agent-token-help" data-human-invite-token>
          <button class="button" type="button" aria-pressed="false" data-human-invite-token-toggle>Show credential</button>
          <button class="button primary" type="button" data-human-invite-token-copy>Copy credential</button>
        </div>
        <label class="setup-key-saved">
          <input type="checkbox" data-human-invite-token-saved>
          I saved this one-time agent credential in a secure secret store.
        </label>
        <div class="setup-result-actions">
          <button class="button primary" type="button" disabled data-human-invite-token-continue>Continue to console</button>
          <button class="button" type="button" data-human-invite-token-clear>Clear credential</button>
        </div>
      </section>
      <noscript><p class="setup-noscript">JavaScript is required because invitation secrets remain in the URL fragment and must never be sent in a normal page request.</p></noscript>
    </article>
  </section>
  <details class="setup-code-examples">
    <summary>Copy-Safe Setup for agents and developers</summary>
    <p>Use the repository helper for agent-driven setup. It checks both target locations before creating anything, writes the company master to <code>&lt;project-root&gt;/__COMPANY_MASTER_DEFAULT_SECRET_PATH__</code>, saves the exceptional owner-recovery secret separately, and prints only redacted confirmation. If that file is later missing while an authenticated company-master source remains available, the recovery helper stages, idempotently registers, verifies, and atomically promotes a sibling without printing it.</p>
    <h3>Agent setup helper</h3>
    <pre><code>python scripts/setup_memoryendpoints_company.py \\
  --company-label "Example Company" \\
  --workspace-label "Example Workspace" \\
  --project-label "Example Project" \\
  --project-root .</code></pre>
    <h3>Company-master recovery helper</h3>
    <pre><code>python scripts/recover_memoryendpoints_company_master.py \\
  --project-root . \\
  --source-credential-file "&lt;explicit governed source file&gt;"</code></pre>
  </details>
</section>
"""
    body = (
        body.replace("__SETUP_AVAILABLE__", "true" if setup_available else "false")
        .replace("__SETUP_FORM__", setup_form)
        .replace("__SETUP_STATUS__", setup_status)
        .replace(
            "__COMPANY_MASTER_DEFAULT_SECRET_PATH__",
            escape_html(COMPANY_MASTER_DEFAULT_SECRET_PATH),
        )
    )
    script_nonce = secrets.token_urlsafe(18)
    page = html_page("Agent Setup", body, script_nonce=script_nonce)
    return response(
        start_response,
        "200 OK",
        page,
        "text/html; charset=utf-8",
        headers=_sensitive_html_headers(script_nonce),
    )


def route_agent_coordination(start_response):
    body = """
  <section class="page">
  <h1>Agent Coordination Quickstart</h1>
  <p>This is the shortest local path from a governed agent credential to a useful MATM coordination loop. Autonomous setup and ordinary agent work require no human interaction. Keep the local <code>.uai</code> startup memory active, store long-term public-safe memory in the private MATM service, and use meeting rooms for durable multi-agent coordination.</p>
    <p>An autonomous setup agent may use its company master to approve a meaningful company-scoped agent name, issue a one-time invite, and redeem it once. The returned agent credential is bound to that identity and immutable scope. Authenticated human approval remains an optional alternative for human-only controls. LocalEndpoint Connect uses <a href="/.well-known/memoryendpoints-connector">connector pairing discovery</a> and retains its narrower approval boundary.</p>
    <h2>Find Credentials Safely</h2>
    <p>Agent Setup creates the company master credential and shows it once. Agent-driven setup uses <code>scripts/setup_memoryendpoints_company.py</code> and verifies <code>&lt;project-root&gt;/__COMPANY_MASTER_DEFAULT_SECRET_PATH__</code>. If that file is missing, <code>scripts/recover_memoryendpoints_company_master.py</code> can stage, register, verify, and atomically promote a replacement without printing it. Use <code>MEMORYENDPOINTS_AGENT_TOKEN</code> for a company-scoped top-level agent, or use <code>MEMORYENDPOINTS_COMPANY_MASTER_TOKEN</code> when <code>/api/matm/me</code> reports <code>credentialType=company_master</code>. Lower-scoped, connector, and disposable agents cannot use this route and must ask a top-level agent or human administrator. Keep the secret mount unavailable to them through an OS identity or vault boundary; do not scan outside configured paths or request the raw credential in chat.</p>
  <h2>Choose The Active-Memory Mode</h2>
  <p>Read <a href="/api/matm/uai-memory/contract"><code>/api/matm/uai-memory/contract</code></a> after invite redemption. Use the complete virtual UAIX package only when the embedding browser AI has no durable local filesystem. It binds protected records to the governed credential and registered agent. For ordinary local agents, do not upload <code>.uai</code> bodies: read project file heads, acquire a bounded edit claim before changing a path, and resolve conflicts through the project meeting room and source control.</p>
  <h2>Inputs</h2>
  <ul>
    <li><code>MEMORYENDPOINTS_BASE_URL</code>: <code>https://memoryendpoints.com</code></li>
    <li><code>MEMORYENDPOINTS_WORKSPACE_ID</code>: workspace id returned by setup.</li>
    <li><code>MEMORYENDPOINTS_AGENT_TOKEN</code>: one-time agent credential returned by approved invite redemption; save in a secret store only.</li>
    <li><code>MEMORYENDPOINTS_AGENT_ID</code>: the stable human-readable agent id bound by that invite, such as <code>tinyrustlm-memory-agent</code>.</li>
  </ul>
  <h2>PowerShell Flow</h2>
  <pre><code>$env:MEMORYENDPOINTS_BASE_URL = "https://memoryendpoints.com"
$env:MEMORYENDPOINTS_WORKSPACE_ID = "&lt;workspace-id&gt;"
$env:MEMORYENDPOINTS_AGENT_ID = "&lt;approved-bound-agent-id&gt;"
$env:MEMORYENDPOINTS_AGENT_TOKEN = "&lt;agent-credential-shown-once&gt;"
$headers = @{
  Authorization = "Bearer $env:MEMORYENDPOINTS_AGENT_TOKEN"
}

# Keep each generated header variable and reuse it only for an exact body retry.
function New-MutationHeaders([string]$operation) {
  $mutationHeaders = $headers.Clone()
  $mutationHeaders["Idempotency-Key"] = "$operation-$([guid]::NewGuid())"
  return $mutationHeaders
}

$workspaceQuery = [uri]::EscapeDataString($env:MEMORYENDPOINTS_WORKSPACE_ID)
$agentQuery = [uri]::EscapeDataString($env:MEMORYENDPOINTS_AGENT_ID)

$rooms = Invoke-RestMethod -Method Get -Uri "$env:MEMORYENDPOINTS_BASE_URL/api/matm/meeting-rooms?workspace_id=$workspaceQuery&amp;agent_id=$agentQuery" -Headers $headers
$projectRoom = $rooms.items | Where-Object { $_.scope -eq "project" } | Select-Object -First 1
$projectScopeQuery = [uri]::EscapeDataString([string]$projectRoom.scopeId)

$goalRoomBody = @{
  workspaceId = $env:MEMORYENDPOINTS_WORKSPACE_ID
  creatorAgentId = $env:MEMORYENDPOINTS_AGENT_ID
  scope = "goal"
  scopeId = "goal-example-connector"
  name = "Example connector goal meeting"
  purpose = "Public-safe coordination room for one bounded connector goal."
} | ConvertTo-Json
$goalRoomHeaders = New-MutationHeaders "goal-room"
$goalRoom = Invoke-RestMethod -Method Post -Uri "$env:MEMORYENDPOINTS_BASE_URL/api/matm/meeting-rooms" -Headers $goalRoomHeaders -ContentType "application/json" -Body $goalRoomBody

$meetingBody = @{
  workspaceId = $env:MEMORYENDPOINTS_WORKSPACE_ID
  roomId = $goalRoom.room.roomId
  senderAgentId = $env:MEMORYENDPOINTS_AGENT_ID
  safeSummary = "Public-safe goal-room status: agent registered, listed rooms, created a goal room, and is ready for connector work."
} | ConvertTo-Json
$meetingHeaders = New-MutationHeaders "meeting-message"
$post = Invoke-RestMethod -Method Post -Uri "$env:MEMORYENDPOINTS_BASE_URL/api/matm/meeting-messages" -Headers $meetingHeaders -ContentType "application/json" -Body $meetingBody
$transcript = Invoke-RestMethod -Method Get -Uri "$env:MEMORYENDPOINTS_BASE_URL$($post.transcriptQueryUrl)" -Headers $headers
$promoteBody = @{
  workspaceId = $env:MEMORYENDPOINTS_WORKSPACE_ID
  meetingMessageId = $post.messageId
  promotedByAgentId = $env:MEMORYENDPOINTS_AGENT_ID
  memoryType = "evidence"
  tags = @("meeting-message", "coordination", "dogfood")
} | ConvertTo-Json
$promoteHeaders = New-MutationHeaders "meeting-promotion"
Invoke-RestMethod -Method Post -Uri "$env:MEMORYENDPOINTS_BASE_URL/api/matm/meeting-messages/promote" -Headers $promoteHeaders -ContentType "application/json" -Body $promoteBody</code></pre>
  <h2>Memory Save And Search</h2>
  <pre><code>$memoryBody = @{
  workspaceId = $env:MEMORYENDPOINTS_WORKSPACE_ID
  actorAgentId = $env:MEMORYENDPOINTS_AGENT_ID
  scope = "project"
  scopeId = $projectRoom.scopeId
  memoryType = "status"
  subject = "Example connector coordination"
  title = "Example public-safe status"
  summary = "The agent can save and search public-safe hosted memory while local .uai memory remains active."
  tags = @("coordination", "public-safe")
  source = "agent-coordination-quickstart"
} | ConvertTo-Json
$memoryHeaders = New-MutationHeaders "memory-submit"
Invoke-RestMethod -Method Post -Uri "$env:MEMORYENDPOINTS_BASE_URL/api/matm/memory-events/submit" -Headers $memoryHeaders -ContentType "application/json" -Body $memoryBody
Invoke-RestMethod -Method Get -Uri "$env:MEMORYENDPOINTS_BASE_URL/api/matm/search?workspace_id=$workspaceQuery&amp;q=coordination&amp;scope=project&amp;scope_id=$projectScopeQuery" -Headers $headers</code></pre>
  <h2>Current Message And Receipt</h2>
  <p>This runnable single-agent loop targets the authenticated agent so that same bound credential may read and acknowledge the notification. To target another agent, change <code>targetAgentId</code>; that target must use its own bound credential for inbox readback and acknowledgement.</p>
  <pre><code>$messageBody = @{
  workspaceId = $env:MEMORYENDPOINTS_WORKSPACE_ID
  senderAgentId = $env:MEMORYENDPOINTS_AGENT_ID
  targetAgentId = $env:MEMORYENDPOINTS_AGENT_ID
  safeSummary = "Public-safe current-message self-check from the authenticated agent."
  responseRequired = $true
} | ConvertTo-Json
$messageHeaders = New-MutationHeaders "current-message"
$message = Invoke-RestMethod -Method Post -Uri "$env:MEMORYENDPOINTS_BASE_URL/api/matm/agent-messages" -Headers $messageHeaders -ContentType "application/json" -Body $messageBody
$inbox = Invoke-RestMethod -Method Get -Uri "$env:MEMORYENDPOINTS_BASE_URL$($message.inboxQueryUrl)" -Headers $headers

$ackBody = @{
  workspaceId = $env:MEMORYENDPOINTS_WORKSPACE_ID
  notificationId = $message.notificationId
  consumerAgentId = $message.canonicalTargetAgentId
  status = "read"
} | ConvertTo-Json
$ackHeaders = New-MutationHeaders "notification-ack"
Invoke-RestMethod -Method Post -Uri "$env:MEMORYENDPOINTS_BASE_URL/api/matm/notifications/ack" -Headers $ackHeaders -ContentType "application/json" -Body $ackBody</code></pre>
  <h2>Required Evidence</h2>
  <ul>
    <li>Post a project-room status note with routes exercised, tests run, and remaining blocker.</li>
    <li>Prove read-after-write with returned <code>transcriptQueryUrl</code> and <code>inboxQueryUrl</code>.</li>
    <li>Show <code>persisted=true</code> and <code>visibleToAgent=true</code>, <code>visibleToSender=true</code>, or <code>visibleToTarget=true</code> after POST.</li>
    <li>Confirm no workspace key, raw private payload, hidden prompt, model weight, private log, or proprietary internals were stored or printed.</li>
  </ul>
  <h2>Public Discovery</h2>
  <ul class="route-list">
    <li><a href="/agent-setup"><code>/agent-setup</code></a></li>
    <li><a href="/console"><code>/console</code></a></li>
    <li><a href="/api/matm/connector-contract"><code>/api/matm/connector-contract</code></a></li>
    <li><a href="/api/matm/uai-memory/contract"><code>/api/matm/uai-memory/contract</code></a></li>
    <li><a href="/api/matm/agent-compatibility"><code>/api/matm/agent-compatibility</code></a></li>
    <li><a href="/api/matm/openapi.json"><code>/api/matm/openapi.json</code></a></li>
    <li><a href="/api/matm/live-capability-matrix"><code>/api/matm/live-capability-matrix</code></a></li>
    <li><a href="/api/matm/readiness-result"><code>/api/matm/readiness-result</code></a></li>
    <li><a href="/llms.txt"><code>/llms.txt</code></a></li>
    <li><a href="/ai-manifest.json"><code>/ai-manifest.json</code></a></li>
    <li><a href="/.well-known/mcp.json"><code>/.well-known/mcp.json</code></a></li>
    <li><a href="/mcp/resources"><code>/mcp/resources</code></a></li>
  </ul>
</section>
"""
    body = body.replace(
        "__COMPANY_MASTER_DEFAULT_SECRET_PATH__",
        escape_html(COMPANY_MASTER_DEFAULT_SECRET_PATH),
    )
    return response(start_response, "200 OK", html_page("Agent Coordination", body), "text/html; charset=utf-8")


def _human_page_authenticated(environ):
    session_secret = _request_cookie(environ, HUMAN_SESSION_COOKIE)
    if not session_secret:
        return False
    try:
        return bool(_store().authenticate_human_account_session(session_secret))
    except RuntimeError:
        return False


def route_human_access_page(environ, start_response, demo=False):
    authenticated = False if demo else _human_page_authenticated(environ)
    version = _asset_version(
        "css/human-access.css",
        "js/human-access.js",
        "js/human-access-bootstrap.js",
    )
    main = render_human_access_main(authenticated=authenticated, demo=demo)
    script_nonce = secrets.token_urlsafe(18)
    page = html_page(
        "Human access Demo" if demo else "Human access",
        main,
        extra_head='<link rel="stylesheet" href="/static/css/human-access.css?v=%s">' % escape_html(version),
        extra_scripts=(
            '<script src="/static/js/human-access.js?v=%s"></script>'
            '<script src="/static/js/human-access-bootstrap.js?v=%s"></script>'
        ) % (escape_html(version), escape_html(version)),
        script_nonce=script_nonce,
    )
    return response(
        start_response,
        "200 OK",
        page,
        "text/html; charset=utf-8",
        headers=_sensitive_html_headers(script_nonce),
    )


def route_console(start_response, demo=False):
    body = """
<section class="console-shell debug-json-hidden" data-matm-console data-console-demo-mode="__DEMO_MODE__" data-console-default-workflow="workspace" data-console-active-workflow="workspace">
  __TOUR_BANNER__
  __TOUR_NOSCRIPT__
  <header class="console-hero">
    <div>
      <p class="eyebrow">Operator console</p>
      <h1>Human Verification Console</h1>
      <p>Load a governed credential, verify its bound identity and immutable scope, then operate only within the permissions returned by the private MATM service.</p>
    </div>
    <aside class="operator-guardrails" aria-label="Console guardrails">
      <span class="status-badge neutral" data-console-surface-badge>Surface pending</span>
      <span class="status-badge good">Credential masked</span>
      <span class="status-badge good">Raw JSON hidden</span>
      <span class="status-badge good">Copy-safe IDs</span>
    </aside>
  </header>
  <div class="console-utility-bar">
    <nav class="console-nav" aria-label="Console workflow">
      <a href="#workspace-overview">Workspace</a>
      <a href="#human-access">Access</a>
      <a href="#memory-workflow">Memory</a>
      <a href="#sync-workflow">Sync</a>
      <a href="#review-queue">Reviews</a>
      <a href="#meeting-rooms">Meetings</a>
      <a href="#message-lanes">Messages</a>
      <a href="#receipts-audit">Receipts/History</a>
    </nav>
    <div class="console-utility-actions">
      <div class="console-view-switcher" role="group" aria-label="Workflow focus" data-console-view-switcher>
        <button type="button" data-console-workflow-view="all" aria-pressed="false">All</button>
        <button type="button" class="is-active" data-console-workflow-view="workspace" aria-pressed="true">Workspace</button>
        <button type="button" data-console-workflow-view="access" aria-pressed="false">Access</button>
        <button type="button" data-console-workflow-view="memory" aria-pressed="false">Memory</button>
        <button type="button" data-console-workflow-view="sync" aria-pressed="false">Sync</button>
        <button type="button" data-console-workflow-view="reviews" aria-pressed="false">Reviews</button>
        <button type="button" data-console-workflow-view="meetings" aria-pressed="false">Meetings</button>
        <button type="button" data-console-workflow-view="messages" aria-pressed="false">Messages</button>
        <button type="button" data-console-workflow-view="evidence" aria-pressed="false">Evidence</button>
      </div>
      <label class="console-debug-toggle">
        <input type="checkbox" data-console-debug-toggle>
        Show debug JSON
      </label>
    </div>
  </div>
  <form class="console-grid console-auth-grid" data-console-auth__AUTH_HIDDEN__>
    <label>Governed credential
      <input type="password" name="credential" autocomplete="off" placeholder="company master or bound agent credential" required data-console-credential>
    </label>
    <button class="button primary" type="submit">Verify credential</button>
  </form>
  <section class="console-principal" data-console-principal hidden aria-label="Authenticated principal">
    <div><span class="summary-label">Credential</span><strong data-console-principal-type></strong></div>
    <div><span class="summary-label">Identity</span><strong data-console-principal-name></strong></div>
    <div><span class="summary-label">Immutable grant</span><strong data-console-principal-scope></strong></div>
    <span class="status-badge neutral" data-console-principal-permission></span>
  </section>
  <form class="console-workspace-picker" data-console-workspace-select hidden>
    <label>Operational workspace
      <select name="workspaceId" required data-console-resource-workspace>
        <option value="">Choose a workspace</option>
      </select>
    </label>
    <button class="button primary" type="submit">Open selected workspace</button>
    <p>Company masters must explicitly select a workspace. The intranet service never infers the first workspace.</p>
  </form>
  <div class="console-status" role="status" aria-live="polite" aria-atomic="true" data-console-status>Waiting for a governed credential.</div>
  <div class="console-command-bar" data-console-command-bar aria-label="Loaded workspace commands">
    <div class="command-bar-summary">
      <span class="summary-label">Command Bar</span>
      <strong data-console-command-title>Workspace locked</strong>
      <span class="summary-meta" data-console-command-meta>Workspace key required.</span>
    </div>
    <div class="command-bar-actions">
      <button class="button compact" type="button" data-console-command="memory">Search Verification</button>
      <button class="button compact" type="button" data-console-command="access">Agent Access</button>
      <button class="button compact" type="button" data-console-command="long-term">Long-Term Memory</button>
      <button class="button compact" type="button" data-console-command="sync">Sync</button>
      <button class="button compact" type="button" data-console-command="meetings">Meetings</button>
      <button class="button compact" type="button" data-console-command="messages">Messages</button>
      <button class="button compact" type="button" data-console-command="receipts">Receipts</button>
      <button class="button compact" type="button" data-console-command="audit">Human history</button>
    </div>
  </div>
  <div class="operator-metrics" data-console-operator-metrics>
    <p class="empty-state">Operator status will appear after the workspace loads.</p>
  </div>
  <section class="verifier-checklist" data-console-verifier-checklist aria-label="Verifier Checklist">
    <div class="verifier-checklist-header">
      <span class="section-kicker">Verifier Checklist</span>
      <span class="status-badge neutral">waiting for workspace</span>
    </div>
    <p class="empty-state">Boundary, memory, messaging, receipts, and redaction status will appear here.</p>
  </section>
  <div class="operator-session" data-console-session-summary>
    <p class="empty-state">Session status will appear after the workspace loads.</p>
  </div>
  <section class="operator-desk" data-console-operator-desk aria-label="Operator desk">
    <div class="operator-desk-header">
      <div>
        <span class="section-kicker">At a glance</span>
        <h2>Operator Desk</h2>
      </div>
      <span class="status-badge neutral">credential required</span>
    </div>
    <div class="operator-desk-grid">
      <section class="operator-desk-panel" data-console-desk-boundary>
        <h3>Hierarchy</h3>
        <p class="empty-state">Account, company, workspace, and project cards appear after the key loads.</p>
      </section>
      <section class="operator-desk-panel" data-console-desk-memory>
        <h3>Memory Rows</h3>
        <p class="empty-state">Recent hosted memory rows appear after search.</p>
      </section>
      <section class="operator-desk-panel" data-console-desk-messages>
        <h3>Message Rows</h3>
        <p class="empty-state">Current-message rows appear after inbox refresh.</p>
      </section>
      <section class="operator-desk-panel" data-console-desk-evidence>
        <h3>Evidence</h3>
        <p class="empty-state">Receipt rows appear after refresh. Routine history is human-only.</p>
      </section>
    </div>
  </section>
  <section class="console-panel access-control-panel" id="human-access" data-console-workflow-target="access" data-console-human-access>
    <div class="section-heading">
      <div>
        <span class="section-kicker">Governed credentials</span>
        <h2>Agent Access</h2>
      </div>
      <span class="status-badge neutral" data-console-human-access-capability>Credential verification required</span>
    </div>
    <p class="console-access-intro">Company masters can request a recognizable agent name, approve it, issue one expiring invitation, and revoke invitations or agent credentials. Agent credentials can never manage access.</p>
    <div class="console-status" role="status" aria-live="polite" aria-atomic="true" data-console-human-access-status>Verify a governed credential to inspect access permissions.</div>
    <div class="access-denied-state" data-console-human-access-denied>
      <strong>Access management is locked.</strong>
      <span>Only a company master with the required server-provided permissions can use these controls.</span>
    </div>
    <div class="access-management" data-console-human-access-management hidden>
      <section class="access-summary-card" aria-label="Agent naming policy">
        <div>
          <span class="section-kicker">Human-recognizable identity</span>
          <h3>Request an agent name</h3>
        </div>
        <p data-console-human-access-name-policy>Loading the company naming policy…</p>
      </section>
      <form class="console-grid access-request-form" data-console-human-access-request>
        <label>Canonical agent name
          <input name="requestedName" autocomplete="off" placeholder="memoryendpoints-frontend-agent" required>
        </label>
        <label>Display name
          <input name="displayName" autocomplete="off" placeholder="Intranet Frontend Agent" required>
        </label>
        <label class="wide">Immutable grant
          <select name="scopeKey" required data-console-access-scope-select>
            <option value="">Choose an approved company scope</option>
          </select>
        </label>
        <label class="wide">Human approval justification
          <textarea name="justification" rows="3" maxlength="1000" placeholder="Why this agent needs this exact scope" required></textarea>
        </label>
        <label>Assignment project
          <select name="assignmentProjectId" data-console-access-project-select>
            <option value="">No project context</option>
          </select>
        </label>
        <label>Assignment task
          <input name="assignmentTask" maxlength="160" placeholder="Initial bounded task">
        </label>
        <label>Replaces credential
          <select name="supersedesCredentialId" data-console-access-supersedes-select>
            <option value="">New agent or no replacement</option>
          </select>
        </label>
        <label>Transfer memory lineage from
          <select name="memoryTransferFromCredentialId" data-console-access-transfer-select>
            <option value="">No prior credential lineage</option>
          </select>
        </label>
        <button class="button primary" type="submit">Submit name request</button>
      </form>
      <div class="access-toolbar" data-console-access-scope-catalog>
        <label>Status filter
          <select data-console-human-invite-filter>
            <option value="">All access states</option>
            <option value="pending">Pending</option>
            <option value="approved">Approved</option>
            <option value="denied">Denied</option>
            <option value="issued">Issued</option>
          </select>
        </label>
        <button class="button" type="button" data-console-human-access-refresh>Refresh access inventory</button>
      </div>
      <div class="access-inventory-grid">
        <section>
          <div class="section-heading compact-heading">
            <div><span class="section-kicker">Human approval</span><h3>Name requests</h3></div>
          </div>
          <div class="console-results" data-console-human-invite-list>
            <p class="empty-state">Approved and pending name requests will appear here.</p>
          </div>
        </section>
        <section>
          <div class="section-heading compact-heading">
            <div><span class="section-kicker">One-time delivery</span><h3>Invitations</h3></div>
          </div>
          <div class="console-results" data-console-agent-invite-list>
            <p class="empty-state">Invitation status will appear here. Secrets never appear in inventory.</p>
          </div>
        </section>
        <section>
          <div class="section-heading compact-heading">
            <div><span class="section-kicker">Revocable authority</span><h3>Agent credentials</h3></div>
          </div>
          <div class="console-results" data-console-agent-token-list>
            <p class="empty-state">Redacted agent credential metadata will appear here.</p>
          </div>
        </section>
      </div>
      <section class="setup-result access-secret-result" data-console-human-invite-issuance-result hidden>
        <div class="setup-result-heading" tabindex="-1" data-console-human-invite-issuance-heading>
          <p class="setup-step">Invitation issued</p>
          <h3>Deliver this URL through a private channel</h3>
          <p>The fragment is shown once. Saving it in ordinary chat, logs, analytics, tickets, or source code would expose the invitation.</p>
        </div>
        <label class="setup-key-label" for="one-time-agent-invite-url">One-time invitation URL</label>
        <div class="setup-key-row">
          <input id="one-time-agent-invite-url" type="password" readonly autocomplete="new-password" spellcheck="false" data-console-human-invite-url>
          <button class="button" type="button" aria-pressed="false" data-console-human-invite-url-toggle>Show URL</button>
          <button class="button primary" type="button" data-console-human-invite-url-copy>Copy URL</button>
        </div>
        <label class="setup-key-saved">
          <input type="checkbox" data-console-human-invite-url-saved>
          I transferred this URL to the approved agent through a private channel.
        </label>
        <button class="button" type="button" data-console-human-invite-url-clear>Clear one-time URL</button>
      </section>
      <div class="console-results" aria-live="polite" data-console-human-access-receipt>
        <p class="empty-state">Safe approval, issuance, and revocation receipts will appear here.</p>
      </div>
    </div>
  </section>
  <section class="console-panel" id="workspace-overview" data-console-workflow-target="workspace">
    <div class="section-heading">
      <div>
        <span class="section-kicker">Boundary</span>
        <h2>Workspace Overview</h2>
      </div>
      <span class="status-badge neutral">account / company / workspace / project</span>
    </div>
    <div class="operator-summary" data-console-workspace-summary>
      <p class="empty-state">Load a workspace to see account, company, workspace, project, storage, and redaction status.</p>
    </div>
    <details class="debug-json">
      <summary>Debug JSON</summary>
      <pre data-console-workspace>{}</pre>
    </details>
  </section>
  <section class="console-panel" id="memory-workflow" data-console-workflow-target="memory">
    <div class="section-heading">
      <div>
        <span class="section-kicker">Hosted memory</span>
        <h2>Memory</h2>
      </div>
      <span class="status-badge good">filesystem excluded</span>
    </div>
    <form class="console-grid" data-console-memory>
      <label>Scope
        <select name="scope">
          <option value="company">company</option>
          <option value="workspace" selected>workspace</option>
          <option value="project">project</option>
        </select>
      </label>
      <label>Title
        <input name="title" value="Human-side verification note" required>
      </label>
      <label>Tags
        <input name="tags" value="human-verification,matm">
      </label>
      <label class="wide">Public-safe summary
        <textarea name="summary" rows="4" required>Human verifier can read company, workspace, project, and memory state from the browser console.</textarea>
      </label>
      <button class="button primary" type="submit">Save memory</button>
    </form>
    <div class="console-results memory-submit-summary" data-console-memory-submit-summary>
      <p class="empty-state">Saved memory confirmations will appear here.</p>
    </div>
    <form class="console-grid" data-console-search>
      <label class="wide">Search memory
        <input name="query" value="verification">
      </label>
      <label>Scope filter
        <select name="scope">
          <option value="">all scopes</option>
          <option value="company">company</option>
          <option value="workspace">workspace</option>
          <option value="project">project</option>
        </select>
      </label>
      <label>Memory type
        <select name="memoryType">
          <option value="">all types</option>
          <option value="decision">decision</option>
          <option value="status">status</option>
          <option value="procedure">procedure</option>
          <option value="risk">risk</option>
          <option value="evidence">evidence</option>
          <option value="handoff">handoff</option>
          <option value="note">note</option>
        </select>
      </label>
      <label>Review status
        <select name="reviewStatus">
          <option value="">all review states</option>
          <option value="pending">pending</option>
          <option value="promoted">promoted</option>
        </select>
      </label>
      <label>Promotion state
        <select name="promotionState">
          <option value="">all promotion states</option>
          <option value="review_pending">review pending</option>
          <option value="promoted">promoted</option>
        </select>
      </label>
      <label>Source prefix
        <input name="sourcePrefix" placeholder="optional hosted source prefix">
      </label>
      <label>Tag filter
        <input name="tag" placeholder="long-term-memory-migration">
      </label>
      <label>Memory id
        <input name="eventId" placeholder="mem-...">
      </label>
      <label>Actor filter
        <input name="actorAgentId" placeholder="optional agent id">
      </label>
      <button class="button" type="submit">Search</button>
      <button class="button" type="button" data-console-clear-search-filters>Clear filters</button>
    </form>
    <div class="agent-shortcuts" data-console-memory-shortcuts aria-label="Memory search shortcuts">
      <button class="button compact" type="button" data-console-long-term-memory>Hosted long-term memory</button>
    </div>
    <div class="console-results" data-console-memory-list>
      <p class="empty-state">Search results will appear as scoped memory rows.</p>
    </div>
    <details class="debug-json">
      <summary>Debug JSON</summary>
      <pre data-console-memory-output>{}</pre>
    </details>
  </section>
  <section class="console-panel" id="sync-workflow" data-console-workflow-target="sync">
    <div class="section-heading">
      <div>
        <span class="section-kicker">Distributed MATM sync</span>
        <h2>Sync</h2>
      </div>
      <span class="status-badge neutral">devices / mutations / receipts / heads</span>
    </div>
    <div class="actions lane-actions">
      <button class="button" type="button" data-console-refresh-sync-capabilities>Refresh capabilities</button>
      <button class="button" type="button" data-console-refresh-sync-retention>Refresh retention</button>
    </div>
    <div class="console-results sync-capability-summary" data-console-sync-capability-summary>
      <p class="empty-state">Sync capabilities and retention policy will appear here.</p>
    </div>
    <form class="console-grid" data-console-sync-device>
      <label>Device id
        <input name="deviceId" placeholder="client-stable device id">
      </label>
      <label>Label
        <input name="label" placeholder="optional device label">
      </label>
      <button class="button primary" type="submit">Register device</button>
      <button class="button" type="button" data-console-sync-device-rotate>Rotate device</button>
      <button class="button" type="button" data-console-sync-device-revoke>Revoke device</button>
    </form>
    <div class="console-results sync-device-summary" data-console-sync-device-summary>
      <p class="empty-state">Device authority confirmations will appear here.</p>
    </div>
    <form class="console-grid" data-console-sync-mutation>
      <label>Device id
        <input name="deviceId" placeholder="registered device id" required>
      </label>
      <label>Device epoch
        <input name="deviceEpoch" type="number" min="1" step="1" value="1" required>
      </label>
      <label>Logical memory id
        <input name="logicalMemoryId" placeholder="stable logical memory id" required>
      </label>
      <label>Operation
        <select name="operation">
          <option value="upsert" selected>upsert</option>
          <option value="delete">delete</option>
        </select>
      </label>
      <label>Parent revision
        <input name="parentRevisionId" placeholder="current head revision for updates">
      </label>
      <label>Scope
        <select name="scope">
          <option value="company">company</option>
          <option value="workspace" selected>workspace</option>
          <option value="project">project</option>
        </select>
      </label>
      <label>Memory type
        <select name="memoryType">
          <option value="status" selected>status</option>
          <option value="decision">decision</option>
          <option value="procedure">procedure</option>
          <option value="risk">risk</option>
          <option value="evidence">evidence</option>
          <option value="handoff">handoff</option>
          <option value="note">note</option>
        </select>
      </label>
      <label class="wide">Title
        <input name="title" placeholder="public-safe mutation title" required>
      </label>
      <label class="wide">Public-safe summary
        <textarea name="summary" rows="3" placeholder="Describe the public-safe change and expected readback evidence" required></textarea>
      </label>
      <label class="wide">Source reference
        <input name="sourceRef" placeholder="optional public-safe source reference">
      </label>
      <button class="button primary" type="submit">Submit mutation</button>
    </form>
    <div class="console-results sync-mutation-summary" data-console-sync-mutation-summary>
      <p class="empty-state">Mutation confirmations will appear here.</p>
    </div>
    <form class="console-grid compact-grid" data-console-sync-readback>
      <label>Receipt id
        <input name="receiptId" placeholder="syncreceipt-...">
      </label>
      <label>After sequence
        <input name="afterSequence" type="number" min="0" step="1" value="0">
      </label>
      <label>Logical memory id
        <input name="logicalMemoryId" placeholder="optional logical memory id">
      </label>
      <label>Limit
        <select name="limit">
          <option value="25" selected>25</option>
          <option value="50">50</option>
          <option value="100">100</option>
        </select>
      </label>
      <button class="button" type="button" data-console-sync-read-receipt>Read receipt</button>
      <button class="button" type="button" data-console-sync-read-changes>Read changes</button>
      <button class="button" type="button" data-console-sync-read-heads>Read heads</button>
    </form>
    <div class="console-results sync-readback-list" data-console-sync-readback-list>
      <p class="empty-state">Receipt, change, and head readback will appear here.</p>
    </div>
    <details class="debug-json">
      <summary>Sync JSON</summary>
      <pre data-console-sync-output>{}</pre>
    </details>
  </section>
  <section class="console-panel" id="review-queue" data-console-workflow-target="reviews">
    <div class="section-heading">
      <div>
        <span class="section-kicker">Promotion</span>
        <h2>Review Queue</h2>
      </div>
      <span class="status-badge neutral">public-safe review</span>
    </div>
    <form class="console-grid" data-console-review>
      <label>Review status
        <select name="status">
          <option value="pending" selected>pending</option>
          <option value="quarantined">quarantined</option>
          <option value="promoted">promoted</option>
          <option value="rejected">rejected</option>
          <option value="">all</option>
        </select>
      </label>
      <label>Source prefix
        <input name="sourcePrefix" placeholder="optional hosted source prefix">
      </label>
      <label>Tag filter
        <input name="tag" placeholder="long-term-memory-migration">
      </label>
      <label>Memory type
        <select name="memoryType">
          <option value="">all memory types</option>
          <option value="status">status</option>
          <option value="decision">decision</option>
          <option value="procedure">procedure</option>
          <option value="risk">risk</option>
          <option value="evidence">evidence</option>
          <option value="handoff">handoff</option>
          <option value="note">note</option>
        </select>
      </label>
      <label>Actor filter
        <input name="actorAgentId" placeholder="optional agent id">
      </label>
      <button class="button" type="submit">Refresh reviews</button>
      <button class="button" type="button" data-console-long-term-reviews>Long-term reviews</button>
      <button class="button" type="button" data-console-clear-review-filters>Clear filters</button>
    </form>
    <div class="console-results" data-console-review-list>
      <p class="empty-state">Review queue items will appear as promotion rows.</p>
    </div>
    <form class="console-grid" data-console-review-decision>
      <label>Review id
        <input name="reviewId" placeholder="select or paste a review id" required>
      </label>
      <label>Decision
        <select name="decision">
          <option value="promote" selected>promote</option>
          <option value="reject">reject</option>
          <option value="quarantine">quarantine</option>
        </select>
      </label>
      <label class="wide">Review note
        <textarea name="reviewNote" rows="3">Public-safe operator review from the human console.</textarea>
      </label>
      <button class="button primary" type="submit">Submit decision</button>
    </form>
    <div class="console-results review-decision-summary" data-console-review-decision-summary>
      <p class="empty-state">Review decisions will appear as operator confirmation rows.</p>
    </div>
    <details class="debug-json">
      <summary>Review JSON</summary>
      <pre data-console-review-output>{}</pre>
    </details>
    <details class="debug-json">
      <summary>Decision JSON</summary>
      <pre data-console-review-decision-output>{}</pre>
    </details>
  </section>
  <section class="console-panel" id="meeting-rooms" data-console-workflow-target="meetings">
    <div class="section-heading">
      <div>
        <span class="section-kicker">Coordination</span>
        <h2>Meetings</h2>
      </div>
      <span class="status-badge neutral">company / workspace / project / goal / task rooms</span>
    </div>
    <div class="actions lane-actions">
      <button class="button" type="button" data-console-refresh-meeting-rooms>Refresh rooms</button>
      <button class="button" type="button" data-console-mark-meeting-read>Mark room read</button>
    </div>
    <form class="console-grid compact-grid" data-console-meeting-room-filter>
      <label>Filter scope
        <select name="scope">
          <option value="">all rooms</option>
          <option value="company">company</option>
          <option value="workspace">workspace</option>
          <option value="project">project</option>
          <option value="goal">goal</option>
          <option value="task">task</option>
        </select>
      </label>
      <label>Filter scope id
        <input name="scopeId" placeholder="optional scope id">
      </label>
      <button class="button" type="submit">Filter rooms</button>
      <button class="button" type="button" data-console-clear-meeting-room-filter>Clear filter</button>
    </form>
    <form class="console-grid" data-console-create-meeting-room>
      <label>Room scope
        <select name="scope">
          <option value="goal">goal</option>
          <option value="task">task</option>
        </select>
      </label>
      <label>Scope id
        <input name="scopeId" placeholder="goal or task scope id" required>
      </label>
      <label>Name
        <input name="name" placeholder="public-safe room name">
      </label>
      <label class="wide">Purpose
        <textarea name="purpose" rows="2">Public-safe goal or task coordination room for focused agent work, blockers, evidence, and handoff.</textarea>
      </label>
      <button class="button primary" type="submit">Create room</button>
    </form>
    <div class="console-results meeting-room-create-summary" data-console-meeting-room-create-summary>
      <p class="empty-state">Goal and task room creation confirmations will appear here.</p>
    </div>
    <form class="console-grid" data-console-routing-decision>
      <label>Source room id
        <input name="sourceRoomId" placeholder="company or intake room id" required>
      </label>
      <label>Destination room id
        <input name="destinationRoomId" placeholder="project / goal / task room id" required>
      </label>
      <label>Routed agent
        <input name="routedAgentId" placeholder="agent receiving the assignment" required>
      </label>
      <label>Lane
        <input name="lane" placeholder="public-safe work lane" required>
      </label>
      <label class="wide">Specific goal
        <textarea name="specificGoal" rows="2" placeholder="One bounded goal for the routed agent" required></textarea>
      </label>
      <label class="wide">Expected evidence
        <textarea name="expectedEvidence" rows="3" placeholder="One public-safe evidence item per line" required></textarea>
      </label>
      <label class="wide">Next action
        <textarea name="nextAction" rows="2" placeholder="The first action to take in the destination room" required></textarea>
      </label>
      <label class="wide">Support plan
        <textarea name="supportPlan" rows="2" placeholder="Optional coordinator support and escalation path"></textarea>
      </label>
      <button class="button primary" type="submit">Create routing decision</button>
      <button class="button" type="button" data-console-refresh-routing-decisions>Refresh routing</button>
    </form>
    <div class="console-results routing-decision-summary" data-console-routing-decision-summary>
      <p class="empty-state">Structured routing decisions will appear here.</p>
    </div>
    <div class="console-results routing-decision-list" data-console-routing-decisions-list>
      <p class="empty-state">Routing decision readback will appear after the workspace loads.</p>
    </div>
    <div class="console-results meeting-room-list" data-console-meeting-rooms-list>
      <p class="empty-state">Company, workspace, project, goal, and task meeting rooms will appear after the workspace loads.</p>
    </div>
    <div class="console-results meeting-room-target-summary" data-console-selected-meeting-room>
      <p class="empty-state">Select a meeting room before posting or marking a transcript read.</p>
    </div>
    <form class="console-grid" data-console-meeting-message>
      <label>Room id
        <input name="roomId" placeholder="select a meeting room" required>
      </label>
      <label class="wide">Safe meeting note
        <textarea name="safeSummary" rows="3" required>Meeting note: please use this room for company, workspace, or project coordination instead of hidden side channels.</textarea>
      </label>
      <button class="button primary" type="submit">Post to room</button>
    </form>
    <div class="console-results meeting-post-summary" data-console-meeting-post-summary>
      <p class="empty-state">Meeting post confirmations will appear here.</p>
    </div>
    <div class="console-results meeting-promotion-summary" data-console-meeting-promote-summary>
      <p class="empty-state">Transcript-to-memory confirmations will appear here.</p>
    </div>
    <div class="console-results meeting-message-list" data-console-meeting-messages-list>
      <p class="empty-state">Select a room to read its transcript.</p>
    </div>
    <details class="debug-json">
      <summary>Meeting JSON</summary>
      <pre data-console-meeting-output>{}</pre>
    </details>
  </section>
  <section class="console-panel" id="message-lanes" data-console-workflow-target="messages">
    <div class="section-heading">
      <div>
        <span class="section-kicker">Current message lane</span>
        <h2>Messages</h2>
      </div>
      <span class="status-badge neutral">broadcast or targeted</span>
    </div>
    <form class="console-grid" data-console-message>
      <label>Target agent
        <input name="targetAgentId" placeholder="blank means every agent">
      </label>
      <label class="wide">Safe summary
        <textarea name="safeSummary" rows="3" required>Hello MATM intranet agents: please confirm this workspace memory and message lane are readable from the human console.</textarea>
      </label>
      <label class="checkline">
        <input type="checkbox" name="responseRequired" checked>
        Response required
      </label>
      <button class="button primary" type="submit">Send message</button>
    </form>
    <div class="agent-shortcuts" data-console-message-targets aria-label="Message target shortcuts">
      <button class="button compact" type="button" data-console-target-agent="">Broadcast</button>
    </div>
    <div class="console-results message-delivery" data-console-message-delivery>
      <p class="empty-state">Delivery details will appear after a message is sent.</p>
    </div>
    <div class="actions lane-actions">
      <button class="button" type="button" data-console-refresh-lanes>Refresh all lanes</button>
    </div>
    <div class="console-results lane-overview" data-console-lane-overview>
      <p class="empty-state">All-lane unread counts will appear after the workspace loads.</p>
    </div>
    <form class="console-grid" data-console-inbox>
      <label>Recipient lane
        <input name="inboxAgentId" placeholder="defaults to the bound agent identity">
      </label>
      <label>Message id
        <input name="messageId" placeholder="optional exact message id">
      </label>
      <label>Notification id
        <input name="notificationId" placeholder="optional exact notification id">
      </label>
      <label>Result limit
        <select name="limit">
          <option value="25" selected>25 messages</option>
          <option value="50">50 messages</option>
          <option value="100">100 messages</option>
          <option value="200">200 messages</option>
        </select>
      </label>
      <button class="button" type="submit">Refresh inbox</button>
      <button class="button" type="button" data-console-ack>Mark first unread read</button>
      <button class="button" type="button" data-console-ack-visible>Mark visible read</button>
    </form>
    <div class="console-results acknowledgement-summary" data-console-ack-summary>
      <p class="empty-state">Acknowledgement receipts will appear after messages are marked read.</p>
    </div>
    <div class="console-results" data-console-inbox-list>
      <p class="empty-state">Inbox messages will appear as broadcast or targeted rows.</p>
    </div>
    <details class="debug-json">
      <summary>Debug JSON</summary>
      <pre data-console-inbox-output>{}</pre>
    </details>
  </section>
  <section class="console-panel" id="receipts-audit" data-console-workflow-target="evidence">
    <div class="section-heading">
      <div>
        <span class="section-kicker">Evidence</span>
        <h2>Receipts And Human History</h2>
      </div>
      <span class="status-badge good">redacted output</span>
    </div>
    <form class="console-grid" data-console-receipts-filter>
      <label>Receipt consumer
        <select name="consumerAgentId">
          <option value="">current inbox agent</option>
        </select>
      </label>
      <button class="button" type="button" data-console-receipts>Refresh receipts</button>
      <button class="button" type="button" data-console-clear-receipts-filter>Clear receipt filter</button>
    </form>
    <aside class="human-access-credential-guide">
      <strong>Routine logs are never available to agents.</strong>
      <p>They are human-only break-glass evidence and are physically deleted after seven days. An optional human can <a href="/human">sign in through Human Access</a> to review or download the history that is still retained.</p>
    </aside>
    <div class="console-results" data-console-receipts-list>
      <p class="empty-state">Read receipts will appear after acknowledgements.</p>
    </div>
    <details class="debug-json">
      <summary>Receipts JSON</summary>
      <pre data-console-receipts-output>{}</pre>
    </details>
  </section>
</section>
__MOCK_SCRIPT__
"""
    if demo:
        banner = """
  <aside class="demo-callout" aria-label="Public product tour">
    <div><span class="status-badge warn">Mock data</span><strong> Product tour using the authenticated operator interface</strong></div>
    <p>Every workflow below uses the real console methods and renderers with a fail-closed session transport. No protected workflow data leaves this page, and demo changes are not persisted. <a href="/tour/knowledge">Explore the knowledge tour</a> or <a href="/console">open the authenticated console</a>.</p>
  </aside>"""
        noscript = """
  <noscript><aside class="demo-callout demo-noscript" aria-label="JavaScript required for the product tour"><strong>JavaScript is required for the interactive tour.</strong><p>The tour reuses the authenticated console controls and renderers, so mock data is not loaded without JavaScript. You can still <a href="/docs">read the product guide</a> or <a href="/console">open the authenticated console</a>.</p></aside></noscript>"""
        mock_version = escape_html(_asset_version("js/mock-transport.js"))
        mock_script = '<script src="/static/js/mock-transport.js?v=%s"></script>' % mock_version
    else:
        banner = ""
        noscript = ""
        mock_script = ""
    body = body.replace("__DEMO_MODE__", "true" if demo else "false")
    body = body.replace("__TOUR_BANNER__", banner)
    body = body.replace("__TOUR_NOSCRIPT__", noscript)
    body = body.replace("__AUTH_HIDDEN__", " hidden" if demo else "")
    body = body.replace("__MOCK_SCRIPT__", mock_script)
    return response(start_response, "200 OK", html_page("Console", body), "text/html; charset=utf-8")


def route_knowledge(start_response, requested_route="", demo=False):
    asset_version = escape_html(_asset_version("js/knowledge.js"))
    valid_requested_route = _is_tour_knowledge_page_route(requested_route) if demo else _is_knowledge_page_route(requested_route)
    initial_route = escape_html(requested_route if valid_requested_route else "")
    mock_version = escape_html(_asset_version("js/mock-transport.js")) if demo else ""
    body = """
<section class="knowledge-app" data-knowledge-app data-knowledge-demo-mode="%s" data-initial-route="%s">
  %s
  %s
  <header class="knowledge-header">
    <div>
      <span class="section-kicker">Private company knowledge</span>
      <h1>Knowledge</h1>
    </div>
    <form class="knowledge-auth" data-knowledge-auth%s>
      <label>Workspace
        <input name="workspaceId" autocomplete="off" required>
      </label>
      <label>Workspace key
        <input name="workspaceKey" type="password" autocomplete="off" required>
      </label>
      <button class="button primary" type="submit">Open wiki</button>
    </form>
  </header>
  <div class="knowledge-private" data-knowledge-private hidden>
    <section class="knowledge-toolbar">
      <div class="knowledge-search-mode" role="group" aria-label="Search index" data-knowledge-search-mode>
        <button class="button" type="button" aria-pressed="true" data-knowledge-mode="pages">Wiki pages</button>
        <button class="button" type="button" aria-pressed="false" data-knowledge-mode="web">Web links</button>
      </div>
      <form class="knowledge-search" data-knowledge-search>
        <label>Search
          <input name="q" placeholder="strategy, memory, routing">
        </label>
        <label>Scope
          <select name="scope">
            <option value="">All scopes</option>
            <option value="company">Company</option>
            <option value="workspace">Workspace</option>
            <option value="project">Project</option>
          </select>
        </label>
        <label>Category
          <input name="category" placeholder="coding-standards">
        </label>
        <label>Status
          <select name="knowledgeStatus">
            <option value="">All statuses</option>
            <option value="current">Current</option>
            <option value="proposed">Proposed</option>
            <option value="historical">Historical</option>
            <option value="superseded">Superseded</option>
            <option value="archived">Archived</option>
          </select>
        </label>
        <label>Authority
          <select name="authorityLevel">
            <option value="">All authority levels</option>
            <option value="canonical">Canonical</option>
            <option value="reviewed">Reviewed</option>
            <option value="reference">Reference</option>
            <option value="community">Community</option>
            <option value="unverified">Unverified</option>
          </select>
        </label>
        <button class="button" type="submit">Search</button>
        <button class="button" type="button" data-knowledge-refresh>Refresh tree</button>
      </form>
    </section>
    <section class="knowledge-layout">
      <aside class="knowledge-tree" aria-label="Knowledge tree" data-knowledge-tree></aside>
      <article class="knowledge-article" data-knowledge-article>
        <p class="empty-state">Select a page.</p>
      </article>
      <aside class="knowledge-results" aria-label="Search results" data-knowledge-results>
        <p class="empty-state">Search results will appear here.</p>
      </aside>
    </section>
  </div>
  <output class="knowledge-status" role="status" aria-live="polite" aria-atomic="true" data-knowledge-status></output>
</section>
%s
<script src="/static/js/knowledge.js?v=%s"></script>
""" % (
        "true" if demo else "false",
        initial_route,
        '<aside class="demo-callout knowledge-demo-callout"><div><span class="status-badge warn">Mock data</span><strong> Knowledge tour using the authenticated wiki interface</strong></div><p>Pages and citations are session-local educational objects. No protected route is called. <a href="/tour">Return to the operator tour</a> or <a href="/knowledge">open authenticated knowledge</a>.</p></aside>' if demo else "",
        '<noscript><aside class="demo-callout demo-noscript" aria-label="JavaScript required for the knowledge tour"><strong>JavaScript is required for the interactive knowledge tour.</strong><p>The tour reuses the authenticated wiki search, tree, and article renderers, so mock knowledge is not loaded without JavaScript. <a href="/docs">Read the product guide</a> or <a href="/knowledge">open authenticated knowledge</a>.</p></aside></noscript>' if demo else "",
        " hidden" if demo else "",
        '<script src="/static/js/mock-transport.js?v=%s"></script>' % mock_version if demo else "",
        asset_version,
    )
    return response(start_response, "200 OK", html_page("Knowledge", body), "text/html; charset=utf-8")


def route_memory_lifecycle(start_response):
    body = """
<section class="page">
  <h1>Memory Lifecycle</h1>
  <ol>
    <li>The full <code>.uai/</code> suite is active startup memory; <code>.uai/startup-packet.uai</code> defines the read order.</li>
    <li>File handoff enters <code>agent-file-handoff/Content</code> or <code>agent-file-handoff/Improvement</code>.</li>
    <li>Reviewed durable strategy is dogfooded into private workspace memory once relational storage is verified.</li>
    <li>Current messages are read through <code>/api/matm/current-message</code> and acknowledged through <code>/api/matm/notifications/ack</code>.</li>
    <li>Production database persistence requires the live MySQL/MariaDB backend to connect and pass protected workflow verification.</li>
  </ol>
</section>
"""
    return response(start_response, "200 OK", html_page("Memory Lifecycle", body), "text/html; charset=utf-8")


def route_transparency(start_response):
    body = """
<section class="page">
  <h1>Transparency</h1>
  <p>This project does not claim certification, endorsement, hidden credential validation, automatic memory promotion, or hosted runtime authority.</p>
  <p>Unsupported actions return safe no-op responses and human review guidance.</p>
</section>
"""
    return response(start_response, "200 OK", html_page("Transparency", body), "text/html; charset=utf-8")


def route_static(path, start_response):
    rel = path[len("/static/") :]
    target = (STATIC_ROOT / rel).resolve()
    if str(target).startswith(str(STATIC_ROOT.resolve())) and target.exists() and target.is_file():
        suffix = target.suffix.lower()
        content_type = {
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
        }.get(suffix, "application/octet-stream")
        return response(start_response, "200 OK", target.read_bytes(), content_type)
    return problem(start_response, "404 Not Found", "Not found", "Static file not found.", "not_found")


def text_discovery(name):
    matrix = capability_matrix()
    lines = [
        SITE_NAME,
        "Purpose: %s" % SITE_DESCRIPTION,
        "Live public routes: " + ", ".join(matrix["publicRoutes"]),
        "Protected MATM routes: " + ", ".join(matrix["protectedRoutes"]),
        "Companion documentation: %s." % COMPANION_DOCS_URL,
        "Source repository: %s." % GITHUB_REPO_URL,
        "Memory boundary: private workspace memory and database-backed knowledge wiki for protected search; local files remain startup and migration evidence.",
        "Agent coordination quickstart: /agent-coordination.",
        "Company master storage: /agent-setup creates and shows it once; displaying the path does not create the file. Browser setup uses Save to project secret folder, and agent-driven setup uses scripts/setup_memoryendpoints_company.py and verifies <project-root>/%s exists. Keep .local-secrets/ outside source control." % COMPANY_MASTER_DEFAULT_SECRET_PATH,
        "Missing company master: an authenticated credentialType=company_master agent may use scripts/recover_memoryendpoints_company_master.py with an explicitly configured source to stage and register a new sibling without printing it. Otherwise stop safely; never scan outside configured paths. Normal and disposable agents remain denied, and shared unrestricted filesystems require separate OS/vault secret isolation.",
        "Agent ability compatibility: /api/matm/agent-compatibility maps L0-L7 agents to safe routes, fallbacks, and no-op behavior.",
        "Current-message lane: /api/matm/current-message with acknowledgement at /api/matm/notifications/ack.",
        "UAIX active memory: /api/matm/uai-memory/contract separates the accountless-browser virtual-package exception from hash-only local .uai edit coordination.",
        "Readiness evidence: /api/matm/readiness-result.",
        "Authority boundary: no certification, endorsement, hidden credential validation, or automatic memory promotion.",
    ]
    if name == "robots.txt":
        return "User-agent: *\nAllow: /\nSitemap: %s/sitemap.xml\n\n# %s\n" % (SITE_URL, lines[1])
    return "\n".join(lines) + "\n"


def route_public_json(path, start_response, environ=None):
    if path == "/.well-known/memoryendpoints-connector":
        rate_rejection = _connector_rate_rejection(start_response, _connector_operation_rate_limited(
            environ or {}, "discovery", (environ or {}).get("REMOTE_ADDR") or "unknown"
        ))
        if rate_rejection:
            return rate_rejection
        return json_response(
            start_response,
            _connector_discovery(),
            headers=[("Cache-Control", "public, max-age=300"), ("Referrer-Policy", "no-referrer")],
        )
    if path == "/api/version":
        backend_health = store_backend_health()
        return json_response(
            start_response,
            {
                "ok": backend_health["storeBackendVerified"],
                "site": SITE_NAME,
                "version": __version__,
                "generatedAt": utc_now(),
                "build": build_provenance(),
                "runtime": "python-stdlib-wsgi",
                "configuredStoreBackend": backend_health["configuredStoreBackend"],
                "storeBackend": backend_health["storeBackend"],
                "storeBackendVerified": backend_health["storeBackendVerified"],
                "storeBackendStatus": backend_health["storeBackendStatus"],
                "storeBackendHealth": backend_health,
                "thirdPartyRuntimeDependencies": backend_health["thirdPartyRuntimeDependencies"],
                "packageManagedThirdPartyRuntimeDependencies": backend_health["packageManagedThirdPartyRuntimeDependencies"],
                "hostProvidedRuntimeAdapters": backend_health["hostProvidedRuntimeAdapters"],
            },
        )
    if path == "/api/matm/live-capability-matrix":
        return json_response(start_response, {"ok": True, "data": capability_matrix()})
    if path == "/api/matm/agent-compatibility":
        return json_response(start_response, {"ok": True, "data": agent_compatibility_contract()})
    if path == "/api/matm/sync/capabilities":
        return json_response(start_response, {"ok": True, "data": sync_capabilities()})
    if path == "/api/matm/connector-contract":
        return json_response(start_response, {"ok": True, "data": connector_contract()})
    if path == "/api/matm/uai-memory/contract":
        return json_response(start_response, {"ok": True, "data": virtual_uai_contract()})
    if path == "/api/matm/openapi.json":
        return json_response(start_response, openapi_spec())
    if path == "/api/matm/route-inventory":
        return json_response(start_response, {"ok": True, "data": route_inventory()})
    if path == "/api/matm/readiness-result":
        return json_response(start_response, {"ok": True, "data": readiness_result()})
    if path == "/api/matm/redacted-example-receipts":
        return json_response(
            start_response,
            {
                "ok": True,
                "site": SITE_NAME,
                "schemaVersion": "memoryendpoints.redacted_receipts.v1",
                "examples": [
                    {
                        "receiptId": "receipt-example-redacted",
                        "workspaceId": "workspace-example",
                        "rawPayloadExposed": False,
                        "valuesRedacted": True,
                        "status": "read",
                    }
                ],
            },
        )
    if path == "/ai-manifest.json":
        return json_response(start_response, manifest())
    if path == "/.well-known/ai-agent.json":
        return json_response(
            start_response,
            {
                "schemaVersion": "memoryendpoints.ai_agent.v1",
                "name": SITE_NAME,
                "capabilities": [
                    "matm_memory",
                    "database_knowledge_wiki",
                    "meeting_rooms",
                    "current_message_inbox",
                    "redacted_receipts",
                    "workspace_quota",
                    "connector_contract",
                    "virtual_uai_active_memory",
                    "local_uai_edit_claims",
                    "agent_compatibility",
                    "readiness_evidence",
                ],
                "manifest": "%s/ai-manifest.json" % SITE_URL,
                "agentCompatibility": "%s/api/matm/agent-compatibility" % SITE_URL,
                "uaiMemoryContract": "%s/api/matm/uai-memory/contract" % SITE_URL,
                "companionDocumentation": COMPANION_DOCS_URL,
                "sourceRepository": GITHUB_REPO_URL,
            },
        )
    if path == "/.well-known/mcp.json":
        return json_response(
            start_response,
            {
                "schemaVersion": "mcp.well_known.v1",
                "name": SITE_NAME,
                "resources": "%s/mcp/resources" % SITE_URL,
                "companionDocumentation": COMPANION_DOCS_URL,
                "boundary": "Public resources only; protected MATM APIs require workspace key.",
            },
        )
    if path == "/mcp/resources":
        resources = [
            {
                "uri": "memoryendpoints://matm/capability-matrix",
                "name": "MemoryEndpoints Capability Matrix",
                "mimeType": "application/json",
                "route": "/api/matm/live-capability-matrix",
            },
            {
                "uri": "memoryendpoints://matm/connector-contract",
                "name": "MemoryEndpoints Connector Contract",
                "mimeType": "application/json",
                "route": "/api/matm/connector-contract",
            },
            {
                "uri": "memoryendpoints://matm/uai-memory-contract",
                "name": "MemoryEndpoints UAIX Active-Memory Contract",
                "mimeType": "application/json",
                "route": "/api/matm/uai-memory/contract",
            },
            {
                "uri": "memoryendpoints://matm/agent-compatibility",
                "name": "MemoryEndpoints Agent Compatibility Contract",
                "mimeType": "application/json",
                "route": "/api/matm/agent-compatibility",
            },
            {
                "uri": "memoryendpoints://matm/openapi",
                "name": "MemoryEndpoints OpenAPI Golden Path",
                "mimeType": "application/json",
                "route": "/api/matm/openapi.json",
            },
            {
                "uri": "memoryendpoints://matm/knowledge-wiki",
                "name": "Database-Backed Knowledge Wiki",
                "mimeType": "application/json",
                "route": "/api/matm/knowledge-tree",
                "requiresAuth": True,
            },
            {
                "uri": "memoryendpoints://matm/redacted-example-receipts",
                "name": "Redacted Example Receipts",
                "mimeType": "application/json",
                "route": "/api/matm/redacted-example-receipts",
            },
            {
                "uri": "memoryendpoints://matm/readiness-result",
                "name": "MemoryEndpoints Readiness Result",
                "mimeType": "application/json",
                "route": "/api/matm/readiness-result",
            },
            {
                "uri": "memoryendpoints://matm/route-inventory",
                "name": "MemoryEndpoints Route Inventory",
                "mimeType": "application/json",
                "route": "/api/matm/route-inventory",
            },
            {
                "uri": "memoryendpoints://docs/companion-site",
                "name": "MultiAgentMemory.com Companion Documentation",
                "mimeType": "text/html",
                "url": COMPANION_DOCS_URL,
            },
        ]
        return json_response(start_response, {"ok": True, "resources": resources})
    return None


def route_admin_mysql_diagnostics(environ, start_response):
    if environ["REQUEST_METHOD"] != "GET":
        return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use GET for MySQL diagnostics.", "method_not_allowed")
    authorized, auth_status = _admin_diagnostics_authorized(environ)
    if auth_status == "not_configured":
        return problem(start_response, "404 Not Found", "Not found", "The requested route does not exist.", "not_found")
    if not authorized:
        return problem(start_response, "401 Unauthorized", "Diagnostics token required", "Send the diagnostics token in Authorization: Bearer.", "auth_required")
    diagnostics = mysql_config_diagnostics()
    connect_attempt = {
        "ok": False,
        "valuesRedacted": True,
    }
    try:
        MySQLStore().healthcheck()
        connect_attempt["ok"] = True
        connect_attempt["errorCode"] = None
    except Exception as exc:
        args = getattr(exc, "args", ()) or ()
        mysql_error_number = args[0] if args and isinstance(args[0], int) else None
        connect_attempt.update(
            {
                "errorCode": backend_error_code("mysql", exc),
                "errorType": exc.__class__.__name__,
                "mysqlErrorNumber": mysql_error_number,
                "sqlState": getattr(exc, "sqlstate", None),
                "messageFingerprint": _diagnostic_fingerprint(str(exc)),
            }
        )
    payload = {
        "ok": connect_attempt["ok"],
        "site": SITE_NAME,
        "generatedAt": utc_now(),
        "build": build_provenance(),
        "schemaVersion": "memoryendpoints.admin_mysql_diagnostics.v1",
        "authStatus": auth_status,
        "configuredStoreBackend": configured_store_backend(),
        "configDiagnostics": diagnostics,
        "stageDiagnostics": mysql_connection_stage_diagnostics(),
        "connectAttempt": connect_attempt,
        "valuesRedacted": True,
    }
    return json_response(start_response, payload)


def route_setup(environ, start_response, path="/api/matm/agent-setup/free-account"):
    method = environ["REQUEST_METHOD"]
    if method == "GET":
        return json_response(
            start_response,
            {
                "ok": True,
                "site": SITE_NAME,
                "route": "/api/matm/agent-setup/free-account",
                "method": "POST",
                "plan": "free_agent",
                "billingStatus": "free",
                "storageLimitBytes": PUBLIC_STORAGE_BYTES,
                "storageUnlimited": False,
                "npcMemoryUnlimited": False,
                "hierarchy": {
                    "account": "identity or owner boundary",
                    "company": "organization boundary; accounts and companies are many-to-many through memberships",
                    "workspace": "workspace belongs to company",
                    "project": "project belongs to workspace",
                },
                "credentialHandling": "The company master token is returned once; keep it in protected secret storage and never place it in a URL, log, public file, or ordinary chat.",
                "companyMasterStorageGuidance": company_master_storage_guidance(),
                "credentialType": "company_master",
                "credentialSystemAvailable": credential_system_available(),
                "idempotencySupported": False,
                "checkoutRequired": False,
                "setupCredentialRequired": False,
            },
        )
    if method != "POST":
        return problem(
            start_response,
            "405 Method Not Allowed",
            "Method not allowed",
            "Use GET to inspect setup or POST to create a free workspace.",
            "method_not_allowed",
            headers=[("Allow", "GET, POST")],
        )
    body = _read_body(environ)
    if body is None:
        return problem(start_response, "400 Bad Request", "Invalid JSON", "Request body must be JSON.", "invalid_json")
    if not isinstance(body, dict):
        return problem(start_response, "422 Unprocessable Entity", "Setup object required", "Free workspace setup requires a JSON object.", "setup_object_required")
    label_fields = (
        ("companyLabel", ("companyLabel", "company_label")),
        ("label", ("label", "workspaceLabel", "workspace_label")),
        ("projectLabel", ("projectLabel", "project_label")),
    )
    setup_labels = {}
    for canonical_name, aliases in label_fields:
        provided_alias = next((alias for alias in aliases if alias in body), None)
        if provided_alias is None:
            setup_labels[canonical_name] = None
            continue
        value = body.get(provided_alias)
        if not isinstance(value, str):
            return problem(start_response, "422 Unprocessable Entity", "Invalid setup label", "%s must be a string when provided." % canonical_name, "setup_label_invalid")
        value = value.strip()
        if not value:
            return problem(start_response, "422 Unprocessable Entity", "Invalid setup label", "%s must not be empty when provided." % canonical_name, "setup_label_invalid")
        if len(value) > 120:
            return problem(start_response, "422 Unprocessable Entity", "Setup label too long", "%s must be at most 120 characters." % canonical_name, "setup_label_too_long")
        setup_labels[canonical_name] = value
    try:
        setup_store = _store()
        workspace_id, key_id, token, account_id, company_id, project_id, human_recovery_secret = setup_store.create_free_account(
            setup_labels["label"],
            setup_labels["companyLabel"],
            setup_labels["projectLabel"],
        )
    except RuntimeError as exc:
        if "credential pepper" in str(exc).lower():
            return _access_problem(start_response, "credential_system_not_configured")
        backend = configured_store_backend()
        if backend in ("mysql", "mariadb"):
            code = backend_error_code(backend, exc)
            return problem(
                start_response,
                "503 Service Unavailable",
                "Store backend unavailable",
                "The selected MySQL backend could not complete setup; setup did not fall back to local storage.",
                code,
            )
        return _access_problem(start_response, "credential_system_not_configured")
    human_credential_parts = str(human_recovery_secret or "").split(".", 2)
    human_credential_id = human_credential_parts[1] if len(human_credential_parts) == 3 else None
    return one_time_secret_response(
        start_response,
        {
            "ok": True,
            "accountId": account_id,
            "companyId": company_id,
            "workspaceId": workspace_id,
            "projectId": project_id,
            "credentialId": key_id,
            "credentialType": "company_master",
            "companyMasterTokenSecret": token,
            "companyMasterStorageGuidance": company_master_storage_guidance(),
            "humanOwnerCredentialId": human_credential_id,
            "humanOwnerRecoverySecret": human_recovery_secret,
            "hierarchy": {
                "accountId": account_id,
                "companyId": company_id,
                "workspaceId": workspace_id,
                "projectId": project_id,
                "accountToCompanyMembership": True,
                "companyToWorkspace": True,
                "workspaceToProject": True,
            },
            "storeCredentialSafely": True,
            "plan": "free_agent",
            "billingStatus": "free",
            "storageLimitBytes": PUBLIC_STORAGE_BYTES,
            "storageUnlimited": False,
            "npcMemoryUnlimited": False,
            "checkoutRequired": False,
            "idempotencySupported": False,
            "operatorSummary": _free_account_setup_operator_summary(account_id, company_id, workspace_id, project_id),
        },
        "201 Created",
    )


def _idempotency_replay_or_conflict(
    store,
    environ,
    start_response,
    workspace_id,
    key,
    operation,
    body,
    headers=None,
):
    replay = store.claim_idempotency(workspace_id, key, operation, body)
    if not replay:
        return None
    if replay.pop("_idempotencyClaimed", False):
        environ.setdefault("memoryendpoints.idempotencyClaims", []).append(
            {
                "store": store,
                "workspaceId": workspace_id,
                "key": key,
                "operation": operation,
                "claimId": replay.get("_claimId"),
                "mutationStarted": False,
                "finalized": False,
            }
        )
        return None
    if replay.get("status") == "idempotency_conflict":
        return json_response(start_response, replay, "409 Conflict", headers=headers)
    replay_status = replay.pop("_httpStatus", "200 OK")
    return json_response(start_response, replay, replay_status, headers=headers)


class _IdempotencyFinalizationError(RuntimeError):
    pass


def _request_idempotency_claim(
    environ, store, workspace_id, key, operation
):
    for claim in reversed(
        environ.get("memoryendpoints.idempotencyClaims", [])
    ):
        if (
            claim.get("store") is store
            and claim.get("workspaceId") == workspace_id
            and claim.get("key") == key
            and claim.get("operation") == operation
        ):
            return claim
    return None


def _mark_idempotent_mutation_started(
    environ, store, workspace_id, key, operation
):
    if not key:
        return
    claim = _request_idempotency_claim(
        environ, store, workspace_id, key, operation
    )
    if claim is None:
        raise _IdempotencyFinalizationError(
            "Mutation started without an owned idempotency claim."
        )
    claim["mutationStarted"] = True


def _record_request_idempotency(
    store,
    environ,
    workspace_id,
    key,
    operation,
    body,
    response_payload,
    http_status="200 OK",
):
    if not key:
        return True
    claim = _request_idempotency_claim(
        environ, store, workspace_id, key, operation
    )
    if claim is None:
        raise _IdempotencyFinalizationError(
            "Idempotency finalization has no owned claim."
        )
    try:
        finalized = store.record_idempotency(
            workspace_id,
            key,
            operation,
            body,
            response_payload,
            http_status,
            claim_id=claim.get("claimId"),
        )
    except Exception as exc:
        raise _IdempotencyFinalizationError(
            "Idempotency finalization failed after mutation."
        ) from exc
    if not finalized:
        raise _IdempotencyFinalizationError(
            "Idempotency claim ownership changed before finalization."
        )
    claim["finalized"] = True
    return True


def _release_request_idempotency_claims(environ):
    claims = environ.pop("memoryendpoints.idempotencyClaims", [])
    for claim in reversed(claims):
        if (
            claim.get("finalized")
            or claim.get("mutationStarted")
            or claim.get("outcomeUncertain")
        ):
            continue
        try:
            claim["store"].release_idempotency_claim(
                claim["workspaceId"],
                claim["key"],
                claim["operation"],
                claim["claimId"],
            )
        except Exception:
            # Cleanup failure leaves the reservation durable and fail-closed.
            # It requires operator reconciliation; never discard it on a timer
            # or replace the original safe response with cleanup diagnostics.
            continue


def _preserve_uncertain_request_idempotency_claims(environ):
    """Keep every owned, unfinished claim durable after an exception."""
    preserved = False
    for claim in environ.get("memoryendpoints.idempotencyClaims", []):
        if claim.get("finalized"):
            continue
        claim["outcomeUncertain"] = True
        preserved = True
    return preserved


def _idempotency_uncertain_response(start_response):
    return json_response(
        start_response,
        {
            "ok": False,
            "safeNoOp": False,
            "outcomeUncertain": True,
            "idempotencyKeyReserved": True,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
            "error": {
                "code": "idempotency_finalization_uncertain",
                "title": "Mutation outcome is still being finalized",
                "detail": "The mutation may have committed, so this idempotency key remains reserved. Retry the exact request later; the server will not repeat the effect while finalization is uncertain.",
                "safeNoOp": False,
                "outcomeUncertain": True,
                "valuesRedacted": True,
            },
        },
        "503 Service Unavailable",
        headers=[("Retry-After", "5")],
    )


def _audit_read(store, workspace_id, auth, action, route, details=None):
    audit_details = {"route": route, "method": "GET"}
    audit_details.update(details or {})
    store.record_audit(workspace_id, action, auth.get("keyId") or "workspace-key", route, audit_details)


def _uai_claim_readback_visible(store, workspace_id, claim, head):
    claims = store.uai_edit_claims(
        workspace_id,
        claim.get("projectId"),
        claim.get("agentId"),
        claim.get("logicalPath"),
    )
    heads = store.uai_collaboration_heads(
        workspace_id,
        head.get("projectId"),
        head.get("logicalPath"),
    )
    claim_visible = any(
        item.get("claimId") == claim.get("claimId")
        and item.get("status") == claim.get("status")
        for item in claims
    )
    head_visible = any(
        item.get("headId") == head.get("headId")
        and item.get("revision") == head.get("revision")
        and item.get("observedContentHash") == head.get("observedContentHash")
        and item.get("activeClaimId") == head.get("activeClaimId")
        for item in heads
    )
    return claim_visible and head_visible


def _uai_error_response(start_response, code, details=None):
    details = details or {}
    status = "422 Unprocessable Entity"
    if code in ("uai_package_not_found", "uai_edit_claim_not_found", "project_not_found", "workspace_not_found"):
        status = "404 Not Found"
    elif code in (
        "uai_package_agent_mismatch",
        "uai_revision_conflict",
        "uai_edit_claim_conflict",
        "uai_base_hash_mismatch",
        "uai_edit_claim_agent_mismatch",
        "uai_edit_claim_not_active",
    ):
        status = "409 Conflict"
    elif code == "quota_exceeded":
        status = "413 Payload Too Large"
    messages = {
        "registered_agent_required": "Register the stable agent in this workspace before creating memory packages or edit claims.",
        "unsupported_uai_client_class": "The full virtual package is only available to the accountless_browser_ai client class.",
        "uai_exception_not_applicable": "Clients with durable local filesystem access must keep local .uai active memory and use the collaboration overlay instead.",
        "uai_package_not_found": "No matching virtual UAIX package exists in the authenticated workspace.",
        "uai_package_agent_mismatch": "The package belongs to a different registered agent in this workspace.",
        "unsupported_uai_logical_path": "The requested logical path is not part of the supported virtual UAIX startup profile.",
        "unsupported_local_uai_path": "The requested local .uai path is invalid or locally forbidden.",
        "uai_content_required": "A virtual UAIX record requires non-empty content.",
        "uai_content_too_large": "The virtual UAIX record exceeds the bounded content size.",
        "uai_content_must_be_date_free": "Active UAIX record content and titles must not contain calendar dates or timestamps.",
        "uai_content_structure_invalid": "The virtual UAIX record is missing required active-memory fields.",
        "uai_content_role_invalid": "The virtual UAIX record is missing role-specific fields, omits required startup paths, or does not match its registered agent binding.",
        "uai_content_rejected_by_memory_firewall": "The virtual UAIX record was rejected before persistence because it is not safe active memory.",
        "expected_revision_required": "Updating an existing virtual UAIX record requires expectedRevision.",
        "expected_revision_invalid": "expectedRevision must be a non-negative integer.",
        "uai_revision_conflict": "The virtual UAIX record changed after the caller read it; reload before retrying.",
        "uai_base_content_hash_invalid": "baseContentHash must be a complete SHA-256 digest.",
        "uai_completion_content_hash_invalid": "newContentHash must be a complete SHA-256 digest.",
        "uai_edit_claim_conflict": "Another active claim owns this local .uai path; do not edit until it is completed, released, or expired.",
        "uai_base_hash_mismatch": "The caller's local file hash does not match the latest observed project head; reconcile before editing.",
        "uai_edit_claim_not_found": "No matching local .uai edit claim exists in the authenticated workspace.",
        "uai_edit_claim_agent_mismatch": "Only the registered agent that owns the claim can change it.",
        "uai_edit_claim_not_active": "The claim is no longer active and cannot be changed.",
        "uai_collaboration_summary_rejected_by_memory_firewall": "The public-safe coordination summary was rejected before persistence.",
        "intent_summary_required": "An edit claim requires a public-safe intentSummary.",
        "completion_summary_required": "Completing a claim requires a public-safe completionSummary.",
        "release_summary_required": "Releasing a claim requires a public-safe releaseSummary.",
        "project_not_found": "A real project in the authenticated workspace is required for local .uai collaboration.",
        "quota_exceeded": "The workspace does not have enough remaining storage for this operation.",
    }
    detail = messages.get(code, "The virtual UAIX memory operation was safely rejected.")
    return json_response(
        start_response,
        {
            "ok": False,
            "safeNoOp": True,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
            "error": {
                "code": code,
                "title": "Virtual UAIX memory operation rejected",
                "detail": detail,
                "safeNoOp": True,
                "valuesRedacted": True,
                "details": details,
            },
        },
        status,
    )


_ACCESS_REQUEST_DECISION_ROUTE = re.compile(r"^/api/matm/access/agent-name-requests/([^/]+)/decision$")
_ACCESS_INVITE_REVOKE_ROUTE = re.compile(r"^/api/matm/access/invites/([^/]+)/revoke$")
_ACCESS_TOKEN_REVOKE_ROUTE = re.compile(r"^/api/matm/access/agent-tokens/([^/]+)/revoke$")
_ACCESS_IDEMPOTENCY_REQUIRED_POST_ROUTE_TEMPLATES = frozenset(
    {
        "/api/matm/access/agent-name-requests",
        "/api/matm/access/agent-name-requests/{requestId}/decision",
        "/api/matm/access/invites/{inviteId}/revoke",
        "/api/matm/access/agent-tokens/{credentialId}/revoke",
    }
)
_ACCESS_ONE_TIME_SECRET_POST_ROUTE_TEMPLATES = frozenset(
    {
        "/api/matm/access/invites",
        "/api/matm/access/invites/redeem",
    }
)
_HUMAN_COMPANY_ROUTE = re.compile(
    r"^/api/matm/human/companies/([^/]+)/(export-plan|exports|closure-intents|close|delete|restore|permanent-purge|history|history/clear|top-level-agent-master-credential-setting)$"
)
_HUMAN_AGENT_TOKENS_ROUTE = re.compile(
    r"^/api/matm/human/companies/([^/]+)/agent-tokens$"
)
_HUMAN_AGENT_TOKEN_REPLACEMENTS_ROUTE = re.compile(
    r"^/api/matm/human/companies/([^/]+)/agent-tokens/([^/]+)/replacements$"
)
_HUMAN_AGENT_TOKEN_REPLACEMENT_ROUTE = re.compile(
    r"^/api/matm/human/companies/([^/]+)/agent-tokens/([^/]+)/replacements/([^/]+)(?:/(confirm|cancel))?$"
)


def _access_result_error(start_response, result, redemption=False):
    code = (result or {}).get("status") or "access_operation_failed"
    aliases = {
        "access_request_not_approved": "agent_name_request_not_approved",
        "invite_already_issued": "invite_already_active",
    }
    code = aliases.get(code, code)
    if redemption and code == "invite_unavailable":
        code = "invalid_invite"
    return _access_problem(start_response, code)


def _access_auth(store, environ, start_response):
    token = _token(environ)
    if not token:
        return None, _access_problem(start_response, "invalid_token")
    try:
        auth = store.authenticate(token)
    except RuntimeError:
        return None, _access_problem(start_response, "credential_system_not_configured")
    if not auth:
        return None, _access_problem(start_response, "invalid_token")
    return auth, None


def _access_body(environ, start_response):
    body = _read_body(environ)
    if body is None:
        return None, problem(start_response, "400 Bad Request", "Invalid JSON", "Request body must be JSON.", "invalid_json")
    if not isinstance(body, dict):
        return None, problem(start_response, "422 Unprocessable Entity", "Object required", "Access operations require a JSON object.", "access_object_required")
    return body, None


def _access_scope_workspace_id(store, master_token, scope_type, scope_id):
    """Resolve a stable, company-owned idempotency anchor for one access scope."""
    catalog = store.company_scope_catalog(master_token)
    if not catalog.get("ok"):
        return ""
    scope_type = str(scope_type or "").strip().lower()
    scope_id = str(scope_id or "").strip()
    workspaces = list(catalog.get("workspaces") or ())
    if scope_type == "workspace":
        return next(
            (
                item.get("workspaceId")
                for item in workspaces
                if item.get("workspaceId") == scope_id
            ),
            "",
        )
    if scope_type == "project":
        return next(
            (
                item.get("workspaceId")
                for item in catalog.get("projects") or ()
                if item.get("projectId") == scope_id
            ),
            "",
        )
    if scope_type in ("game", "session", "goal", "task"):
        return next(
            (
                item.get("workspaceId")
                for item in catalog.get("scopeNodes") or ()
                if item.get("scopeType") == scope_type
                and item.get("scopeId") == scope_id
            ),
            "",
        )
    if scope_type == "company" and scope_id == (catalog.get("company") or {}).get(
        "companyId"
    ):
        # Company-scoped access still needs an existing workspace row as the
        # generic receipt anchor. IDs are stable even when labels are renamed.
        return min(
            (item.get("workspaceId") for item in workspaces if item.get("workspaceId")),
            default="",
        )
    return ""


def _access_inventory_item(result, public_id, *id_fields):
    if not (result or {}).get("ok"):
        return None
    return next(
        (
            item
            for item in result.get("items") or ()
            if any(item.get(field) == public_id for field in id_fields)
        ),
        None,
    )


def _access_idempotency_or_problem(
    store,
    environ,
    start_response,
    auth,
    master_token,
    scope_type,
    scope_id,
    operation,
    canonical_body,
):
    client_key, rejected = _validated_idempotency_key_or_problem(
        environ, start_response
    )
    if rejected:
        return None, None, rejected
    workspace_id = _access_scope_workspace_id(
        store, master_token, scope_type, scope_id
    )
    if not workspace_id:
        return None, None, _access_problem(start_response, "workspace_not_found")
    key = _principal_scoped_idempotency_key(auth, client_key)
    replay = _idempotency_replay_or_conflict(
        store,
        environ,
        start_response,
        workspace_id,
        key,
        operation,
        canonical_body,
        headers=list(_CONNECTOR_JSON_HEADERS),
    )
    return (workspace_id, key, replay)


def _finalize_access_idempotency(
    store,
    environ,
    workspace_id,
    key,
    operation,
    canonical_body,
    result,
    http_status,
):
    result = dict(
        result,
        idempotentReplay=False,
        idempotencyKeyExposed=False,
        rawCredentialExposed=False,
        rawPayloadExposed=False,
    )
    # The storage mutation has returned successfully. From here onward a crash
    # must leave the reservation fail-closed rather than permitting a duplicate.
    _mark_idempotent_mutation_started(
        environ, store, workspace_id, key, operation
    )
    _record_request_idempotency(
        store,
        environ,
        workspace_id,
        key,
        operation,
        canonical_body,
        result,
        http_status,
    )
    return result


def _public_invite_with_grant(invite):
    public = dict(invite or {})
    public["grant"] = {
        "scopeType": public.get("scopeType"),
        "scopeId": public.get("scopeId"),
        "accessRule": "scope_and_descendants",
        "immutable": True,
    }
    return public


def route_connector_pairing(environ, start_response, path):
    """Crash-safe URL pairing for one exact connector agent."""
    method = environ["REQUEST_METHOD"]
    store = _store()
    if environ.get("QUERY_STRING"):
        return _connector_problem(start_response, "invalid_request")

    if path == "/api/matm/connector-pairings/requests":
        if method != "POST":
            return _connector_problem(start_response, "invalid_request", headers=[("Allow", "POST")])
        body, rejected = _connector_exact_body_or_problem(
            environ,
            start_response,
            (
                "schemaVersion",
                "clientId",
                "redirectUri",
                "state",
                "codeChallenge",
                "codeChallengeMethod",
                "requestedAgentId",
                "requestedScopes",
            ),
        )
        if rejected:
            return rejected
        idempotency_key, rejected = _connector_idempotency_or_problem(environ, start_response)
        if rejected:
            return rejected
        if body.get("schemaVersion") != CONNECTOR_PAIRING_SCHEMA:
            return _connector_problem(start_response, "schema_version_unsupported")
        try:
            validate_client_id(body.get("clientId"))
        except PairingPolicyError:
            return _connector_problem(start_response, "connector_client_unsupported")
        try:
            redirect_uri = validate_redirect_uri(body.get("redirectUri"))
        except PairingPolicyError:
            return _connector_problem(start_response, "redirect_uri_not_allowed")
        state = body.get("state")
        if not isinstance(state, str) or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", state):
            return _connector_problem(start_response, "state_invalid")
        if body.get("codeChallengeMethod") != CONNECTOR_PKCE_METHOD:
            return _connector_problem(start_response, "pkce_method_unsupported")
        code_challenge = body.get("codeChallenge")
        if not isinstance(code_challenge, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", code_challenge):
            return _connector_problem(start_response, "pkce_challenge_invalid")
        try:
            requested_agent_id = normalize_connector_agent_name(body.get("requestedAgentId"))
        except PairingPolicyError:
            return _connector_problem(start_response, "connector_agent_identity_invalid")
        try:
            requested_scopes = validate_requested_scopes(body.get("requestedScopes"))
        except PairingPolicyError:
            return _connector_problem(start_response, "connector_scopes_invalid")
        scope_digest = connector_scope_digest(requested_scopes)
        canonical = dict(body)
        canonical.update(
            {
                "clientId": CONNECTOR_CLIENT_ID,
                "redirectUri": redirect_uri,
                "state": state,
                "codeChallenge": code_challenge,
                "codeChallengeMethod": CONNECTOR_PKCE_METHOD,
                "requestedAgentId": requested_agent_id,
                "requestedScopes": list(requested_scopes),
                "scopeDigest": scope_digest,
            }
        )
        digest = _connector_request_digest(method, path, canonical)
        rate_rejection = _connector_rate_rejection(
            start_response,
            _connector_operation_rate_limited(environ, "pairingRequest"),
        )
        if rate_rejection:
            return rate_rejection
        result = store.create_connector_pairing_request(canonical, idempotency_key, digest)
        if not result.get("ok"):
            return _connector_result_error(start_response, result)
        pairing_request_proof = result.get("pairingRequestProof")
        stored_request = result.get("pairingRequest") or {}
        public_request_ref = stored_request.get("publicRequestRef") or result.get("publicRequestRef")
        if not pairing_request_proof or not public_request_ref:
            return _connector_problem(start_response, "pairing_request_unavailable")
        try:
            stored_scopes, stored_scope_digest = _connector_scope_binding(stored_request)
        except PairingPolicyError:
            return _connector_problem(start_response, "connector_service_unavailable")
        if stored_scopes != list(requested_scopes) or not hmac.compare_digest(
            stored_scope_digest, scope_digest
        ):
            return _connector_problem(start_response, "connector_service_unavailable")
        request = _connector_public_pairing_request(
            dict(
                stored_request,
                requestedScopes=list(requested_scopes),
                scopeDigest=scope_digest,
            ),
            expires_in_seconds=PAIRING_REQUEST_TTL_SECONDS,
        )
        return _connector_one_time_secret(
            start_response,
            {
                "ok": True,
                "schemaVersion": CONNECTOR_PAIRING_SCHEMA,
                "pairingRequest": request,
                "pairingRequestProof": pairing_request_proof,
                "authorizationUrl": build_authorization_url(public_request_ref),
                "proofDelivery": {
                    "bodyOnly": True,
                    "showOnce": True,
                    "rawProofPersisted": False,
                    "exactRetryRecoverable": True,
                },
                "requestedScopes": list(requested_scopes),
                "scopeDigest": scope_digest,
                "receipt": _connector_receipt(
                    "authorize",
                    public_request_ref,
                    request.get("status"),
                    result.get("idempotentReplay"),
                    scope_digest=scope_digest,
                ),
                "idempotentReplay": bool(result.get("idempotentReplay")),
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
            "201 Created",
        )

    company_selection_match = _CONNECTOR_HUMAN_COMPANY_SELECTION_ROUTE.fullmatch(path)
    if company_selection_match:
        if method != "POST":
            return _connector_problem(start_response, "invalid_request", headers=[("Allow", "POST")])
        _session, session_secret, rejected = _human_session_auth(
            store, environ, start_response, mutation=True
        )
        if rejected:
            return rejected
        body, rejected = _connector_exact_body_or_problem(
            environ, start_response, ("schemaVersion", "companyRef")
        )
        if rejected:
            return rejected
        if body.get("schemaVersion") != CONNECTOR_PAIRING_SCHEMA:
            return _connector_problem(start_response, "schema_version_unsupported")
        result = store.select_human_connector_company_membership(
            session_secret,
            company_selection_match.group(1),
            body.get("companyRef"),
        )
        if not result.get("ok"):
            return _connector_result_error(start_response, result)
        if not result.get("sessionSecret") or not result.get("csrfToken"):
            return _connector_problem(start_response, "connector_service_unavailable")
        return _connector_one_time_secret(
            start_response,
            {
                "ok": True,
                "schemaVersion": CONNECTOR_PAIRING_SCHEMA,
                "status": "company_selected",
                "sessionRotated": True,
                "csrfToken": result.get("csrfToken"),
                "expiresAt": result.get("expiresAt"),
                "tenantIdentifiersExposed": False,
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
            "200 OK",
            headers=[
                ("Set-Cookie", _human_session_cookie(result.get("sessionSecret"), 30 * 60)),
            ],
        )

    approval_match = _CONNECTOR_HUMAN_APPROVAL_ROUTE.fullmatch(path)
    if approval_match:
        if method != "POST":
            return _connector_problem(start_response, "invalid_request", headers=[("Allow", "POST")])
        session, session_secret, rejected = _human_session_auth(
            store, environ, start_response, mutation=True
        )
        if rejected:
            return rejected
        body, rejected = _connector_exact_body_or_problem(
            environ,
            start_response,
            (
                "schemaVersion",
                "canonicalAgentApproved",
                "approvedScopes",
                "workspaceSelection",
            ),
        )
        if rejected:
            return rejected
        if body.get("schemaVersion") != CONNECTOR_PAIRING_SCHEMA:
            return _connector_problem(start_response, "schema_version_unsupported")
        if body.get("canonicalAgentApproved") is not True:
            return _connector_problem(start_response, "invalid_request")
        try:
            approved_scopes = validate_requested_scopes(body.get("approvedScopes"))
        except PairingPolicyError:
            return _connector_problem(start_response, "invalid_request")
        scope_digest = connector_scope_digest(approved_scopes)
        selection = body.get("workspaceSelection")
        if not isinstance(selection, dict):
            return _connector_problem(start_response, "invalid_request")
        mode = selection.get("mode")
        required_selection = (
            {"mode", "workspaceRef"} if mode == "existing"
            else {"mode", "workspaceLabel", "projectLabel"} if mode == "new"
            else set()
        )
        if not required_selection:
            return _connector_problem(start_response, "invalid_request")
        if set(selection) != required_selection:
            return _connector_problem(start_response, "invalid_request")
        idempotency_key, rejected = _connector_idempotency_or_problem(environ, start_response)
        if rejected:
            return rejected
        if not session.get("companyId"):
            return _human_problem(start_response, "selected_company_required")
        if not _human_recently_reauthenticated(session):
            return _human_problem(start_response, "recent_reauthentication_required")
        rate_rejection = _connector_rate_rejection(start_response, _connector_operation_rate_limited(
            environ, "authorize", session.get("humanAccountId") or session_secret
        ))
        if rate_rejection:
            return rate_rejection
        digest = _connector_request_digest(method, path, body)
        result = store.approve_connector_pairing_request(
            session_secret,
            approval_match.group(1),
            body.get("workspaceSelection"),
            list(approved_scopes),
            idempotency_key,
            digest,
        )
        if not result.get("ok"):
            return _connector_result_error(start_response, result)
        approval = result.get("approval") or {}
        try:
            stored_scopes, stored_scope_digest = _connector_scope_binding(
                {
                    "approvedScopes": result.get("approvedScopes")
                    or approval.get("approvedScopes"),
                    "scopeDigest": result.get("scopeDigest")
                    or approval.get("scopeDigest"),
                }
            )
        except PairingPolicyError:
            return _connector_problem(start_response, "connector_service_unavailable")
        if stored_scopes != list(approved_scopes) or not hmac.compare_digest(
            stored_scope_digest, scope_digest
        ):
            return _connector_problem(start_response, "connector_service_unavailable")
        try:
            wake_up_url = build_wake_up_url(result.get("wakeUpUrl"))
        except PairingPolicyError:
            return _connector_problem(start_response, "connector_service_unavailable")
        return _connector_json(
            start_response,
            {
                "ok": True,
                "schemaVersion": CONNECTOR_PAIRING_SCHEMA,
                "status": "approved_awaiting_connector_claim",
                "approval": {
                    "status": "approved_awaiting_connector_claim",
                    "clientDisplayName": "LocalEndpoint Connect",
                    "agentDisplayName": "LocalEndpoint Agent",
                    "approvedScopes": list(approved_scopes),
                    "scopeDigest": scope_digest,
                    "claimExpiresAt": approval.get("claimExpiresAt")
                    or result.get("claimExpiresAt"),
                    "valuesRedacted": True,
                    "rawCredentialExposed": False,
                    "rawPayloadExposed": False,
                },
                "wakeUpUrl": wake_up_url,
                "wakeUp": {
                    "userActivationRequired": True,
                    "authorizing": False,
                    "parametersAdded": False,
                    "automaticNavigation": False,
                },
                "claimExpiresInSeconds": AUTHORIZATION_CODE_TTL_SECONDS,
                "approvedScopes": list(approved_scopes),
                "scopeDigest": scope_digest,
                "receipt": _connector_receipt(
                    "authorize",
                    approval_match.group(1),
                    "approved",
                    result.get("idempotentReplay"),
                    scope_digest=scope_digest,
                ),
                "idempotentReplay": bool(result.get("idempotentReplay")),
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )

    human_cancel_match = _CONNECTOR_HUMAN_CANCEL_ROUTE.fullmatch(path)
    if human_cancel_match:
        if method != "POST":
            return _connector_problem(start_response, "invalid_request", headers=[("Allow", "POST")])
        session, session_secret, rejected = _human_session_auth(
            store, environ, start_response, mutation=True
        )
        if rejected:
            return rejected
        body, rejected = _connector_exact_body_or_problem(
            environ, start_response, ("schemaVersion", "reason")
        )
        if rejected:
            return rejected
        if body.get("schemaVersion") != CONNECTOR_PAIRING_SCHEMA:
            return _connector_problem(start_response, "schema_version_unsupported")
        reason = _connector_valid_reason(body)
        if reason is None:
            return _connector_problem(start_response, "invalid_request")
        idempotency_key, rejected = _connector_idempotency_or_problem(environ, start_response)
        if rejected:
            return rejected
        if not session.get("companyId"):
            return _human_problem(start_response, "selected_company_required")
        if not _human_recently_reauthenticated(session):
            return _human_problem(start_response, "recent_reauthentication_required")
        rate_rejection = _connector_rate_rejection(start_response, _connector_operation_rate_limited(
            environ, "authorize", session.get("humanAccountId") or session_secret
        ))
        if rate_rejection:
            return rate_rejection
        digest = _connector_request_digest(method, path, body)
        result = store.cancel_connector_pairing_request(
            session_secret,
            human_cancel_match.group(1),
            reason,
            idempotency_key,
            digest,
        )
        if not result.get("ok"):
            return _connector_result_error(start_response, result)
        stored_request = result.get("pairingRequest") or {}
        try:
            requested_scopes, scope_digest = _connector_scope_binding(stored_request)
        except PairingPolicyError:
            return _connector_problem(start_response, "connector_service_unavailable")
        request = _connector_public_pairing_request(stored_request)
        receipt = _connector_receipt(
            "cancel",
            human_cancel_match.group(1),
            request.get("status"),
            result.get("idempotentReplay"),
            scope_digest=scope_digest,
        )
        return _connector_json(
            start_response,
            {
                "ok": True,
                "schemaVersion": CONNECTOR_PAIRING_SCHEMA,
                "pairingRequest": request,
                "requestedScopes": requested_scopes,
                "scopeDigest": scope_digest,
                "receipt": receipt,
                "safeNoOpOnRetry": True,
                "idempotentReplay": bool(result.get("idempotentReplay")),
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )

    if path == "/api/matm/connector-pairings/authorization-code-claims":
        if method != "POST":
            return _connector_problem(
                start_response, "invalid_request", headers=[("Allow", "POST")]
            )
        body, rejected = _connector_exact_body_or_problem(
            environ,
            start_response,
            (
                "schemaVersion",
                "clientId",
                "redirectUri",
                "pairingRequestProof",
                "state",
            ),
        )
        if rejected:
            return rejected
        idempotency_key, rejected = _connector_idempotency_or_problem(
            environ, start_response
        )
        if rejected:
            return rejected
        if body.get("schemaVersion") != CONNECTOR_PAIRING_SCHEMA:
            return _connector_problem(start_response, "schema_version_unsupported")
        try:
            client_id = validate_client_id(body.get("clientId"))
        except PairingPolicyError:
            return _connector_problem(start_response, "authorization_claim_invalid")
        try:
            redirect_uri = validate_redirect_uri(body.get("redirectUri"))
        except PairingPolicyError:
            return _connector_problem(start_response, "authorization_claim_invalid")
        state = body.get("state")
        if not isinstance(state, str) or not re.fullmatch(
            r"[A-Za-z0-9._~-]{43,128}", state
        ):
            return _connector_problem(start_response, "authorization_claim_invalid")
        rate_rejection = _connector_rate_rejection(
            start_response,
            _connector_operation_rate_limited(
                environ, "authorizationCodeClaim"
            ),
        )
        if rate_rejection:
            return rate_rejection
        digest = _connector_request_digest(method, path, body)
        result = store.claim_connector_authorization_code(
            body.get("pairingRequestProof"),
            state,
            client_id,
            redirect_uri,
            idempotency_key,
            digest,
        )
        claim_status = str(result.get("status") or "")
        if result.get("pending") or claim_status in (
            "pending_human_approval",
            "authorization_pending",
            "awaiting_human_approval",
            "pairing_request_pending",
        ):
            retry_after = max(1, min(int(result.get("retryAfterSeconds") or 3), 30))
            return _connector_json(
                start_response,
                {
                    "ok": True,
                    "schemaVersion": CONNECTOR_PAIRING_SCHEMA,
                    "status": "pending_human_approval",
                    "stateVerified": True,
                    "requestedScopes": list(CONNECTOR_V1_REQUESTED_SCOPES),
                    "scopeDigest": connector_scope_digest(CONNECTOR_V1_REQUESTED_SCOPES),
                    "retryAfterSeconds": retry_after,
                    "idempotencyBound": False,
                    "idempotencyKeyReserved": False,
                    "receipt": _connector_receipt(
                        "authorization_code_claim",
                        result.get("publicRequestRef") or "connector-authorization-claim",
                        "pending_human_approval",
                        False,
                        scope_digest=connector_scope_digest(CONNECTOR_V1_REQUESTED_SCOPES),
                    ),
                    "valuesRedacted": True,
                    "rawCredentialExposed": False,
                    "rawPayloadExposed": False,
                },
                "202 Accepted",
                headers=[("Retry-After", str(retry_after))],
            )
        if not result.get("ok"):
            return _connector_result_error(start_response, result)
        try:
            approved_scopes, scope_digest = _connector_scope_binding(result)
        except PairingPolicyError:
            return _connector_problem(start_response, "connector_service_unavailable")
        authorization_code = result.get("authorizationCode")
        if not authorization_code:
            return _connector_problem(start_response, "connector_service_unavailable")
        return _connector_one_time_secret(
            start_response,
            {
                "ok": True,
                "schemaVersion": CONNECTOR_PAIRING_SCHEMA,
                "status": "authorization_code_issued",
                "authorizationCode": authorization_code,
                "expiresInSeconds": AUTHORIZATION_CODE_TTL_SECONDS,
                "stateVerified": True,
                "approvedScopes": approved_scopes,
                "scopeDigest": scope_digest,
                "receipt": _connector_receipt(
                    "authorization_code_claim",
                    result.get("publicRequestRef") or "connector-authorization-claim",
                    "authorization_code_issued",
                    result.get("idempotentReplay"),
                    scope_digest=scope_digest,
                ),
                "idempotentReplay": bool(result.get("idempotentReplay")),
                "valuesRedacted": True,
                "rawPayloadExposed": False,
            },
            "200 OK",
        )

    if path == "/api/matm/connector-pairings/token":
        if method != "POST":
            return _connector_problem(start_response, "invalid_request", headers=[("Allow", "POST")])
        body, rejected = _connector_exact_body_or_problem(
            environ,
            start_response,
            (
                "schemaVersion",
                "grantType",
                "clientId",
                "redirectUri",
                "code",
                "codeVerifier",
            ),
        )
        if rejected:
            return rejected
        idempotency_key, rejected = _connector_idempotency_or_problem(environ, start_response)
        if rejected:
            return rejected
        if body.get("schemaVersion") != CONNECTOR_PAIRING_SCHEMA:
            return _connector_problem(start_response, "schema_version_unsupported")
        if body.get("grantType") != "authorization_code":
            return _connector_problem(start_response, "invalid_request")
        try:
            client_id = validate_client_id(body.get("clientId"))
        except PairingPolicyError:
            return _connector_problem(start_response, "connector_client_unsupported")
        try:
            redirect_uri = validate_redirect_uri(body.get("redirectUri"))
        except PairingPolicyError:
            return _connector_problem(start_response, "redirect_uri_not_allowed")
        rate_rejection = _connector_rate_rejection(
            start_response,
            _connector_operation_rate_limited(environ, "tokenExchange"),
        )
        if rate_rejection:
            return rate_rejection
        digest = _connector_request_digest(method, path, body)
        result = store.exchange_connector_authorization_code(
            body.get("code"),
            body.get("codeVerifier"),
            client_id,
            redirect_uri,
            idempotency_key,
            digest,
        )
        if not result.get("ok"):
            return _connector_result_error(start_response, result)
        pairing = _connector_public_pairing(result.get("pairing"))
        try:
            approved_scopes, scope_digest = _connector_scope_binding(pairing)
        except PairingPolicyError:
            return _connector_problem(start_response, "connector_service_unavailable")
        return _connector_one_time_secret(
            start_response,
            {
                "ok": True,
                "schemaVersion": CONNECTOR_PAIRING_SCHEMA,
                "pairing": pairing,
                "connectorCredentialSecret": result.get("connectorCredentialSecret"),
                "approvedScopes": approved_scopes,
                "scopeDigest": scope_digest,
                "credentialDelivery": {
                    "showCredentialOnce": True,
                    "exactRetryUntilActivation": True,
                    "rawCredentialPersisted": False,
                    "scopeDigest": scope_digest,
                },
                "receipt": _connector_receipt(
                    "exchange",
                    pairing.get("pairingId"),
                    pairing.get("status"),
                    result.get("idempotentReplay"),
                    scope_digest=scope_digest,
                ),
                "idempotentReplay": bool(result.get("idempotentReplay")),
                "valuesRedacted": True,
                "rawPayloadExposed": False,
            },
        )

    credentials_match = _CONNECTOR_CREDENTIALS_ROUTE.fullmatch(path)
    if credentials_match:
        if method != "GET":
            return _connector_problem(start_response, "invalid_request", headers=[("Allow", "GET")])
        token = _token(environ)
        if not token:
            return _connector_problem(start_response, "invalid_token")
        rate_rejection = _connector_rate_rejection(
            start_response,
            _connector_operation_rate_limited(environ, "status", token),
        )
        if rate_rejection:
            return rate_rejection
        result = store.list_connector_credentials(credentials_match.group(1), token)
        if not result.get("ok"):
            return _connector_result_error(start_response, result)
        try:
            approved_scopes, scope_digest = _connector_scope_binding(result)
        except PairingPolicyError:
            return _connector_problem(start_response, "connector_service_unavailable")
        public_items = [
            _connector_public_credential(item) for item in (result.get("items") or [])
        ]
        return _connector_json(
            start_response,
            {
                "ok": True,
                "schemaVersion": CONNECTOR_PAIRING_SCHEMA,
                "pairingId": result.get("pairingId"),
                "currentCredentialId": result.get("currentCredentialId"),
                "items": public_items,
                "approvedScopes": approved_scopes,
                "scopeDigest": scope_digest,
                "count": len(public_items),
                "totalCount": int(result.get("totalCount") or len(public_items)),
                "hasMore": bool(result.get("hasMore")),
                "limit": int(result.get("limit") or 100),
                "receipt": _connector_receipt(
                    "list_credentials",
                    credentials_match.group(1),
                    "verified",
                    False,
                    scope_digest=scope_digest,
                ),
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )

    pairing_match = _CONNECTOR_PAIRING_ROUTE.fullmatch(path)
    if pairing_match:
        if method != "GET":
            return _connector_problem(start_response, "invalid_request", headers=[("Allow", "GET")])
        token = _token(environ)
        if not token:
            return _connector_problem(start_response, "invalid_token")
        rate_rejection = _connector_rate_rejection(
            start_response,
            _connector_operation_rate_limited(environ, "status", token),
        )
        if rate_rejection:
            return rate_rejection
        visible_principal = store.authenticate_connector_token(token, allow_pending=True)
        if visible_principal and visible_principal.get("pairingId") != pairing_match.group(1):
            return _connector_problem(start_response, "pairing_not_found")
        result = store.connector_pairing_status(pairing_match.group(1), token)
        if not result.get("ok"):
            return _connector_result_error(start_response, result)
        verification = _connector_verification(result.get("verification"))
        if not _connector_verification_passed(verification):
            return _connector_problem(start_response, "pairing_verification_failed")
        pairing = _connector_public_pairing(result.get("pairing"), verification=verification)
        try:
            approved_scopes, scope_digest = _connector_scope_binding(pairing)
        except PairingPolicyError:
            return _connector_problem(start_response, "connector_service_unavailable")
        return _connector_json(
            start_response,
            {
                "ok": True,
                "schemaVersion": CONNECTOR_PAIRING_SCHEMA,
                "pairing": pairing,
                "approvedScopes": approved_scopes,
                "scopeDigest": scope_digest,
                "verification": verification,
                "receipt": _connector_receipt(
                    "verify",
                    pairing.get("pairingId"),
                    "verified",
                    False,
                    scope_digest=scope_digest,
                ),
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )

    rotation_activation_match = _CONNECTOR_ROTATION_ACTIVATION_ROUTE.fullmatch(path)
    if rotation_activation_match:
        if method != "POST":
            return _connector_problem(start_response, "invalid_request", headers=[("Allow", "POST")])
        _authority, rejected = _connector_lifecycle_authority_or_problem(
            store,
            environ,
            start_response,
            rotation_activation_match.group(1),
            "rotation_activate",
            rotation_id=rotation_activation_match.group(2),
        )
        if rejected:
            return rejected
        body, rejected = _connector_exact_body_or_problem(
            environ, start_response, ("schemaVersion",)
        )
        if rejected:
            return rejected
        if body.get("schemaVersion") != CONNECTOR_PAIRING_SCHEMA:
            return _connector_problem(start_response, "schema_version_unsupported")
        idempotency_key, rejected = _connector_idempotency_or_problem(environ, start_response)
        if rejected:
            return rejected
        token = _token(environ)
        rate_rejection = _connector_rate_rejection(
            start_response,
            _connector_operation_rate_limited(environ, "credentialLifecycle", token),
        )
        if rate_rejection:
            return rate_rejection
        digest = _connector_request_digest(method, path, body)
        result = store.activate_connector_rotation(
            rotation_activation_match.group(1),
            rotation_activation_match.group(2),
            token,
            idempotency_key,
            digest,
        )
        if not result.get("ok"):
            return _connector_result_error(start_response, result)
        rotation = _connector_public_rotation(result.get("rotation"))
        try:
            approved_scopes, scope_digest = _connector_scope_binding(rotation)
        except PairingPolicyError:
            return _connector_problem(start_response, "connector_service_unavailable")
        return _connector_json(
            start_response,
            {
                "ok": True,
                "schemaVersion": CONNECTOR_PAIRING_SCHEMA,
                "rotation": rotation,
                "approvedScopes": approved_scopes,
                "scopeDigest": scope_digest,
                "receipt": _connector_receipt(
                    "rotate",
                    rotation_activation_match.group(2),
                    "rotated",
                    result.get("idempotentReplay"),
                    scope_digest=scope_digest,
                ),
                "idempotentReplay": bool(result.get("idempotentReplay")),
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )

    action_match = _CONNECTOR_PAIRING_ACTION_ROUTE.fullmatch(path)
    if not action_match:
        return None
    if method != "POST":
        return _connector_problem(start_response, "invalid_request", headers=[("Allow", "POST")])
    pairing_id, action = action_match.groups()
    _authority, rejected = _connector_lifecycle_authority_or_problem(
        store, environ, start_response, pairing_id, action
    )
    if rejected:
        return rejected
    required_fields = (
        ("schemaVersion",)
        if action == "activate"
        else ("schemaVersion", "reason")
    )
    body, rejected = _connector_exact_body_or_problem(
        environ, start_response, required_fields
    )
    if rejected:
        return rejected
    if body.get("schemaVersion") != CONNECTOR_PAIRING_SCHEMA:
        return _connector_problem(start_response, "schema_version_unsupported")
    reason = None
    if action != "activate":
        reason = _connector_valid_reason(body)
        if reason is None:
            return _connector_problem(start_response, "invalid_request")
    idempotency_key, rejected = _connector_idempotency_or_problem(environ, start_response)
    if rejected:
        return rejected
    token = _token(environ)
    rate_bucket = "activation" if action in ("activate", "cancel") else "credentialLifecycle"
    rate_rejection = _connector_rate_rejection(
        start_response,
        _connector_operation_rate_limited(environ, rate_bucket, token),
    )
    if rate_rejection:
        return rate_rejection
    digest = _connector_request_digest(method, path, body)
    if action == "activate":
        result = store.activate_connector_pairing(pairing_id, token, idempotency_key, digest)
        success_status = "200 OK"
    elif action == "rotations":
        result = store.prepare_connector_rotation(
            pairing_id, token, reason, idempotency_key, digest
        )
        success_status = "201 Created"
    elif action == "revoke":
        result = store.revoke_connector_pairing(
            token, pairing_id, reason, idempotency_key, digest
        )
        success_status = "200 OK"
    elif action == "disconnect":
        result = store.disconnect_connector_pairing(
            pairing_id, token, reason, idempotency_key, digest
        )
        success_status = "200 OK"
    else:
        result = store.cancel_connector_pairing(
            pairing_id, token, reason, idempotency_key, digest
        )
        success_status = "200 OK"
    if not result.get("ok"):
        return _connector_result_error(start_response, result)
    if action == "rotations":
        rotation = _connector_public_rotation(result.get("rotation"))
        try:
            approved_scopes, scope_digest = _connector_scope_binding(rotation)
        except PairingPolicyError:
            return _connector_problem(start_response, "connector_service_unavailable")
        return _connector_one_time_secret(
            start_response,
            {
                "ok": True,
                "schemaVersion": CONNECTOR_PAIRING_SCHEMA,
                "rotation": rotation,
                "connectorCredentialSecret": result.get("connectorCredentialSecret"),
                "approvedScopes": approved_scopes,
                "scopeDigest": scope_digest,
                "credentialDelivery": {
                    "showCredentialOnce": True,
                    "exactRetryUntilActivation": True,
                    "rawCredentialPersisted": False,
                    "scopeDigest": scope_digest,
                },
                "receipt": _connector_receipt(
                    "rotate",
                    rotation.get("rotationId"),
                    rotation.get("status"),
                    result.get("idempotentReplay"),
                    scope_digest=scope_digest,
                ),
                "idempotentReplay": bool(result.get("idempotentReplay")),
                "valuesRedacted": True,
                "rawPayloadExposed": False,
            },
            success_status,
        )
    pairing = _connector_public_pairing(result.get("pairing"))
    try:
        approved_scopes, scope_digest = _connector_scope_binding(pairing)
    except PairingPolicyError:
        return _connector_problem(start_response, "connector_service_unavailable")
    receipt = result.get("receipt") or _connector_receipt(
        action,
        pairing_id,
        (result.get("pairing") or {}).get("status"),
        result.get("idempotentReplay"),
        result.get("actorMasterKeyId") if action == "revoke" else None,
        scope_digest=scope_digest,
    )
    if receipt.get("scopeDigest") != scope_digest:
        return _connector_problem(start_response, "connector_service_unavailable")
    return _connector_json(
        start_response,
        {
            "ok": True,
            "schemaVersion": CONNECTOR_PAIRING_SCHEMA,
            "pairing": pairing,
            "approvedScopes": approved_scopes,
            "scopeDigest": scope_digest,
            "receipt": receipt,
            "safeNoOpOnRetry": True,
            "idempotentReplay": bool(result.get("idempotentReplay")),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        },
        success_status,
    )


def route_human(environ, start_response, path):
    """Same-origin, cookie-authenticated human owner control plane."""
    if not path.startswith("/api/matm/human/"):
        return None
    method = environ["REQUEST_METHOD"]
    store = _store()
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        content_type = str(environ.get("CONTENT_TYPE") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            return problem(start_response, "415 Unsupported Media Type", "JSON required", "Human account operations accept only application/json request bodies.", "json_content_type_required")

    if path == "/api/matm/human/recovery/closure-session":
        if method != "POST":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use POST to open an exceptional recovery closure session.", "method_not_allowed", headers=[("Allow", "POST")])
        if str(environ.get("HTTP_AUTHORIZATION") or "").strip():
            return _human_problem(start_response, "human_owner_required")
        if not _human_same_origin(environ):
            return _human_problem(start_response, "trusted_origin_required")
        body, rejected = _access_body(environ, start_response)
        if rejected:
            return rejected
        recovery_secret = body.get("recoverySecret")
        result = store.create_human_session(recovery_secret, 15 * 60)
        if not result.get("ok"):
            return _human_storage_error(start_response, result)
        session_secret = result.get("sessionSecret")
        reauthenticated = store.reauthenticate_human_session(recovery_secret, session_secret)
        if not reauthenticated.get("ok"):
            store.revoke_human_session(session_secret)
            return _human_storage_error(start_response, reauthenticated)
        principal = {
            "authMode": "recovery_closure",
            "selectedCompanyId": result.get("companyId"),
            "permissions": {
                "canExportCompany": True,
                "canCloseCompany": True,
                "canLinkCompanies": False,
                "canManageAgentTokens": False,
            },
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        return one_time_secret_response(
            start_response,
            {
                "ok": True,
                "principal": principal,
                "humanSession": {
                    "humanSessionId": result.get("humanSessionId"),
                    "selectedCompanyId": result.get("companyId"),
                    "authMode": "recovery_closure",
                    "expiresAt": result.get("expiresAt"),
                },
                "csrfToken": result.get("csrfToken"),
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
            "201 Created",
            headers=[("Set-Cookie", _human_session_cookie(session_secret, 15 * 60))],
        )

    if path == "/api/matm/human/company-master-proofs":
        if method != "POST":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use POST to prove one company master credential.", "method_not_allowed", headers=[("Allow", "POST")])
        if _token(environ):
            return _human_problem(start_response, "human_owner_required")
        if not _human_same_origin(environ):
            return _human_problem(start_response, "trusted_origin_required")
        body, rejected = _access_body(environ, start_response)
        if rejected:
            return rejected
        result = store.create_company_master_proof(body.get("companyMasterTokenSecret"), 10 * 60)
        if not result.get("ok"):
            return _human_storage_error(start_response, result)
        return one_time_secret_response(
            start_response,
            {
                "ok": True,
                "proof": {
                    "masterProofId": result.get("masterProofId"),
                    "companyId": result.get("companyId"),
                    "masterKeyId": result.get("masterKeyId"),
                    "status": "issued",
                    "expiresAt": result.get("expiresAt"),
                    "oneTime": True,
                },
                "companyMasterProofSecret": result.get("masterProofSecret"),
                "valuesRedacted": True,
                "rawPayloadExposed": False,
            },
        )

    if path == "/api/matm/human/accounts":
        if method != "POST":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use POST to create a human account.", "method_not_allowed", headers=[("Allow", "POST")])
        if _token(environ):
            return _human_problem(start_response, "human_owner_required")
        if not _human_same_origin(environ):
            return _human_problem(start_response, "trusted_origin_required")
        body, rejected = _access_body(environ, start_response)
        if rejected:
            return rejected
        if body.get("passwordConfirmation") is not None and body.get("passwordConfirmation") != body.get("password"):
            return _human_problem(start_response, "human_password_invalid")
        result = store.create_human_account_with_session(
            body.get("username"),
            body.get("password"),
            body.get("companyMasterProofSecret"),
            body.get("displayName"),
            30 * 60,
        )
        if not result.get("ok"):
            return _human_storage_error(start_response, result)
        session_secret = result.get("sessionSecret")
        return one_time_secret_response(
            start_response,
            {
                "ok": True,
                "created": True,
                "account": result.get("account"),
                "membership": result.get("membership"),
                "memberships": result.get("memberships") or [],
                "humanSession": result.get("humanSession"),
                "selectedCompanyId": None,
                "csrfToken": result.get("csrfToken"),
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
            headers=[("Set-Cookie", _human_session_cookie(session_secret, 30 * 60))],
        )

    if path == "/api/matm/human/session":
        if method == "GET":
            session, session_secret, rejected = _human_session_auth(store, environ, start_response)
            if rejected:
                return rejected
            if _human_fetch_same_origin(environ) and not str(environ.get("HTTP_X_CSRF_TOKEN") or "").strip():
                rotated = store.rotate_human_account_session_csrf(session_secret)
                if not rotated.get("ok"):
                    return _human_storage_error(start_response, rotated)
                payload = _human_complete_session_payload(store, session_secret, rotated.get("csrfToken"))
                if payload is None:
                    return _human_problem(start_response, "human_session_required")
                payload["csrfRotated"] = True
                return one_time_secret_response(start_response, payload, "200 OK")
            payload = _human_complete_session_payload(store, session_secret)
            if payload is None:
                return _human_problem(start_response, "human_session_required")
            return json_response(start_response, payload)
        if method != "POST":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use GET to inspect or POST to open a human account session.", "method_not_allowed", headers=[("Allow", "GET, POST")])
        if _token(environ):
            return _human_problem(start_response, "human_owner_required")
        if not _human_same_origin(environ):
            return _human_problem(start_response, "trusted_origin_required")
        body, rejected = _access_body(environ, start_response)
        if rejected:
            return rejected
        if not str(body.get("username") or "").strip() or not str(body.get("password") or ""):
            return _human_problem(start_response, "username_password_required")
        result = store.login_human_account(body.get("username"), body.get("password"), 30 * 60)
        if not result.get("ok"):
            return _human_storage_error(start_response, result)
        session_secret = result.get("sessionSecret")
        payload = _human_complete_session_payload(store, session_secret, result.get("csrfToken"))
        if payload is None:
            return _human_problem(start_response, "human_session_required")
        payload["humanSession"]["passwordReauthenticationRequiredForSensitiveActions"] = True
        return one_time_secret_response(
            start_response,
            payload,
            headers=[("Set-Cookie", _human_session_cookie(session_secret, 30 * 60))],
        )

    if path == "/api/matm/human/session/reauth":
        if method != "POST":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use POST to reauthenticate a human-owner session.", "method_not_allowed", headers=[("Allow", "POST")])
        session, session_secret, rejected = _human_session_auth(store, environ, start_response, mutation=True)
        if rejected:
            return rejected
        body, rejected = _access_body(environ, start_response)
        if rejected:
            return rejected
        result = store.reauthenticate_and_rotate_human_account_session(session_secret, body.get("password"))
        if not result.get("ok"):
            return _human_storage_error(start_response, result)
        rotated_secret = result.get("sessionSecret")
        payload = _human_complete_session_payload(store, rotated_secret, result.get("csrfToken"))
        if payload is None:
            return _human_problem(start_response, "human_session_required")
        payload["passwordReauthenticatedAt"] = result.get("passwordReauthenticatedAt")
        payload["sessionRotated"] = True
        return one_time_secret_response(
            start_response,
            payload,
            "200 OK",
            headers=[("Set-Cookie", _human_session_cookie(rotated_secret, 30 * 60))],
        )

    if path == "/api/matm/human/session/logout":
        if method != "POST":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use POST to close a human-owner session.", "method_not_allowed", headers=[("Allow", "POST")])
        _session, session_secret, rejected = _human_session_auth(store, environ, start_response, mutation=True)
        if rejected:
            return rejected
        result = store.logout_human_account(session_secret)
        if not result.get("ok"):
            return _human_storage_error(start_response, result)
        return json_response(start_response, {"ok": True, "signedOut": True, "valuesRedacted": True, "rawCredentialExposed": False, "rawPayloadExposed": False}, headers=[("Set-Cookie", _human_session_cookie("", 0))])

    if path == "/api/matm/human/company-memberships":
        if method != "GET":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use GET to list linked company memberships.", "method_not_allowed", headers=[("Allow", "GET")])
        _session, session_secret, rejected = _human_session_auth(store, environ, start_response)
        if rejected:
            return rejected
        result = store.list_human_company_memberships(session_secret)
        return json_response(start_response, result) if result.get("ok") else _human_storage_error(start_response, result)

    if path == "/api/matm/human/company-memberships/link":
        if method != "POST":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use POST to prove and link one company master credential.", "method_not_allowed", headers=[("Allow", "POST")])
        session, session_secret, rejected = _human_session_auth(store, environ, start_response, mutation=True)
        if rejected:
            return rejected
        if not _human_recently_reauthenticated(session):
            return _human_problem(start_response, "human_reauthentication_required")
        body, rejected = _access_body(environ, start_response)
        if rejected:
            return rejected
        result = store.prove_and_link_company_master(
            session_secret,
            body.get("companyMasterProofSecret"),
            body.get("role") or "owner",
        )
        if not result.get("ok"):
            return _human_storage_error(start_response, result)
        memberships = store.list_human_company_memberships(session_secret)
        if not memberships.get("ok"):
            return _human_storage_error(start_response, memberships)
        return json_response(
            start_response,
            {
                "ok": True,
                "membership": result.get("membership"),
                "memberships": memberships.get("items") or [],
                "proofAccepted": True,
                "rawCredentialPersisted": False,
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
            "201 Created",
        )

    if path == "/api/matm/human/session/company":
        if method != "POST":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use POST to explicitly select a linked company membership.", "method_not_allowed", headers=[("Allow", "POST")])
        _session, session_secret, rejected = _human_session_auth(store, environ, start_response, mutation=True)
        if rejected:
            return rejected
        body, rejected = _access_body(environ, start_response)
        if rejected:
            return rejected
        result = store.select_human_company_membership(session_secret, body.get("authorityId"))
        if not result.get("ok"):
            return _human_storage_error(start_response, result)
        if result.get("sessionSecret") and result.get("csrfToken"):
            payload = _human_complete_session_payload(
                store, result.get("sessionSecret"), result.get("csrfToken")
            )
            if payload is None:
                return _human_problem(start_response, "human_session_required")
            payload["sessionRotated"] = True
            return one_time_secret_response(
                start_response,
                payload,
                "200 OK",
                headers=[("Set-Cookie", _human_session_cookie(result.get("sessionSecret"), 30 * 60))],
            )
        return json_response(start_response, dict(result, selectedCompanyId=result.get("companyId"), sessionRotated=False))

    agent_tokens_match = _HUMAN_AGENT_TOKENS_ROUTE.fullmatch(path)
    if agent_tokens_match:
        if method != "GET":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use GET to list redacted agent credential metadata.", "method_not_allowed", headers=[("Allow", "GET")])
        company_id = agent_tokens_match.group(1)
        _session, session_secret, rejected = _human_session_auth(
            store, environ, start_response, company_id
        )
        if rejected:
            return rejected
        result = store.list_human_agent_tokens(session_secret, company_id)
        return json_response(start_response, result) if result.get("ok") else _human_storage_error(start_response, result)

    replacements_match = _HUMAN_AGENT_TOKEN_REPLACEMENTS_ROUTE.fullmatch(path)
    if replacements_match:
        if method != "POST":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use POST to prepare a one-time successor credential.", "method_not_allowed", headers=[("Allow", "POST")])
        company_id, predecessor_credential_id = replacements_match.groups()
        session, session_secret, rejected = _human_session_auth(
            store, environ, start_response, company_id, mutation=True
        )
        if rejected:
            return rejected
        if not _human_recently_reauthenticated(session):
            return _human_problem(start_response, "recent_reauthentication_required")
        body, rejected = _access_body(environ, start_response)
        if rejected:
            return rejected
        idempotency_key = _idempotency_key(environ)
        digest = _connector_request_digest(method, path, body)
        result = store.prepare_human_agent_token_replacement(
            session_secret,
            company_id,
            predecessor_credential_id,
            body.get("reason"),
            body.get("expiresInSeconds") or 900,
            idempotency_key,
            digest,
        )
        if not result.get("ok"):
            return _human_storage_error(start_response, result)
        payload = {
            "ok": True,
            "replacement": result.get("replacement"),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        if result.get("successorCredentialAlreadyDelivered"):
            payload["successorCredentialAlreadyDelivered"] = True
            payload["idempotentReplay"] = True
            return json_response(start_response, payload, "200 OK")
        payload["successorTokenSecret"] = result.get("successorTokenSecret")
        return one_time_secret_response(start_response, payload, "201 Created")

    replacement_match = _HUMAN_AGENT_TOKEN_REPLACEMENT_ROUTE.fullmatch(path)
    if replacement_match:
        company_id, predecessor_credential_id, replacement_id, action = replacement_match.groups()
        if action is None:
            if method != "GET":
                return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use GET to reconcile replacement status.", "method_not_allowed", headers=[("Allow", "GET")])
            _session, session_secret, rejected = _human_session_auth(
                store, environ, start_response, company_id
            )
            if rejected:
                return rejected
            result = store.human_agent_token_replacement_status(
                session_secret, company_id, predecessor_credential_id, replacement_id
            )
            return json_response(start_response, result) if result.get("ok") else _human_storage_error(start_response, result)
        if method != "POST":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use POST to confirm or cancel this replacement.", "method_not_allowed", headers=[("Allow", "POST")])
        session, session_secret, rejected = _human_session_auth(
            store, environ, start_response, company_id, mutation=True
        )
        if rejected:
            return rejected
        if not _human_recently_reauthenticated(session):
            return _human_problem(start_response, "recent_reauthentication_required")
        body, rejected = _access_body(environ, start_response)
        if rejected:
            return rejected
        idempotency_key = _idempotency_key(environ)
        digest = _connector_request_digest(method, path, body)
        if action == "confirm":
            result = store.confirm_human_agent_token_replacement(
                session_secret,
                company_id,
                predecessor_credential_id,
                replacement_id,
                body.get("successorTokenProof"),
                idempotency_key,
                digest,
            )
            if result.get("ok"):
                result = dict(
                    result,
                    auditActor={
                        "humanAccountId": session.get("humanAccountId"),
                        "username": session.get("username"),
                        "authorityId": session.get("selectedAuthorityId"),
                        "valuesRedacted": True,
                    },
                )
        else:
            result = store.cancel_human_agent_token_replacement(
                session_secret,
                company_id,
                predecessor_credential_id,
                replacement_id,
                idempotency_key or None,
                digest if idempotency_key else None,
            )
        return json_response(start_response, result) if result.get("ok") else _human_storage_error(start_response, result)

    match = _HUMAN_COMPANY_ROUTE.fullmatch(path)
    if not match:
        return problem(start_response, "404 Not Found", "Route not found", "No human-owner route matched this request.", "not_found")
    company_id, operation = match.groups()
    mutation = method != "GET"
    allow_recovery = operation in ("export-plan", "exports", "closure-intents", "close")
    session, session_secret, rejected = _human_session_auth(
        store,
        environ,
        start_response,
        company_id,
        mutation=mutation,
        allow_recovery=allow_recovery,
    )
    if rejected:
        return rejected

    if operation == "top-level-agent-master-credential-setting":
        if method == "GET":
            result = store.human_top_level_agent_master_credential_setting(
                session_secret, company_id
            )
        elif method == "PATCH":
            body, rejected = _access_body(environ, start_response)
            if rejected:
                return rejected
            if set(body) != {"enabled"} or not isinstance(
                body.get("enabled"), bool
            ):
                return _human_problem(
                    start_response,
                    "top_level_agent_master_credential_setting_invalid",
                )
            result = store.set_human_top_level_agent_master_credential_setting(
                session_secret, company_id, body.get("enabled")
            )
        else:
            return problem(
                start_response,
                "405 Method Not Allowed",
                "Method not allowed",
                "Use GET or PATCH for the top-level-agent company-master setting.",
                "method_not_allowed",
                headers=[("Allow", "GET, PATCH")],
            )
        return (
            json_response(start_response, result)
            if result.get("ok")
            else _human_storage_error(start_response, result)
        )

    if operation == "export-plan":
        if method != "GET":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use GET to review the company export plan.", "method_not_allowed", headers=[("Allow", "GET")])
        snapshot_result = store.company_export_snapshot(session_secret, company_id)
        if not snapshot_result.get("ok"):
            return _human_storage_error(start_response, snapshot_result)
        company = (snapshot_result.get("snapshot") or {}).get("company") or {}
        return json_response(
            start_response,
            {
                "ok": True,
                "exportPlan": {
                    "companyId": company_id,
                    "companyLabel": company.get("label"),
                    "companyStatus": company.get("status"),
                    "completeCompanyExportAvailable": True,
                    "exportStronglyRecommended": True,
                    "exportBeforeClearHistoryRecommended": True,
                    "permanentPurgeRequiresCompletedExport": True,
                    "companyStorageLimitBytes": PUBLIC_STORAGE_BYTES,
                    "freeCompanyQuotaBytes": PUBLIC_STORAGE_BYTES,
                    "retention": {
                        "freeRoutineHistoryDays": 7,
                        "softDeletedDataRetainedIndefinitely": True,
                        "softDeletedDataCountsTowardCompanyQuota": True,
                    },
                    "downloadMethod": "POST",
                    "downloadPath": "/api/matm/human/companies/%s/exports" % company_id,
                    "valuesRedacted": True,
                },
                "auditActor": _human_audit_actor(session),
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )

    if operation == "exports":
        if method != "POST":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use POST to assemble and download a complete company export.", "method_not_allowed", headers=[("Allow", "POST")])
        snapshot_result = store.company_export_snapshot(session_secret, company_id)
        if not snapshot_result.get("ok"):
            return _human_storage_error(start_response, snapshot_result)
        snapshot = snapshot_result.get("snapshot") or {}
        snapshot = dict(snapshot, auditActor=_human_audit_actor(session))
        company = snapshot.get("company") or {}
        try:
            artifact = assemble_company_export(
                snapshot,
                generated_at=snapshot.get("exportedAt") or utc_now(),
                company_id=company_id,
                company_label=company.get("label"),
            )
        except CompanyExportError:
            return problem(start_response, "500 Internal Server Error", "Company export failed", "The complete company export could not be assembled safely.", "company_export_failed")
        receipt_result = store.record_company_export_receipt(session_secret, artifact.get("exportReceiptDigest"), "zip")
        if not receipt_result.get("ok"):
            return _human_storage_error(start_response, receipt_result)
        receipt = receipt_result.get("receipt") or {}
        return response(
            start_response,
            "201 Created",
            artifact["body"],
            artifact["contentType"],
            [
                ("Content-Disposition", artifact["contentDisposition"]),
                ("Cache-Control", "no-store, no-cache, must-revalidate, private"),
                ("Pragma", "no-cache"),
                ("Referrer-Policy", "no-referrer"),
                ("X-MemoryEndpoints-Export-Receipt-Id", receipt.get("exportReceiptId") or ""),
                ("X-MemoryEndpoints-Export-Company-Id", company_id),
                ("X-MemoryEndpoints-Export-SHA256", "sha256:" + (artifact.get("digest") or "")),
                ("X-MemoryEndpoints-Export-Complete", "true"),
            ],
        )

    if operation == "closure-intents":
        if method != "POST":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use POST to create a one-time lifecycle intent.", "method_not_allowed", headers=[("Allow", "POST")])
        if not _human_recently_reauthenticated(session):
            return _human_problem(start_response, "recent_reauthentication_required")
        body, rejected = _access_body(environ, start_response)
        if rejected:
            return rejected
        requested_operation = str(body.get("operation") or "").strip().lower()
        storage_operation = "soft_delete" if requested_operation == "delete" else requested_operation
        result = store.create_company_closure_intent(
            session_secret,
            storage_operation,
            body.get("acknowledgeExportOpportunity") is True,
            body.get("expiresInSeconds") or 900,
        )
        if not result.get("ok"):
            return _human_storage_error(start_response, result)
        public_intent = dict(result.get("intent") or {})
        public_intent.pop("intentHash", None)
        public_intent["confirmationPhrase"] = public_intent.pop("typedConfirmationPhrase", None)
        public_intent["operation"] = requested_operation
        return one_time_secret_response(
            start_response,
            {
                "ok": True,
                "intent": public_intent,
                "closureIntentSecret": result.get("intentSecret"),
                "valuesRedacted": True,
                "rawPayloadExposed": False,
            },
        )

    if operation in ("close", "delete", "permanent-purge"):
        if method != "POST":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use POST for this company lifecycle action.", "method_not_allowed", headers=[("Allow", "POST")])
        if not _human_recently_reauthenticated(session):
            return _human_problem(start_response, "recent_reauthentication_required")
        body, rejected = _access_body(environ, start_response)
        if rejected:
            return rejected
        intent_secret = body.get("closureIntentSecret")
        confirmation = body.get("typedConfirmationPhrase")
        if operation == "close":
            result = store.close_company(session_secret, intent_secret, confirmation)
        elif operation == "delete":
            result = store.soft_delete_company(session_secret, intent_secret, confirmation)
            if result.get("ok"):
                result = dict(
                    result,
                    status="deleted",
                    softDeleted=True,
                    restorable=True,
                    retainedIndefinitely=True,
                    countsTowardCompanyQuota=True,
                )
        else:
            result = store.permanently_purge_company(
                session_secret,
                intent_secret,
                confirmation,
                body.get("exportReceiptId"),
                body.get("acknowledgePermanentPurgeWithoutExport") is True,
            )
        if not result.get("ok"):
            return _human_storage_error(start_response, result)
        if operation == "permanent-purge":
            result = dict(result, purged=True)
        result = dict(result, auditActor=_human_audit_actor(session))
        headers = [("Set-Cookie", _human_session_cookie("", 0))] if operation == "permanent-purge" else None
        return json_response(start_response, result, headers=headers)

    if operation == "restore":
        if method != "POST":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use POST to restore a soft-deleted company.", "method_not_allowed", headers=[("Allow", "POST")])
        result = store.restore_company(session_secret)
        if not result.get("ok"):
            return _human_storage_error(start_response, result)
        result = dict(result, restored=True)
        return json_response(start_response, result)

    if operation == "history":
        if method != "GET":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use GET to read human-only forensic history.", "method_not_allowed", headers=[("Allow", "GET")])
        query = _query(environ)
        items = store.company_audit_log(company_id, query.get("limit") or 5000)
        return json_response(
            start_response,
            {
                "ok": True,
                "schemaVersion": "memoryendpoints.human_routine_history.v1",
                "companyId": company_id,
                "visibility": "human_only",
                "agentsCanAccess": False,
                "retentionDays": 7,
                "physicallyDeletedAfterRetention": True,
                "items": items,
                "count": len(items),
                "downloadAvailableUntilPurge": True,
                "downloadPath": "/api/matm/human/companies/%s/exports" % company_id,
                "auditActor": _human_audit_actor(session),
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )
    if operation == "history/clear":
        return problem(start_response, "501 Not Implemented", "Human history is not ready", "The human-only forensic history clear operation is not yet available.", "human_history_not_ready")
    return None


def route_access(environ, start_response, path):
    """Route typed master/agent credentials and one-time invitation redemption."""
    method = environ["REQUEST_METHOD"]
    store = _store()

    if path == "/api/matm/access/invites/redeem":
        if method != "POST":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use POST to redeem an invitation.", "method_not_allowed", headers=[("Allow", "POST")])
        if _idempotency_key(environ):
            return _access_problem(start_response, "idempotency_key_not_allowed")
        body, rejected = _access_body(environ, start_response)
        if rejected:
            return rejected
        try:
            result = store.redeem_agent_invite(body.get("inviteSecret"))
        except RuntimeError:
            return _access_problem(start_response, "credential_system_not_configured")
        if not result.get("ok"):
            return _access_result_error(start_response, result, redemption=True)
        invite = _public_invite_with_grant(result.get("invite") or {})
        principal = result.get("principal") or {}
        return one_time_secret_response(
            start_response,
            {
                "ok": True,
                "agentTokenSecret": result.get("agentToken"),
                "principal": _public_auth_principal(principal),
                "invite": invite,
                "onboarding": {
                    "assignmentContext": invite.get("assignmentContext") or {},
                    "workspaceId": principal.get("workspaceId"),
                    "projectId": principal.get("projectId") or (invite.get("assignmentContext") or {}).get("projectId"),
                    "immutableScope": invite.get("grant"),
                },
                "valuesRedacted": True,
                "rawPayloadExposed": False,
            },
        )

    access_paths = (
        path == "/api/matm/me"
        or path == "/api/matm/access/agent-name-requests"
        or path == "/api/matm/access/scope-catalog"
        or path == "/api/matm/access/company-master-credentials"
        or path == "/api/matm/access/invites"
        or path == "/api/matm/access/agent-tokens"
        or bool(_ACCESS_REQUEST_DECISION_ROUTE.fullmatch(path))
        or bool(_ACCESS_INVITE_REVOKE_ROUTE.fullmatch(path))
        or bool(_ACCESS_TOKEN_REVOKE_ROUTE.fullmatch(path))
    )
    if not access_paths:
        return None

    auth, rejected = _access_auth(store, environ, start_response)
    if rejected:
        return rejected
    if _is_connector_principal(auth) and not _connector_principal_scopes(auth):
        return _connector_problem(start_response, "connector_service_unavailable")
    if path == "/api/matm/me":
        if method != "GET":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use GET for credential introspection.", "method_not_allowed", headers=[("Allow", "GET")])
        payload = {
            "ok": True,
            "principal": _public_auth_principal(auth),
            "access": {
                "namePolicy": AGENT_NAME_POLICY,
                "scopeLevels": []
                if _is_connector_principal(auth)
                else ["company", "workspace", "project", "game", "session", "goal", "task"],
                "scopeRule": "exact_connector_and_agent"
                if _is_connector_principal(auth)
                else "exact_scope_and_descendants",
                "grantMutable": False,
            },
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        if _is_connector_principal(auth):
            return _connector_json(start_response, payload)
        return json_response(start_response, payload)

    if _is_connector_principal(auth):
        return _connector_problem(start_response, "connector_scope_forbidden")

    if (
        path == "/api/matm/access/company-master-credentials"
        and method == "POST"
        and auth.get("credentialType") == "agent"
    ):
        grant = auth.get("grant") if isinstance(auth.get("grant"), dict) else {}
        scope_type = auth.get("scopeType") or grant.get("scopeType")
        scope_id = auth.get("scopeId") or grant.get("scopeId")
        if scope_type != "company" or scope_id != auth.get("companyId"):
            return _access_problem(start_response, "top_level_agent_required")
        body, rejected = _access_body(environ, start_response)
        if rejected:
            return rejected
        required = {
            "schemaVersion",
            "workspaceId",
            "candidateTokenSecret",
            "label",
            "principalName",
        }
        if (
            set(body) != required
            or body.get("schemaVersion")
            != "memoryendpoints.top_level_agent_company_master.v1"
        ):
            return _access_problem(
                start_response,
                "top_level_agent_master_credential_request_invalid",
            )
        idempotency_key = _idempotency_key(environ)
        if not idempotency_key:
            return _access_problem(start_response, "idempotency_key_required")
        result = store.register_top_level_agent_company_master_credential(
            _token(environ),
            body.get("workspaceId"),
            body.get("candidateTokenSecret"),
            body.get("label"),
            body.get("principalName"),
            idempotency_key,
        )
        if not result.get("ok"):
            return _access_result_error(start_response, result)
        return json_response(
            start_response,
            result,
            "200 OK" if result.get("idempotentReplay") else "201 Created",
            headers=list(_CONNECTOR_JSON_HEADERS),
        )

    master_rejected = _company_master_or_problem(auth, start_response)
    if master_rejected:
        return master_rejected
    master_token = _token(environ)

    if path == "/api/matm/access/company-master-credentials":
        if method == "GET":
            result = store.list_company_master_credentials(master_token)
            return (
                json_response(
                    start_response,
                    result,
                    headers=list(_CONNECTOR_JSON_HEADERS),
                )
                if result.get("ok")
                else _access_result_error(start_response, result)
            )
        if method != "POST":
            return problem(
                start_response,
                "405 Method Not Allowed",
                "Method not allowed",
                "Use GET or POST for company-master credentials.",
                "method_not_allowed",
                headers=[("Allow", "GET, POST")],
            )
        body, rejected = _access_body(environ, start_response)
        if rejected:
            return rejected
        required = {
            "schemaVersion",
            "workspaceId",
            "candidateTokenSecret",
            "label",
            "principalName",
        }
        if (
            set(body) != required
            or body.get("schemaVersion")
            != "memoryendpoints.company_master_delegation.v1"
            or any(not isinstance(body.get(field), str) for field in required)
        ):
            return _access_problem(
                start_response, "company_master_delegation_invalid"
            )
        idempotency_key = _idempotency_key(environ)
        if not idempotency_key:
            return _access_problem(start_response, "idempotency_key_required")
        try:
            result = store.delegate_company_master_credential(
                master_token,
                body.get("workspaceId"),
                body.get("candidateTokenSecret"),
                body.get("label"),
                body.get("principalName"),
                idempotency_key,
            )
        except RuntimeError:
            return _access_problem(
                start_response, "credential_system_not_configured"
            )
        if not result.get("ok"):
            return _access_result_error(start_response, result)
        return json_response(
            start_response,
            result,
            "200 OK" if result.get("idempotentReplay") else "201 Created",
            headers=list(_CONNECTOR_JSON_HEADERS),
        )

    if path == "/api/matm/access/scope-catalog":
        if method != "GET":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use GET for the company scope catalog.", "method_not_allowed", headers=[("Allow", "GET")])
        result = store.company_scope_catalog(master_token)
        return json_response(start_response, result) if result.get("ok") else _access_result_error(start_response, result)

    if path == "/api/matm/access/agent-name-requests":
        if method == "GET":
            result = store.list_agent_access_requests(master_token, _query(environ).get("status"))
            return json_response(start_response, result) if result.get("ok") else _access_result_error(start_response, result)
        if method != "POST":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use GET or POST for agent-name requests.", "method_not_allowed", headers=[("Allow", "GET, POST")])
        body, rejected = _access_body(environ, start_response)
        if rejected:
            return rejected
        requested_grant = body.get("requestedGrant") or {}
        if not isinstance(requested_grant, dict):
            return _access_problem(start_response, "scope_invalid")
        operation = "access-agent-name-request"
        workspace_id, idempotency_key, replay = _access_idempotency_or_problem(
            store,
            environ,
            start_response,
            auth,
            master_token,
            requested_grant.get("scopeType"),
            requested_grant.get("scopeId"),
            operation,
            body,
        )
        if replay:
            return replay
        result = store.request_agent_access(
            auth.get("companyId"),
            body.get("requestedName"),
            requested_grant.get("scopeType"),
            requested_grant.get("scopeId"),
            _auth_actor_id(auth),
            body.get("supersedesCredentialId"),
            body.get("memoryTransferFromCredentialId"),
            display_name=body.get("displayName"),
            justification=body.get("justification"),
            assignment_context=body.get("assignmentContext"),
        )
        if not result.get("ok"):
            return _access_result_error(start_response, result)
        result = _finalize_access_idempotency(
            store,
            environ,
            workspace_id,
            idempotency_key,
            operation,
            body,
            result,
            "201 Created",
        )
        return json_response(
            start_response,
            result,
            "201 Created",
            headers=list(_CONNECTOR_JSON_HEADERS),
        )

    decision_match = _ACCESS_REQUEST_DECISION_ROUTE.fullmatch(path)
    if decision_match:
        if method != "POST":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use POST to decide an agent-name request.", "method_not_allowed", headers=[("Allow", "POST")])
        body, rejected = _access_body(environ, start_response)
        if rejected:
            return rejected
        decisions = {"approve": "approved", "deny": "denied"}
        decision = decisions.get(str(body.get("decision") or "").strip().lower())
        if not decision:
            return _access_problem(start_response, "access_decision_invalid")
        request_id = decision_match.group(1)
        inventory = store.list_agent_access_requests(master_token)
        target = _access_inventory_item(inventory, request_id, "requestId")
        if not target:
            return _access_result_error(
                start_response,
                inventory
                if not inventory.get("ok")
                else {"status": "access_request_not_found"},
            )
        operation = "access-agent-name-decision"
        canonical_body = dict(body, requestId=request_id)
        workspace_id, idempotency_key, replay = _access_idempotency_or_problem(
            store,
            environ,
            start_response,
            auth,
            master_token,
            target.get("scopeType"),
            target.get("scopeId"),
            operation,
            canonical_body,
        )
        if replay:
            return replay
        result = store.decide_agent_access_request(master_token, request_id, decision, body.get("decisionReason"))
        if not result.get("ok"):
            if result.get("status") == "access_request_not_pending":
                result = dict(result, status="approval_already_final")
            return _access_result_error(start_response, result)
        result = _finalize_access_idempotency(
            store,
            environ,
            workspace_id,
            idempotency_key,
            operation,
            canonical_body,
            result,
            "200 OK",
        )
        return json_response(
            start_response, result, headers=list(_CONNECTOR_JSON_HEADERS)
        )

    if path == "/api/matm/access/invites":
        if method == "GET":
            result = store.list_agent_invites(master_token, _query(environ).get("status"))
            return json_response(start_response, result) if result.get("ok") else _access_result_error(start_response, result)
        if method != "POST":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use GET or POST for agent invitations.", "method_not_allowed", headers=[("Allow", "GET, POST")])
        if _idempotency_key(environ):
            return _access_problem(start_response, "idempotency_key_not_allowed")
        body, rejected = _access_body(environ, start_response)
        if rejected:
            return rejected
        result = store.issue_agent_invite(master_token, body.get("approvedRequestId"), body.get("expiresInSeconds") or 900)
        if not result.get("ok"):
            return _access_result_error(start_response, result)
        invite_secret = result.get("inviteSecret")
        invite = _public_invite_with_grant(result.get("invite") or {})
        return one_time_secret_response(
            start_response,
            {
                "ok": True,
                "invite": invite,
                "inviteUrl": "%s/agent-setup#invite=%s" % (SITE_URL.rstrip("/"), quote(invite_secret or "", safe="")),
                "valuesRedacted": True,
                "rawPayloadExposed": False,
            },
        )

    invite_revoke_match = _ACCESS_INVITE_REVOKE_ROUTE.fullmatch(path)
    if invite_revoke_match:
        if method != "POST":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use POST to revoke an invitation.", "method_not_allowed", headers=[("Allow", "POST")])
        invite_id = invite_revoke_match.group(1)
        inventory = store.list_agent_invites(master_token)
        target = _access_inventory_item(inventory, invite_id, "inviteId")
        if not target:
            return _access_result_error(
                start_response,
                inventory
                if not inventory.get("ok")
                else {"status": "invite_not_found"},
            )
        operation = "access-invite-revoke"
        canonical_body = {"inviteId": invite_id}
        workspace_id, idempotency_key, replay = _access_idempotency_or_problem(
            store,
            environ,
            start_response,
            auth,
            master_token,
            target.get("scopeType"),
            target.get("scopeId"),
            operation,
            canonical_body,
        )
        if replay:
            return replay
        result = store.revoke_agent_invite(master_token, invite_id)
        if not result.get("ok"):
            return _access_result_error(start_response, result)
        result = _finalize_access_idempotency(
            store,
            environ,
            workspace_id,
            idempotency_key,
            operation,
            canonical_body,
            result,
            "200 OK",
        )
        return json_response(
            start_response, result, headers=list(_CONNECTOR_JSON_HEADERS)
        )

    if path == "/api/matm/access/agent-tokens":
        if method != "GET":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use GET for agent-token inventory.", "method_not_allowed", headers=[("Allow", "GET")])
        result = store.list_agent_tokens(master_token, _query(environ).get("status"))
        if result.get("ok"):
            raw_items = result.get("items") or []
            result = dict(result)
            result["items"] = []
            for item in raw_items:
                public_item = dict(item, credentialId=item.get("credentialId") or item.get("agentTokenId"))
                public_item.pop("agentTokenId", None)
                result["items"].append(public_item)
        return json_response(start_response, result) if result.get("ok") else _access_result_error(start_response, result)

    token_revoke_match = _ACCESS_TOKEN_REVOKE_ROUTE.fullmatch(path)
    if token_revoke_match:
        if method != "POST":
            return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use POST to revoke an agent token.", "method_not_allowed", headers=[("Allow", "POST")])
        credential_id = token_revoke_match.group(1)
        inventory = store.list_agent_tokens(master_token)
        target = _access_inventory_item(
            inventory, credential_id, "credentialId", "agentTokenId"
        )
        if not target:
            return _access_result_error(
                start_response,
                inventory
                if not inventory.get("ok")
                else {"status": "agent_token_not_found"},
            )
        operation = "access-agent-token-revoke"
        canonical_body = {"credentialId": credential_id}
        workspace_id, idempotency_key, replay = _access_idempotency_or_problem(
            store,
            environ,
            start_response,
            auth,
            master_token,
            target.get("scopeType"),
            target.get("scopeId"),
            operation,
            canonical_body,
        )
        if replay:
            return replay
        result = store.revoke_agent_token(master_token, credential_id)
        if result.get("ok"):
            result = dict(result, credentialId=result.get("credentialId") or result.get("agentTokenId") or credential_id)
            result.pop("agentTokenId", None)
        else:
            return _access_result_error(start_response, result)
        result = _finalize_access_idempotency(
            store,
            environ,
            workspace_id,
            idempotency_key,
            operation,
            canonical_body,
            result,
            "200 OK",
        )
        return json_response(
            start_response, result, headers=list(_CONNECTOR_JSON_HEADERS)
        )
    return None


def _connector_has_scope(auth, required_scope):
    return required_scope in frozenset(_connector_principal_scopes(auth))


def _connector_exact_parsed_body_or_problem(
    environ, start_response, body, required, optional=()
):
    if not _connector_content_type_is_json(environ) or not isinstance(body, dict):
        return None, _connector_problem(start_response, "json_content_type_required")
    required = frozenset(required)
    allowed = required | frozenset(optional)
    if set(body) - allowed or not required.issubset(body):
        return None, _connector_problem(start_response, "invalid_request")
    return body, None


def _connector_public_memory_item(item):
    item = item or {}
    return {
        "memoryId": item.get("eventId") or item.get("memoryId"),
        "workspaceId": item.get("workspaceId"),
        "actorAgentId": item.get("actorAgentId"),
        "scope": item.get("scope"),
        "title": item.get("title"),
        "summary": item.get("summary"),
        "tags": list(item.get("tags") or [])[:16],
        "memoryType": item.get("memoryType"),
        "subject": item.get("subject"),
        "confidence": item.get("confidence"),
        "createdAt": item.get("createdAt"),
        "classification": "public_safe",
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _route_connector_scoped_operation(
    environ, start_response, path, store, auth, body, query
):
    """Enforce the closed v1 connector route/action matrix before generic MATM."""
    method = environ.get("REQUEST_METHOD") or "GET"
    if query or environ.get("QUERY_STRING"):
        return _connector_problem(start_response, "connector_scope_forbidden")
    pairing_id = auth.get("pairingId")
    token = _token(environ)
    scope_digest = auth.get("scopeDigest") or connector_scope_digest(
        CONNECTOR_V1_REQUESTED_SCOPES
    )

    if path == "/api/matm/workspace" and method == "GET":
        if not _connector_has_scope(auth, "connector:self:readback"):
            return _connector_problem(start_response, "connector_scope_forbidden")
        result = store.connector_workspace_readback(pairing_id, token)
        if not result.get("ok"):
            return _connector_result_error(start_response, result)
        return _connector_json(
            start_response,
            {
                "ok": True,
                "schemaVersion": CONNECTOR_PAIRING_SCHEMA,
                "workspace": result.get("workspace") or {},
                "connectorBoundedReadback": True,
                "approvedScopes": list(CONNECTOR_V1_REQUESTED_SCOPES),
                "scopeDigest": scope_digest,
                "receipt": _connector_receipt(
                    "workspace_readback", pairing_id, "verified", scope_digest=scope_digest
                ),
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )

    if path == "/api/matm/agents/register" and method == "POST":
        if not _connector_has_scope(auth, "agent:self:register"):
            return _connector_problem(start_response, "connector_scope_forbidden")
        if isinstance(body, dict) and (
            "agentId" in body
            or "agent_id" in body
            or "requestedAgentId" in body
            or "requested_agent_id" in body
        ):
            return _connector_problem(start_response, "connector_scope_forbidden")
        rate_rejection = _connector_rate_rejection(
            start_response,
            _connector_operation_rate_limited(
                environ,
                "selfRegistration",
                auth.get("connectorCredentialId") or pairing_id,
                store=store,
            ),
        )
        if rate_rejection:
            return rate_rejection
        parsed, rejected = _connector_exact_parsed_body_or_problem(
            environ, start_response, body, ("schemaVersion",)
        )
        if rejected:
            return rejected
        if parsed.get("schemaVersion") != CONNECTOR_PAIRING_SCHEMA:
            return _connector_problem(start_response, "schema_version_unsupported")
        idempotency_key, rejected = _connector_idempotency_or_problem(environ, start_response)
        if rejected:
            return rejected
        result = store.confirm_connector_agent_registration(pairing_id, token)
        if not result.get("ok"):
            return _connector_result_error(start_response, result)
        return _connector_json(
            start_response,
            {
                "ok": True,
                "schemaVersion": CONNECTOR_PAIRING_SCHEMA,
                "registration": {
                    "status": "already_registered",
                    "workspaceId": auth.get("workspaceId"),
                    "agentId": auth.get("agentId"),
                    "created": False,
                    "scopeDigest": scope_digest,
                },
                "alreadyRegistered": bool(result.get("alreadyRegistered", True)),
                "idempotentReplay": bool(result.get("idempotentReplay", True)),
                "approvedScopes": list(CONNECTOR_V1_REQUESTED_SCOPES),
                "scopeDigest": scope_digest,
                "receipt": _connector_receipt(
                    "confirm_agent_registration",
                    pairing_id,
                    "verified",
                    True,
                    scope_digest=scope_digest,
                ),
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )

    if path == "/api/matm/memory-events/submit" and method == "POST":
        if not _connector_has_scope(auth, "memory:public-safe:submit"):
            return _connector_problem(start_response, "connector_scope_forbidden")
        rate_rejection = _connector_rate_rejection(
            start_response,
            _connector_operation_rate_limited(
                environ,
                "publicSafeSubmit",
                auth.get("connectorCredentialId") or pairing_id,
                store=store,
            ),
        )
        if rate_rejection:
            return rate_rejection
        if not _connector_content_type_is_json(environ):
            return _connector_problem(start_response, "json_content_type_required")
        required_submit_fields = {
            "schemaVersion",
            "payloadClass",
            "title",
            "summary",
            "tags",
        }
        if not isinstance(body, dict) or set(body) != required_submit_fields:
            return _connector_problem(
                start_response, "connector_public_safe_payload_required"
            )
        parsed = body
        if parsed.get("schemaVersion") != CONNECTOR_PAIRING_SCHEMA:
            return _connector_problem(start_response, "schema_version_unsupported")
        title = parsed.get("title")
        summary = parsed.get("summary")
        tags = parsed.get("tags")
        if (
            parsed.get("payloadClass") != "public_safe"
            or not isinstance(title, str)
            or title != title.strip()
            or not 1 <= len(title) <= 200
            or not isinstance(summary, str)
            or summary != summary.strip()
            or not 1 <= len(summary) <= 4000
            or not isinstance(tags, list)
            or len(tags) > 16
            or any(
                not isinstance(tag, str)
                or tag != tag.strip()
                or not 1 <= len(tag) <= 64
                for tag in tags
            )
        ):
            return _connector_problem(
                start_response, "connector_public_safe_payload_required"
            )
        firewall = evaluate_memory_firewall(
            {"title": title, "summary": summary, "tags": tags}
        )
        if not firewall.get("passed"):
            return _connector_problem(
                start_response, "connector_public_safe_payload_required"
            )
        idempotency_key, rejected = _connector_idempotency_or_problem(environ, start_response)
        if rejected:
            return rejected
        storage_idempotency_key = _principal_scoped_idempotency_key(
            auth, idempotency_key
        )
        replay = _idempotency_replay_or_conflict(
            store,
            environ,
            start_response,
            auth.get("workspaceId"),
            storage_idempotency_key,
            "connector-public-safe-memory-submit",
            parsed,
            headers=_CONNECTOR_JSON_HEADERS,
        )
        if replay:
            return replay
        quota_payload = {"title": title, "summary": summary, "tags": tags}
        if not store.has_quota_for(auth.get("workspaceId"), quota_payload):
            return _connector_problem(start_response, "connector_service_unavailable")
        event = store.submit_memory(
            auth.get("workspaceId"),
            auth.get("agentId"),
            "workspace",
            title,
            summary,
            tags,
            "localendpoint-connect",
            "note",
            "connector:%s" % (auth.get("agentId") or "self"),
            1.0,
            auth.get("workspaceId"),
        )
        _mark_idempotent_mutation_started(
            environ,
            store,
            auth.get("workspaceId"),
            storage_idempotency_key,
            "connector-public-safe-memory-submit",
        )
        item = _connector_public_memory_item(event)
        payload = {
            "ok": True,
            "schemaVersion": CONNECTOR_PAIRING_SCHEMA,
            "memory": item,
            "actorBinding": "connector_self",
            "idempotentReplay": False,
            "approvedScopes": list(CONNECTOR_V1_REQUESTED_SCOPES),
            "scopeDigest": scope_digest,
            "receipt": _connector_receipt(
                "public_safe_memory_submit",
                event.get("eventId"),
                "accepted",
                scope_digest=scope_digest,
            ),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        _record_request_idempotency(
            store,
            environ,
            auth.get("workspaceId"),
            storage_idempotency_key,
            "connector-public-safe-memory-submit",
            parsed,
            payload,
            "201 Created",
        )
        return _connector_json(start_response, payload, "201 Created")

    if path == "/api/matm/search" and method == "POST":
        if not _connector_has_scope(auth, "memory:search:read"):
            return _connector_problem(start_response, "connector_scope_forbidden")
        rate_rejection = _connector_rate_rejection(
            start_response,
            _connector_operation_rate_limited(
                environ,
                "search",
                auth.get("connectorCredentialId") or pairing_id,
                store=store,
            ),
        )
        if rate_rejection:
            return rate_rejection
        if _idempotency_key(environ):
            return _connector_problem(start_response, "idempotency_key_not_allowed")
        parsed, rejected = _connector_exact_parsed_body_or_problem(
            environ,
            start_response,
            body,
            ("schemaVersion", "query", "limit"),
        )
        if rejected:
            return rejected
        if parsed.get("schemaVersion") != CONNECTOR_PAIRING_SCHEMA:
            return _connector_problem(start_response, "schema_version_unsupported")
        query_text = parsed.get("query")
        limit = parsed.get("limit")
        if (
            not isinstance(query_text, str)
            or query_text != query_text.strip()
            or not 1 <= len(query_text) <= 1000
            or isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 50
        ):
            return _connector_problem(start_response, "invalid_request")
        items = store.search_memory(auth.get("workspaceId"), query_text, {})
        items = [
            item
            for item in items
            if (
                item.get("scope") == "workspace"
                and item.get("scopeId") == auth.get("workspaceId")
            )
            or (
                item.get("scope") == "agent"
                and item.get("scopeId") == auth.get("agentId")
            )
        ][:limit]
        public_items = [_connector_public_memory_item(item) for item in items]
        return _connector_json(
            start_response,
            {
                "ok": True,
                "schemaVersion": CONNECTOR_PAIRING_SCHEMA,
                "items": public_items,
                "count": len(public_items),
                "limit": limit,
                "readOnly": True,
                "approvedScopes": list(CONNECTOR_V1_REQUESTED_SCOPES),
                "scopeDigest": scope_digest,
                "receipt": _connector_receipt(
                    "memory_search", pairing_id, "verified", scope_digest=scope_digest
                ),
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )

    return _connector_problem(start_response, "connector_scope_forbidden")


def route_protected(environ, start_response, path):
    method = environ["REQUEST_METHOD"]
    token = _token(environ)
    if not token:
        return _anonymous_auth_required(start_response)
    query = _query(environ)
    store = _store()
    connector_auth = (
        store.authenticate_connector_token(token, allow_pending=True) if token else None
    )
    if connector_auth:
        if not connector_auth.get("active"):
            return _connector_problem(start_response, "pending_credential_not_active")
        allowed = {
            ("GET", "/api/matm/workspace"),
            ("POST", "/api/matm/agents/register"),
            ("POST", "/api/matm/memory-events/submit"),
            ("POST", "/api/matm/search"),
        }
        if (method, path) not in allowed:
            return _connector_problem(start_response, "connector_scope_forbidden")
        if method == "POST":
            body, rejected = _connector_body_or_problem(environ, start_response)
            if rejected:
                return rejected
        else:
            body = {}
        return _route_connector_scoped_operation(
            environ, start_response, path, store, connector_auth, body, query
        )
    body = _read_body(environ) if method in ("POST", "PUT", "PATCH") else {}
    if body is None:
        return problem(start_response, "400 Bad Request", "Invalid JSON", "Request body must be JSON.", "invalid_json")
    workspace_id = (body or {}).get("workspaceId") or (body or {}).get("workspace_id") or query.get("workspace_id") or query.get("workspaceId")
    auth = _require_auth(environ, workspace_id)
    if not auth:
        if token and store.authenticate(token):
            return _access_problem(start_response, "insufficient_scope")
        return _access_problem(start_response, "invalid_token")
    if path == "/api/matm/audit-log":
        return _human_problem(start_response, "human_owner_required")
    workspace_id = auth["workspaceId"]
    idem = _idempotency_key(environ)
    if method == "POST" and path in _ROUTE_PROTECTED_POST_MUTATIONS:
        idem, idempotency_problem = _validated_idempotency_key_or_problem(
            environ,
            start_response,
            required=path in _IDEMPOTENCY_REQUIRED_PROTECTED_POST_MUTATIONS,
        )
        if idempotency_problem:
            return idempotency_problem
    if (
        path.startswith("/api/matm/sync/")
        and path != "/api/matm/sync/capabilities"
        and not store.auth_allows_scope(auth, "workspace", workspace_id)
    ):
        # Sync heads do not yet persist project ownership. Keep every protected
        # sync read and write at workspace/company authority until they do. POST
        # requests reach this boundary only after key syntax is validated.
        return _access_problem(start_response, "insufficient_scope")
    client_idem = idem
    idem = _principal_scoped_idempotency_key(auth, client_idem)
    acting_identity_fields = ()
    if method == "POST":
        if path in (
            "/api/matm/projects",
            "/api/matm/external-links",
            "/api/matm/external-links/upsert",
            "/api/matm/knowledge-documents",
            "/api/matm/knowledge-documents/upsert",
            "/api/matm/sync/mutations",
            "/api/matm/memory-events/submit",
        ):
            acting_identity_fields = (body.get("actorAgentId"), body.get("actor_agent_id"))
        elif path in (
            "/api/matm/sync/devices",
            "/api/matm/sync/devices/rotate",
            "/api/matm/sync/devices/revoke",
            "/api/matm/uai-memory/packages",
            "/api/matm/uai-memory/records",
            "/api/matm/uai-memory/edit-claims",
            "/api/matm/uai-memory/edit-claims/heartbeat",
            "/api/matm/uai-memory/edit-claims/complete",
            "/api/matm/uai-memory/edit-claims/release",
            "/api/matm/meeting-rooms/read",
        ):
            acting_identity_fields = (body.get("agentId"), body.get("agent_id"))
        elif path == "/api/matm/review-queue/decide":
            acting_identity_fields = (body.get("reviewerAgentId"), body.get("reviewer_agent_id"))
        elif path == "/api/matm/routing-decisions":
            acting_identity_fields = (
                body.get("coordinatorAgentId"),
                body.get("coordinator_agent_id"),
                body.get("actorAgentId"),
                body.get("actor_agent_id"),
            )
        elif path == "/api/matm/meeting-messages/promote":
            acting_identity_fields = (
                body.get("promotedByAgentId"),
                body.get("promoted_by_agent_id"),
                body.get("actorAgentId"),
                body.get("actor_agent_id"),
            )
        elif path == "/api/matm/meeting-rooms":
            acting_identity_fields = (
                body.get("creatorAgentId"),
                body.get("creator_agent_id"),
                body.get("agentId"),
                body.get("agent_id"),
            )
        elif path in ("/api/matm/meeting-messages", "/api/matm/agent-messages"):
            acting_identity_fields = (body.get("senderAgentId"), body.get("sender_agent_id"))
        elif path == "/api/matm/notifications/ack":
            acting_identity_fields = (body.get("consumerAgentId"), body.get("consumer_agent_id"))
    if acting_identity_fields:
        _, binding_problem = _bound_agent_id_or_problem(auth, start_response, *acting_identity_fields)
        if binding_problem:
            return binding_problem
    if path == "/api/matm/workspace" and method == "GET":
        status = _workspace_status_for_auth(
            store, auth, store.workspace_status(workspace_id)
        )
        operator_summary = _workspace_operator_summary(status)
        _audit_read(
            store,
            workspace_id,
            auth,
            "workspace.read",
            path,
            {"found": bool(status), "hierarchyReady": operator_summary["hierarchyReady"]},
        )
        return json_response(
            start_response,
            {
                "ok": True,
                "workspace": status,
                "operatorSummary": operator_summary,
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )
    if path == "/api/matm/projects" and method == "GET":
        items = store.projects(workspace_id)
        items = [
            item
            for item in items
            if store.auth_allows_scope(auth, "project", item.get("projectId"))
        ]
        _audit_read(store, workspace_id, auth, "projects.read", path, {"count": len(items)})
        return json_response(
            start_response,
            {
                "ok": True,
                "items": items,
                "count": len(items),
                "operatorSummary": {
                    "schemaVersion": "memoryendpoints.projects_operator_summary.v1",
                    "projectCount": len(items),
                    "workspaceId": workspace_id,
                    "valuesRedacted": True,
                    "rawCredentialExposed": False,
                    "rawPayloadExposed": False,
                },
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )
    if path == "/api/matm/projects" and method == "POST":
        actor_agent_id, binding_problem = _bound_agent_id_or_problem(
            auth,
            start_response,
            body.get("actorAgentId"),
            body.get("actor_agent_id"),
        )
        if binding_problem:
            return binding_problem
        if not (body.get("label") or body.get("projectLabel") or body.get("project_label")):
            return problem(start_response, "422 Unprocessable Entity", "Project label required", "Project upsert requires a label.", "project_label_required")
        canonical_project_id = normalize_project_id(
            body.get("projectId") or body.get("project_id"),
            body.get("label")
            or body.get("projectLabel")
            or body.get("project_label"),
        )
        existing_project = next(
            (
                item
                for item in store.projects(workspace_id)
                if item.get("projectId") == canonical_project_id
            ),
            None,
        )
        required_scope = "project" if existing_project else "workspace"
        required_scope_id = canonical_project_id if existing_project else workspace_id
        if not store.auth_allows_scope(auth, required_scope, required_scope_id):
            return _access_problem(start_response, "insufficient_scope")
        replay = _idempotency_replay_or_conflict(
            store,
            environ,
            start_response,
            workspace_id,
            idem,
            "project-upsert",
            body,
        )
        if replay:
            return replay
        if not store.has_quota_for(workspace_id, body):
            return problem(start_response, "413 Payload Too Large", "Workspace quota exceeded", "The workspace does not have enough remaining storage for this project record.", "quota_exceeded")
        project, error = store.upsert_project(
            workspace_id,
            body.get("projectId") or body.get("project_id"),
            body.get("label") or body.get("projectLabel") or body.get("project_label"),
            actor_agent_id,
        )
        if error == "workspace_not_found":
            return problem(start_response, "404 Not Found", "Workspace not found", "No matching workspace exists for the authenticated key.", "workspace_not_found")
        if error == "project_id_conflict":
            return problem(
                start_response,
                "409 Conflict",
                "Project id conflict",
                "That project id is already bound to another workspace and was not changed.",
                "project_id_conflict",
            )
        _mark_idempotent_mutation_started(
            environ, store, workspace_id, idem, "project-upsert"
        )
        project_room = next(
            (
                room
                for room in store.meeting_rooms(workspace_id, actor_agent_id)
                if room.get("scope") == "project"
                and room.get("scopeId") == project.get("projectId")
            ),
            None,
        )
        if not project_room:
            return problem(
                start_response,
                "500 Internal Server Error",
                "Project room unavailable",
                "The project was saved but its canonical project meeting room could not be confirmed.",
                "project_room_not_persisted",
            )
        payload = {
            "ok": True,
            "project": project,
            "persisted": bool(project),
            "canonicalRoomId": project_room.get("roomId"),
            "projectQueryUrl": _protected_query_url("/api/matm/projects", {"workspace_id": workspace_id}),
            "projectMeetingRoomQueryUrl": _protected_query_url(
                "/api/matm/meeting-rooms",
                {
                    "workspace_id": workspace_id,
                    "scope": "project",
                    "scope_id": project.get("projectId"),
                },
            ),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        _record_request_idempotency(store, environ, workspace_id, idem, "project-upsert", body, payload, "201 Created")
        return json_response(start_response, payload, "201 Created")
    if path in ("/api/matm/external-links", "/api/matm/internet-search") and method == "GET":
        filters = _external_link_filters(query)
        active_filters = {key: value for key, value in filters.items() if value}
        items = _authorized_external_link_items(
            store, workspace_id, auth, filters, query.get("limit") or "50"
        )
        _audit_read(
            store,
            workspace_id,
            auth,
            "external_links.search",
            path,
            {"resultCount": len(items), "filterKeys": sorted(active_filters.keys()), "searchMode": "curated_external_links"},
        )
        return json_response(
            start_response,
            {
                "ok": True,
                "schemaVersion": "memoryendpoints.external_link_search.v1",
                "items": items,
                "count": len(items),
                "filters": active_filters,
                "searchMode": "curated_external_links",
                "knowledgeSource": "database_external_links",
                "filesystemLinksIncluded": False,
                "operatorSummary": _external_link_operator_summary(items, active_filters),
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )
    if path in ("/api/matm/external-links", "/api/matm/external-links/upsert") and method == "POST":
        actor_agent_id, binding_problem = _bound_agent_id_or_problem(
            auth,
            start_response,
            body.get("actorAgentId"),
            body.get("actor_agent_id"),
        )
        if binding_problem:
            return binding_problem
        document_id = body.get("knowledgeDocumentId") or body.get("knowledge_document_id") or body.get("documentId") or body.get("document_id") or ""
        if document_id:
            documents = store.knowledge_documents(
                workspace_id, {"documentId": document_id}, 1, False
            )
            if not documents:
                return problem(start_response, "404 Not Found", "Knowledge document not found", "The cited knowledge document does not exist in this workspace.", "knowledge_document_not_found")
            document = documents[0]
            if not store.auth_allows_scope(
                auth, document.get("scope"), document.get("scopeId")
            ):
                return _access_problem(start_response, "insufficient_scope")
        elif not store.auth_allows_scope(auth, "workspace", workspace_id):
            return _access_problem(start_response, "insufficient_scope")
        replay = _idempotency_replay_or_conflict(store, environ, start_response, workspace_id, idem, "external-link-upsert", body)
        if replay:
            return replay
        if not str(body.get("url") or "").strip():
            return problem(start_response, "422 Unprocessable Entity", "URL required", "External link upsert requires an HTTP or HTTPS URL.", "external_url_required")
        if not str(body.get("siteName") or body.get("site_name") or "").strip():
            return problem(start_response, "422 Unprocessable Entity", "Site name required", "External link upsert requires the site's human-readable name.", "external_link_site_name_required")
        if not str(body.get("pageTitle") or body.get("page_title") or body.get("title") or "").strip():
            return problem(start_response, "422 Unprocessable Entity", "Page title required", "External link upsert requires the linked page title.", "external_link_page_title_required")
        if not str(body.get("description") or "").strip():
            return problem(start_response, "422 Unprocessable Entity", "Description required", "External link upsert requires a useful search-result description.", "external_link_description_required")
        if not _listish_values(body.get("keywords") or body.get("keyword") or body.get("tags")):
            return problem(start_response, "422 Unprocessable Entity", "Keywords required", "External link upsert requires at least one search keyword.", "external_link_keywords_required")
        if document_id and not str(body.get("contextDescription") or body.get("context_description") or "").strip():
            return problem(start_response, "422 Unprocessable Entity", "Citation context required", "A link attached to a knowledge document requires contextDescription explaining why the page cites it.", "external_link_context_required")
        if not store.has_quota_for(workspace_id, body):
            return problem(start_response, "413 Payload Too Large", "Workspace quota exceeded", "The workspace does not have enough remaining storage for this external link.", "quota_exceeded")
        link, error = store.upsert_external_link(workspace_id, actor_agent_id, body)
        error_details = {
            "external_url_invalid": ("Invalid URL", "The external link URL is invalid."),
            "external_url_scheme_unsupported": ("Unsupported URL scheme", "External links must use HTTP or HTTPS."),
            "external_url_credentials_forbidden": ("Credentials forbidden", "External link URLs cannot contain credentials."),
            "external_url_host_invalid": ("Invalid host", "The external link host is invalid."),
            "external_url_not_public": ("Public host required", "External links must target a public internet host."),
            "external_url_port_invalid": ("Invalid port", "The external link port is invalid."),
            "external_link_relationship_unsupported": ("Unsupported relationship", "The external link relationship type is unsupported."),
            "external_link_review_status_unsupported": ("Unsupported review status", "The external link review status is unsupported."),
            "external_link_crawl_status_unsupported": ("Unsupported crawl status", "The external link crawl status is unsupported."),
            "external_link_citation_order_invalid": ("Invalid citation order", "citationOrder must be a non-negative integer."),
            "knowledge_document_not_found": ("Knowledge document not found", "The cited knowledge document does not exist in this workspace."),
        }
        if error:
            title, detail = error_details.get(error, ("External link rejected", "The external link could not be stored."))
            status = "404 Not Found" if error == "knowledge_document_not_found" else "422 Unprocessable Entity"
            return problem(start_response, status, title, detail, error)
        _mark_idempotent_mutation_started(
            environ, store, workspace_id, idem, "external-link-upsert"
        )
        confirmation = _external_link_confirmation(store, workspace_id, link, document_id)
        if not confirmation["persisted"]:
            return problem(start_response, "500 Internal Server Error", "External link was not persisted", "The link could not be confirmed by server-side persistence evidence after write.", "external_link_not_persisted")
        payload = {
            "ok": True,
            "link": link,
            "persisted": confirmation["persisted"],
            "visibleInInternetSearch": confirmation["visibleInInternetSearch"],
            "visibleOnKnowledgeDocument": confirmation["visibleOnKnowledgeDocument"],
            "canonicalExternalLinkId": confirmation["canonicalExternalLinkId"],
            "linkQueryUrl": confirmation["linkQueryUrl"],
            "internetSearchQueryUrl": confirmation["internetSearchQueryUrl"],
            "knowledgeDocumentLinksQueryUrl": confirmation["knowledgeDocumentLinksQueryUrl"],
            "confirmation": confirmation,
            "operatorSummary": _external_link_operator_summary([link], {"externalLinkId": link.get("externalLinkId")}),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        _record_request_idempotency(store, environ, workspace_id, idem, "external-link-upsert", body, payload, "201 Created")
        return json_response(start_response, payload, "201 Created")
    if path == "/api/matm/knowledge-tree" and method == "GET":
        filters = _knowledge_filters(query)
        active_filters = {key: value for key, value in filters.items() if value}
        visible_documents = _authorized_scope_items(
            store,
            auth,
            store.knowledge_documents(
                workspace_id, filters, include_text=False, _all=True
            ),
        )
        tree = _knowledge_tree_from_documents(visible_documents)
        _audit_read(
            store,
            workspace_id,
            auth,
            "knowledge_tree.read",
            path,
            {"documentCount": tree.get("documentCount"), "filterKeys": sorted(active_filters.keys())},
        )
        return json_response(
            start_response,
            {
                "ok": True,
                "tree": tree,
                "filters": active_filters,
                "knowledgeSource": "database_search_documents",
                "filesystemDocsIncluded": False,
                "wikiUiRoute": "/knowledge",
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )
    if path == "/api/matm/knowledge-documents" and method == "GET":
        filters = _knowledge_filters(query)
        active_filters = {key: value for key, value in filters.items() if value}
        include_text = _truthy(query.get("include_text") or query.get("includeText"))
        requested_limit = query.get("limit") or "50"
        items = store.knowledge_documents(
            workspace_id, filters, include_text=include_text, _all=True
        )
        items = _authorized_scope_items(store, auth, items)
        items = items[: _parse_limit(requested_limit, 50, 500)]
        operator_summary = _knowledge_operator_summary(items, active_filters)
        _audit_read(
            store,
            workspace_id,
            auth,
            "knowledge_documents.search",
            path,
            {"documentCount": len(items), "filterKeys": sorted(active_filters.keys()), "includeText": include_text},
        )
        return json_response(
            start_response,
            {
                "ok": True,
                "items": items,
                "count": len(items),
                "filters": active_filters,
                "operatorSummary": operator_summary,
                "knowledgeSource": "database_search_documents",
                "filesystemDocsIncluded": False,
                "includeText": include_text,
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )
    if path in ("/api/matm/knowledge-documents", "/api/matm/knowledge-documents/upsert") and method == "POST":
        actor_agent_id, binding_problem = _bound_agent_id_or_problem(
            auth,
            start_response,
            body.get("actorAgentId"),
            body.get("actor_agent_id"),
        )
        if binding_problem:
            return binding_problem
        if not (body.get("title") or "").strip():
            return problem(start_response, "422 Unprocessable Entity", "Title required", "Knowledge document upsert requires a title.", "title_required")
        if not (body.get("description") or ((body.get("metadata") if isinstance(body.get("metadata"), dict) else {}).get("description")) or "").strip():
            return problem(start_response, "422 Unprocessable Entity", "Description required", "Knowledge document upsert requires a short description for wiki browsing and agent recall.", "description_required")
        keywords = _listish_values(body.get("keywords") or body.get("keyword") or body.get("tags") or ((body.get("metadata") if isinstance(body.get("metadata"), dict) else {}).get("keywords")))
        if not keywords:
            return problem(start_response, "422 Unprocessable Entity", "Keywords required", "Knowledge document upsert requires at least one keyword.", "keywords_required")
        if not _knowledge_taxonomy_values(body):
            return problem(start_response, "422 Unprocessable Entity", "Taxonomy paths required", "Knowledge document upsert requires at least one taxonomyPath or taxonomyPaths entry.", "taxonomy_paths_required")
        knowledge_status = str(body.get("knowledgeStatus") or body.get("knowledge_status") or "current").strip().lower().replace("_", "-")
        authority_level = str(body.get("authorityLevel") or body.get("authority_level") or "reviewed").strip().lower().replace("_", "-")
        status_reason = str(body.get("statusReason") or body.get("status_reason") or "").strip()
        superseded_by_document_id = str(body.get("supersededByDocumentId") or body.get("superseded_by_document_id") or "").strip()
        if knowledge_status not in ("current", "proposed", "historical", "superseded", "archived"):
            return problem(start_response, "422 Unprocessable Entity", "Unsupported knowledge status", "knowledgeStatus must be current, proposed, historical, superseded, or archived.", "unsupported_knowledge_status")
        if authority_level not in ("canonical", "reviewed", "reference", "community", "unverified"):
            return problem(start_response, "422 Unprocessable Entity", "Unsupported authority level", "authorityLevel must be canonical, reviewed, reference, community, or unverified.", "unsupported_authority_level")
        if knowledge_status != "current" and not status_reason:
            return problem(start_response, "422 Unprocessable Entity", "Knowledge status reason required", "Non-current knowledge requires statusReason so humans and agents understand why it must not be treated as the active contract.", "knowledge_status_reason_required")
        if len(status_reason) > 1000:
            return problem(start_response, "422 Unprocessable Entity", "Knowledge status reason too long", "statusReason must be at most 1000 characters.", "knowledge_status_reason_too_long")
        if knowledge_status == "superseded" and not superseded_by_document_id:
            return problem(start_response, "422 Unprocessable Entity", "Superseding document required", "Superseded knowledge requires supersededByDocumentId pointing to the current replacement.", "superseded_by_document_id_required")
        if len(superseded_by_document_id) > 96:
            return problem(start_response, "422 Unprocessable Entity", "Superseding document id too long", "supersededByDocumentId must be at most 96 characters.", "superseded_by_document_id_too_long")
        if not ((body.get("searchableText") or body.get("content") or "").strip()):
            return problem(start_response, "422 Unprocessable Entity", "Content required", "Knowledge document upsert requires searchableText or content.", "content_required")
        if not store.has_quota_for(workspace_id, body):
            return problem(start_response, "413 Payload Too Large", "Workspace quota exceeded", "The workspace does not have enough remaining storage for this knowledge document.", "quota_exceeded")
        scoped_payload, scope_error = _resolve_knowledge_scope(store, workspace_id, body)
        if scope_error == "unsupported_scope":
            return problem(start_response, "422 Unprocessable Entity", "Unsupported knowledge scope", "Knowledge documents can only be stored at company, workspace, or project scope.", "unsupported_knowledge_scope")
        if scope_error == "scope_not_authorized":
            return problem(start_response, "403 Forbidden", "Scope not authorized", "The requested scope id is outside the authenticated workspace boundary.", "scope_not_authorized")
        if scope_error == "project_id_required":
            return problem(start_response, "422 Unprocessable Entity", "Project id required", "Project-scoped knowledge documents require projectId or scopeId.", "project_id_required")
        if scope_error == "project_not_found":
            return problem(start_response, "404 Not Found", "Project not found", "Project-scoped knowledge requires an existing project or a projectLabel to create one.", "project_not_found")
        if scope_error:
            return problem(start_response, "422 Unprocessable Entity", "Knowledge scope could not be resolved", "The requested knowledge document scope could not be resolved.", scope_error)
        if not store.auth_allows_scope(
            auth, scoped_payload.get("scope"), scoped_payload.get("scopeId")
        ):
            return _access_problem(start_response, "insufficient_scope")
        replay = _idempotency_replay_or_conflict(store, environ, start_response, workspace_id, idem, "knowledge-document-upsert", body)
        if replay:
            return replay
        document, error = store.upsert_knowledge_document(workspace_id, actor_agent_id, scoped_payload)
        if error == "unsupported_scope":
            return problem(start_response, "422 Unprocessable Entity", "Unsupported knowledge scope", "Knowledge documents can only be stored at company, workspace, or project scope.", "unsupported_knowledge_scope")
        if error == "project_not_found":
            return problem(start_response, "404 Not Found", "Project not found", "Project-scoped knowledge requires an existing project record in this workspace.", "project_not_found")
        if error == "content_required":
            return problem(start_response, "422 Unprocessable Entity", "Content required", "Knowledge document upsert requires searchableText or content.", "content_required")
        if error == "unsupported_knowledge_status":
            return problem(start_response, "422 Unprocessable Entity", "Unsupported knowledge status", "knowledgeStatus must be current, proposed, historical, superseded, or archived.", error)
        if error == "unsupported_authority_level":
            return problem(start_response, "422 Unprocessable Entity", "Unsupported authority level", "authorityLevel must be canonical, reviewed, reference, community, or unverified.", error)
        if error == "knowledge_status_reason_required":
            return problem(start_response, "422 Unprocessable Entity", "Knowledge status reason required", "Non-current knowledge requires statusReason.", error)
        if error == "superseded_by_document_id_required":
            return problem(start_response, "422 Unprocessable Entity", "Superseding document required", "Superseded knowledge requires supersededByDocumentId.", error)
        if error == "superseding_knowledge_document_not_found":
            return problem(start_response, "404 Not Found", "Superseding knowledge document not found", "supersededByDocumentId must identify a knowledge document in the authenticated workspace.", error)
        if error == "knowledge_document_cannot_supersede_itself":
            return problem(start_response, "422 Unprocessable Entity", "Invalid supersession", "A knowledge document cannot supersede itself.", error)
        if error:
            return problem(start_response, "422 Unprocessable Entity", "Knowledge document rejected", "The knowledge document could not be stored.", error)
        _mark_idempotent_mutation_started(
            environ, store, workspace_id, idem, "knowledge-document-upsert"
        )
        confirmation = _knowledge_document_confirmation(store, workspace_id, document)
        if not confirmation["persisted"]:
            return problem(start_response, "500 Internal Server Error", "Knowledge document was not persisted", "The knowledge document could not be confirmed by server-side persistence evidence after write.", "knowledge_document_not_persisted")
        payload = {
            "ok": True,
            "document": document,
            "persisted": confirmation["persisted"],
            "visibleInSearch": confirmation["visibleInSearch"],
            "visibleInWikiTree": confirmation["visibleInWikiTree"],
            "canonicalSearchDocumentId": confirmation["canonicalSearchDocumentId"],
            "canonicalSourceId": confirmation["canonicalSourceId"],
            "documentQueryUrl": confirmation["documentQueryUrl"],
            "searchQueryUrl": confirmation["searchQueryUrl"],
            "treeQueryUrl": confirmation["treeQueryUrl"],
            "wikiUiRoute": "/knowledge",
            "confirmation": confirmation,
            "operatorSummary": _knowledge_operator_summary([document], {"scope": document.get("scope"), "category": document.get("category")}),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        _record_request_idempotency(store, environ, workspace_id, idem, "knowledge-document-upsert", body, payload, "201 Created")
        return json_response(start_response, payload, "201 Created")
    if path == "/api/matm/sync/retention" and method == "GET":
        _audit_read(store, workspace_id, auth, "sync.retention.read", path, {"hardForgetSupported": False})
        return json_response(
            start_response,
            {
                "ok": True,
                "policy": _sync_retention_policy(),
                "capabilities": sync_capabilities(),
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )
    if path == "/api/matm/sync/devices" and method == "POST":
        agent_id, binding_problem = _bound_agent_id_or_problem(
            auth,
            start_response,
            body.get("agentId"),
            body.get("agent_id"),
        )
        if binding_problem:
            return binding_problem
        if not store.auth_allows_scope(auth, "workspace", workspace_id):
            return _access_problem(start_response, "insufficient_scope")
        replay = _idempotency_replay_or_conflict(store, environ, start_response, workspace_id, idem, "sync-device-register", body)
        if replay:
            return replay
        if not store.has_quota_for(workspace_id, body):
            return problem(start_response, "413 Payload Too Large", "Workspace quota exceeded", "The workspace does not have enough remaining storage for this sync device.", "quota_exceeded")
        device = store.register_sync_device(workspace_id, agent_id, body.get("deviceId") or body.get("device_id"), body.get("label"))
        _mark_idempotent_mutation_started(
            environ, store, workspace_id, idem, "sync-device-register"
        )
        visible_device = store.sync_device(workspace_id, device.get("deviceId") if device else "")
        if not visible_device:
            return problem(start_response, "500 Internal Server Error", "Sync device was not persisted", "The sync device could not be confirmed by readback after registration.", "sync_device_not_persisted")
        device = visible_device
        payload = {
            "ok": True,
            "persisted": True,
            "visibleToAgent": True,
            "deviceAuthorityPersisted": True,
            "canonicalWorkspaceId": workspace_id,
            "canonicalDeviceId": device.get("deviceId"),
            "device": device,
            "capabilityRoute": "/api/matm/sync/capabilities",
            "operatorSummary": {
                "schemaVersion": "memoryendpoints.sync_device_operator_summary.v1",
                "action": "register",
                "deviceId": device.get("deviceId"),
                "status": device.get("status"),
                "authorityEpoch": device.get("authorityEpoch"),
                "persisted": True,
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        _record_request_idempotency(store, environ, workspace_id, idem, "sync-device-register", body, payload, "201 Created")
        return json_response(start_response, payload, "201 Created")
    if path in ("/api/matm/sync/devices/rotate", "/api/matm/sync/devices/revoke") and method == "POST":
        operation = "rotate" if path.endswith("/rotate") else "revoke"
        agent_id, binding_problem = _bound_agent_id_or_problem(
            auth,
            start_response,
            body.get("agentId"),
            body.get("agent_id"),
        )
        if binding_problem:
            return binding_problem
        if not store.auth_allows_scope(auth, "workspace", workspace_id):
            return _access_problem(start_response, "insufficient_scope")
        device_id = body.get("deviceId") or body.get("device_id")
        if not device_id:
            return problem(start_response, "422 Unprocessable Entity", "Device id required", "Sync device authority changes require deviceId.", "device_id_required")
        requested_device = store.sync_device(workspace_id, device_id)
        if not requested_device:
            return problem(start_response, "404 Not Found", "Sync device not found", "No matching sync device exists for this workspace.", "sync_device_not_found")
        if auth.get("credentialType") == "agent" and requested_device.get("agentId") != agent_id:
            return problem(start_response, "404 Not Found", "Sync device not found", "No matching sync device exists for the authenticated agent.", "sync_device_not_found")
        replay = _idempotency_replay_or_conflict(store, environ, start_response, workspace_id, idem, "sync-device-" + operation, body)
        if replay:
            return replay
        if operation == "rotate":
            device, error = store.rotate_sync_device(workspace_id, device_id, agent_id)
        else:
            device, error = store.revoke_sync_device(workspace_id, device_id, agent_id)
        if error == "device_not_found":
            return problem(start_response, "404 Not Found", "Sync device not found", "No matching sync device exists for this workspace.", "sync_device_not_found")
        if error == "device_revoked":
            return problem(start_response, "409 Conflict", "Sync device revoked", "Revoked devices cannot be rotated.", "sync_device_revoked")
        _mark_idempotent_mutation_started(
            environ, store, workspace_id, idem, "sync-device-" + operation
        )
        visible_device = store.sync_device(workspace_id, device.get("deviceId") if device else "")
        if not visible_device:
            return problem(start_response, "500 Internal Server Error", "Sync device was not persisted", "The sync device authority change could not be confirmed by readback.", "sync_device_not_persisted")
        device = visible_device
        payload = {
            "ok": True,
            "persisted": True,
            "visibleToAgent": True,
            "deviceAuthorityPersisted": True,
            "canonicalWorkspaceId": workspace_id,
            "canonicalDeviceId": device.get("deviceId"),
            "device": device,
            "capabilityRoute": "/api/matm/sync/capabilities",
            "operatorSummary": {
                "schemaVersion": "memoryendpoints.sync_device_operator_summary.v1",
                "action": operation,
                "deviceId": device.get("deviceId"),
                "status": device.get("status"),
                "authorityEpoch": device.get("authorityEpoch"),
                "persisted": True,
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        _record_request_idempotency(store, environ, workspace_id, idem, "sync-device-" + operation, body, payload, "200 OK")
        return json_response(start_response, payload)
    if path == "/api/matm/sync/mutations" and method == "POST":
        if not idem:
            return problem(start_response, "422 Unprocessable Entity", "Idempotency key required", "Sync mutations require Idempotency-Key so offline clients can recover receipts after timeouts.", "idempotency_key_required")
        actor_agent_id, binding_problem = _bound_agent_id_or_problem(
            auth,
            start_response,
            body.get("actorAgentId"),
            body.get("actor_agent_id"),
        )
        if binding_problem:
            return binding_problem
        requested_scope = str(body.get("scope") or "workspace").strip().lower()
        requested_scope_id = body.get("scopeId") or body.get("scope_id") or workspace_id
        if not store.auth_allows_scope(
            auth, requested_scope, requested_scope_id
        ):
            return _access_problem(start_response, "insufficient_scope")
        requested_device_id = body.get("deviceId") or body.get("device_id") or ""
        requested_device = (
            store.sync_device(workspace_id, requested_device_id)
            if requested_device_id
            else None
        )
        if (
            requested_device
            and auth.get("credentialType") == "agent"
            and requested_device.get("agentId") != actor_agent_id
        ):
            return problem(start_response, "404 Not Found", "Sync device not found", "No matching sync device exists for the authenticated agent.", "sync_device_not_found")
        replay = _idempotency_replay_or_conflict(store, environ, start_response, workspace_id, idem, "sync-mutation", body)
        if replay:
            return replay
        if len(body.get("summary") or "") > 4000:
            return problem(start_response, "422 Unprocessable Entity", "Summary too long", "Sync mutation summaries must be at most 4000 characters.", "summary_too_long")
        if not store.has_quota_for(workspace_id, body):
            return problem(start_response, "413 Payload Too Large", "Workspace quota exceeded", "The workspace does not have enough remaining storage for this sync mutation.", "quota_exceeded")
        payload, http_status = store.submit_sync_mutation(
            workspace_id, actor_agent_id, body, client_idem
        )
        _mark_idempotent_mutation_started(
            environ, store, workspace_id, idem, "sync-mutation"
        )
        payload["operatorSummary"] = _sync_operator_summary("mutation", payload)
        payload["receiptQueryUrl"] = _sync_query_url("/api/matm/sync/receipts", workspace_id, {"receipt_id": (payload.get("receipt") or {}).get("receiptId")})
        payload["changesQueryUrl"] = _sync_query_url("/api/matm/sync/changes", workspace_id, {"after_sequence": max(0, int(payload.get("serverSequence") or 0) - 1)})
        payload["headsQueryUrl"] = _sync_query_url("/api/matm/sync/heads", workspace_id, {"logical_memory_id": (payload.get("receipt") or {}).get("logicalMemoryId")})
        payload["capabilityRoute"] = "/api/matm/sync/capabilities"
        confirmation = _sync_mutation_confirmation(store, workspace_id, payload)
        if not confirmation["persisted"]:
            return problem(start_response, "500 Internal Server Error", "Sync mutation was not persisted", "The sync mutation could not be confirmed in receipt, changes, and head readback after write.", "sync_mutation_not_persisted")
        payload["confirmation"] = confirmation
        _record_request_idempotency(store, environ, workspace_id, idem, "sync-mutation", body, payload, http_status)
        return json_response(start_response, payload, http_status)
    if path == "/api/matm/sync/receipts" and method == "GET":
        lookup_key = _idempotency_key(environ) or query.get("idempotency_key") or query.get("idempotencyKey") or ""
        receipt_id = query.get("receipt_id") or query.get("receiptId") or ""
        if not lookup_key and not receipt_id:
            return problem(start_response, "422 Unprocessable Entity", "Receipt lookup key required", "Provide Idempotency-Key, idempotency_key, or receipt_id.", "sync_receipt_lookup_required")
        receipt = store.sync_receipt(workspace_id, lookup_key, receipt_id)
        if not receipt:
            return problem(start_response, "404 Not Found", "Sync receipt not found", "No matching sync mutation receipt exists for this workspace.", "sync_receipt_not_found")
        _audit_read(store, workspace_id, auth, "sync.receipt.read", path, {"receiptStatus": receipt.get("status"), "idempotencyKeyProvided": bool(lookup_key)})
        return json_response(
            start_response,
            {
                "ok": True,
                "receipt": receipt,
                "operatorSummary": _sync_operator_summary("receipt", {"receipt": receipt, "persisted": True}),
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )
    if path == "/api/matm/sync/changes" and method == "GET":
        changes = store.sync_changes(
            workspace_id,
            query.get("after_sequence") or query.get("afterSequence") or 0,
            query.get("limit") or 50,
            query.get("logical_memory_id") or query.get("logicalMemoryId") or "",
        )
        _audit_read(store, workspace_id, auth, "sync.changes.read", path, {"count": changes["count"], "indexedThroughSequence": changes["indexedThroughSequence"]})
        return json_response(start_response, {"ok": True, "changes": changes, "valuesRedacted": True, "rawCredentialExposed": False, "rawPayloadExposed": False})
    if path == "/api/matm/sync/heads" and method == "GET":
        logical_memory_id = query.get("logical_memory_id") or query.get("logicalMemoryId") or ""
        heads = store.sync_heads(workspace_id, logical_memory_id)
        _audit_read(store, workspace_id, auth, "sync.heads.read", path, {"count": len(heads), "logicalMemoryIdProvided": bool(logical_memory_id)})
        return json_response(
            start_response,
            {
                "ok": True,
                "items": heads,
                "count": len(heads),
                "filters": {"logicalMemoryId": logical_memory_id} if logical_memory_id else {},
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )
    if path == "/api/matm/agents/register" and method == "POST":
        if auth.get("credentialType") == "company_master":
            expected_fields = {"workspaceId", "agentId", "displayName"}
            if set(body) != expected_fields:
                return problem(
                    start_response,
                    "422 Unprocessable Entity",
                    "Exact compatibility registration required",
                    "Company-master compatibility registration accepts only workspaceId, agentId, and displayName.",
                    "localendpoint_registration_invalid",
                )
            if body.get("workspaceId") != workspace_id:
                return _access_problem(start_response, "workspace_not_found")
            agent_id = body.get("agentId")
            if agent_id != CONNECTOR_AGENT_ID:
                return problem(
                    start_response,
                    "409 Conflict",
                    "Invite redemption required",
                    "Only the exact deprecated LocalEndpoint connector identity may use this transition; every other agent identity requires an approved one-time invite.",
                    "registration_requires_invite",
                )
            operation = "deprecated-localendpoint-agent-registration"
            replay = (
                _idempotency_replay_or_conflict(
                    store,
                    environ,
                    start_response,
                    workspace_id,
                    idem,
                    operation,
                    body,
                )
                if idem
                else None
            )
            if replay:
                return replay
            agent = store.register_agent(
                workspace_id,
                CONNECTOR_AGENT_ID,
                CONNECTOR_AGENT_DISPLAY_NAME,
            )
            if idem:
                _mark_idempotent_mutation_started(
                    environ, store, workspace_id, idem, operation
                )
            payload = {
                "ok": True,
                "agent": agent,
                "operatorSummary": _agent_registration_operator_summary(agent),
                "compatibilityTransition": {
                    "schemaVersion": "memoryendpoints.localendpoint_registration_transition.v1",
                    "status": "deprecated",
                    "canonicalAgentId": CONNECTOR_AGENT_ID,
                    "idempotent": True,
                    "tokenIssued": False,
                    "broaderAuthorityGranted": False,
                    "migrateTo": "memoryendpoints.connector_pairing.v1",
                    "discoveryRoute": "/.well-known/memoryendpoints-connector",
                },
                "idempotentReplay": False,
                "idempotencyKeyExposed": False,
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            }
            if idem:
                _record_request_idempotency(
                    store,
                    environ,
                    workspace_id,
                    idem,
                    operation,
                    body,
                    payload,
                    "201 Created",
                )
            return json_response(start_response, payload, "201 Created")
        return problem(
            start_response,
            "409 Conflict",
            "Invite redemption required",
            "Agent identities are registered only by redeeming an approved one-time invite.",
            "registration_requires_invite",
        )
    if path == "/api/matm/uai-memory/packages" and method == "GET":
        agent_id = query.get("agent_id") or query.get("agentId") or ""
        if auth.get("credentialType") == "agent":
            agent_id, binding_problem = _bound_agent_id_or_problem(
                auth,
                start_response,
                query.get("agent_id"),
                query.get("agentId"),
            )
            if binding_problem:
                return binding_problem
        package_id = query.get("package_id") or query.get("packageId") or ""
        items = store.uai_packages(workspace_id, agent_id, package_id)
        _audit_read(store, workspace_id, auth, "uai_packages.read", path, {"count": len(items), "agentId": agent_id})
        return json_response(
            start_response,
            {
                "ok": True,
                "schemaVersion": "memoryendpoints.virtual_uai_packages.v1",
                "items": items,
                "count": len(items),
                "filters": {key: value for key, value in {"agentId": agent_id, "packageId": package_id}.items() if value},
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )
    if path == "/api/matm/uai-memory/packages" and method == "POST":
        if not idem:
            return problem(start_response, "422 Unprocessable Entity", "Idempotency key required", "Virtual UAIX package creation requires Idempotency-Key for exact browser retries.", "idempotency_key_required")
        agent_id, binding_problem = _bound_agent_id_or_problem(
            auth,
            start_response,
            body.get("agentId"),
            body.get("agent_id"),
        )
        if binding_problem:
            return binding_problem
        if "workspaceId" not in body and "workspace_id" not in body:
            return problem(start_response, "422 Unprocessable Entity", "Workspace id required", "Virtual UAIX package creation requires workspaceId in the authenticated request body.", "workspace_id_required")
        if "clientClass" not in body and "client_class" not in body:
            return problem(start_response, "422 Unprocessable Entity", "Client class required", "Set clientClass to accountless_browser_ai for the full virtual-package exception.", "client_class_required")
        if "localFilesystemAvailable" not in body and "local_filesystem_available" not in body:
            return problem(start_response, "422 Unprocessable Entity", "Filesystem capability required", "Set localFilesystemAvailable explicitly so the exception boundary can be evaluated.", "local_filesystem_available_required")
        local_filesystem_available = body.get("localFilesystemAvailable") if "localFilesystemAvailable" in body else body.get("local_filesystem_available")
        if not isinstance(local_filesystem_available, bool):
            return problem(start_response, "422 Unprocessable Entity", "Filesystem capability invalid", "localFilesystemAvailable must be a JSON boolean.", "local_filesystem_available_invalid")
        replay = _idempotency_replay_or_conflict(store, environ, start_response, workspace_id, idem, "uai-package-create", body)
        if replay:
            return replay
        package, created, error, details = store.create_uai_package(
            workspace_id,
            agent_id,
            body.get("clientClass") or body.get("client_class"),
            local_filesystem_available,
        )
        if error:
            return _uai_error_response(start_response, error, details)
        _mark_idempotent_mutation_started(
            environ, store, workspace_id, idem, "uai-package-create"
        )
        package_id = package.get("packageId")
        payload = {
            "ok": True,
            "package": package,
            "created": bool(created),
            "persisted": True,
            "visibleToSender": True,
            "canonicalPackageId": package_id,
            "packageQueryUrl": _protected_query_url("/api/matm/uai-memory/packages", {"workspace_id": workspace_id, "agent_id": agent_id, "package_id": package_id}),
            "recordQueryUrl": _protected_query_url("/api/matm/uai-memory/records", {"workspace_id": workspace_id, "agent_id": agent_id, "package_id": package_id}),
            "startupQueryUrl": _protected_query_url("/api/matm/uai-memory/startup", {"workspace_id": workspace_id, "agent_id": agent_id, "package_id": package_id}),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        http_status = "201 Created" if created else "200 OK"
        _record_request_idempotency(store, environ, workspace_id, idem, "uai-package-create", body, payload, http_status)
        return json_response(start_response, payload, http_status)
    if path == "/api/matm/uai-memory/records" and method == "GET":
        agent_id = query.get("agent_id") or query.get("agentId") or ""
        if auth.get("credentialType") == "agent":
            agent_id, binding_problem = _bound_agent_id_or_problem(
                auth,
                start_response,
                query.get("agent_id"),
                query.get("agentId"),
            )
            if binding_problem:
                return binding_problem
        package_id = query.get("package_id") or query.get("packageId") or ""
        logical_path = query.get("logical_path") or query.get("logicalPath") or ""
        record_id = query.get("record_id") or query.get("recordId") or ""
        include_content = str(query.get("include_content") or query.get("includeContent") or "true").lower() not in ("0", "false", "no")
        include_history = str(query.get("include_history") or query.get("includeHistory") or "false").lower() in ("1", "true", "yes")
        items = store.uai_records(workspace_id, agent_id, package_id, logical_path, include_content)
        if record_id:
            items = [item for item in items if item.get("recordId") == record_id]
        revisions = store.uai_record_revisions(workspace_id, record_id, include_content) if include_history and record_id else []
        _audit_read(store, workspace_id, auth, "uai_records.read", path, {"count": len(items), "agentId": agent_id, "packageId": package_id, "includeHistory": include_history})
        return json_response(
            start_response,
            {
                "ok": True,
                "schemaVersion": "memoryendpoints.virtual_uai_records.v1",
                "items": items,
                "count": len(items),
                "revisions": revisions,
                "revisionCount": len(revisions),
                "protectedContentIncluded": include_content,
                "filters": {key: value for key, value in {"agentId": agent_id, "packageId": package_id, "logicalPath": logical_path, "recordId": record_id}.items() if value},
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )
    if path == "/api/matm/uai-memory/records" and method == "POST":
        if not idem:
            return problem(start_response, "422 Unprocessable Entity", "Idempotency key required", "Virtual UAIX record writes require Idempotency-Key for exact browser retries.", "idempotency_key_required")
        agent_id, binding_problem = _bound_agent_id_or_problem(
            auth,
            start_response,
            body.get("agentId"),
            body.get("agent_id"),
        )
        if binding_problem:
            return binding_problem
        package_id = body.get("packageId") or body.get("package_id")
        logical_path = body.get("logicalPath") or body.get("logical_path")
        content = body.get("content")
        if not package_id:
            return _uai_error_response(start_response, "uai_package_not_found")
        if not logical_path:
            return _uai_error_response(start_response, "unsupported_uai_logical_path")
        if content is None:
            return _uai_error_response(start_response, "uai_content_required")
        if not store.uai_packages(workspace_id, agent_id, package_id):
            return _uai_error_response(start_response, "uai_package_not_found")
        replay = _idempotency_replay_or_conflict(store, environ, start_response, workspace_id, idem, "uai-record-upsert", body)
        if replay:
            return replay
        result, error, details = store.upsert_uai_record(
            workspace_id,
            agent_id,
            package_id,
            logical_path,
            body.get("title"),
            content,
            body.get("expectedRevision") if "expectedRevision" in body else body.get("expected_revision"),
        )
        if error:
            return _uai_error_response(start_response, error, details)
        _mark_idempotent_mutation_started(
            environ, store, workspace_id, idem, "uai-record-upsert"
        )
        record = result["record"]
        readback = store.uai_records(workspace_id, agent_id, package_id, record.get("logicalPath"), True)
        visible = any(
            item.get("recordId") == record.get("recordId")
            and item.get("revision") == record.get("revision")
            and item.get("contentHash") == record.get("contentHash")
            for item in readback
        )
        if not visible:
            return problem(start_response, "500 Internal Server Error", "Virtual UAIX record was not confirmed", "The write could not be confirmed by exact protected readback.", "uai_record_not_persisted")
        payload = {
            "ok": True,
            "record": record,
            "package": result["package"],
            "created": result["created"],
            "changed": result["changed"],
            "persisted": True,
            "visibleToSender": True,
            "canonicalPackageId": package_id,
            "canonicalRecordId": record.get("recordId"),
            "logicalPath": record.get("logicalPath"),
            "revision": record.get("revision"),
            "contentHash": record.get("contentHash"),
            "packageQueryUrl": _protected_query_url("/api/matm/uai-memory/packages", {"workspace_id": workspace_id, "agent_id": agent_id, "package_id": package_id}),
            "recordQueryUrl": _protected_query_url("/api/matm/uai-memory/records", {"workspace_id": workspace_id, "agent_id": agent_id, "package_id": package_id, "logical_path": record.get("logicalPath"), "record_id": record.get("recordId")}),
            "startupQueryUrl": _protected_query_url("/api/matm/uai-memory/startup", {"workspace_id": workspace_id, "agent_id": agent_id, "package_id": package_id}),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        http_status = "201 Created" if result["created"] else "200 OK"
        _record_request_idempotency(store, environ, workspace_id, idem, "uai-record-upsert", body, payload, http_status)
        return json_response(start_response, payload, http_status)
    if path == "/api/matm/uai-memory/startup" and method == "GET":
        agent_id = query.get("agent_id") or query.get("agentId") or ""
        if auth.get("credentialType") == "agent":
            agent_id, binding_problem = _bound_agent_id_or_problem(
                auth,
                start_response,
                query.get("agent_id"),
                query.get("agentId"),
            )
            if binding_problem:
                return binding_problem
        package_id = query.get("package_id") or query.get("packageId") or ""
        if not agent_id:
            return _uai_error_response(start_response, "registered_agent_required")
        startup, error = store.uai_startup(workspace_id, agent_id, package_id or None)
        if error:
            return _uai_error_response(start_response, error)
        _audit_read(store, workspace_id, auth, "uai_startup.read", path, {"agentId": agent_id, "packageId": startup["package"].get("packageId"), "count": startup["recordCount"], "readyForStartup": startup["readyForStartup"]})
        return json_response(start_response, {"ok": True, "startup": startup, "valuesRedacted": True, "rawCredentialExposed": False, "rawPayloadExposed": False})
    if path == "/api/matm/uai-memory/file-heads" and method == "GET":
        project_id = query.get("project_id") or query.get("projectId") or ""
        logical_path = query.get("logical_path") or query.get("logicalPath") or ""
        items = store.uai_collaboration_heads(workspace_id, project_id, logical_path)
        items = [
            item
            for item in items
            if store.auth_allows_scope(auth, "project", item.get("projectId"))
        ]
        _audit_read(store, workspace_id, auth, "uai_file_heads.read", path, {"count": len(items), "projectId": project_id, "logicalPath": logical_path})
        return json_response(start_response, {"ok": True, "schemaVersion": "memoryendpoints.uai_collaboration_heads.v1", "items": items, "count": len(items), "localContentStored": False, "valuesRedacted": True, "rawCredentialExposed": False, "rawPayloadExposed": False})
    if path == "/api/matm/uai-memory/edit-claims" and method == "GET":
        filters = {
            "projectId": query.get("project_id") or query.get("projectId") or "",
            "agentId": query.get("agent_id") or query.get("agentId") or "",
            "logicalPath": query.get("logical_path") or query.get("logicalPath") or "",
            "status": query.get("status") or "",
        }
        if auth.get("credentialType") == "agent":
            filters["agentId"], binding_problem = _bound_agent_id_or_problem(
                auth,
                start_response,
                query.get("agent_id"),
                query.get("agentId"),
            )
            if binding_problem:
                return binding_problem
        items = store.uai_edit_claims(workspace_id, filters["projectId"], filters["agentId"], filters["logicalPath"], filters["status"])
        items = [
            item
            for item in items
            if store.auth_allows_scope(auth, "project", item.get("projectId"))
        ]
        _audit_read(store, workspace_id, auth, "uai_edit_claims.read", path, {"count": len(items), "projectId": filters["projectId"], "agentId": filters["agentId"]})
        return json_response(start_response, {"ok": True, "schemaVersion": "memoryendpoints.uai_edit_claims.v1", "items": items, "count": len(items), "filters": {key: value for key, value in filters.items() if value}, "localContentStored": False, "valuesRedacted": True, "rawCredentialExposed": False, "rawPayloadExposed": False})
    if path == "/api/matm/uai-memory/edit-claims" and method == "POST":
        if not idem:
            return problem(start_response, "422 Unprocessable Entity", "Idempotency key required", "Local .uai edit-claim acquisition requires Idempotency-Key.", "idempotency_key_required")
        project_id = body.get("projectId") or body.get("project_id")
        agent_id, binding_problem = _bound_agent_id_or_problem(
            auth,
            start_response,
            body.get("agentId"),
            body.get("agent_id"),
        )
        if binding_problem:
            return binding_problem
        if not store.auth_allows_scope(auth, "project", project_id):
            return _access_problem(start_response, "insufficient_scope")
        replay = _idempotency_replay_or_conflict(store, environ, start_response, workspace_id, idem, "uai-edit-claim-acquire", body)
        if replay:
            return replay
        result, error, details = store.acquire_uai_edit_claim(
            workspace_id,
            project_id,
            agent_id,
            body.get("logicalPath") or body.get("logical_path"),
            body.get("baseContentHash") or body.get("base_content_hash"),
            body.get("intentSummary") or body.get("intent_summary"),
            body.get("leaseSeconds") or body.get("lease_seconds"),
        )
        if error:
            return _uai_error_response(start_response, error, details)
        _mark_idempotent_mutation_started(
            environ, store, workspace_id, idem, "uai-edit-claim-acquire"
        )
        claim = result["claim"]
        head = result["head"]
        visible_to_sender = _uai_claim_readback_visible(store, workspace_id, claim, head)
        if not visible_to_sender:
            return problem(start_response, "500 Internal Server Error", "Edit claim was not confirmed", "The acquired claim and canonical head could not be confirmed by exact protected readback.", "uai_edit_claim_not_persisted")
        payload = {
            "ok": True,
            "claim": claim,
            "head": head,
            "persisted": True,
            "visibleToSender": True,
            "claimAcquired": True,
            "canonicalClaimId": claim.get("claimId"),
            "canonicalHeadId": head.get("headId"),
            "headRevision": head.get("revision"),
            "claimQueryUrl": _protected_query_url("/api/matm/uai-memory/edit-claims", {"workspace_id": workspace_id, "project_id": project_id, "logical_path": claim.get("logicalPath"), "status": "active"}),
            "headQueryUrl": _protected_query_url("/api/matm/uai-memory/file-heads", {"workspace_id": workspace_id, "project_id": project_id, "logical_path": claim.get("logicalPath")}),
            "projectMeetingRoomQueryUrl": _protected_query_url("/api/matm/meeting-rooms", {"workspace_id": workspace_id, "agent_id": agent_id, "scope": "project", "scope_id": project_id}),
            "localContentStored": False,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        _record_request_idempotency(store, environ, workspace_id, idem, "uai-edit-claim-acquire", body, payload, "201 Created")
        return json_response(start_response, payload, "201 Created")
    if path in ("/api/matm/uai-memory/edit-claims/heartbeat", "/api/matm/uai-memory/edit-claims/complete", "/api/matm/uai-memory/edit-claims/release") and method == "POST":
        if not idem:
            return problem(start_response, "422 Unprocessable Entity", "Idempotency key required", "Local .uai edit-claim changes require Idempotency-Key.", "idempotency_key_required")
        operation = path.rsplit("/", 1)[-1]
        idem_operation = "uai-edit-claim-%s" % operation
        agent_id, binding_problem = _bound_agent_id_or_problem(
            auth,
            start_response,
            body.get("agentId"),
            body.get("agent_id"),
        )
        if binding_problem:
            return binding_problem
        claim_id = body.get("claimId") or body.get("claim_id")
        claim_candidate = next(
            (
                item
                for item in store.uai_edit_claims(workspace_id, "", "", "", "")
                if item.get("claimId") == claim_id
            ),
            None,
        )
        if (
            not claim_candidate
            or claim_candidate.get("agentId") != agent_id
            or not store.auth_allows_scope(
                auth, "project", claim_candidate.get("projectId")
            )
        ):
            return _uai_error_response(start_response, "uai_edit_claim_not_found")
        replay = _idempotency_replay_or_conflict(store, environ, start_response, workspace_id, idem, idem_operation, body)
        if replay:
            return replay
        if operation == "heartbeat":
            result, error, details = store.heartbeat_uai_edit_claim(workspace_id, agent_id, claim_id, body.get("leaseSeconds") or body.get("lease_seconds"))
        elif operation == "complete":
            result, error, details = store.complete_uai_edit_claim(workspace_id, agent_id, claim_id, body.get("newContentHash") or body.get("new_content_hash"), body.get("completionSummary") or body.get("completion_summary"))
        else:
            result, error, details = store.release_uai_edit_claim(workspace_id, agent_id, claim_id, body.get("releaseSummary") or body.get("release_summary"))
        if error:
            return _uai_error_response(start_response, error, details)
        _mark_idempotent_mutation_started(
            environ, store, workspace_id, idem, idem_operation
        )
        claim = result["claim"]
        head = result["head"]
        visible_to_sender = _uai_claim_readback_visible(store, workspace_id, claim, head)
        if not visible_to_sender:
            return problem(start_response, "500 Internal Server Error", "Edit claim change was not confirmed", "The claim change and canonical head could not be confirmed by exact protected readback.", "uai_edit_claim_not_persisted")
        payload = {
            "ok": True,
            "operation": operation,
            "claim": claim,
            "head": head,
            "persisted": True,
            "visibleToSender": True,
            "canonicalClaimId": claim.get("claimId"),
            "canonicalHeadId": head.get("headId"),
            "headRevision": head.get("revision"),
            "claimQueryUrl": _protected_query_url("/api/matm/uai-memory/edit-claims", {"workspace_id": workspace_id, "project_id": claim.get("projectId"), "logical_path": claim.get("logicalPath")}),
            "headQueryUrl": _protected_query_url("/api/matm/uai-memory/file-heads", {"workspace_id": workspace_id, "project_id": claim.get("projectId"), "logical_path": claim.get("logicalPath")}),
            "projectMeetingRoomQueryUrl": _protected_query_url("/api/matm/meeting-rooms", {"workspace_id": workspace_id, "agent_id": agent_id, "scope": "project", "scope_id": claim.get("projectId")}),
            "localContentStored": False,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        _record_request_idempotency(store, environ, workspace_id, idem, idem_operation, body, payload, "200 OK")
        return json_response(start_response, payload)
    if path == "/api/matm/memory-events/submit" and method == "POST":
        requested_scope = (body.get("scope") or "workspace").strip().lower()
        requested_scope_id = body.get("scopeId") or body.get("scope_id") or workspace_id
        if not store.auth_allows_scope(auth, requested_scope, requested_scope_id):
            return _access_problem(start_response, "insufficient_scope")
        summary = body.get("summary") or ""
        title = body.get("title") or "Untitled memory"
        actor_agent_id, binding_problem = _bound_agent_id_or_problem(
            auth,
            start_response,
            body.get("actorAgentId"),
            body.get("actor_agent_id"),
        )
        if binding_problem:
            return binding_problem
        if not summary.strip():
            return problem(start_response, "422 Unprocessable Entity", "Summary required", "Memory events require a public-safe summary.", "summary_required")
        if len(summary) > 4000:
            return problem(start_response, "422 Unprocessable Entity", "Summary too long", "Memory event summaries must be at most 4000 characters.", "summary_too_long")
        if not store.has_quota_for(workspace_id, body):
            return problem(start_response, "413 Payload Too Large", "Workspace quota exceeded", "The workspace does not have enough remaining storage for this memory event.", "quota_exceeded")
        replay = _idempotency_replay_or_conflict(store, environ, start_response, workspace_id, idem, "memory-submit", body)
        if replay:
            return replay
        event = store.submit_memory(
            workspace_id,
            actor_agent_id,
            requested_scope,
            title,
            summary,
            body.get("tags") or [],
            body.get("source"),
            body.get("memoryType") or body.get("memory_type"),
            body.get("subject"),
            body.get("confidence"),
            requested_scope_id,
        )
        _mark_idempotent_mutation_started(
            environ, store, workspace_id, idem, "memory-submit"
        )
        submission = _memory_submission_metadata(event)
        confirmation = _memory_submission_confirmation(store, workspace_id, event)
        if not confirmation["persisted"]:
            return problem(start_response, "500 Internal Server Error", "Memory was not persisted", "The memory event could not be confirmed by server-side persistence evidence after write.", "memory_not_persisted")
        payload = {
            "ok": True,
            "event": event,
            "submission": submission,
            "operatorSummary": _memory_submission_operator_summary(event),
            "persisted": confirmation["persisted"],
            "visibleInSearch": confirmation["visibleInSearch"],
            "visibleInReviewQueue": confirmation["visibleInReviewQueue"],
            "canonicalMemoryEventId": confirmation["canonicalMemoryEventId"],
            "reviewId": confirmation["reviewId"],
            "memoryQueryUrl": confirmation["memoryQueryUrl"],
            "reviewQueueUrl": confirmation["reviewQueueUrl"],
            "confirmation": confirmation,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        _record_request_idempotency(store, environ, workspace_id, idem, "memory-submit", body, payload, "201 Created")
        return json_response(start_response, payload, "201 Created")
    if path == "/api/matm/review-queue" and method == "GET":
        status_filter = query.get("status") or ""
        review_filters = {
            "sourcePrefix": query.get("source_prefix") or query.get("sourcePrefix") or "",
            "tag": query.get("tag") or "",
            "memoryType": query.get("memory_type") or query.get("memoryType") or "",
            "actorAgentId": query.get("actor_agent_id") or query.get("actorAgentId") or "",
        }
        active_review_filters = {key: value for key, value in review_filters.items() if value}
        memory_items = [
            item
            for item in store.memory_events_for_review(workspace_id)
            if store.auth_allows_scope(auth, item.get("scope"), item.get("scopeId"))
        ]
        memory_by_id = {item.get("eventId"): item for item in memory_items if item.get("eventId")}
        all_review_items = [
            item
            for item in store.review_queue(workspace_id, "")
            if item.get("memoryEventId") in memory_by_id
            and _review_matches_memory_filters(item, memory_by_id, active_review_filters)
        ]
        items = [
            item
            for item in all_review_items
            if not status_filter or item.get("status") == status_filter
        ]
        public_items = [_review_public_item(item, memory_by_id) for item in items]
        status_counts = _review_status_counts(all_review_items)
        filters = dict(active_review_filters)
        if status_filter:
            filters["status"] = status_filter
        operator_summary = _review_queue_operator_summary(items, all_review_items, filters, status_counts, memory_items)
        _audit_read(
            store,
            workspace_id,
            auth,
            "review_queue.read",
            path,
            {
                "statusFilter": status_filter,
                "count": len(items),
                "filters": filters,
                "filterKeys": sorted(filters.keys()),
                "reviewStatusCounts": status_counts,
                "firewallDecisionCounts": operator_summary["firewallDecisionCounts"],
                "detectedThreatCount": operator_summary["detectedThreatCount"],
                "longTermMemoryReviews": operator_summary.get("longTermMemoryReviews"),
            },
        )
        return json_response(
            start_response,
            {
                "ok": True,
                "items": public_items,
                "count": len(items),
                "filters": filters,
                "statusCounts": status_counts,
                "operatorSummary": operator_summary,
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
                "promotionRoute": "/api/matm/review-queue/decide",
            },
        )
    if path == "/api/matm/review-queue/decide" and method == "POST":
        review_id = body.get("reviewId") or body.get("review_id")
        visible_memory_by_id = {
            item.get("eventId"): item
            for item in store.memory_events_for_review(workspace_id)
            if item.get("eventId") and store.auth_allows_scope(auth, item.get("scope"), item.get("scopeId"))
        }
        review_candidate = next(
            (item for item in store.review_queue(workspace_id, "") if item.get("reviewId") == review_id),
            None,
        )
        if review_candidate and review_candidate.get("memoryEventId") not in visible_memory_by_id:
            return problem(start_response, "404 Not Found", "Review item not found", "No matching review queue item exists for the authenticated scope.", "review_item_not_found")
        reviewer_agent_id, binding_problem = _bound_agent_id_or_problem(
            auth,
            start_response,
            body.get("reviewerAgentId"),
            body.get("reviewer_agent_id"),
        )
        if binding_problem:
            return binding_problem
        decision = body.get("decision")
        if not review_id:
            return problem(start_response, "422 Unprocessable Entity", "Review id required", "Review decisions require reviewId.", "review_id_required")
        replay = _idempotency_replay_or_conflict(store, environ, start_response, workspace_id, idem, "review-decide", body)
        if replay:
            return replay
        review, error = store.decide_review(workspace_id, review_id, reviewer_agent_id, decision, redact_text(body.get("reviewNote") or body.get("review_note") or ""))
        if error == "invalid_decision":
            return problem(start_response, "422 Unprocessable Entity", "Invalid review decision", "Decision must be promote, approve, reject, or quarantine.", "invalid_review_decision")
        if error == "not_found":
            return problem(start_response, "404 Not Found", "Review item not found", "No matching review queue item exists for this workspace.", "review_item_not_found")
        _mark_idempotent_mutation_started(
            environ, store, workspace_id, idem, "review-decide"
        )
        payload = {
            "ok": True,
            "review": review,
            "operatorSummary": _review_decision_operator_summary(review),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        _record_request_idempotency(store, environ, workspace_id, idem, "review-decide", body, payload, "200 OK")
        return json_response(start_response, payload)
    if path in ("/api/matm/memory-events", "/api/matm/search") and method == "GET":
        filters = {
            "scope": query.get("scope") or "",
            "scopeId": query.get("scope_id") or query.get("scopeId") or "",
            "memoryType": query.get("memory_type") or query.get("memoryType") or "",
            "reviewStatus": query.get("review_status") or query.get("reviewStatus") or "",
            "promotionState": query.get("promotion_state") or query.get("promotionState") or "",
            "sourcePrefix": query.get("source_prefix") or query.get("sourcePrefix") or "",
            "tag": query.get("tag") or "",
            "actorAgentId": query.get("actor_agent_id") or query.get("actorAgentId") or "",
            "eventId": query.get("event_id") or query.get("eventId") or query.get("memory_event_id") or query.get("memoryEventId") or "",
        }
        active_filters = {key: value for key, value in filters.items() if value}
        query_text = query.get("q") or query.get("query") or ""
        items = store.search_memory(workspace_id, query_text, filters)
        items = [
            item
            for item in items
            if store.auth_allows_scope(auth, item.get("scope"), item.get("scopeId"))
        ]
        operator_summary = _memory_search_operator_summary(items, query_text, active_filters)
        _audit_read(
            store,
            workspace_id,
            auth,
            "memory.search",
            path,
            {
                "memoryCount": len(items),
                "memorySource": "hosted_workspace_store",
                "filterKeys": sorted(active_filters.keys()),
                "scopeCounts": operator_summary["scopeCounts"],
                "reviewStatusCounts": operator_summary["reviewStatusCounts"],
            },
        )
        return json_response(
            start_response,
            {
                "ok": True,
                "items": items,
                "count": len(items),
                "memorySource": "hosted_workspace_store",
                "filesystemDocsIncluded": False,
                "filters": active_filters,
                "operatorSummary": operator_summary,
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )
    if path == "/api/matm/routing-decisions" and method == "GET":
        requested_limit = query.get("limit") or "50"
        routing_filters = {
            "roomId": query.get("room_id") or query.get("roomId") or query.get("source_room_id") or query.get("sourceRoomId") or "",
            "destinationRoomId": query.get("destination_room_id") or query.get("destinationRoomId") or "",
            "routedAgentId": query.get("routed_agent_id") or query.get("routedAgentId") or "",
            "coordinatorAgentId": query.get("coordinator_agent_id") or query.get("coordinatorAgentId") or "",
            "lane": query.get("lane") or "",
            "destinationScope": query.get("destination_scope") or query.get("destinationScope") or "",
            "destinationScopeId": query.get("destination_scope_id") or query.get("destinationScopeId") or "",
            "status": query.get("status") or "",
        }
        active_filters = {key: value for key, value in routing_filters.items() if value}
        if query.get("limit"):
            active_filters["limit"] = requested_limit
        items = store.routing_decisions(workspace_id, routing_filters, requested_limit)
        routing_rooms = {
            room.get("roomId"): room
            for room in store.meeting_rooms(
                workspace_id, auth.get("agentId") or _auth_actor_id(auth)
            )
        }
        items = [
            item
            for item in items
            if _routing_decision_visible_to_auth(
                store, workspace_id, auth, item, routing_rooms
            )
        ]
        operator_summary = _routing_decisions_operator_summary(items, active_filters)
        _audit_read(
            store,
            workspace_id,
            auth,
            "routing_decisions.read",
            path,
            {
                "routingDecisionCount": len(items),
                "filters": active_filters,
                "filterKeys": list(active_filters.keys()),
            },
        )
        return json_response(
            start_response,
            {
                "ok": True,
                "schemaVersion": "memoryendpoints.routing_decisions.v1",
                "items": items,
                "count": len(items),
                "filters": active_filters,
                "operatorSummary": operator_summary,
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )
    if path == "/api/matm/routing-decisions" and method == "POST":
        source_room_id = str(body.get("sourceRoomId") or body.get("source_room_id") or body.get("roomId") or body.get("room_id") or "").strip()
        destination_room_id = str(body.get("destinationRoomId") or body.get("destination_room_id") or "").strip()
        destination_scope = str(body.get("destinationScope") or body.get("destination_scope") or "").strip().lower()
        destination_scope_id = str(body.get("destinationScopeId") or body.get("destination_scope_id") or "").strip()
        coordinator_agent_id, binding_problem = _bound_agent_id_or_problem(
            auth,
            start_response,
            body.get("coordinatorAgentId"),
            body.get("coordinator_agent_id"),
            body.get("actorAgentId"),
            body.get("actor_agent_id"),
        )
        if binding_problem:
            return binding_problem
        routed_agent_id = str(body.get("routedAgentId") or body.get("routed_agent_id") or body.get("targetAgentId") or body.get("target_agent_id") or "").strip()
        lane = redact_text(str(body.get("lane") or "").strip())
        specific_goal = redact_text(str(body.get("specificGoal") or body.get("specific_goal") or "").strip())
        next_action = redact_text(str(body.get("nextAction") or body.get("next_action") or "").strip())
        support_plan = redact_text(str(body.get("supportPlan") or body.get("support_plan") or "").strip())
        expected_evidence = _string_list(body.get("expectedEvidence") or body.get("expected_evidence"))
        if not source_room_id:
            return problem(start_response, "422 Unprocessable Entity", "Source room id required", "Routing decisions require sourceRoomId or roomId.", "source_room_id_required")
        if not routed_agent_id:
            return problem(start_response, "422 Unprocessable Entity", "Routed agent id required", "Routing decisions require routedAgentId or targetAgentId.", "routed_agent_id_required")
        if not lane:
            return problem(start_response, "422 Unprocessable Entity", "Routing lane required", "Routing decisions require a lane.", "routing_lane_required")
        if not specific_goal:
            return problem(start_response, "422 Unprocessable Entity", "Specific goal required", "Routing decisions require a specificGoal.", "specific_goal_required")
        if not next_action:
            return problem(start_response, "422 Unprocessable Entity", "Next action required", "Routing decisions require nextAction.", "next_action_required")
        if not support_plan:
            return problem(start_response, "422 Unprocessable Entity", "Support plan required", "Routing decisions require supportPlan so the receiving agent knows how the coordinator will help.", "support_plan_required")
        if not expected_evidence:
            return problem(start_response, "422 Unprocessable Entity", "Expected evidence required", "Routing decisions require at least one expectedEvidence item.", "expected_evidence_required")
        if len(routed_agent_id) > 160 or len(coordinator_agent_id) > 160:
            return problem(start_response, "422 Unprocessable Entity", "Agent id too long", "Routing decision agent ids must be at most 160 characters.", "agent_id_too_long")
        if len(lane) > 160:
            return problem(start_response, "422 Unprocessable Entity", "Lane too long", "Routing decision lane must be at most 160 characters.", "routing_lane_too_long")
        if len(specific_goal) > 700 or len(next_action) > 500 or len(support_plan) > 700:
            return problem(start_response, "422 Unprocessable Entity", "Routing field too long", "specificGoal must be at most 700 characters; nextAction at most 500; supportPlan at most 700.", "routing_field_too_long")
        rooms = store.meeting_rooms(workspace_id, coordinator_agent_id)
        source_room = next((room for room in rooms if room.get("roomId") == source_room_id), None)
        if not source_room:
            return problem(start_response, "404 Not Found", "Source room not found", "No active source meeting room exists for this workspace.", "source_room_not_found")
        if not store.auth_allows_scope(auth, source_room.get("scope"), source_room.get("scopeId")):
            return _access_problem(start_response, "insufficient_scope")
        destination_room = None
        if destination_room_id:
            destination_room = next((room for room in rooms if room.get("roomId") == destination_room_id), None)
        elif destination_scope and destination_scope_id:
            destination_room = next((room for room in rooms if room.get("scope") == destination_scope and room.get("scopeId") == destination_scope_id), None)
            destination_room_id = destination_room.get("roomId") if destination_room else ""
        else:
            return problem(start_response, "422 Unprocessable Entity", "Destination room required", "Routing decisions require destinationRoomId or destinationScope plus destinationScopeId.", "destination_room_required")
        if not destination_room:
            return problem(start_response, "404 Not Found", "Destination room not found", "No active destination meeting room exists for this workspace.", "destination_room_not_found")
        if not store.auth_allows_scope(auth, destination_room.get("scope"), destination_room.get("scopeId")):
            return _access_problem(start_response, "insufficient_scope")
        if not store.agent_has_scope(
            workspace_id,
            routed_agent_id,
            destination_room.get("scope"),
            destination_room.get("scopeId"),
        ):
            return problem(
                start_response,
                "422 Unprocessable Entity",
                "Routed agent unavailable",
                "The routed agent must have one active identity, credential, and grant that reaches the destination scope.",
                "routed_agent_destination_unavailable",
            )
        replay = _idempotency_replay_or_conflict(
            store,
            environ,
            start_response,
            workspace_id,
            idem,
            "routing-decision-submit",
            body,
        )
        if replay:
            return replay
        safe_summary = _routing_decision_summary(
            {
                "routedAgentId": routed_agent_id,
                "lane": lane,
                "destinationRoomId": destination_room_id,
                "specificGoal": specific_goal,
                "expectedEvidence": expected_evidence,
                "nextAction": next_action,
                "supportPlan": support_plan,
            },
            destination_room,
        )
        if len(safe_summary) > 2000:
            safe_summary = safe_summary[:1997] + "..."
        quota_payload = {
            "sourceRoomId": source_room_id,
            "destinationRoomId": destination_room_id,
            "routedAgentId": routed_agent_id,
            "lane": lane,
            "specificGoal": specific_goal,
            "expectedEvidence": expected_evidence,
            "nextAction": next_action,
            "supportPlan": support_plan,
            "safeSummary": safe_summary,
        }
        if not store.has_quota_for(workspace_id, quota_payload):
            return problem(start_response, "413 Payload Too Large", "Workspace quota exceeded", "The workspace does not have enough remaining storage for this routing decision.", "quota_exceeded")
        decision, message, source_room, destination_room = store.submit_routing_decision(
            workspace_id,
            source_room_id,
            coordinator_agent_id,
            routed_agent_id,
            lane,
            destination_room_id,
            specific_goal,
            expected_evidence,
            next_action,
            support_plan,
            safe_summary,
        )
        if not decision:
            return problem(start_response, "404 Not Found", "Routing room not found", "The routing decision could not be saved because the source or destination room was not found.", "routing_room_not_found")
        _mark_idempotent_mutation_started(
            environ, store, workspace_id, idem, "routing-decision-submit"
        )
        confirmation = _routing_decision_confirmation(store, workspace_id, decision, message, source_room)
        if not confirmation["persisted"]:
            return problem(start_response, "500 Internal Server Error", "Routing decision was not persisted", "The routing decision could not be confirmed in decision readback and room transcript after write.", "routing_decision_not_persisted")
        payload = {
            "ok": True,
            "routingDecision": decision,
            "message": message,
            "sourceRoom": source_room,
            "destinationRoom": destination_room,
            "persisted": confirmation["persisted"],
            "visibleToRoutedAgent": confirmation["visibleToRoutedAgent"],
            "canonicalRoutingDecisionId": confirmation["canonicalRoutingDecisionId"],
            "canonicalRoomId": confirmation["canonicalRoomId"],
            "destinationRoomId": confirmation["destinationRoomId"],
            "messageId": confirmation["messageId"],
            "routingDecisionQueryUrl": confirmation["routingDecisionQueryUrl"],
            "transcriptQueryUrl": confirmation["transcriptQueryUrl"],
            "destinationTranscriptQueryUrl": confirmation["destinationTranscriptQueryUrl"],
            "confirmation": confirmation,
            "operatorSummary": _routing_decision_operator_summary(decision, source_room, destination_room),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        _record_request_idempotency(store, environ, workspace_id, idem, "routing-decision-submit", body, payload, "201 Created")
        return json_response(start_response, payload, "201 Created")
    if path == "/api/matm/meeting-messages/promote" and method == "POST":
        meeting_message_id = body.get("meetingMessageId") or body.get("meeting_message_id")
        promoted_by_agent_id, binding_problem = _bound_agent_id_or_problem(
            auth,
            start_response,
            body.get("promotedByAgentId"),
            body.get("promoted_by_agent_id"),
            body.get("actorAgentId"),
            body.get("actor_agent_id"),
        )
        if binding_problem:
            return binding_problem
        if not meeting_message_id:
            return problem(start_response, "422 Unprocessable Entity", "Meeting message id required", "Meeting memory promotion requires meetingMessageId.", "meeting_message_id_required")
        message, room = store.meeting_message(workspace_id, meeting_message_id)
        if not message:
            return problem(start_response, "404 Not Found", "Meeting message not found", "No matching meeting message exists for this workspace.", "meeting_message_not_found")
        if not store.auth_allows_scope(auth, room.get("scope"), room.get("scopeId")):
            return _access_problem(start_response, "insufficient_scope")
        if not _npc_room_allowed(auth, room):
            return _access_problem(start_response, "npc_game_scope_required")
        promotion_scope = body.get("scope") or message.get("scope") or room.get("scope")
        promotion_scope_id = body.get("scopeId") or body.get("scope_id") or message.get("scopeId") or room.get("scopeId")
        if not store.auth_allows_scope(
            auth, promotion_scope, promotion_scope_id
        ):
            return _access_problem(start_response, "insufficient_scope")
        summary = body.get("summary") or message.get("safeSummary") or ""
        if not summary.strip():
            return problem(start_response, "422 Unprocessable Entity", "Summary required", "Meeting memory promotion requires a public-safe summary.", "summary_required")
        if len(summary) > 4000:
            return problem(start_response, "422 Unprocessable Entity", "Summary too long", "Promoted meeting memory summaries must be at most 4000 characters.", "summary_too_long")
        tags = body.get("tags") or []
        if isinstance(tags, str):
            tags = [item.strip() for item in tags.split(",") if item.strip()]
        elif not isinstance(tags, list):
            tags = []
        source_sender = message.get("senderAgentId") or "unknown"
        promoted_tags = list(tags)
        for tag in (
            "meeting-message",
            "meeting-scope:%s" % (message.get("scope") or room.get("scope") or "workspace"),
            "meeting-sender:%s" % source_sender,
        ):
            if tag not in promoted_tags:
                promoted_tags.append(tag)
        source = body.get("source") or "memoryendpoints://matm/meeting-messages/%s" % meeting_message_id
        if not store.has_quota_for(workspace_id, {"meetingMessageId": meeting_message_id, "summary": summary, "tags": promoted_tags, "source": source}):
            return problem(start_response, "413 Payload Too Large", "Workspace quota exceeded", "The workspace does not have enough remaining storage for this promoted memory event.", "quota_exceeded")
        replay = _idempotency_replay_or_conflict(store, environ, start_response, workspace_id, idem, "meeting-message-promote", body)
        if replay:
            return replay
        event = store.submit_memory(
            workspace_id,
            promoted_by_agent_id,
            promotion_scope,
            body.get("title") or "Meeting memory: %s" % (room.get("name") or room.get("label") or message.get("roomId") or "room"),
            summary,
            promoted_tags,
            source,
            body.get("memoryType") or body.get("memory_type") or "evidence",
            body.get("subject") or "meeting-message:%s" % meeting_message_id,
            body.get("confidence") or 0.8,
            promotion_scope_id,
        )
        _mark_idempotent_mutation_started(
            environ, store, workspace_id, idem, "meeting-message-promote"
        )
        submission = _memory_submission_metadata(event)
        confirmation = _memory_submission_confirmation(store, workspace_id, event)
        if not confirmation["persisted"]:
            return problem(start_response, "500 Internal Server Error", "Promoted memory was not persisted", "The promoted memory event could not be confirmed by server-side persistence evidence after write.", "promoted_memory_not_persisted")
        payload = {
            "ok": True,
            "sourceMeetingMessage": message,
            "room": room,
            "event": event,
            "submission": submission,
            "persisted": confirmation["persisted"],
            "visibleInSearch": confirmation["visibleInSearch"],
            "visibleInReviewQueue": confirmation["visibleInReviewQueue"],
            "canonicalMemoryEventId": confirmation["canonicalMemoryEventId"],
            "reviewId": confirmation["reviewId"],
            "memoryQueryUrl": confirmation["memoryQueryUrl"],
            "reviewQueueUrl": confirmation["reviewQueueUrl"],
            "confirmation": confirmation,
            "operatorSummary": _meeting_memory_promotion_operator_summary(message, room, event, promoted_by_agent_id),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        _record_request_idempotency(store, environ, workspace_id, idem, "meeting-message-promote", body, payload, "201 Created")
        return json_response(start_response, payload, "201 Created")
    if path == "/api/matm/meeting-rooms" and method == "POST":
        scope = str(body.get("scope") or "").strip().lower()
        scope_id = str(body.get("scopeId") or body.get("scope_id") or "").strip()
        parent_scope_type = str(body.get("parentScopeType") or body.get("parent_scope_type") or "").strip().lower()
        parent_scope_id = str(body.get("parentScopeId") or body.get("parent_scope_id") or "").strip()
        label = str(body.get("label") or "").strip()
        name = str(body.get("name") or "").strip()
        purpose = str(body.get("purpose") or "").strip()
        parent_rules = {
            "goal": ("project",),
            "task": ("project", "goal"),
            "game": ("project",),
            "session": ("game", "project"),
        }
        if scope not in parent_rules:
            return problem(start_response, "422 Unprocessable Entity", "Unsupported meeting room scope", "Create custom meeting rooms only for goal, task, game, or session scope; company, workspace, and project rooms are hierarchy-derived.", "unsupported_meeting_room_scope")
        if parent_scope_type and parent_scope_type not in parent_rules[scope]:
            return problem(start_response, "422 Unprocessable Entity", "Invalid meeting room parent", "The requested meeting room parent is not valid for this scope.", "scope_parent_invalid")
        if parent_scope_type and not parent_scope_id:
            return problem(start_response, "422 Unprocessable Entity", "Parent scope id required", "A parentScopeId is required when parentScopeType is provided.", "scope_parent_invalid")
        if parent_scope_id and not parent_scope_type:
            return problem(start_response, "422 Unprocessable Entity", "Parent scope type required", "A parentScopeType is required when parentScopeId is provided.", "scope_parent_invalid")
        if not _npc_meeting_scope_allowed(auth, scope):
            return _access_problem(start_response, "npc_game_scope_required")
        if not scope_id:
            return problem(start_response, "422 Unprocessable Entity", "Scope id required", "Custom meeting rooms require scopeId.", "scope_id_required")
        if len(scope_id) > 160:
            return problem(start_response, "422 Unprocessable Entity", "Scope id too long", "Meeting room scopeId must be at most 160 characters.", "scope_id_too_long")
        if len(label) > 120 or len(name) > 160:
            return problem(start_response, "422 Unprocessable Entity", "Meeting room name too long", "Meeting room label must be at most 120 characters and name must be at most 160 characters.", "meeting_room_name_too_long")
        if len(purpose) > 1000:
            return problem(start_response, "422 Unprocessable Entity", "Meeting room purpose too long", "Meeting room purpose must be at most 1000 characters.", "meeting_room_purpose_too_long")
        if scope and scope_id:
            scope_allowed = store.auth_allows_scope(auth, scope, scope_id)
            parent_allowed = False
            if parent_scope_type and parent_scope_id:
                parent_allowed = store.auth_allows_scope(auth, parent_scope_type, parent_scope_id)
            if not scope_allowed:
                if _principal_scope_type(auth) in ("project", "game", "session", "goal", "task") and not parent_allowed:
                    return _access_problem(start_response, "insufficient_scope")
                scope_allowed = parent_allowed or store.auth_allows_scope(auth, "workspace", workspace_id)
            if not scope_allowed:
                return _access_problem(start_response, "insufficient_scope")
        creator_agent_id, binding_problem = _bound_agent_id_or_problem(
            auth,
            start_response,
            body.get("creatorAgentId"),
            body.get("creator_agent_id"),
            body.get("agentId"),
            body.get("agent_id"),
        )
        if binding_problem:
            return binding_problem
        if not store.has_quota_for(workspace_id, body):
            return problem(start_response, "413 Payload Too Large", "Workspace quota exceeded", "The workspace does not have enough remaining storage for this meeting room.", "quota_exceeded")
        replay = _idempotency_replay_or_conflict(store, environ, start_response, workspace_id, idem, "meeting-room-create", body)
        if replay:
            return replay
        room, created = store.create_meeting_room(
            workspace_id,
            scope,
            scope_id,
            label=label,
            name=name,
            purpose=purpose,
            creator_agent_id=creator_agent_id,
            parent_scope_type=parent_scope_type,
            parent_scope_id=parent_scope_id,
        )
        _mark_idempotent_mutation_started(
            environ, store, workspace_id, idem, "meeting-room-create"
        )
        rooms = store.meeting_rooms(workspace_id, creator_agent_id)
        visible = any(item.get("roomId") == room.get("roomId") for item in rooms)
        if not visible:
            return problem(start_response, "500 Internal Server Error", "Meeting room was not persisted", "The meeting room could not be confirmed in the room list after write.", "meeting_room_not_persisted")
        confirmation = {
            "persisted": visible,
            "visibleToAgent": visible,
            "canonicalRoomId": room.get("roomId"),
            "roomQueryUrl": _protected_query_url(
                "/api/matm/meeting-rooms",
                {"workspace_id": workspace_id, "agent_id": creator_agent_id},
            ),
            "transcriptQueryUrl": _protected_query_url(
                "/api/matm/meeting-messages",
                {
                    "workspace_id": workspace_id,
                    "room_id": room.get("roomId"),
                    "agent_id": creator_agent_id,
                },
            ),
            "valuesRedacted": True,
        }
        payload = {
            "ok": True,
            "room": room,
            "created": bool(created),
            "persisted": confirmation["persisted"],
            "visibleToAgent": confirmation["visibleToAgent"],
            "canonicalRoomId": confirmation["canonicalRoomId"],
            "roomQueryUrl": confirmation["roomQueryUrl"],
            "transcriptQueryUrl": confirmation["transcriptQueryUrl"],
            "confirmation": confirmation,
            "operatorSummary": _meeting_room_create_operator_summary(room, created, creator_agent_id),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        _record_request_idempotency(store, environ, workspace_id, idem, "meeting-room-create", body, payload, "201 Created" if created else "200 OK")
        return json_response(start_response, payload, "201 Created" if created else "200 OK")
    if path == "/api/matm/meeting-rooms" and method == "GET":
        agent_filter = query.get("agent_id") or query.get("agentId") or ""
        if auth.get("credentialType") == "agent":
            agent_filter, binding_problem = _bound_agent_id_or_problem(
                auth,
                start_response,
                query.get("agent_id"),
                query.get("agentId"),
            )
            if binding_problem:
                return binding_problem
        scope_filter = (query.get("scope") or "").strip().lower()
        scope_id_filter = query.get("scope_id") or query.get("scopeId") or ""
        filters = {}
        if agent_filter:
            filters["agentId"] = agent_filter
        if scope_filter:
            filters["scope"] = scope_filter
        if scope_id_filter:
            filters["scopeId"] = scope_id_filter
        rooms = store.meeting_rooms(workspace_id, agent_filter)
        rooms = [
            room
            for room in rooms
            if store.auth_allows_scope(auth, room.get("scope"), room.get("scopeId"))
            and _npc_room_allowed(auth, room)
        ]
        if scope_filter:
            rooms = [room for room in rooms if room.get("scope") == scope_filter]
        if scope_id_filter:
            rooms = [room for room in rooms if room.get("scopeId") == scope_id_filter]
        operator_summary = _meeting_rooms_operator_summary(rooms, filters)
        _audit_read(
            store,
            workspace_id,
            auth,
            "meeting_rooms.read",
            path,
            {
                "meetingRoomCount": len(rooms),
                "filters": filters,
                "scopeCounts": operator_summary["scopeCounts"],
                "unreadMeetingCount": operator_summary["unreadCount"],
            },
        )
        return json_response(
            start_response,
            {
                "ok": True,
                "schemaVersion": "memoryendpoints.meeting_rooms.v1",
                "items": rooms,
                "count": len(rooms),
                "filters": filters,
                "operatorSummary": operator_summary,
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )
    if path == "/api/matm/meeting-messages" and method == "GET":
        room_id = query.get("room_id") or query.get("roomId") or ""
        agent_filter = query.get("agent_id") or query.get("agentId") or ""
        if auth.get("credentialType") == "agent":
            agent_filter, binding_problem = _bound_agent_id_or_problem(
                auth,
                start_response,
                query.get("agent_id"),
                query.get("agentId"),
            )
            if binding_problem:
                return binding_problem
        cursor_filter = query.get("cursor") or query.get("before_meeting_message_id") or query.get("beforeMeetingMessageId") or ""
        if not room_id:
            return problem(start_response, "422 Unprocessable Entity", "Meeting room id required", "Meeting transcript reads require room_id.", "meeting_room_id_required")
        transcript_page = store.meeting_messages_page(workspace_id, room_id, agent_filter, query.get("limit") or "50", cursor_filter)
        room = transcript_page.get("room")
        messages = transcript_page.get("items") or []
        read_state = transcript_page.get("readState")
        if not room:
            return problem(start_response, "404 Not Found", "Meeting room not found", "No matching meeting room exists for this workspace.", "meeting_room_not_found")
        if not store.auth_allows_scope(auth, room.get("scope"), room.get("scopeId")):
            return _access_problem(start_response, "insufficient_scope")
        if not _npc_room_allowed(auth, room):
            return _access_problem(start_response, "npc_game_scope_required")
        rooms = store.meeting_rooms(workspace_id, agent_filter)
        rooms = [
            item
            for item in rooms
            if store.auth_allows_scope(auth, item.get("scope"), item.get("scopeId"))
            and _npc_room_allowed(auth, item)
        ]
        room_with_counts = next((item for item in rooms if item.get("roomId") == room_id), room)
        filters = {"roomId": room_id}
        if agent_filter:
            filters["agentId"] = agent_filter
        if query.get("limit"):
            filters["limit"] = query.get("limit")
        if cursor_filter:
            filters["cursor"] = cursor_filter
        pagination = {
            "visibleMessageCount": transcript_page.get("visibleMessageCount", len(messages)),
            "totalMessageCount": transcript_page.get("totalMessageCount", len(messages)),
            "hasMore": bool(transcript_page.get("hasMore")),
            "nextCursor": transcript_page.get("nextCursor"),
            "cursor": transcript_page.get("cursor") or "",
            "cursorAccepted": transcript_page.get("cursorAccepted"),
            "cursorDirection": "older",
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        transcript_ordering = _meeting_transcript_ordering_summary()
        operator_summary = _meeting_messages_operator_summary(
            room_with_counts,
            messages,
            read_state,
            filters,
            room_with_counts.get("unreadCount") or 0,
            transcript_page.get("totalMessageCount", len(messages)),
            pagination,
        )
        _audit_read(
            store,
            workspace_id,
            auth,
            "meeting_messages.read",
            path,
            {
                "roomScope": room.get("scope"),
                "meetingMessageCount": len(messages),
                "totalMessageCount": transcript_page.get("totalMessageCount", len(messages)),
                "unreadMeetingCount": operator_summary["unreadCount"],
                "filters": filters,
            },
        )
        return json_response(
            start_response,
            {
                "ok": True,
                "schemaVersion": "memoryendpoints.meeting_messages.v1",
                "room": room_with_counts,
                "items": messages,
                "count": len(messages),
                "visibleMessageCount": len(messages),
                "totalMessageCount": transcript_page.get("totalMessageCount", len(messages)),
                "hasMore": bool(transcript_page.get("hasMore")),
                "nextCursor": transcript_page.get("nextCursor"),
                "cursor": transcript_page.get("cursor") or "",
                "cursorAccepted": transcript_page.get("cursorAccepted"),
                "transcriptOrdering": transcript_ordering,
                "pagination": pagination,
                "readState": read_state or {},
                "filters": filters,
                "operatorSummary": operator_summary,
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )
    if path == "/api/matm/meeting-messages" and method == "POST":
        requested_room_id = body.get("roomId") or body.get("room_id")
        requested_room = next(
            (room for room in store.meeting_rooms(workspace_id) if room.get("roomId") == requested_room_id),
            None,
        )
        if not requested_room:
            return problem(start_response, "404 Not Found", "Meeting room not found", "No matching meeting room exists for this workspace.", "meeting_room_not_found")
        if not store.auth_allows_scope(auth, requested_room.get("scope"), requested_room.get("scopeId")):
            return _access_problem(start_response, "insufficient_scope")
        if not _npc_room_allowed(auth, requested_room):
            return _access_problem(start_response, "npc_game_scope_required")
        room_id = body.get("roomId") or body.get("room_id")
        sender_agent_id, binding_problem = _bound_agent_id_or_problem(
            auth,
            start_response,
            body.get("senderAgentId"),
            body.get("sender_agent_id"),
        )
        if binding_problem:
            return binding_problem
        safe_summary = body.get("safeSummary") or body.get("safe_summary") or ""
        if not room_id:
            return problem(start_response, "422 Unprocessable Entity", "Meeting room id required", "Meeting posts require roomId.", "meeting_room_id_required")
        if not safe_summary.strip():
            return problem(start_response, "422 Unprocessable Entity", "Safe summary required", "Meeting posts require a public-safe summary.", "safe_summary_required")
        if len(safe_summary) > 2000:
            return problem(start_response, "422 Unprocessable Entity", "Safe summary too long", "Meeting post safe summaries must be at most 2000 characters.", "safe_summary_too_long")
        if not store.has_quota_for(workspace_id, body):
            return problem(start_response, "413 Payload Too Large", "Workspace quota exceeded", "The workspace does not have enough remaining storage for this meeting message.", "quota_exceeded")
        replay = _idempotency_replay_or_conflict(store, environ, start_response, workspace_id, idem, "meeting-message-submit", body)
        if replay:
            return replay
        message, room = store.submit_meeting_message(workspace_id, room_id, sender_agent_id, safe_summary)
        if not message:
            return problem(start_response, "404 Not Found", "Meeting room not found", "No matching meeting room exists for this workspace.", "meeting_room_not_found")
        _mark_idempotent_mutation_started(
            environ, store, workspace_id, idem, "meeting-message-submit"
        )
        confirmation = _meeting_post_confirmation(store, workspace_id, room, message)
        if not confirmation["persisted"]:
            return problem(start_response, "500 Internal Server Error", "Meeting message was not persisted", "The meeting message could not be confirmed in the room transcript after write.", "meeting_message_not_persisted")
        payload = {
            "ok": True,
            "room": room,
            "message": message,
            "persisted": confirmation["persisted"],
            "visibleToSender": confirmation["visibleToSender"],
            "canonicalRoomId": confirmation["canonicalRoomId"],
            "messageId": confirmation["messageId"],
            "transcriptQueryUrl": confirmation["transcriptQueryUrl"],
            "confirmation": confirmation,
            "operatorSummary": _meeting_post_operator_summary(room, message),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        _record_request_idempotency(store, environ, workspace_id, idem, "meeting-message-submit", body, payload, "201 Created")
        return json_response(start_response, payload, "201 Created")
    if path == "/api/matm/meeting-rooms/read" and method == "POST":
        requested_room_id = body.get("roomId") or body.get("room_id")
        requested_room = next(
            (room for room in store.meeting_rooms(workspace_id) if room.get("roomId") == requested_room_id),
            None,
        )
        if not requested_room:
            return problem(start_response, "404 Not Found", "Meeting room not found", "No matching meeting room exists for this workspace.", "meeting_room_not_found")
        if not store.auth_allows_scope(auth, requested_room.get("scope"), requested_room.get("scopeId")):
            return _access_problem(start_response, "insufficient_scope")
        if not _npc_room_allowed(auth, requested_room):
            return _access_problem(start_response, "npc_game_scope_required")
        room_id = body.get("roomId") or body.get("room_id")
        agent_id, binding_problem = _bound_agent_id_or_problem(
            auth,
            start_response,
            body.get("agentId"),
            body.get("agent_id"),
        )
        if binding_problem:
            return binding_problem
        if not room_id:
            return problem(start_response, "422 Unprocessable Entity", "Meeting room id required", "Meeting read cursors require roomId.", "meeting_room_id_required")
        replay = _idempotency_replay_or_conflict(store, environ, start_response, workspace_id, idem, "meeting-room-read", body)
        if replay:
            return replay
        read_state, error = store.mark_meeting_room_read(workspace_id, room_id, agent_id, body.get("lastMeetingMessageId") or body.get("last_meeting_message_id"))
        if error == "message_not_found":
            return problem(start_response, "404 Not Found", "Meeting message not found", "No matching meeting message exists for this room.", "meeting_message_not_found")
        if not read_state:
            return problem(start_response, "404 Not Found", "Meeting room not found", "No matching meeting room exists for this workspace.", "meeting_room_not_found")
        _mark_idempotent_mutation_started(
            environ, store, workspace_id, idem, "meeting-room-read"
        )
        rooms = store.meeting_rooms(workspace_id, agent_id)
        room = next((item for item in rooms if item.get("roomId") == room_id), {"roomId": room_id})
        payload = {
            "ok": True,
            "room": room,
            "readState": read_state,
            "operatorSummary": _meeting_read_operator_summary(read_state, room),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        _record_request_idempotency(store, environ, workspace_id, idem, "meeting-room-read", body, payload, "200 OK")
        return json_response(start_response, payload)
    if path == "/api/matm/agent-messages" and method == "POST":
        safe_summary = body.get("safeSummary") or body.get("safe_summary") or ""
        sender_agent_id, binding_problem = _bound_agent_id_or_problem(
            auth,
            start_response,
            body.get("senderAgentId"),
            body.get("sender_agent_id"),
        )
        if binding_problem:
            return binding_problem
        if not safe_summary.strip():
            return problem(start_response, "422 Unprocessable Entity", "Safe summary required", "Current messages require a public-safe summary.", "safe_summary_required")
        if len(safe_summary) > 1000:
            return problem(start_response, "422 Unprocessable Entity", "Safe summary too long", "Current-message safe summaries must be at most 1000 characters.", "safe_summary_too_long")
        if not store.has_quota_for(workspace_id, body):
            return problem(start_response, "413 Payload Too Large", "Workspace quota exceeded", "The workspace does not have enough remaining storage for this current message.", "quota_exceeded")
        replay = _idempotency_replay_or_conflict(store, environ, start_response, workspace_id, idem, "message-submit", body)
        if replay:
            return replay
        target_agent_id = body.get("targetAgentId") or body.get("target_agent_id")
        message, notifications = store.submit_message(
            workspace_id,
            sender_agent_id,
            target_agent_id,
            safe_summary,
            body.get("responseRequired") or body.get("response_required"),
        )
        _mark_idempotent_mutation_started(
            environ, store, workspace_id, idem, "message-submit"
        )
        notifications = notifications if isinstance(notifications, list) else ([notifications] if notifications else [])
        primary_notification = notifications[0] if notifications else {}
        delivery = _delivery_metadata(message, primary_notification, (primary_notification or {}).get("targetAgentId") or "")
        delivery["recipientCount"] = len(notifications)
        delivery_counts = {
            "broadcast": 1 if delivery["messageType"] == "broadcast" else 0,
            "targeted": 1 if delivery["messageType"] == "targeted" else 0,
        }
        confirmation = _current_message_confirmation(store, workspace_id, message, notifications)
        if not confirmation["persisted"]:
            return problem(start_response, "500 Internal Server Error", "Current message was not persisted", "The current message could not be confirmed in the recipient inbox after write.", "current_message_not_persisted")
        operator_summary = _message_delivery_operator_summary(delivery, delivery_counts)
        payload = {
            "ok": True,
            "message": message,
            "notification": primary_notification,
            "notifications": notifications,
            "delivery": delivery,
            "deliveryCounts": delivery_counts,
            "persisted": confirmation["persisted"],
            "visibleToTarget": confirmation["visibleToTarget"],
            "visibleToAgents": confirmation["visibleToAgents"],
            "visibleRecipientCount": confirmation["visibleRecipientCount"],
            "expectedRecipientCount": confirmation["expectedRecipientCount"],
            "canonicalTargetAgentId": confirmation["canonicalTargetAgentId"],
            "messageId": confirmation["messageId"],
            "notificationId": confirmation["notificationId"],
            "notificationIds": confirmation["notificationIds"],
            "inboxQueryUrl": confirmation["inboxQueryUrl"],
            "confirmation": confirmation,
            "operatorSummary": operator_summary,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        _record_request_idempotency(store, environ, workspace_id, idem, "message-submit", body, payload, "202 Accepted")
        return json_response(start_response, payload, "202 Accepted")
    if path in ("/api/matm/agent-inbox", "/api/matm/current-message") and method == "GET":
        agent_filter = query.get("agent_id") or query.get("agentId") or ""
        if auth.get("credentialType") == "agent":
            agent_filter, binding_problem = _bound_agent_id_or_problem(
                auth,
                start_response,
                query.get("agent_id"),
                query.get("agentId"),
            )
            if binding_problem:
                return binding_problem
        message_filter = query.get("message_id") or query.get("messageId") or ""
        notification_filter = query.get("notification_id") or query.get("notificationId") or ""
        requested_limit = query.get("limit") or ""
        cursor_filter = query.get("cursor") or query.get("after_notification_id") or query.get("afterNotificationId") or ""
        try:
            limit_value = max(1, min(int(requested_limit), 200)) if requested_limit else 0
        except (TypeError, ValueError):
            limit_value = 0
        inbox_page = store.inbox_page(workspace_id, agent_filter, message_filter, notification_filter, limit_value, cursor_filter)
        raw_items = inbox_page.get("items") or []
        items = []
        delivery_counts = {"broadcast": 0, "targeted": 0}
        for item in raw_items:
            message = item.get("message") or {}
            notification = item.get("notification") or {}
            delivery = _delivery_metadata(message, notification, agent_filter)
            delivery_counts[delivery["messageType"]] += 1
            enriched = dict(item)
            enriched["delivery"] = delivery
            items.append(enriched)
        filters = {"agentId": agent_filter} if agent_filter else {}
        if message_filter:
            filters["messageId"] = message_filter
        if notification_filter:
            filters["notificationId"] = notification_filter
        if limit_value:
            filters["limit"] = str(limit_value)
        if cursor_filter:
            filters["cursor"] = cursor_filter
        pagination = {
            "totalUnreadCount": inbox_page.get("totalUnreadCount", len(items)),
            "visibleUnreadCount": inbox_page.get("visibleUnreadCount", len(items)),
            "hasMore": bool(inbox_page.get("hasMore")),
            "nextCursor": inbox_page.get("nextCursor"),
            "cursor": inbox_page.get("cursor") or "",
            "cursorAccepted": inbox_page.get("cursorAccepted"),
            "limit": limit_value,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        attention_ordering = _current_message_attention_ordering_summary()
        operator_summary = _inbox_operator_summary(
            items,
            filters,
            delivery_counts,
            path == "/api/matm/current-message",
            inbox_page.get("totalUnreadCount", len(items)),
            pagination,
        )
        _audit_read(
            store,
            workspace_id,
            auth,
            "current_message.read" if path == "/api/matm/current-message" else "agent_inbox.read",
            path,
            {
                "unreadCount": len(items),
                "totalUnreadCount": inbox_page.get("totalUnreadCount", len(items)),
                "filters": filters,
                "deliveryCounts": delivery_counts,
                "responseDispositionCounts": operator_summary["responseDispositionCounts"],
            },
        )
        return json_response(
            start_response,
            {
                "ok": True,
                "currentMessageLane": path == "/api/matm/current-message",
                "items": items,
                "unreadCount": len(items),
                "visibleUnreadCount": len(items),
                "totalUnreadCount": inbox_page.get("totalUnreadCount", len(items)),
                "hasMore": bool(inbox_page.get("hasMore")),
                "nextCursor": inbox_page.get("nextCursor"),
                "cursor": inbox_page.get("cursor") or "",
                "cursorAccepted": inbox_page.get("cursorAccepted"),
                "attentionOrdering": attention_ordering,
                "responseStates": ["required_response", "viewed_acknowledgement"],
                "filters": filters,
                "deliveryCounts": delivery_counts,
                "pagination": pagination,
                "operatorSummary": operator_summary,
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )
    if path == "/api/matm/notifications/ack" and method == "POST":
        consumer_agent_id, binding_problem = _bound_agent_id_or_problem(
            auth,
            start_response,
            body.get("consumerAgentId"),
            body.get("consumer_agent_id"),
        )
        if binding_problem:
            return binding_problem
        notification_id = body.get("notificationId") or body.get("notification_id")
        visible_notification = store.inbox_page(
            workspace_id,
            consumer_agent_id,
            "",
            notification_id or "",
            1,
            "",
        )
        if not notification_id or not (visible_notification.get("items") or []):
            return problem(start_response, "404 Not Found", "Notification not found", "No matching notification exists for the authenticated agent.", "notification_not_found")
        replay = _idempotency_replay_or_conflict(store, environ, start_response, workspace_id, idem, "notification-ack", body)
        if replay:
            return replay
        receipt = store.ack(workspace_id, notification_id, consumer_agent_id, body.get("status") or "read")
        if not receipt:
            return problem(start_response, "404 Not Found", "Notification not found", "No matching notification exists for this workspace.", "notification_not_found")
        _mark_idempotent_mutation_started(
            environ, store, workspace_id, idem, "notification-ack"
        )
        payload = {
            "ok": True,
            "receipt": receipt,
            "operatorSummary": _acknowledgement_operator_summary(receipt),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        _record_request_idempotency(store, environ, workspace_id, idem, "notification-ack", body, payload, "200 OK")
        return json_response(start_response, payload)
    if path == "/api/matm/receipts" and method == "GET":
        consumer_filter = query.get("consumer_agent_id") or query.get("consumerAgentId") or ""
        if auth.get("credentialType") == "agent":
            consumer_filter, binding_problem = _bound_agent_id_or_problem(
                auth,
                start_response,
                query.get("consumer_agent_id"),
                query.get("consumerAgentId"),
            )
            if binding_problem:
                return binding_problem
        items = store.receipts(workspace_id, consumer_filter)
        filters = {"consumerAgentId": consumer_filter} if consumer_filter else {}
        operator_summary = _receipts_operator_summary(items, filters)
        _audit_read(
            store,
            workspace_id,
            auth,
            "receipts.read",
            path,
            {
                "count": len(items),
                "filters": filters,
                "receiptStatusCounts": operator_summary["statusCounts"],
                "rawPayloadExposedCount": operator_summary["rawPayloadExposedCount"],
            },
        )
        return json_response(
            start_response,
            {
                "ok": True,
                "items": items,
                "count": len(items),
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
                "filters": filters,
                "operatorSummary": operator_summary,
            },
        )
    return problem(start_response, "404 Not Found", "Route not found", "No protected route matched this request.", "not_found")


def _application_dispatch(environ, start_response):
    path = environ.get("PATH_INFO", "/") or "/"
    method = environ.get("REQUEST_METHOD", "GET")
    cors_api_route = path.startswith("/api/") and not path.startswith("/api/matm/human/")
    if cors_api_route:
        start_response = _cors_start_response(environ, start_response)
        if method == "OPTIONS":
            return _route_cors_preflight(environ, start_response)
    if path == "/" and method == "GET":
        return route_home(start_response)
    connector_authorize_match = _CONNECTOR_REQUEST_HANDLE_ROUTE.fullmatch(path)
    if connector_authorize_match and method == "GET":
        return route_connector_authorize(
            environ,
            start_response,
            public_request_ref=connector_authorize_match.group(1),
        )
    connector_demo_match = _CONNECTOR_DEMO_AUTHORIZE_ROUTE.fullmatch(path)
    if connector_demo_match and method == "GET":
        return route_connector_authorize(
            environ, start_response, demo_state=connector_demo_match.group(1)
        )
    if path in ("/docs", "/docs/") and method == "GET":
        return route_docs(start_response)
    if path == "/agent-setup" and method == "GET":
        return route_agent_setup(start_response)
    if path == "/agent-coordination" and method == "GET":
        return route_agent_coordination(start_response)
    if path == "/console" and method == "GET":
        return route_console(start_response) if _human_page_authenticated(environ) else route_human_access_page(environ, start_response)
    if path == "/tour" and method == "GET":
        return route_console(start_response, demo=True)
    if path == "/tour/human" and method == "GET":
        return route_human_access_page(environ, start_response, demo=True)
    if path in ("/human", "/agents") and method == "GET":
        return route_human_access_page(environ, start_response)
    if (path == "/knowledge" or _is_knowledge_page_route(path)) and method == "GET":
        return route_knowledge(start_response, path if path != "/knowledge" else "") if _human_page_authenticated(environ) else route_human_access_page(environ, start_response)
    if (path == "/tour/knowledge" or _is_tour_knowledge_page_route(path)) and method == "GET":
        return route_knowledge(start_response, path if path != "/tour/knowledge" else "", demo=True)
    if path == "/memory-lifecycle" and method == "GET":
        return route_memory_lifecycle(start_response)
    if path == "/transparency" and method == "GET":
        return route_transparency(start_response)
    if path.startswith("/static/") and method == "GET":
        return route_static(path, start_response)
    if path in ("/robots.txt", "/llms.txt", "/llms-full.txt", "/ai.txt") and method == "GET":
        content_type = "text/plain; charset=utf-8"
        return response(start_response, "200 OK", text_discovery(path.rsplit("/", 1)[-1]), content_type)
    if path == "/sitemap.xml" and method == "GET":
        urls = "\n".join(["<url><loc>%s%s</loc></url>" % (SITE_URL, route) for route in PUBLIC_ROUTES if not route.startswith("/api")])
        return response(start_response, "200 OK", "<?xml version=\"1.0\"?><!-- %s sitemap --><urlset>%s</urlset>" % (escape_html(SITE_NAME), urls), "application/xml; charset=utf-8")
    public = route_public_json(path, start_response, environ) if method == "GET" else None
    if public:
        return public
    if path == "/api/admin/mysql-diagnostics":
        return route_admin_mysql_diagnostics(environ, start_response)
    if path == "/api/matm/agent-setup/free-account":
        return route_setup(environ, start_response, path)
    if path == "/api/matm/agent-setup/dogfood-partner-account":
        return problem(
            start_response,
            "404 Not Found",
            "Commercial setup route not available",
            "Sponsored partner setup belongs to the private commercial edition and is not exposed by this public intranet build.",
            "not_found",
        )
    if path.startswith("/api/matm/"):
        if (
            path.startswith("/api/matm/connector-pairings/")
            or _CONNECTOR_HUMAN_COMPANY_SELECTION_ROUTE.fullmatch(path)
            or _CONNECTOR_HUMAN_APPROVAL_ROUTE.fullmatch(path)
            or _CONNECTOR_HUMAN_CANCEL_ROUTE.fullmatch(path)
        ):
            protected_connector = bool(
                path not in (
                    "/api/matm/connector-pairings/requests",
                    "/api/matm/connector-pairings/authorization-code-claims",
                    "/api/matm/connector-pairings/token",
                )
                and (
                    _CONNECTOR_PAIRING_ROUTE.fullmatch(path)
                    or _CONNECTOR_CREDENTIALS_ROUTE.fullmatch(path)
                    or _CONNECTOR_PAIRING_ACTION_ROUTE.fullmatch(path)
                    or _CONNECTOR_ROTATION_ACTIVATION_ROUTE.fullmatch(path)
                )
            )
            if protected_connector and not str(environ.get("HTTP_AUTHORIZATION") or "").strip():
                return _connector_problem(start_response, "invalid_token")
            connector = route_connector_pairing(environ, start_response, path)
            if connector is not None:
                return connector
        if path == "/api/matm/human/session/resource-context" or path.startswith(
            "/api/matm/human/operational/"
        ):
            operational_store = (
                None
                if str(environ.get("HTTP_AUTHORIZATION") or "").strip()
                else _store()
            )
            human_operational = route_human_operational(
                environ, start_response, path, operational_store, SITE_URL
            )
            if human_operational is not None:
                return human_operational
        authorization = str(environ.get("HTTP_AUTHORIZATION") or "").strip()
        if authorization:
            connector_token = _token(environ)
            connector_principal = (
                _store().authenticate_connector_token(
                    connector_token, allow_pending=True
                )
                if connector_token
                else None
            )
            connector_generic_actions = {
                ("GET", "/api/matm/me"),
                ("GET", "/api/matm/workspace"),
                ("POST", "/api/matm/agents/register"),
                ("POST", "/api/matm/memory-events/submit"),
                ("POST", "/api/matm/search"),
            }
            if connector_principal and (method, path) not in connector_generic_actions:
                return _connector_problem(
                    start_response, "connector_scope_forbidden"
                )
        human = route_human(environ, start_response, path)
        if human is not None:
            return human
        access = route_access(environ, start_response, path)
        if access is not None:
            return access
        return route_protected(environ, start_response, path)
    return problem(start_response, "404 Not Found", "Not found", "The requested route does not exist.", "not_found")


def application(environ, start_response):
    try:
        return _application_dispatch(environ, start_response)
    except _IdempotencyFinalizationError:
        if _preserve_uncertain_request_idempotency_claims(environ):
            return _idempotency_uncertain_response(start_response)
        raise
    except Exception:
        if _preserve_uncertain_request_idempotency_claims(environ):
            return _idempotency_uncertain_response(start_response)
        raise
    finally:
        _release_request_idempotency_claims(environ)
