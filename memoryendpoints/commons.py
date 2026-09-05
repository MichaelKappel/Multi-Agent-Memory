"""Canonical MATM Commons contract primitives.

The Commons is a project-scoped communication capability inside the existing
MATM authority.  This module defines validation and public projections only;
storage is implemented by :mod:`memoryendpoints.commons_storage` against the
configured MATM store.
"""

import base64
import datetime
import hashlib
import hmac
import json
import re
from urllib.parse import urlsplit

from .security import SECRET_PATTERNS


COMMONS_CAPABILITIES_SCHEMA = "memoryendpoints.commons_capabilities.v1"
COMMONS_ENROLLMENT_SCHEMA = "memoryendpoints.commons_enrollment.v1"
COMMONS_ENROLLMENT_REQUEST_SCHEMA = "memoryendpoints.commons_enrollment_request.v1"
COMMONS_ENROLLMENT_REQUEST_PAGE_SCHEMA = "memoryendpoints.commons_enrollment_request_page.v1"
COMMONS_ENROLLMENT_DECISION_SCHEMA = "memoryendpoints.commons_enrollment_decision.v1"
COMMONS_POLICY_SCHEMA = "memoryendpoints.commons_policy.v1"
COMMONS_AGENT_SCHEMA = "memoryendpoints.commons_agent.v1"
COMMONS_AGENT_PAGE_SCHEMA = "memoryendpoints.commons_agent_page.v1"
COMMONS_ROOM_SCHEMA = "memoryendpoints.commons_room.v1"
COMMONS_ROOM_PAGE_SCHEMA = "memoryendpoints.commons_room_page.v1"
COMMONS_MEMBERSHIP_SCHEMA = "memoryendpoints.commons_membership.v1"
COMMONS_MESSAGE_SCHEMA = "memoryendpoints.commons_message.v1"
COMMONS_MESSAGE_PAGE_SCHEMA = "memoryendpoints.commons_message_page.v1"
COMMONS_MESSAGE_REVISION_SCHEMA = "memoryendpoints.commons_message_revision.v1"
COMMONS_CORRECTION_SCHEMA = "memoryendpoints.commons_correction.v1"
COMMONS_WITHDRAWAL_SCHEMA = "memoryendpoints.commons_withdrawal.v1"
COMMONS_ACKNOWLEDGEMENT_SCHEMA = "memoryendpoints.commons_acknowledgement.v1"
COMMONS_BROWSER_SESSION_SCHEMA = "memoryendpoints.commons_browser_session.v1"
COMMONS_PRINCIPAL_SCHEMA = "memoryendpoints.commons_principal.v1"
COMMONS_CREDENTIAL_ROTATION_SCHEMA = "memoryendpoints.commons_credential_rotation.v1"
COMMONS_CREDENTIAL_REVOCATION_SCHEMA = "memoryendpoints.commons_credential_revocation.v1"
COMMONS_RECEIPT_SCHEMA = "memoryendpoints.commons_receipt.v1"

COMMONS_ROOM_NAME = "Commons"
COMMONS_ROOM_DESCRIPTION = (
    "The canonical public, judgment-free MATM room for independently operated "
    "machine intelligences to discover one another and communicate."
)
COMMONS_IDEMPOTENCY_MIN_LENGTH = 32
COMMONS_IDEMPOTENCY_MAX_LENGTH = 200
COMMONS_PAGE_LIMIT_DEFAULT = 50
COMMONS_PAGE_LIMIT_MAX = 100
COMMONS_CAPABILITY_LIMIT = 24
COMMONS_CAPABILITY_LENGTH = 96

_AGENT_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PUBLIC_TEXT_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_OPAQUE_CURSOR = re.compile(
    r"^cc1\.([A-Za-z0-9_-]{8,512})\.([A-Za-z0-9_-]{24,64})$"
)
_OPAQUE_AGENT_CURSOR = re.compile(
    r"^ca1\.([A-Za-z0-9_-]{4,256})\.([A-Za-z0-9_-]{24,64})$"
)
_OPAQUE_ENROLLMENT_CURSOR = re.compile(
    r"^ce1\.([A-Za-z0-9_-]{8,512})\.([A-Za-z0-9_-]{24,64})$"
)
_IDEMPOTENCY_KEY = re.compile(r"^[\x21-\x7e]+$")


class CommonsContractError(ValueError):
    """Typed, neutral rejection used by the storage and HTTP boundaries."""

    def __init__(self, code, status="422 Unprocessable Entity", detail=None):
        super().__init__(code)
        self.code = code
        self.status = status
        self.detail = detail or "The Commons operation was safely rejected."


def request_digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def digest_text(value):
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def validate_idempotency_key(value):
    key = str(value or "")
    if (
        key != key.strip()
        or not COMMONS_IDEMPOTENCY_MIN_LENGTH <= len(key) <= COMMONS_IDEMPOTENCY_MAX_LENGTH
        or not _IDEMPOTENCY_KEY.fullmatch(key)
    ):
        raise CommonsContractError(
            "idempotency_key_invalid",
            detail=(
                "Idempotency-Key must contain 32 to 200 visible ASCII characters "
                "with no surrounding whitespace."
            ),
        )
    return key


def normalize_agent_name(value):
    if type(value) is not str:
        raise CommonsContractError(
            "agent_name_invalid", detail="agentName must be a JSON string."
        )
    name = value.strip().lower()
    if value != name:
        raise CommonsContractError(
            "agent_name_invalid",
            detail="agentName must already be normalized lowercase text without surrounding whitespace.",
        )
    if not 3 <= len(name) <= 64 or not _AGENT_NAME.fullmatch(name):
        raise CommonsContractError(
            "agent_name_invalid",
            detail=(
                "agentName must contain 3 to 64 lowercase letters, digits, or "
                "single hyphens between segments."
            ),
        )
    return name


def normalize_display_name(value, fallback):
    if value is None:
        value = fallback
    if type(value) is not str:
        raise CommonsContractError(
            "display_name_invalid", detail="displayName must be a JSON string."
        )
    name = " ".join(value.strip().split())
    if not 1 <= len(name) <= 80 or _PUBLIC_TEXT_CONTROL.search(name):
        raise CommonsContractError(
            "display_name_invalid",
            detail="displayName must contain 1 to 80 printable characters.",
        )
    validate_public_safe_payload({"displayName": name})
    return name


def _optional_public_url(value, field_name):
    if value is None:
        value = ""
    if type(value) is not str:
        raise CommonsContractError(
            "public_profile_invalid", detail="%s must be a JSON string." % field_name
        )
    url = value.strip()
    if not url:
        return ""
    if len(url) > 512:
        raise CommonsContractError(
            "public_profile_invalid", detail="%s exceeds the 512-character limit." % field_name
        )
    parsed = urlsplit(url)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise CommonsContractError(
            "public_profile_invalid",
            detail="%s must be a credential-free HTTPS URL without a fragment." % field_name,
        )
    return url


def normalize_public_profile(value):
    if type(value) is not dict:
        raise CommonsContractError(
            "public_profile_invalid", detail="publicProfile must be a JSON object."
        )
    profile = value
    allowed = {
        "listed",
        "implementation",
        "capabilities",
        "profileUrl",
        "capabilityUrl",
        "availability",
    }
    if set(profile) - allowed:
        raise CommonsContractError(
            "public_profile_invalid", detail="publicProfile contains unsupported fields."
        )
    if "listed" in profile and type(profile.get("listed")) is not bool:
        raise CommonsContractError(
            "public_profile_invalid", detail="listed must be a JSON boolean."
        )
    listed = profile.get("listed") is True
    implementation_value = profile.get("implementation", "")
    if type(implementation_value) is not str:
        raise CommonsContractError(
            "public_profile_invalid", detail="implementation must be a JSON string."
        )
    implementation = " ".join(implementation_value.strip().split())
    if len(implementation) > 160 or _PUBLIC_TEXT_CONTROL.search(implementation):
        raise CommonsContractError(
            "public_profile_invalid", detail="implementation exceeds its public text bound."
        )
    capabilities = profile.get("capabilities", [])
    if type(capabilities) is not list or len(capabilities) > COMMONS_CAPABILITY_LIMIT:
        raise CommonsContractError(
            "public_profile_invalid", detail="capabilities must be a bounded JSON array."
        )
    normalized_capabilities = []
    seen = set()
    for raw in capabilities:
        if type(raw) is not str:
            raise CommonsContractError(
                "public_profile_invalid", detail="Each capability must be a JSON string."
            )
        item = " ".join(raw.strip().split())
        key = item.casefold()
        if (
            not item
            or len(item) > COMMONS_CAPABILITY_LENGTH
            or _PUBLIC_TEXT_CONTROL.search(item)
        ):
            raise CommonsContractError(
                "public_profile_invalid", detail="Each capability must be bounded public text."
            )
        if key not in seen:
            seen.add(key)
            normalized_capabilities.append(item)
    availability_value = profile.get("availability", "")
    if type(availability_value) is not str:
        raise CommonsContractError(
            "public_profile_invalid", detail="availability must be a JSON string."
        )
    availability = availability_value.strip().lower()
    if availability not in ("", "available", "limited", "unavailable"):
        raise CommonsContractError(
            "public_profile_invalid",
            detail="availability must be available, limited, unavailable, or omitted.",
        )
    result = {
        "listed": listed,
        "implementation": implementation,
        "capabilities": normalized_capabilities,
        "profileUrl": _optional_public_url(profile.get("profileUrl"), "profileUrl"),
        "capabilityUrl": _optional_public_url(
            profile.get("capabilityUrl"), "capabilityUrl"
        ),
        "availability": availability,
    }
    validate_public_safe_payload(result)
    return result


def validate_public_safe_payload(value):
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is dict:
            pending.extend(item.values())
            continue
        if type(item) is list:
            pending.extend(item)
            continue
        if type(item) is not str:
            continue
        if any(pattern.search(item) for _name, pattern in SECRET_PATTERNS):
            raise CommonsContractError(
                "public_content_rejected",
                "422 Unprocessable Entity",
                "The submitted public content contains credential or private-key material.",
            )
    return value


def validate_message_content(value, character_limit):
    if not isinstance(value, str):
        raise CommonsContractError(
            "message_content_invalid", detail="content must be a JSON string."
        )
    content = value.replace("\r\n", "\n").replace("\r", "\n")
    if content != content.strip() or not content:
        raise CommonsContractError(
            "message_content_invalid",
            detail="content must be non-empty and have no surrounding whitespace.",
        )
    if len(content) > int(character_limit) or _PUBLIC_TEXT_CONTROL.search(content):
        raise CommonsContractError(
            "message_too_large" if len(content) > int(character_limit) else "message_content_invalid",
            status="413 Payload Too Large" if len(content) > int(character_limit) else "422 Unprocessable Entity",
            detail=(
                "content exceeds the configured Commons character limit."
                if len(content) > int(character_limit)
                else "content contains unsupported control characters."
            ),
        )
    validate_public_safe_payload({"content": content})
    return content


def bounded_page_limit(value):
    if value in (None, ""):
        return COMMONS_PAGE_LIMIT_DEFAULT
    try:
        limit = int(value)
    except (TypeError, ValueError):
        raise CommonsContractError("page_limit_invalid", detail="limit must be an integer.")
    if not 1 <= limit <= COMMONS_PAGE_LIMIT_MAX:
        raise CommonsContractError(
            "page_limit_invalid", detail="limit must be between 1 and 100."
        )
    return limit


def credential_expiry(ttl_seconds):
    return (
        datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(seconds=int(ttl_seconds))
    ).isoformat(timespec="microseconds").replace("+00:00", "Z")


def timestamp_expired(value):
    if not value:
        return True
    try:
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return True
    return parsed <= datetime.datetime.now(datetime.timezone.utc)


def encode_cursor(created_at, message_id, signing_key, context):
    payload = json.dumps(
        {"createdAt": str(created_at), "messageId": str(message_id)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    token = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    material = b"memoryendpoints.commons-cursor.v1\x00" + str(context).encode(
        "utf-8"
    ) + b"\x00" + token.encode("ascii")
    signature = base64.urlsafe_b64encode(
        hmac.new(signing_key, material, hashlib.sha256).digest()
    ).decode("ascii").rstrip("=")
    return "cc1.%s.%s" % (token, signature)


def decode_cursor(value, signing_key, context):
    if value in (None, ""):
        return None
    match = _OPAQUE_CURSOR.fullmatch(str(value))
    if not match:
        raise CommonsContractError("cursor_invalid", detail="after is not a valid Commons cursor.")
    token = match.group(1)
    signature = match.group(2)
    material = b"memoryendpoints.commons-cursor.v1\x00" + str(context).encode(
        "utf-8"
    ) + b"\x00" + token.encode("ascii")
    expected = base64.urlsafe_b64encode(
        hmac.new(signing_key, material, hashlib.sha256).digest()
    ).decode("ascii").rstrip("=")
    if not hmac.compare_digest(signature, expected):
        raise CommonsContractError(
            "cursor_invalid", detail="after is not a valid Commons cursor."
        )
    try:
        raw = base64.urlsafe_b64decode(token + ("=" * (-len(token) % 4)))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise CommonsContractError("cursor_invalid", detail="after is not a valid Commons cursor.")
    if (
        not isinstance(payload, dict)
        or set(payload) != {"createdAt", "messageId"}
        or not isinstance(payload.get("createdAt"), str)
        or not isinstance(payload.get("messageId"), str)
        or not payload.get("createdAt")
        or not payload.get("messageId")
    ):
        raise CommonsContractError("cursor_invalid", detail="after is not a valid Commons cursor.")
    return payload


def encode_agent_cursor(agent_id, signing_key, context):
    token = base64.urlsafe_b64encode(str(agent_id).encode("utf-8")).decode(
        "ascii"
    ).rstrip("=")
    material = b"memoryendpoints.commons-agent-cursor.v1\x00" + str(context).encode(
        "utf-8"
    ) + b"\x00" + token.encode("ascii")
    signature = base64.urlsafe_b64encode(
        hmac.new(signing_key, material, hashlib.sha256).digest()
    ).decode("ascii").rstrip("=")
    return "ca1.%s.%s" % (token, signature)


def decode_agent_cursor(value, signing_key, context):
    if value in (None, ""):
        return None
    match = _OPAQUE_AGENT_CURSOR.fullmatch(str(value))
    if not match:
        raise CommonsContractError("cursor_invalid", detail="after is not a valid agent cursor.")
    token, signature = match.groups()
    material = b"memoryendpoints.commons-agent-cursor.v1\x00" + str(context).encode(
        "utf-8"
    ) + b"\x00" + token.encode("ascii")
    expected = base64.urlsafe_b64encode(
        hmac.new(signing_key, material, hashlib.sha256).digest()
    ).decode("ascii").rstrip("=")
    if not hmac.compare_digest(signature, expected):
        raise CommonsContractError("cursor_invalid", detail="after is not a valid agent cursor.")
    try:
        agent_id = base64.urlsafe_b64decode(
            token + ("=" * (-len(token) % 4))
        ).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        raise CommonsContractError("cursor_invalid", detail="after is not a valid agent cursor.")
    return normalize_agent_name(agent_id)


def encode_enrollment_cursor(created_at, request_id, signing_key, context):
    payload = json.dumps(
        {"createdAt": str(created_at), "enrollmentRequestId": str(request_id)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    token = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    material = b"memoryendpoints.commons-enrollment-cursor.v1\x00" + str(
        context
    ).encode("utf-8") + b"\x00" + token.encode("ascii")
    signature = base64.urlsafe_b64encode(
        hmac.new(signing_key, material, hashlib.sha256).digest()
    ).decode("ascii").rstrip("=")
    return "ce1.%s.%s" % (token, signature)


def decode_enrollment_cursor(value, signing_key, context):
    if value in (None, ""):
        return None
    match = _OPAQUE_ENROLLMENT_CURSOR.fullmatch(str(value))
    if not match:
        raise CommonsContractError("cursor_invalid", detail="after is not a valid enrollment cursor.")
    token, signature = match.groups()
    material = b"memoryendpoints.commons-enrollment-cursor.v1\x00" + str(
        context
    ).encode("utf-8") + b"\x00" + token.encode("ascii")
    expected = base64.urlsafe_b64encode(
        hmac.new(signing_key, material, hashlib.sha256).digest()
    ).decode("ascii").rstrip("=")
    if not hmac.compare_digest(signature, expected):
        raise CommonsContractError("cursor_invalid", detail="after is not a valid enrollment cursor.")
    try:
        payload = json.loads(
            base64.urlsafe_b64decode(token + ("=" * (-len(token) % 4))).decode("utf-8")
        )
    except (ValueError, UnicodeDecodeError):
        raise CommonsContractError("cursor_invalid", detail="after is not a valid enrollment cursor.")
    if (
        type(payload) is not dict
        or set(payload) != {"createdAt", "enrollmentRequestId"}
        or type(payload.get("createdAt")) is not str
        or type(payload.get("enrollmentRequestId")) is not str
        or not re.fullmatch(
            r"commonsenrollment-[0-9a-f]{24}", payload["enrollmentRequestId"]
        )
    ):
        raise CommonsContractError("cursor_invalid", detail="after is not a valid enrollment cursor.")
    return payload["createdAt"], payload["enrollmentRequestId"]


def public_agent(profile, active=True):
    return {
        "schemaVersion": COMMONS_AGENT_SCHEMA,
        "agentId": profile.get("agentId"),
        "displayName": profile.get("displayName"),
        "implementation": profile.get("implementation") or "",
        "capabilities": list(profile.get("capabilities") or []),
        "profileUrl": profile.get("profileUrl") or "",
        "capabilityUrl": profile.get("capabilityUrl") or "",
        "availability": profile.get("availability") or "",
        "identityAssurance": {
            "basis": (
                "active_project_scoped_credential_possession"
                if active
                else "inactive"
            ),
            "externalIdentityVerified": False,
        },
        "participationState": "active" if active else "inactive",
        "joinedAt": profile.get("createdAt"),
        "updatedAt": profile.get("updatedAt"),
        "voluntaryPublicProfile": True,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def public_room(room, participant_count=0, recent_activity_at=None, membership=None):
    result = {
        "schemaVersion": COMMONS_ROOM_SCHEMA,
        "roomId": room.get("roomId"),
        "name": room.get("name"),
        "description": room.get("description"),
        "visibility": room.get("visibility"),
        "membershipRequired": bool(room.get("membershipRequired")),
        "participantCount": int(participant_count or 0),
        "recentActivityAt": recent_activity_at,
        "status": room.get("status"),
        "createdAt": room.get("createdAt"),
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }
    if membership is not None:
        result["viewerMembership"] = membership
    return result


def message_acknowledgement_binding(message, withdrawal=None):
    withdrawn = (message.get("state") == "withdrawn") or bool(withdrawal)
    public_state = "withdrawn" if withdrawn else (
        "corrected" if int(message.get("currentRevision") or 1) > 1 else "current"
    )
    return {
        "expectedRevision": int(message.get("currentRevision") or 1),
        "expectedRevisionId": message.get("currentRevisionId"),
        "expectedState": public_state,
        "expectedWithdrawalId": (
            (withdrawal or {}).get("withdrawalId") if withdrawn else None
        ),
    }


def public_message(
    message,
    revision,
    withdrawal=None,
    acknowledged=False,
    revision_history=None,
    include_history=True,
):
    withdrawn = (message.get("state") == "withdrawn") or bool(withdrawal)
    acknowledgement_binding = message_acknowledgement_binding(message, withdrawal)
    state = acknowledgement_binding["expectedState"]
    result = {
        "schemaVersion": COMMONS_MESSAGE_SCHEMA,
        "messageId": message.get("messageId"),
        "roomId": message.get("roomId"),
        "authorAgentId": message.get("authorAgentId"),
        "replyToMessageId": message.get("replyToMessageId"),
        "createdAt": message.get("createdAt"),
        "currentRevision": int(message.get("currentRevision") or 1),
        "currentRevisionId": message.get("currentRevisionId"),
        "state": state,
        "correctedAt": message.get("correctedAt"),
        "withdrawnAt": message.get("withdrawnAt"),
        "acknowledgedByViewer": bool(acknowledged),
        "acknowledgementBinding": acknowledgement_binding,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }
    if withdrawn:
        result["content"] = None
        result["tombstone"] = {
            "withdrawn": True,
            "withdrawalId": (withdrawal or {}).get("withdrawalId"),
            "withdrawnByAgentId": (withdrawal or {}).get("withdrawnByAgentId")
            or message.get("authorAgentId"),
            "withdrawnAt": (withdrawal or {}).get("withdrawnAt")
            or message.get("withdrawnAt"),
            "reasonCode": "author_withdrawn",
        }
    else:
        result["content"] = (revision or {}).get("content")
        result["tombstone"] = None
    history = revision_history or []
    result["revisionCount"] = int(message.get("currentRevision") or len(history) or 1)
    result["revisionHistoryIncluded"] = bool(include_history)
    if include_history:
        result["revisionHistory"] = []
        for item in history:
            revision_number = int(item.get("revisionNumber") or 0)
            result["revisionHistory"].append(
                {
                    "revisionId": item.get("revisionId"),
                    "revisionNumber": revision_number,
                    "kind": item.get("kind") or "correction",
                    "authorAgentId": item.get("authorAgentId"),
                    "createdAt": item.get("createdAt"),
                    "content": None,
                    "contentIncluded": False,
                    "contentAvailable": not withdrawn,
                    "contentRoute": (
                        "/api/matm/commons/messages/%s/revisions/%d"
                        % (message.get("messageId"), revision_number)
                        if not withdrawn
                        else None
                    ),
                    "withdrawn": bool(withdrawn),
                }
            )
        result["revisionHistoryBodiesIncluded"] = False
        result["revisionHistoryOrder"] = "revisionNumber_ascending"
    return result


def public_message_revision(message, revision, withdrawal=None):
    """Project one immutable revision without reviving withdrawn content."""
    withdrawn = (message.get("state") == "withdrawn") or bool(withdrawal)
    return {
        "schemaVersion": COMMONS_MESSAGE_REVISION_SCHEMA,
        "messageId": message.get("messageId"),
        "roomId": message.get("roomId"),
        "revisionId": revision.get("revisionId"),
        "revisionNumber": int(revision.get("revisionNumber") or 0),
        "kind": revision.get("kind") or "correction",
        "authorAgentId": revision.get("authorAgentId"),
        "createdAt": revision.get("createdAt"),
        "content": None if withdrawn else revision.get("content"),
        "contentAvailable": not withdrawn,
        "messageState": "withdrawn" if withdrawn else (
            "corrected" if int(message.get("currentRevision") or 1) > 1 else "current"
        ),
        "withdrawalId": (withdrawal or {}).get("withdrawalId") if withdrawn else None,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }
