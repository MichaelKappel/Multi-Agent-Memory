"""Security primitives for ``memoryendpoints.connector_pairing.v1``.

This module deliberately has no HTTP or storage dependencies.  It owns the
strict public policy shared by the pairing routes: issuer and redirect
validation, PKCE, short-lived opaque values, persistence-safe verifiers,
exact-retry classification, deterministic recovery of a pending connector
credential, and public-safe discovery/receipt envelopes.

Raw connector credentials are returned only through :class:`OneTimeSecret`.
Its representation and persistence projection are intentionally redacted.
"""

import base64
import datetime
from enum import Enum
import hashlib
import hmac
import json
import math
import re
import secrets
import unicodedata
from urllib.parse import urlsplit, urlunsplit


SCHEMA = "memoryendpoints.connector_pairing.v1"
SCHEMA_VERSION = SCHEMA
ISSUER = "https://memoryendpoints.com"
CLIENT_ID = "localendpoint-connect"
CANONICAL_AGENT_ID = "localendpoint-agent"
CANONICAL_AGENT_DISPLAY_NAME = "LocalEndpoint Agent"

DISCOVERY_PATH = "/.well-known/memoryendpoints-connector"
PAIRING_REQUEST_PATH = "/api/matm/connector-pairings/requests"
AUTHORIZE_PATH = "/connect/authorize"
TOKEN_PATH = "/api/matm/connector-pairings/token"
AUTHORIZATION_CODE_CLAIM_PATH = "/api/matm/connector-pairings/authorization-code-claims"
PAIRING_RESOURCE_PATH_TEMPLATE = "/api/matm/connector-pairings/{pairingId}"
APPROVAL_PATH_TEMPLATE = "/api/matm/human/connector-pairings/{publicRequestRef}/approve"
ACTIVATION_PATH = PAIRING_RESOURCE_PATH_TEMPLATE + "/activate"
STATUS_PATH = PAIRING_RESOURCE_PATH_TEMPLATE
ROTATION_PATH = PAIRING_RESOURCE_PATH_TEMPLATE + "/rotations"
ROTATION_ACTIVATION_PATH = ROTATION_PATH + "/{rotationId}/activate"
CREDENTIALS_PATH = PAIRING_RESOURCE_PATH_TEMPLATE + "/credentials"
REVOCATION_PATH = PAIRING_RESOURCE_PATH_TEMPLATE + "/revoke"
DISCONNECT_PATH = PAIRING_RESOURCE_PATH_TEMPLATE + "/disconnect"
CANCELLATION_PATH = PAIRING_RESOURCE_PATH_TEMPLATE + "/cancel"

REGISTERED_CUSTOM_REDIRECT_URI = "localendpoint-connect://memoryendpoints/callback"
LOOPBACK_REDIRECT_PATH = "/memoryendpoints/callback"
LOOPBACK_MIN_PORT = 1024
LOOPBACK_MAX_PORT = 65535

PAIRING_REQUEST_TTL_SECONDS = 600
AUTHORIZATION_CODE_TTL_SECONDS = 60
PENDING_ACTIVATION_TTL_SECONDS = 600

PKCE_METHOD = "S256"
PKCE_VERIFIER_MIN_LENGTH = 43
PKCE_VERIFIER_MAX_LENGTH = 128
OPAQUE_VALUE_BYTES = 32
MIN_PEPPER_BYTES = 32
MAX_PEPPER_BYTES = 4096
MAX_CANONICAL_REQUEST_BYTES = 32 * 1024
MAX_JSON_REQUEST_BYTES = 32 * 1024
MAX_DISCOVERY_RESPONSE_BYTES = 16 * 1024
AGENT_NAME_MIN_LENGTH = 3
AGENT_NAME_MAX_LENGTH = 64

_PKCE_PATTERN = re.compile(r"[A-Za-z0-9._~-]{43,128}")
_STATE_PATTERN = re.compile(r"[A-Za-z0-9._~-]{43,128}")
_B64URL_256_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")
_OPAQUE_VALUE_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")
_PUBLIC_ID_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{7,95}")
_REQUEST_DIGEST_PATTERN = re.compile(r"sha256-v1:[a-f0-9]{64}")
_HMAC_VERIFIER_PATTERN = re.compile(r"hmac-sha256-v1:[a-f0-9]{64}")
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"[\x21-\x7e]{16,200}")
_RECEIPT_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{8,128}")
_AGENT_NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
PUBLIC_REQUEST_REF_PATTERN = r"pairref_[A-Za-z0-9_-]{43}"
_PUBLIC_REQUEST_REF_PATTERN = re.compile(PUBLIC_REQUEST_REF_PATTERN)
_PAIRING_REQUEST_PROOF_PATTERN = re.compile(
    r"me_pairproof_v1\.([A-Za-z][A-Za-z0-9_-]{7,95})\.([A-Za-z0-9_-]{43})"
)
_AUTHORIZATION_CODE_PATTERN = re.compile(
    r"me_paircode_v1\.([A-Za-z][A-Za-z0-9_-]{7,95})\.([A-Za-z0-9_-]{43})"
)

V1_REQUESTED_SCOPES = (
    "connector:self:readback",
    "agent:self:register",
    "memory:public-safe:submit",
    "memory:search:read",
)
CONNECTOR_SCOPE_IMPACT_LABELS = {
    "connector:self:readback": "Verify this exact connector, workspace, and agent binding.",
    "agent:self:register": "Register the exact LocalEndpoint agent during activation.",
    "memory:public-safe:submit": "Submit public-safe memory as this exact connector agent.",
    "memory:search:read": "Search memory readable by this exact connector grant.",
}

_HMAC_CONTEXTS = frozenset(
    {
        "pairing_request_proof",
        "pairing_request_proof_derivation",
        "pairing_state",
        "authorization_code",
        "authorization_code_derivation",
        "connector_secret",
        "idempotency_key",
        "pending_connector_derivation",
    }
)

RATE_LIMIT_POLICIES = {
    "discovery": {
        "limit": 60,
        "windowSeconds": 60,
        "partition": "source_ip",
    },
    "authorize": {
        "limit": 10,
        "windowSeconds": 600,
        "partition": "source_ip_and_client",
    },
    "pairingRequest": {
        "limit": 10,
        "windowSeconds": 600,
        "partition": "source_ip_and_client",
    },
    "tokenExchange": {
        "limit": 10,
        "windowSeconds": 600,
        "partition": "source_ip_and_client",
    },
    "authorizationCodeClaim": {
        "limit": 10,
        "windowSeconds": 600,
        "partition": "source_ip_and_client",
    },
    "activation": {
        "limit": 20,
        "windowSeconds": 600,
        "partition": "pending_grant",
    },
    "status": {
        "limit": 60,
        "windowSeconds": 60,
        "partition": "connector_credential",
    },
    "credentialLifecycle": {
        "limit": 10,
        "windowSeconds": 3600,
        "partition": "connector_credential",
    },
    "selfRegistration": {
        "limit": 5,
        "windowSeconds": 600,
        "partition": "connector_credential",
    },
    "publicSafeSubmit": {
        "limit": 60,
        "windowSeconds": 60,
        "partition": "connector_credential",
    },
    "search": {
        "limit": 120,
        "windowSeconds": 60,
        "partition": "connector_credential",
    },
}

_SAFE_ERROR_MESSAGES = {
    "invalid_request": "The pairing request is invalid.",
    "invalid_service_root": "The service root is not supported.",
    "invalid_redirect_uri": "The redirect URI is not registered.",
    "invalid_client": "The connector client is not supported.",
    "invalid_state": "The pairing state is invalid.",
    "invalid_pkce": "PKCE verification failed.",
    "invalid_code": "The authorization code is invalid.",
    "code_expired": "The authorization code expired.",
    "code_replayed": "The authorization code was already used.",
    "request_expired": "The pairing request expired.",
    "pending_grant_expired": "The pending connector grant expired.",
    "grant_not_active": "The connector grant is not active.",
    "grant_revoked": "The connector grant was revoked.",
    "idempotency_conflict": "The idempotency key was used for another request.",
    "rate_limited": "Too many pairing requests were made.",
    "not_found": "The requested pairing resource was not found.",
    "service_error": "The pairing service is temporarily unavailable.",
}

_SAFE_RECEIPT_ACTIONS = frozenset(
    {
        "authorize",
        "exchange",
        "activate",
        "verify",
        "rotate",
        "revoke",
        "disconnect",
        "cancel",
    }
)
_SAFE_RECEIPT_STATUSES = frozenset(
    {
        "approved",
        "pending_activation",
        "active",
        "verified",
        "rotated",
        "revoked",
        "disconnected",
        "cancelled",
        "already_complete",
    }
)


class PairingPolicyError(ValueError):
    """A stable, public-safe pairing policy failure."""

    def __init__(self, code):
        self.code = str(code)
        super().__init__(self.code)


class ReplayDecision(str, Enum):
    """Storage-independent decisions for a one-use, exact-retry operation."""

    FIRST_USE = "first_use"
    EXACT_RETRY = "exact_retry"
    REPLAY_REJECTED = "replay_rejected"
    EXPIRED = "expired"


class OneTimeSecret:
    """Transient raw credential plus only its persistence-safe projection."""

    __slots__ = ("_secret", "_public_id", "_verifier")

    def __init__(self, secret, public_id, verifier):
        self._secret = secret
        self._public_id = public_id
        self._verifier = verifier

    @property
    def public_id(self):
        return self._public_id

    def reveal(self):
        """Reveal the raw value for one protected response boundary."""
        return self._secret

    def persistable_state(self):
        """Return state that can be stored without the raw credential."""
        return {
            "credentialId": self._public_id,
            "credentialType": "connector_agent",
            "credentialVerifier": self._verifier,
            "rawCredentialPersisted": False,
        }

    def __repr__(self):
        return "OneTimeSecret(public_id=%r, secret=[REDACTED])" % self._public_id

    def __str__(self):
        return "[REDACTED]"

    def __reduce__(self):
        raise TypeError("OneTimeSecret is transient and cannot be serialized")


def _b64url_encode(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _validate_unpadded_b64url_256(value, code):
    if not isinstance(value, str) or _B64URL_256_PATTERN.fullmatch(value) is None:
        raise PairingPolicyError(code)
    try:
        decoded = base64.urlsafe_b64decode(value + "=")
    except (ValueError, TypeError) as exc:
        raise PairingPolicyError(code) from exc
    if len(decoded) != 32 or _b64url_encode(decoded) != value:
        raise PairingPolicyError(code)
    return value


def _validate_pepper(pepper):
    if isinstance(pepper, bytearray):
        pepper = bytes(pepper)
    if not isinstance(pepper, bytes) or not MIN_PEPPER_BYTES <= len(pepper) <= MAX_PEPPER_BYTES:
        raise PairingPolicyError("credential_pepper_invalid")
    return pepper


def _validate_public_id(value, code="public_id_invalid"):
    if not isinstance(value, str) or _PUBLIC_ID_PATTERN.fullmatch(value) is None:
        raise PairingPolicyError(code)
    return value


def validate_service_root(value):
    """Validate and canonicalize the only v1 issuer/service root.

    The empty root path and a single trailing slash are equivalent inputs.  An
    explicit port, even 443, is rejected so the normalized issuer is exact.
    """
    if not isinstance(value, str) or not value or value != value.strip():
        raise PairingPolicyError("invalid_service_root")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise PairingPolicyError("invalid_service_root") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "memoryendpoints.com"
        or parsed.netloc != "memoryendpoints.com"
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise PairingPolicyError("invalid_service_root")
    return ISSUER


def validate_client_id(value):
    if not isinstance(value, str) or not hmac.compare_digest(value, CLIENT_ID):
        raise PairingPolicyError("invalid_client")
    return CLIENT_ID


def validate_redirect_uri(value, registered_custom_redirects=None):
    """Validate one registered custom URI or an exact IPv4 loopback callback."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise PairingPolicyError("invalid_redirect_uri")
    allowed_custom = tuple(registered_custom_redirects or (REGISTERED_CUSTOM_REDIRECT_URI,))
    if value in allowed_custom:
        if value != REGISTERED_CUSTOM_REDIRECT_URI:
            # v1 publishes exactly one custom callback, not a pattern-based
            # allowlist whose entries could silently widen the public contract.
            raise PairingPolicyError("invalid_redirect_uri")
        return value
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise PairingPolicyError("invalid_redirect_uri") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != LOOPBACK_REDIRECT_PATH
        or parsed.query
        or parsed.fragment
        or port is None
        or not LOOPBACK_MIN_PORT <= port <= LOOPBACK_MAX_PORT
        or parsed.netloc != "127.0.0.1:%d" % port
    ):
        raise PairingPolicyError("invalid_redirect_uri")
    return "http://127.0.0.1:%d%s" % (port, LOOPBACK_REDIRECT_PATH)


def agent_name_policy():
    """Return the canonical company-scoped agent-name contract."""
    return {
        "minimumLength": AGENT_NAME_MIN_LENGTH,
        "maximumLength": AGENT_NAME_MAX_LENGTH,
        "allowedPattern": r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        "canonicalization": "nfkc_trim_lowercase",
        "unicodeInputRule": "normalized_result_must_be_ascii",
        "uniquenessScope": "company",
        "collisionCode": "agent_name_unavailable",
        "automaticSuffixing": False,
    }


def normalize_company_agent_name(value):
    """Normalize one human-readable agent name for company-scoped uniqueness."""
    if not isinstance(value, str):
        raise PairingPolicyError("invalid_agent_identity")
    normalized = unicodedata.normalize("NFKC", value).strip(" \t\r\n\f\v").lower()
    try:
        normalized.encode("ascii")
    except UnicodeEncodeError as exc:
        raise PairingPolicyError("invalid_agent_identity") from exc
    if (
        not AGENT_NAME_MIN_LENGTH <= len(normalized) <= AGENT_NAME_MAX_LENGTH
        or _AGENT_NAME_PATTERN.fullmatch(normalized) is None
    ):
        raise PairingPolicyError("invalid_agent_identity")
    return normalized


def normalize_connector_agent_name(value):
    """Accept only the byte-for-byte canonical v1 connector agent id."""
    if not isinstance(value, str):
        raise PairingPolicyError("invalid_agent_identity")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise PairingPolicyError("invalid_agent_identity") from exc
    if not hmac.compare_digest(value, CANONICAL_AGENT_ID):
        raise PairingPolicyError("invalid_agent_identity")
    return CANONICAL_AGENT_ID


def validate_requested_scopes(value):
    """Return the only v1 connector scope tuple or reject before persistence."""
    if not isinstance(value, (list, tuple)) or tuple(value) != V1_REQUESTED_SCOPES:
        raise PairingPolicyError("connector_scopes_invalid")
    return V1_REQUESTED_SCOPES


def connector_scope_digest(value=V1_REQUESTED_SCOPES):
    """Return a deterministic digest binding every connector credential."""
    scopes = validate_requested_scopes(value)
    encoded = json.dumps(
        {"schemaVersion": SCHEMA, "scopes": list(scopes)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256-v1:" + hashlib.sha256(encoded).hexdigest()


def validate_persisted_connector_scope(value, scope_digest):
    """Validate one persisted v1 scope binding independently of peer records.

    Storage records must never be trusted merely because their copied scope
    fields agree with each other.  This helper first enforces the exact ordered
    v1 scope set, then recomputes the schema-bound digest and compares it in
    constant time.  Callers may safely use the returned canonical tuple only
    after this check succeeds.
    """
    scopes = validate_requested_scopes(value)
    expected = connector_scope_digest(scopes)
    if not isinstance(scope_digest, str) or not hmac.compare_digest(
        scope_digest, expected
    ):
        raise PairingPolicyError("connector_scopes_invalid")
    return scopes


def connector_scope_impacts(value=V1_REQUESTED_SCOPES):
    scopes = validate_requested_scopes(value)
    return [
        {"scope": scope, "impact": CONNECTOR_SCOPE_IMPACT_LABELS[scope]}
        for scope in scopes
    ]


def generate_state():
    """Generate 256 bits of desktop-owned CSRF/correlation state."""
    return _b64url_encode(secrets.token_bytes(OPAQUE_VALUE_BYTES))


def validate_state(value):
    if not isinstance(value, str) or _STATE_PATTERN.fullmatch(value) is None:
        raise PairingPolicyError("invalid_state")
    return value


def derive_authorization_code(pepper, code_id, approval_request_digest, scope_digest):
    """Re-derive one prefixed approval code for an exact lost-response retry."""
    pepper = _validate_pepper(pepper)
    code_id = _validate_public_id(code_id, "authorization_code_id_invalid")
    if not isinstance(approval_request_digest, str) or _REQUEST_DIGEST_PATTERN.fullmatch(
        approval_request_digest
    ) is None:
        raise PairingPolicyError("request_digest_invalid")
    if not isinstance(scope_digest, str) or _REQUEST_DIGEST_PATTERN.fullmatch(scope_digest) is None:
        raise PairingPolicyError("scope_digest_invalid")
    message = _hmac_message(
        "authorization_code_derivation",
        json.dumps(
            [code_id, approval_request_digest, scope_digest],
            ensure_ascii=True,
            separators=(",", ":"),
        ),
    )
    material = _b64url_encode(hmac.new(pepper, message, hashlib.sha256).digest())
    return "me_paircode_v1.%s.%s" % (code_id, material)


def validate_authorization_code(value):
    if not isinstance(value, str) or _AUTHORIZATION_CODE_PATTERN.fullmatch(value) is None:
        raise PairingPolicyError("invalid_code")
    return value


def parse_authorization_code(value):
    validate_authorization_code(value)
    return _AUTHORIZATION_CODE_PATTERN.fullmatch(value).group(1)


def generate_public_request_ref():
    """Generate a persisted tenant-neutral reference with no authority."""
    return "pairref_" + _b64url_encode(secrets.token_bytes(OPAQUE_VALUE_BYTES))


def validate_public_request_ref(value):
    if not isinstance(value, str) or _PUBLIC_REQUEST_REF_PATTERN.fullmatch(value) is None:
        raise PairingPolicyError("public_request_ref_invalid")
    return value


def derive_pairing_request_proof(pepper, request_id, request_digest, scope_digest):
    """Re-derive the body-only pairing proof for an exact request retry.

    Only its contextual verifier and bounded derivation inputs are persisted.
    The separate ``publicRequestRef`` is non-secret and cannot prove authority.
    """
    pepper = _validate_pepper(pepper)
    request_id = _validate_public_id(request_id, "request_id_invalid")
    if not isinstance(request_digest, str) or _REQUEST_DIGEST_PATTERN.fullmatch(request_digest) is None:
        raise PairingPolicyError("request_digest_invalid")
    if not isinstance(scope_digest, str) or _REQUEST_DIGEST_PATTERN.fullmatch(scope_digest) is None:
        raise PairingPolicyError("scope_digest_invalid")
    message = _hmac_message(
        "pairing_request_proof_derivation",
        json.dumps(
            [request_id, request_digest, scope_digest],
            ensure_ascii=True,
            separators=(",", ":"),
        ),
    )
    material = _b64url_encode(hmac.new(pepper, message, hashlib.sha256).digest())
    return "me_pairproof_v1.%s.%s" % (request_id, material)


def validate_pairing_request_proof(value):
    if not isinstance(value, str) or _PAIRING_REQUEST_PROOF_PATTERN.fullmatch(value) is None:
        raise PairingPolicyError("pairing_request_proof_invalid")
    return value


def parse_pairing_request_proof(value):
    validate_pairing_request_proof(value)
    return _PAIRING_REQUEST_PROOF_PATTERN.fullmatch(value).group(1)


def build_authorization_url(public_request_ref):
    """Build an approval URL containing only its public non-authorizing ref."""
    return _endpoint(AUTHORIZE_PATH + "/" + validate_public_request_ref(public_request_ref))


def build_wake_up_url(redirect_uri):
    """Return a registered callback byte-for-byte with no parameters added."""
    validated = validate_redirect_uri(redirect_uri)
    if not hmac.compare_digest(validated, redirect_uri):
        raise PairingPolicyError("invalid_redirect_uri")
    return redirect_uri


def generate_connector_credential_id():
    """Generate non-secret recovery metadata for one connector credential."""
    return "connector_" + _b64url_encode(secrets.token_bytes(18))


def _connector_secret_value(credential_id, secret_material):
    _validate_public_id(credential_id, "credential_id_invalid")
    if not isinstance(secret_material, bytes) or len(secret_material) != OPAQUE_VALUE_BYTES:
        raise PairingPolicyError("connector_secret_material_invalid")
    return "me_connector_v1.%s.%s" % (credential_id, _b64url_encode(secret_material))


def connector_secret_verifier(value, pepper, scope_digest):
    if not isinstance(scope_digest, str) or _REQUEST_DIGEST_PATTERN.fullmatch(scope_digest) is None:
        raise PairingPolicyError("scope_digest_invalid")
    material = json.dumps([value, scope_digest], ensure_ascii=True, separators=(",", ":"))
    return contextual_hmac_verifier(material, pepper, "connector_secret")


def verify_connector_secret(value, verifier, pepper, scope_digest):
    try:
        expected = connector_secret_verifier(value, pepper, scope_digest)
    except PairingPolicyError:
        return False
    valid = isinstance(verifier, str) and _HMAC_VERIFIER_PATTERN.fullmatch(verifier) is not None
    candidate = verifier if valid else "hmac-sha256-v1:" + ("0" * 64)
    return bool(valid and hmac.compare_digest(expected, candidate))


def generate_connector_secret(pepper, scope_digest, credential_id=None):
    """Issue a fresh connector secret for initial issue or rotation."""
    credential_id = credential_id or generate_connector_credential_id()
    raw = _connector_secret_value(credential_id, secrets.token_bytes(OPAQUE_VALUE_BYTES))
    verifier = connector_secret_verifier(raw, pepper, scope_digest)
    return OneTimeSecret(raw, credential_id, verifier)


def _validate_pkce_verifier(value):
    if not isinstance(value, str) or _PKCE_PATTERN.fullmatch(value) is None:
        raise PairingPolicyError("invalid_pkce")
    return value


def pkce_s256_challenge(verifier):
    """Return the RFC 7636 S256 challenge for a canonical verifier."""
    verifier = _validate_pkce_verifier(verifier)
    return _b64url_encode(hashlib.sha256(verifier.encode("ascii")).digest())


def validate_pkce_s256(verifier, expected_challenge):
    """Validate a verifier/challenge pair using constant-time comparison."""
    actual = pkce_s256_challenge(verifier)
    expected = _validate_unpadded_b64url_256(expected_challenge, "invalid_pkce")
    if not hmac.compare_digest(actual, expected):
        raise PairingPolicyError("invalid_pkce")
    return True


def _hmac_message(context, value):
    if context not in _HMAC_CONTEXTS:
        raise PairingPolicyError("verifier_context_invalid")
    if not isinstance(value, str) or not 1 <= len(value) <= 4096 or "\x00" in value:
        raise PairingPolicyError("verifier_value_invalid")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PairingPolicyError("verifier_value_invalid") from exc
    return b"\x00".join(
        (
            SCHEMA.encode("ascii"),
            context.encode("ascii"),
            str(len(encoded)).encode("ascii"),
            encoded,
        )
    )


def contextual_hmac_verifier(value, pepper, context):
    """Create a domain-separated verifier suitable for persistence."""
    digest = hmac.new(_validate_pepper(pepper), _hmac_message(context, value), hashlib.sha256)
    return "hmac-sha256-v1:" + digest.hexdigest()


def verify_contextual_hmac(value, verifier, pepper, context):
    """Verify a raw value without accepting malformed verifier shortcuts."""
    try:
        expected = contextual_hmac_verifier(value, pepper, context)
    except PairingPolicyError:
        return False
    valid = isinstance(verifier, str) and _HMAC_VERIFIER_PATTERN.fullmatch(verifier) is not None
    candidate = verifier if valid else "hmac-sha256-v1:" + ("0" * 64)
    return bool(valid and hmac.compare_digest(expected, candidate))


def _scope_bound_verifier(value, pepper, context, scope_digest):
    if not isinstance(scope_digest, str) or _REQUEST_DIGEST_PATTERN.fullmatch(scope_digest) is None:
        raise PairingPolicyError("scope_digest_invalid")
    material = json.dumps([value, scope_digest], ensure_ascii=True, separators=(",", ":"))
    return contextual_hmac_verifier(material, pepper, context)


def _verify_scope_bound(value, verifier, pepper, context, scope_digest):
    try:
        expected = _scope_bound_verifier(value, pepper, context, scope_digest)
    except PairingPolicyError:
        return False
    valid = isinstance(verifier, str) and _HMAC_VERIFIER_PATTERN.fullmatch(verifier) is not None
    candidate = verifier if valid else "hmac-sha256-v1:" + ("0" * 64)
    return bool(valid and hmac.compare_digest(expected, candidate))


def pairing_request_proof_verifier(value, pepper, scope_digest):
    validate_pairing_request_proof(value)
    return _scope_bound_verifier(value, pepper, "pairing_request_proof", scope_digest)


def verify_pairing_request_proof(value, verifier, pepper, scope_digest):
    try:
        validate_pairing_request_proof(value)
    except PairingPolicyError:
        return False
    return _verify_scope_bound(value, verifier, pepper, "pairing_request_proof", scope_digest)


def pairing_state_verifier(value, pepper, scope_digest):
    validate_state(value)
    return _scope_bound_verifier(value, pepper, "pairing_state", scope_digest)


def verify_pairing_state(value, verifier, pepper, scope_digest):
    try:
        validate_state(value)
    except PairingPolicyError:
        return False
    return _verify_scope_bound(value, verifier, pepper, "pairing_state", scope_digest)


def authorization_code_verifier(value, pepper, scope_digest):
    validate_authorization_code(value)
    return _scope_bound_verifier(value, pepper, "authorization_code", scope_digest)


def verify_authorization_code_binding(value, verifier, pepper, scope_digest):
    try:
        validate_authorization_code(value)
    except PairingPolicyError:
        return False
    return _verify_scope_bound(value, verifier, pepper, "authorization_code", scope_digest)


def _canonical_json_value(value, depth=0):
    if depth > 12:
        raise PairingPolicyError("request_too_complex")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PairingPolicyError("request_invalid_number")
        return value
    if isinstance(value, list):
        return [_canonical_json_value(item, depth + 1) for item in value]
    if isinstance(value, dict):
        canonical = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise PairingPolicyError("request_invalid_key")
            canonical[key] = _canonical_json_value(item, depth + 1)
        return canonical
    raise PairingPolicyError("request_invalid_value")


def exact_request_digest(method, path, payload):
    """Hash the exact canonical method, path, and JSON request body."""
    if not isinstance(method, str) or method.upper() not in ("GET", "POST", "DELETE"):
        raise PairingPolicyError("request_method_invalid")
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or path.startswith("//")
        or "?" in path
        or "#" in path
        or "\x00" in path
    ):
        raise PairingPolicyError("request_path_invalid")
    envelope = {
        "method": method.upper(),
        "path": path,
        "payload": _canonical_json_value(payload),
        "schema": SCHEMA,
    }
    encoded = json.dumps(
        envelope,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_CANONICAL_REQUEST_BYTES:
        raise PairingPolicyError("request_too_large")
    return "sha256-v1:" + hashlib.sha256(encoded).hexdigest()


def idempotency_digest(idempotency_key, request_digest, pepper):
    """Bind a non-persisted idempotency key to one exact request digest."""
    if (
        not isinstance(idempotency_key, str)
        or idempotency_key != idempotency_key.strip()
        or _IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key) is None
    ):
        raise PairingPolicyError("idempotency_key_invalid")
    if not isinstance(request_digest, str) or _REQUEST_DIGEST_PATTERN.fullmatch(request_digest) is None:
        raise PairingPolicyError("request_digest_invalid")
    value = json.dumps(
        [idempotency_key, request_digest],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return contextual_hmac_verifier(value, pepper, "idempotency_key")


def validate_idempotency_key(value):
    """Validate one high-entropy-looking exact-retry key.

    The protocol cannot measure true entropy, but it rejects short, padded,
    control-bearing, and oversized values before storage sees the request.
    """
    if (
        not isinstance(value, str)
        or value != value.strip()
        or _IDEMPOTENCY_KEY_PATTERN.fullmatch(value) is None
    ):
        raise PairingPolicyError("idempotency_key_invalid")
    return value


def classify_one_use_replay(
    request_digest,
    idempotency_verifier,
    stored_request_digest=None,
    stored_idempotency_verifier=None,
    consumed=False,
    expired=False,
):
    """Classify first use, safe exact retry, divergent replay, or expiry.

    An exact retry never creates another grant.  It may re-derive the same
    pending credential while the activation window remains open.  A changed
    request using a consumed code is always rejected.
    """
    if not isinstance(request_digest, str) or _REQUEST_DIGEST_PATTERN.fullmatch(request_digest) is None:
        raise PairingPolicyError("request_digest_invalid")
    if not isinstance(idempotency_verifier, str) or _HMAC_VERIFIER_PATTERN.fullmatch(
        idempotency_verifier
    ) is None:
        raise PairingPolicyError("idempotency_digest_invalid")
    if expired:
        return ReplayDecision.EXPIRED
    if not consumed:
        if stored_request_digest not in (None, "") or stored_idempotency_verifier not in (None, ""):
            raise PairingPolicyError("replay_state_invalid")
        return ReplayDecision.FIRST_USE
    if not isinstance(stored_request_digest, str) or _REQUEST_DIGEST_PATTERN.fullmatch(
        stored_request_digest
    ) is None:
        raise PairingPolicyError("replay_state_invalid")
    if not isinstance(stored_idempotency_verifier, str) or _HMAC_VERIFIER_PATTERN.fullmatch(
        stored_idempotency_verifier
    ) is None:
        raise PairingPolicyError("replay_state_invalid")
    if hmac.compare_digest(request_digest, stored_request_digest) and hmac.compare_digest(
        idempotency_verifier,
        stored_idempotency_verifier,
    ):
        return ReplayDecision.EXACT_RETRY
    return ReplayDecision.REPLAY_REJECTED


def derive_pending_connector_secret(
    pepper,
    credential_id,
    exchange_request_digest,
    scope_digest,
):
    """Recover the same pending secret for an exact lost-response retry.

    The server persists only ``credential_id``, ``exchange_request_digest``,
    the returned verifier, state, and expiry.  The raw value is deterministically
    re-derived from the injected server pepper until the pending grant expires.
    """
    pepper = _validate_pepper(pepper)
    credential_id = _validate_public_id(credential_id, "credential_id_invalid")
    if not isinstance(exchange_request_digest, str) or _REQUEST_DIGEST_PATTERN.fullmatch(
        exchange_request_digest
    ) is None:
        raise PairingPolicyError("request_digest_invalid")
    if not isinstance(scope_digest, str) or _REQUEST_DIGEST_PATTERN.fullmatch(scope_digest) is None:
        raise PairingPolicyError("scope_digest_invalid")
    message = _hmac_message(
        "pending_connector_derivation",
        json.dumps(
            [credential_id, exchange_request_digest, scope_digest],
            ensure_ascii=True,
            separators=(",", ":"),
        ),
    )
    material = hmac.new(pepper, message, hashlib.sha256).digest()
    raw = _connector_secret_value(credential_id, material)
    verifier = connector_secret_verifier(raw, pepper, scope_digest)
    return OneTimeSecret(raw, credential_id, verifier)


def expires_at(now, ttl_seconds):
    """Return a UTC expiry using one of the three fixed protocol TTLs."""
    if ttl_seconds not in (
        PAIRING_REQUEST_TTL_SECONDS,
        AUTHORIZATION_CODE_TTL_SECONDS,
        PENDING_ACTIVATION_TTL_SECONDS,
    ):
        raise PairingPolicyError("ttl_invalid")
    if not isinstance(now, datetime.datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise PairingPolicyError("time_invalid")
    return now.astimezone(datetime.timezone.utc) + datetime.timedelta(seconds=ttl_seconds)


def is_expired(expiry, now):
    if (
        not isinstance(expiry, datetime.datetime)
        or expiry.tzinfo is None
        or expiry.utcoffset() is None
        or not isinstance(now, datetime.datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
    ):
        raise PairingPolicyError("time_invalid")
    return now.astimezone(datetime.timezone.utc) >= expiry.astimezone(datetime.timezone.utc)


def _endpoint(path):
    return ISSUER + path


def build_discovery_document():
    """Return the bounded, tenant-free, same-origin v1 discovery document."""
    endpoints = {
        "pairingRequest": _endpoint(PAIRING_REQUEST_PATH),
        "authorization": _endpoint(AUTHORIZE_PATH),
        "humanApproval": _endpoint(APPROVAL_PATH_TEMPLATE),
        "authorizationCodeClaim": _endpoint(AUTHORIZATION_CODE_CLAIM_PATH),
        "tokenExchange": _endpoint(TOKEN_PATH),
        "activation": _endpoint(ACTIVATION_PATH),
        "status": _endpoint(STATUS_PATH),
        "credentialRotation": _endpoint(ROTATION_PATH),
        "credentialRotationActivation": _endpoint(ROTATION_ACTIVATION_PATH),
        "credentialList": _endpoint(CREDENTIALS_PATH),
        "credentialRevocation": _endpoint(REVOCATION_PATH),
        "disconnect": _endpoint(DISCONNECT_PATH),
        "cancellation": _endpoint(CANCELLATION_PATH),
    }
    for endpoint in endpoints.values():
        parsed = urlsplit(endpoint)
        if urlunsplit((parsed.scheme, parsed.netloc, "", "", "")) != ISSUER:
            raise RuntimeError("connector discovery endpoint origin mismatch")
        if parsed.query or parsed.fragment:
            raise RuntimeError("connector discovery endpoint contains URL data")
    document = {
        "schema": SCHEMA,
        "schemaVersion": SCHEMA_VERSION,
        "supportedSchemaVersions": [SCHEMA_VERSION],
        "issuer": ISSUER,
        "clientId": CLIENT_ID,
        "canonicalAgentIdentity": {
            "agentId": CANONICAL_AGENT_ID,
            "displayName": CANONICAL_AGENT_DISPLAY_NAME,
            "credentialScope": "connector_and_exact_agent",
        },
        "requestedScopes": list(V1_REQUESTED_SCOPES),
        "scopeDigest": connector_scope_digest(),
        "scopeImpacts": connector_scope_impacts(),
        "agentNamePolicy": agent_name_policy(),
        "endpoints": endpoints,
        "authorizationCode": {
            "oneUse": True,
            "callbackFields": [],
            "callbackParametersAllowed": False,
            "claimDelivery": "body_only",
            "claimFields": [
                "pairingRequestProof",
                "state",
                "clientId",
                "redirectUri",
            ],
            "pkceMethodsSupported": [PKCE_METHOD],
            "requestTtlSeconds": PAIRING_REQUEST_TTL_SECONDS,
            "codeTtlSeconds": AUTHORIZATION_CODE_TTL_SECONDS,
            "authorizationUrlShape": _endpoint(AUTHORIZE_PATH + "/{publicRequestRef}"),
        },
        "pendingGrant": {
            "activationRequired": True,
            "activationTtlSeconds": PENDING_ACTIVATION_TTL_SECONDS,
            "rawCredentialPersistedByServer": False,
            "exactExchangeRetryRecoverable": True,
            "abandonedGrantDurable": False,
        },
        "redirectUris": {
            "registeredCustom": [REGISTERED_CUSTOM_REDIRECT_URI],
            "loopback": "http://127.0.0.1:{dynamicPort}" + LOOPBACK_REDIRECT_PATH,
            "localhostAliasAllowed": False,
        },
        "transport": {
            "httpsRequired": True,
            "sameOriginEndpoints": True,
            "redirectsAllowedForApiOperations": False,
            "normalOperatingSystemTlsValidation": True,
            "jsonContentTypeRequired": True,
            "maximumJsonRequestBytes": MAX_JSON_REQUEST_BYTES,
            "maximumJsonResponseBytes": MAX_DISCOVERY_RESPONSE_BYTES,
            "credentialsInUrlsAllowed": False,
            "authorizationCallbackNavigation": "registered_custom_or_ipv4_loopback_only",
            "noRedirectOperations": [
                "discovery",
                "pairing_request",
                "authorization_code_claim",
                "token_exchange",
                "activation",
                "status",
                "rotation",
                "revocation",
                "disconnect",
            ],
        },
        "rateLimits": json.loads(json.dumps(RATE_LIMIT_POLICIES, sort_keys=True)),
        "publicResponse": {
            "tenantIdentifiersIncluded": False,
            "privatePayloadsIncluded": False,
            "rawCredentialsIncluded": False,
        },
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_DISCOVERY_RESPONSE_BYTES:
        raise RuntimeError("connector discovery document exceeds response bound")
    return document


def safe_error(code, retry_after_seconds=None):
    """Return a fixed, non-reflective public error envelope."""
    if code not in _SAFE_ERROR_MESSAGES:
        code = "service_error"
    error = {
        "code": code,
        "message": _SAFE_ERROR_MESSAGES[code],
        "retryable": code in ("rate_limited", "service_error"),
    }
    if retry_after_seconds is not None:
        if code != "rate_limited" or not isinstance(retry_after_seconds, int) or not 1 <= retry_after_seconds <= 3600:
            raise PairingPolicyError("retry_after_invalid")
        error["retryAfterSeconds"] = retry_after_seconds
    return {
        "ok": False,
        "error": error,
        "rawCredentialExposed": False,
        "privatePayloadExposed": False,
    }


def safe_receipt(action, status, receipt_id, idempotent_replay=False):
    """Return a redacted mutation receipt with no arbitrary reflected values."""
    if action not in _SAFE_RECEIPT_ACTIONS:
        raise PairingPolicyError("receipt_action_invalid")
    if status not in _SAFE_RECEIPT_STATUSES:
        raise PairingPolicyError("receipt_status_invalid")
    if not isinstance(receipt_id, str) or _RECEIPT_ID_PATTERN.fullmatch(receipt_id) is None:
        raise PairingPolicyError("receipt_id_invalid")
    return {
        "ok": True,
        "receipt": {
            "receiptId": receipt_id,
            "action": action,
            "status": status,
            "idempotentReplay": bool(idempotent_replay),
            "rawCredentialExposed": False,
            "privatePayloadExposed": False,
        },
    }


__all__ = [
    "ACTIVATION_PATH",
    "AGENT_NAME_MAX_LENGTH",
    "AGENT_NAME_MIN_LENGTH",
    "APPROVAL_PATH_TEMPLATE",
    "AUTHORIZATION_CODE_CLAIM_PATH",
    "AUTHORIZATION_CODE_TTL_SECONDS",
    "AUTHORIZE_PATH",
    "CANONICAL_AGENT_DISPLAY_NAME",
    "CANONICAL_AGENT_ID",
    "CANCELLATION_PATH",
    "CLIENT_ID",
    "CREDENTIALS_PATH",
    "DISCONNECT_PATH",
    "DISCOVERY_PATH",
    "ISSUER",
    "LOOPBACK_REDIRECT_PATH",
    "MAX_DISCOVERY_RESPONSE_BYTES",
    "MAX_JSON_REQUEST_BYTES",
    "OneTimeSecret",
    "PAIRING_REQUEST_PATH",
    "PAIRING_RESOURCE_PATH_TEMPLATE",
    "PAIRING_REQUEST_TTL_SECONDS",
    "PENDING_ACTIVATION_TTL_SECONDS",
    "PKCE_METHOD",
    "PUBLIC_REQUEST_REF_PATTERN",
    "PairingPolicyError",
    "RATE_LIMIT_POLICIES",
    "REGISTERED_CUSTOM_REDIRECT_URI",
    "REVOCATION_PATH",
    "ROTATION_PATH",
    "ROTATION_ACTIVATION_PATH",
    "ReplayDecision",
    "SCHEMA",
    "SCHEMA_VERSION",
    "STATUS_PATH",
    "TOKEN_PATH",
    "V1_REQUESTED_SCOPES",
    "authorization_code_verifier",
    "build_authorization_url",
    "build_discovery_document",
    "build_wake_up_url",
    "classify_one_use_replay",
    "connector_scope_digest",
    "connector_scope_impacts",
    "connector_secret_verifier",
    "contextual_hmac_verifier",
    "derive_pending_connector_secret",
    "derive_authorization_code",
    "derive_pairing_request_proof",
    "exact_request_digest",
    "expires_at",
    "generate_connector_credential_id",
    "generate_connector_secret",
    "generate_public_request_ref",
    "generate_state",
    "idempotency_digest",
    "is_expired",
    "agent_name_policy",
    "normalize_company_agent_name",
    "normalize_connector_agent_name",
    "parse_authorization_code",
    "parse_pairing_request_proof",
    "pairing_request_proof_verifier",
    "pairing_state_verifier",
    "pkce_s256_challenge",
    "safe_error",
    "safe_receipt",
    "validate_authorization_code",
    "validate_client_id",
    "validate_idempotency_key",
    "validate_pairing_request_proof",
    "validate_pkce_s256",
    "validate_public_request_ref",
    "validate_persisted_connector_scope",
    "validate_redirect_uri",
    "validate_requested_scopes",
    "validate_service_root",
    "validate_state",
    "verify_contextual_hmac",
    "verify_connector_secret",
    "verify_authorization_code_binding",
    "verify_pairing_request_proof",
    "verify_pairing_state",
]
