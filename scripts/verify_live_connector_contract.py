"""Verify the deployed connector-pairing v1 contract without leaking secrets.

Public verification is read-only. Optional authenticated verification reads an
active connector's exact pairing, credential lifecycle, principal, and
workspace. It never rotates, revokes, disconnects, or otherwise mutates a
grant. Reports contain hashes of expected identifiers and never raw tokens or
tenant identifiers.
"""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "memoryendpoints.connector_pairing.v1"
ISSUER = "https://memoryendpoints.com"
REQUESTED_SCOPES = [
    "connector:self:readback",
    "agent:self:register",
    "memory:public-safe:submit",
    "memory:search:read",
]
SCOPE_DIGEST = "sha256-v1:" + hashlib.sha256(
    json.dumps(
        {"schemaVersion": SCHEMA, "scopes": REQUESTED_SCOPES},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
).hexdigest()
DEFAULT_SECRET = ROOT / ".local-secrets" / "localendpoint-connector.json"
DEFAULT_REPORT = ROOT / "var" / "reports" / "live-connector-pairing-verification.json"
DISCOVERY_PATH = "/.well-known/memoryendpoints-connector"
CONTRACT_PATH = "/api/matm/connector-contract"
OPENAPI_PATH = "/api/matm/openapi.json"
MAX_DISCOVERY_BYTES = 16 * 1024
MAX_CONNECTOR_JSON_BYTES = 64 * 1024
MAX_CONTRACT_BYTES = 128 * 1024
MAX_OPENAPI_BYTES = 1024 * 1024
PUBLIC_RESPONSE_BYTE_LIMITS = {
    DISCOVERY_PATH: MAX_DISCOVERY_BYTES,
    CONTRACT_PATH: MAX_CONTRACT_BYTES,
    OPENAPI_PATH: MAX_OPENAPI_BYTES,
}
EXPECTED_ENDPOINTS = {
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
}
HUMAN_APPROVAL_PATH = "/api/matm/human/connector-pairings/{publicRequestRef}/approve"
HUMAN_CANCEL_PATH = "/api/matm/human/connector-pairings/{publicRequestRef}/cancel"
HUMAN_COMPANY_SELECTION_PATH = "/api/matm/human/connector-pairings/{publicRequestRef}/company-selection"
MUTATION_PATH_SCHEMAS = {
    EXPECTED_ENDPOINTS["pairingRequest"]: "ConnectorPairingRequestInput",
    EXPECTED_ENDPOINTS["authorizationCodeClaim"]: "ConnectorAuthorizationCodeClaimInput",
    EXPECTED_ENDPOINTS["token"]: "ConnectorTokenExchangeInput",
    HUMAN_APPROVAL_PATH: "ConnectorApprovalInput",
    HUMAN_CANCEL_PATH: "ConnectorLifecycleReasonInput",
    HUMAN_COMPANY_SELECTION_PATH: "ConnectorCompanySelectionInput",
    EXPECTED_ENDPOINTS["activation"]: "ConnectorActivationInput",
    EXPECTED_ENDPOINTS["rotation"]: "ConnectorLifecycleReasonInput",
    EXPECTED_ENDPOINTS["rotationActivation"]: "ConnectorActivationInput",
    EXPECTED_ENDPOINTS["revocation"]: "ConnectorLifecycleReasonInput",
    EXPECTED_ENDPOINTS["disconnect"]: "ConnectorLifecycleReasonInput",
    EXPECTED_ENDPOINTS["cancellation"]: "ConnectorLifecycleReasonInput",
}
RECEIPT_FIELDS = {
    "receiptId",
    "action",
    "status",
    "idempotentReplay",
    "rawCredentialExposed",
    "privatePayloadExposed",
    "scopeDigest",
}
ERROR_TOP_LEVEL_FIELDS = {
    "ok",
    "safeNoOp",
    "valuesRedacted",
    "rawCredentialExposed",
    "rawPayloadExposed",
    "error",
}
ERROR_FIELDS = {"code", "title", "detail", "safeNoOp", "valuesRedacted"}
CREDENTIAL_ITEM_FIELDS = {
    "credentialId",
    "status",
    "isCurrent",
    "createdAt",
    "activatedAt",
    "revokedAt",
    "lastUsedAt",
    "approvedScopes",
    "scopeDigest",
}
RECEIPT_RESPONSE_SCHEMAS = (
    "ConnectorPairingRequestResult",
    "ConnectorApprovalResult",
    "ConnectorAuthorizationCodeClaimResult",
    "ConnectorTokenExchangeResult",
    "ConnectorPairingMutationResult",
    "ConnectorPairingRequestMutationResult",
    "ConnectorRotationPrepareResult",
    "ConnectorRotationActivationResult",
    "ConnectorPairingVerification",
    "ConnectorCredentialListResult",
)
FORBIDDEN_CREDENTIAL_KEYS = {
    "connectorCredentialSecret",
    "secret",
    "secretHash",
    "secretVerifier",
    "credentialHash",
    "credentialVerifier",
    "tokenHash",
}


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def sha256_text(value):
    return "sha256:" + hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _header(headers, name):
    wanted = name.lower()
    for key, value in (headers or {}).items():
        if str(key).lower() == wanted:
            return str(value)
    return ""


def _redacted_http_observation(result):
    return {
        "status": result.get("status"),
        "contentType": result.get("contentType"),
        "byteCount": result.get("byteCount"),
        "redirectObserved": result.get("redirectObserved"),
        "jsonParsed": result.get("jsonParsed"),
        "transportError": result.get("transportError"),
    }


def request_json(base_url, path, token=None, maximum_bytes=MAX_CONNECTOR_JSON_BYTES):
    url = base_url.rstrip("/") + path
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = Request(url, headers=headers, method="GET")
    opener = build_opener(NoRedirectHandler())
    status = 0
    response_headers = {}
    raw = b""
    transport_error = ""
    try:
        with opener.open(request, timeout=30) as response:
            status = response.status
            response_headers = dict(response.headers)
            raw = response.read(maximum_bytes + 1)
    except HTTPError as exc:
        status = exc.code
        response_headers = dict(exc.headers)
        raw = exc.read(maximum_bytes + 1)
    except URLError as exc:
        transport_error = type(exc.reason).__name__ if getattr(exc, "reason", None) else type(exc).__name__

    oversized = len(raw) > maximum_bytes
    payload = None
    json_parsed = False
    if raw and not oversized:
        try:
            payload = json.loads(raw.decode("utf-8", errors="strict"))
            json_parsed = isinstance(payload, dict)
        except (UnicodeDecodeError, ValueError):
            payload = None
    content_type = _header(response_headers, "Content-Type").split(";", 1)[0].strip().lower()
    return {
        "status": status,
        "headers": response_headers,
        "contentType": content_type,
        "byteCount": len(raw),
        "oversized": oversized,
        "payload": payload or {},
        "jsonParsed": json_parsed,
        "redirectObserved": 300 <= status < 400 or bool(_header(response_headers, "Location")),
        "transportError": transport_error,
    }


def _schema_from_operation(openapi, path, method="post"):
    operation = ((openapi.get("paths") or {}).get(path) or {}).get(method) or {}
    schema = ((((operation.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {})
    reference = schema.get("$ref") or ""
    if not reference.startswith("#/components/schemas/"):
        return "", {}
    name = reference.rsplit("/", 1)[-1]
    return name, ((openapi.get("components") or {}).get("schemas") or {}).get(name) or {}


def _merge_openapi_schema(left, right):
    """Merge the structural parts of resolved OpenAPI allOf members."""
    merged = dict(left or {})
    for key, value in (right or {}).items():
        if key == "properties":
            properties = dict(merged.get("properties") or {})
            properties.update(value or {})
            merged["properties"] = properties
        elif key == "required":
            required = list(merged.get("required") or [])
            for item in value or []:
                if item not in required:
                    required.append(item)
            merged["required"] = required
        elif key not in ("$ref", "allOf"):
            merged[key] = value
    return merged


def _resolve_openapi_schema(openapi, schema, seen=None):
    """Resolve local component refs and allOf without weakening strict schemas."""
    if not isinstance(schema, dict):
        return {}
    seen = frozenset(seen or ())
    resolved = {}
    reference = schema.get("$ref") or ""
    if reference.startswith("#/components/schemas/"):
        name = reference.rsplit("/", 1)[-1]
        if name not in seen:
            target = ((openapi.get("components") or {}).get("schemas") or {}).get(name) or {}
            resolved = _resolve_openapi_schema(openapi, target, seen | {name})
    for member in schema.get("allOf") or ():
        resolved = _merge_openapi_schema(
            resolved, _resolve_openapi_schema(openapi, member, seen)
        )
    return _merge_openapi_schema(resolved, schema)


def receipt_check(receipt, action=None, status=None):
    receipt = receipt or {}
    return bool(
        RECEIPT_FIELDS.issubset(receipt)
        and isinstance(receipt.get("receiptId"), str)
        and receipt.get("receiptId").startswith("connector-")
        and isinstance(receipt.get("action"), str)
        and isinstance(receipt.get("status"), str)
        and isinstance(receipt.get("idempotentReplay"), bool)
        and receipt.get("rawCredentialExposed") is False
        and receipt.get("privatePayloadExposed") is False
        and receipt.get("scopeDigest") == SCOPE_DIGEST
        and (action is None or receipt.get("action") == action)
        and (status is None or receipt.get("status") == status)
    )


def public_contract_check(discovery_result, contract_result, openapi_result):
    discovery = discovery_result.get("payload") or {}
    contract_envelope = contract_result.get("payload") or {}
    contract = contract_envelope.get("data") or {}
    openapi = openapi_result.get("payload") or {}
    observations = {
        "discovery": _redacted_http_observation(discovery_result),
        "contract": _redacted_http_observation(contract_result),
        "openApi": _redacted_http_observation(openapi_result),
    }
    transport_verified = all(
        item.get("status") == 200
        and item.get("contentType") == "application/json"
        and item.get("jsonParsed")
        and not item.get("redirectObserved")
        and not item.get("transportError")
        for item in observations.values()
    )
    response_bounds_verified = bool(
        discovery_result.get("byteCount", PUBLIC_RESPONSE_BYTE_LIMITS[DISCOVERY_PATH] + 1)
        <= PUBLIC_RESPONSE_BYTE_LIMITS[DISCOVERY_PATH]
        and contract_result.get("byteCount", PUBLIC_RESPONSE_BYTE_LIMITS[CONTRACT_PATH] + 1)
        <= PUBLIC_RESPONSE_BYTE_LIMITS[CONTRACT_PATH]
        and openapi_result.get("byteCount", PUBLIC_RESPONSE_BYTE_LIMITS[OPENAPI_PATH] + 1)
        <= PUBLIC_RESPONSE_BYTE_LIMITS[OPENAPI_PATH]
        and not discovery_result.get("oversized")
        and not contract_result.get("oversized")
        and not openapi_result.get("oversized")
    )
    discovery_verified = bool(
        discovery.get("schemaVersion") == SCHEMA
        and discovery.get("supportedSchemaVersions") == [SCHEMA]
        and discovery.get("issuer") == ISSUER
        and (discovery.get("serviceRoot") or {}).get("exact") == ISSUER
        and discovery.get("endpoints") == EXPECTED_ENDPOINTS
        and discovery.get("requestedScopes") == REQUESTED_SCOPES
        and discovery.get("scopeDigest") == SCOPE_DIGEST
        and all(str(route).startswith("/") and "?" not in str(route) and "#" not in str(route) for route in EXPECTED_ENDPOINTS.values())
        and ((discovery.get("transport") or {}).get("noRedirectsForApiEndpoints") is True)
        and ((discovery.get("transport") or {}).get("sameOriginEndpoints") is True)
    )
    contract_verified = bool(
        contract_envelope.get("ok") is True
        and contract.get("schemaVersion") == SCHEMA
        and contract.get("issuer") == ISSUER
        and contract.get("endpoints") == EXPECTED_ENDPOINTS
        and contract.get("requestedScopes") == REQUESTED_SCOPES
        and contract.get("scopeDigest") == SCOPE_DIGEST
        and ((contract.get("credentialListReadback") or {}).get("limit") == 100)
        and ((contract.get("credentialListReadback") or {}).get("receipt") or {}).get("action") == "list_credentials"
        and "message" not in ((contract.get("errorContract") or {}).get("envelope") or {}).get("error", {})
    )

    paths = openapi.get("paths") or {}
    schemas = ((openapi.get("components") or {}).get("schemas") or {})
    mutation_schemas_verified = True
    mutation_details = {}
    for path, expected_schema_name in MUTATION_PATH_SCHEMAS.items():
        actual_name, schema = _schema_from_operation(openapi, path)
        required = set(schema.get("required") or [])
        verified = bool(
            actual_name == expected_schema_name
            and schema.get("type") == "object"
            and schema.get("additionalProperties") is False
            and "schemaVersion" in required
            and ((schema.get("properties") or {}).get("schemaVersion") or {}).get("const") == SCHEMA
        )
        mutation_details[path] = verified
        mutation_schemas_verified = mutation_schemas_verified and verified

    connector_error = schemas.get("ConnectorError") or {}
    error_properties = set((connector_error.get("properties") or {}).keys())
    nested_error = ((connector_error.get("properties") or {}).get("error") or {})
    nested_properties = set((nested_error.get("properties") or {}).keys())
    error_schema_verified = bool(
        connector_error.get("additionalProperties") is False
        and set(connector_error.get("required") or []) == ERROR_TOP_LEVEL_FIELDS
        and error_properties == ERROR_TOP_LEVEL_FIELDS
        and nested_error.get("additionalProperties") is False
        and set(nested_error.get("required") or []) == ERROR_FIELDS
        and nested_properties == ERROR_FIELDS
        and "invalid_request" in ((((nested_error.get("properties") or {}).get("code") or {}).get("enum")) or [])
        and "pairing_verification_failed" in ((((nested_error.get("properties") or {}).get("code") or {}).get("enum")) or [])
    )

    approval = schemas.get("ConnectorApprovalResult") or {}
    pairing = schemas.get("ConnectorPairingSummary") or {}
    rotation_prepare = schemas.get("ConnectorRotationPrepareResult") or {}
    rotation_activate = schemas.get("ConnectorRotationActivationResult") or {}
    credential_list = schemas.get("ConnectorCredentialListResult") or {}
    rotation_prepare_summary = _resolve_openapi_schema(
        openapi, (rotation_prepare.get("properties") or {}).get("rotation") or {}
    )
    rotation_activate_summary = _resolve_openapi_schema(
        openapi, (rotation_activate.get("properties") or {}).get("rotation") or {}
    )
    public_fields_verified = bool(
        "wakeUpUrl" in (approval.get("properties") or {})
        and "callbackUrl" not in (approval.get("properties") or {})
        and "agentId" not in (((approval.get("properties") or {}).get("approval") or {}).get("properties") or {})
        and "workspaceId" not in (((approval.get("properties") or {}).get("approval") or {}).get("properties") or {})
        and "approvedScopes" in (((approval.get("properties") or {}).get("approval") or {}).get("properties") or {})
        and "scopeDigest" in (((approval.get("properties") or {}).get("approval") or {}).get("properties") or {})
        and "credentialId" in (pairing.get("properties") or {})
        and "credentialId" in (rotation_prepare_summary.get("properties") or {})
        and "credentialId" in (rotation_activate_summary.get("properties") or {})
    )
    credential_item_schema = (((credential_list.get("properties") or {}).get("items") or {}).get("items") or {})
    credential_list_schema_verified = bool(
        set(credential_list.get("required") or {})
        >= {"pairingId", "currentCredentialId", "items", "count", "totalCount", "hasMore", "limit", "receipt"}
        and ((credential_list.get("properties") or {}).get("limit") or {}).get("const") == 100
        and credential_item_schema.get("additionalProperties") is False
        and set(credential_item_schema.get("required") or []) == CREDENTIAL_ITEM_FIELDS
        and set((credential_item_schema.get("properties") or {}).keys()) == CREDENTIAL_ITEM_FIELDS
    )
    connector_receipt = schemas.get("ConnectorReceipt") or {}
    receipt_schema_verified = bool(
        RECEIPT_FIELDS.issubset(set(connector_receipt.get("required") or []))
        and "list_credentials" in ((((connector_receipt.get("properties") or {}).get("action") or {}).get("enum")) or [])
        and all(
            "receipt" in set((schemas.get(name) or {}).get("required") or [])
            and ((schemas.get(name) or {}).get("properties") or {}).get("receipt") is not None
            for name in RECEIPT_RESPONSE_SCHEMAS
        )
    )
    required_paths = set(EXPECTED_ENDPOINTS.values()) | {HUMAN_APPROVAL_PATH, HUMAN_CANCEL_PATH, HUMAN_COMPANY_SELECTION_PATH, "/.well-known/memoryendpoints-connector"}
    openapi_verified = bool(
        openapi.get("openapi") == "3.1.0"
        and required_paths.issubset(paths)
        and mutation_schemas_verified
        and error_schema_verified
        and public_fields_verified
        and credential_list_schema_verified
        and receipt_schema_verified
    )
    result = {
        "transportVerified": transport_verified,
        "responseBoundsVerified": response_bounds_verified,
        "discoveryVerified": discovery_verified,
        "connectorContractVerified": contract_verified,
        "openApiVerified": openapi_verified,
        "mutationSchemasVerified": mutation_schemas_verified,
        "mutationSchemaChecks": mutation_details,
        "errorSchemaVerified": error_schema_verified,
        "publicCanonicalFieldsVerified": public_fields_verified,
        "credentialListSchemaVerified": credential_list_schema_verified,
        "receiptSchemasVerified": receipt_schema_verified,
        "observations": observations,
    }
    result["ok"] = all(
        result[key]
        for key in (
            "transportVerified",
            "responseBoundsVerified",
            "discoveryVerified",
            "connectorContractVerified",
            "openApiVerified",
            "mutationSchemasVerified",
            "errorSchemaVerified",
            "publicCanonicalFieldsVerified",
            "credentialListSchemaVerified",
            "receiptSchemasVerified",
        )
    )
    return result


def authenticated_lifecycle_check(pairing_result, credentials_result, me_result, workspace_result, expected):
    pairing_payload = pairing_result.get("payload") or {}
    credential_payload = credentials_result.get("payload") or {}
    me_payload = me_result.get("payload") or {}
    workspace_payload = workspace_result.get("payload") or {}
    pairing = pairing_payload.get("pairing") or {}
    verification = pairing_payload.get("verification") or {}
    principal = me_payload.get("principal") or {}
    workspace = workspace_payload.get("workspace") or workspace_payload
    items = credential_payload.get("items") or []
    expected_pairing_id = expected.get("pairingId") or ""
    expected_workspace_id = expected.get("workspaceId") or ""
    expected_agent_id = expected.get("agentId") or ""
    expected_credential_id = expected.get("credentialId") or ""

    transport_verified = all(
        result.get("status") == 200
        and result.get("contentType") == "application/json"
        and result.get("jsonParsed")
        and not result.get("redirectObserved")
        and not result.get("oversized")
        for result in (pairing_result, credentials_result, me_result, workspace_result)
    )
    exact_pairing_verified = bool(
        pairing_payload.get("ok") is True
        and pairing_payload.get("schemaVersion") == SCHEMA
        and pairing.get("pairingId") == expected_pairing_id
        and pairing.get("credentialId") == expected_credential_id
        and ((pairing.get("workspace") or {}).get("workspaceId") == expected_workspace_id)
        and ((pairing.get("agent") or {}).get("agentId") == expected_agent_id)
        and pairing_payload.get("approvedScopes") == REQUESTED_SCOPES
        and pairing_payload.get("scopeDigest") == SCOPE_DIGEST
        and pairing.get("approvedScopes") == REQUESTED_SCOPES
        and pairing.get("scopeDigest") == SCOPE_DIGEST
        and ((pairing.get("grant") or {}).get("credentialType") == "connector_agent")
        and ((pairing.get("grant") or {}).get("approvedScopes") == REQUESTED_SCOPES)
        and ((pairing.get("grant") or {}).get("scopeDigest") == SCOPE_DIGEST)
        and all(
            verification.get(field) is True
            for field in (
                "canonicalWorkspaceReadable",
                "canonicalWorkspaceIdMatches",
                "exactAgentReadable",
                "exactAgentIdMatches",
                "credentialScopedToConnectorAndAgent",
                "grantActive",
            )
        )
        and verification.get("grantRevoked") is False
        and receipt_check(pairing_payload.get("receipt"), "verify", "verified")
    )
    item_shapes_verified = bool(
        isinstance(items, list)
        and len(items) <= 100
        and all(set(item) == CREDENTIAL_ITEM_FIELDS for item in items)
        and not any(FORBIDDEN_CREDENTIAL_KEYS.intersection(item) for item in items)
    )
    credential_inventory_verified = bool(
        credential_payload.get("ok") is True
        and credential_payload.get("schemaVersion") == SCHEMA
        and credential_payload.get("pairingId") == expected_pairing_id
        and credential_payload.get("currentCredentialId") == expected_credential_id
        and credential_payload.get("approvedScopes") == REQUESTED_SCOPES
        and credential_payload.get("scopeDigest") == SCOPE_DIGEST
        and credential_payload.get("count") == len(items)
        and isinstance(credential_payload.get("totalCount"), int)
        and credential_payload.get("totalCount") >= len(items)
        and credential_payload.get("limit") == 100
        and isinstance(credential_payload.get("hasMore"), bool)
        and item_shapes_verified
        and all(item.get("approvedScopes") == REQUESTED_SCOPES and item.get("scopeDigest") == SCOPE_DIGEST for item in items)
        and any(item.get("credentialId") == expected_credential_id and item.get("isCurrent") is True and item.get("status") == "active" for item in items)
        and receipt_check(credential_payload.get("receipt"), "list_credentials", "verified")
        and credential_payload.get("valuesRedacted") is True
        and credential_payload.get("rawCredentialExposed") is False
        and credential_payload.get("rawPayloadExposed") is False
    )
    principal_verified = bool(
        me_payload.get("ok") is True
        and principal.get("credentialType") == "connector_agent"
        and principal.get("credentialId") == expected_credential_id
        and principal.get("agentId") == expected_agent_id
        and principal.get("approvedScopes") == REQUESTED_SCOPES
        and principal.get("scopeDigest") == SCOPE_DIGEST
        and ((principal.get("resourceContext") or {}).get("workspaceId") == expected_workspace_id)
        and ((principal.get("grant") or {}).get("scopeType") == "agent")
        and ((principal.get("grant") or {}).get("scopeId") == expected_agent_id)
        and ((principal.get("grant") or {}).get("approvedScopes") == REQUESTED_SCOPES)
        and ((principal.get("grant") or {}).get("scopeDigest") == SCOPE_DIGEST)
    )
    workspace_verified = bool(
        workspace_payload.get("ok") is True
        and (workspace.get("workspaceId") or workspace_payload.get("workspaceId")) == expected_workspace_id
        and workspace_payload.get("approvedScopes") == REQUESTED_SCOPES
        and workspace_payload.get("scopeDigest") == SCOPE_DIGEST
    )
    redaction_verified = all(
        payload.get("rawCredentialExposed") is False
        and payload.get("rawPayloadExposed") is False
        for payload in (pairing_payload, credential_payload, me_payload, workspace_payload)
    )
    result = {
        "attempted": True,
        "transportVerified": transport_verified,
        "exactPairingVerified": exact_pairing_verified,
        "credentialInventoryVerified": credential_inventory_verified,
        "credentialItemShapesVerified": item_shapes_verified,
        "principalVerified": principal_verified,
        "workspaceVerified": workspace_verified,
        "redactionVerified": redaction_verified,
        "pairingIdHash": sha256_text(expected_pairing_id),
        "workspaceIdHash": sha256_text(expected_workspace_id),
        "agentIdHash": sha256_text(expected_agent_id),
        "credentialIdHash": sha256_text(expected_credential_id),
        "credentialCount": len(items),
        "observedCredentialStatuses": sorted({str(item.get("status") or "") for item in items}),
        "observations": {
            "pairing": _redacted_http_observation(pairing_result),
            "credentials": _redacted_http_observation(credentials_result),
            "me": _redacted_http_observation(me_result),
            "workspace": _redacted_http_observation(workspace_result),
        },
    }
    result["ok"] = all(
        result[key]
        for key in (
            "transportVerified",
            "exactPairingVerified",
            "credentialInventoryVerified",
            "credentialItemShapesVerified",
            "principalVerified",
            "workspaceVerified",
            "redactionVerified",
        )
    )
    return result


def _validate_service_root(value):
    parsed = urlsplit(str(value or ""))
    if (
        str(value or "").rstrip("/") != ISSUER
        or parsed.scheme != "https"
        or parsed.hostname != "memoryendpoints.com"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("live connector verification requires the exact https://memoryendpoints.com service root")
    return ISSUER


def _safe_report_path(value):
    path = Path(value).resolve()
    try:
        relative = path.relative_to(ROOT.resolve())
    except ValueError:
        return path
    if not relative.parts or relative.parts[0].lower() != "var":
        raise ValueError("connector verification reports inside the repository must be written under ignored var/")
    return path


def write_report(path, report):
    path = _safe_report_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def build_report(base_url, public_check, authenticated_check=None, require_authenticated=False, secrets=None):
    authenticated_check = authenticated_check or {"attempted": False, "ok": False}
    report = {
        "schemaVersion": "memoryendpoints.live_connector_pairing_verification.v1",
        "issuer": base_url,
        "public": public_check,
        "authenticatedLifecycle": authenticated_check,
        "authenticatedLifecycleRequired": bool(require_authenticated),
        "valuesRedacted": True,
        "rawCredentialValuesStored": False,
        "rawTenantIdentifiersStored": False,
        "trackedDocumentationWritten": False,
    }
    serialized = json.dumps(report, sort_keys=True)
    secrets = secrets or {}
    raw_token = secrets.get("connectorCredentialSecret") or ""
    raw_identifiers = [
        secrets.get("pairingId") or "",
        secrets.get("workspaceId") or "",
        secrets.get("agentId") or "",
        secrets.get("credentialId") or "",
    ]
    report["rawCredentialValuesStored"] = bool(raw_token and raw_token in serialized)
    report["rawTenantIdentifiersStored"] = any(value and value in serialized for value in raw_identifiers)
    report["ok"] = bool(
        public_check.get("ok")
        and (authenticated_check.get("ok") if require_authenticated or authenticated_check.get("attempted") else True)
        and not report["rawCredentialValuesStored"]
        and not report["rawTenantIdentifiersStored"]
    )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=ISSUER)
    parser.add_argument("--secret", default=str(DEFAULT_SECRET))
    parser.add_argument("--json-out", default=str(DEFAULT_REPORT))
    parser.add_argument("--skip-authenticated", action="store_true")
    parser.add_argument("--require-authenticated", action="store_true")
    args = parser.parse_args(argv)

    base_url = _validate_service_root(args.base_url)
    discovery = request_json(base_url, DISCOVERY_PATH, maximum_bytes=PUBLIC_RESPONSE_BYTE_LIMITS[DISCOVERY_PATH])
    contract = request_json(base_url, CONTRACT_PATH, maximum_bytes=PUBLIC_RESPONSE_BYTE_LIMITS[CONTRACT_PATH])
    openapi = request_json(base_url, OPENAPI_PATH, maximum_bytes=PUBLIC_RESPONSE_BYTE_LIMITS[OPENAPI_PATH])
    public_check = public_contract_check(discovery, contract, openapi)

    secret_path = Path(args.secret)
    secrets = {}
    authenticated_check = {"attempted": False, "ok": False}
    if not args.skip_authenticated and secret_path.exists():
        secrets = read_json(secret_path)
        required = ("connectorCredentialSecret", "pairingId", "workspaceId", "agentId", "credentialId")
        missing = [field for field in required if not secrets.get(field)]
        if missing:
            raise RuntimeError("connector secret file is missing required non-output fields: %s" % ", ".join(missing))
        token = secrets["connectorCredentialSecret"]
        pairing_id = secrets["pairingId"]
        pairing = request_json(base_url, EXPECTED_ENDPOINTS["status"].replace("{pairingId}", pairing_id), token=token)
        credentials = request_json(base_url, EXPECTED_ENDPOINTS["credentialList"].replace("{pairingId}", pairing_id), token=token)
        me = request_json(base_url, "/api/matm/me", token=token)
        workspace = request_json(base_url, "/api/matm/workspace", token=token)
        authenticated_check = authenticated_lifecycle_check(pairing, credentials, me, workspace, secrets)
    elif args.require_authenticated:
        raise RuntimeError("authenticated connector verification requires the local secret file")

    report = build_report(base_url, public_check, authenticated_check, args.require_authenticated, secrets)
    output = write_report(args.json_out, report)
    print(json.dumps({"ok": report["ok"], "schemaVersion": report["schemaVersion"], "reportPath": str(output), "publicVerified": public_check.get("ok"), "authenticatedVerified": authenticated_check.get("ok")}, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
