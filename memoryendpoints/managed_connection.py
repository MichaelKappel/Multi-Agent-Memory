"""Connect through one installer-managed MemoryEndpoints agent profile.

The command-line entry point is a per-user diagnostic client.  Unattended
services use the separate prompt-free reconciliation adapter contract and must
supply their installer-bound service identity, vault, signed-profile verifier,
crash-durable state, and independent recovery authority in code.  That contract
accepts no human-supplied endpoint, CA, invitation, credential, username, or
machine-name input; a consuming product is not an executable unattended
integration until it supplies those concrete adapters.  The client creates and
protects its credential candidate and exact-retry key before redemption; the
service never returns the raw credential.
"""

import argparse
import base64
import ctypes
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import ipaddress
import json
import os
import re
import secrets
import ssl
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


AGENT_CREDENTIAL_SCHEMA = "memoryendpoints.agent_credential_file.v4"
PENDING_SCHEMA = "memoryendpoints.agent_onboarding_pending.v4"
MANAGED_PROFILE_SCHEMA = "multiagentmemory.lan_agent_profile.v2"
MANAGED_INVITE_SCHEMA = "multiagentmemory.lan_agent_invitation.v3"
DEFAULT_BASE_URL = "https://memoryendpoints.com"
DEFAULT_INVITE_ENVIRONMENT = "MEMORYENDPOINTS_INVITE_SECRET"
BASE_URL_ENVIRONMENT = "MEMORYENDPOINTS_BASE_URL"
CA_BUNDLE_ENVIRONMENT = "MEMORYENDPOINTS_CA_BUNDLE"
MANAGED_PROFILE_FILE = "connection.json"
MANAGED_TRUST_FILE = Path("trust") / "lan-ca.pem"
MANAGED_INVITE_FILE = Path("enrollment") / "invite.json"
MANAGED_CREDENTIAL_FILE = Path("credentials") / "agent.json"
MANAGED_PENDING_FILE = Path("credentials") / ".agent.pending.json"
MANAGED_TRUST_MODE = "bundled-ca"
MANAGED_PROFILE_PURPOSE = "managed-agent-connection"
MANAGED_ENROLLMENT_KIND = "governed-agent-invitation"
MANAGED_FALLBACK_POLICY = "forbidden"
MANAGED_RUNTIME_CLASS_PER_USER = "per-user-agent"
MANAGED_RUNTIME_CLASS_UNATTENDED_SERVICE = "unattended-service"
MANAGED_RUNTIME_CLASSES = frozenset(
    {
        MANAGED_RUNTIME_CLASS_PER_USER,
        MANAGED_RUNTIME_CLASS_UNATTENDED_SERVICE,
    }
)
WINDOWS_USER_PROTECTION_ID = "windows-dpapi-current-user"
MANAGED_USER_DIRECTORY = Path("LocalEndpoints") / "MemoryEndpoints"
MAX_LOCAL_JSON_BYTES = 64 * 1024
MAX_CA_BYTES = 1024 * 1024
MAX_HTTP_RESPONSE_BYTES = 1024 * 1024
REDEEM_ROUTE = "/api/matm/access/invites/redeem"
ME_ROUTE = "/api/matm/me"
MANAGED_RESULT_SCHEMA = "multiagentmemory.managed_connection_result.v2"
MANAGED_CONTROLLER_STATE_SCHEMA = "multiagentmemory.managed_controller_state.v1"
MANAGED_RECONCILIATION_RESULT_SCHEMA = (
    "multiagentmemory.managed_reconciliation_result.v1"
)
MANAGED_RECOVERY_REQUEST_SCHEMA = "multiagentmemory.managed_recovery_request.v1"
MANAGED_RECOVERY_DIRECTIVE_SCHEMA = "multiagentmemory.managed_recovery_directive.v1"
MANAGED_RECOVERY_ACTIONS = frozenset({"retry_after", "quarantine_replace", "halt"})
CONTROLLER_ACTIONS = frozenset(
    {
        "halt_managed_connection_controller",
        "hold_for_compatible_server_release",
        "install_managed_connection_profile",
        "install_managed_invitation",
        "install_supported_connection_controller",
        "install_supported_credential_provider",
        "none",
        "quarantine_credential_state",
        "quarantine_enrollment_state",
        "quarantine_identity",
        "quarantine_profile_conflict",
        "reconcile_credential_with_recovery_authority",
        "reconcile_enrollment_with_recovery_authority",
        "repair_managed_connection_controller",
        "repair_managed_connection_installation",
        "repair_protected_credential_store",
        "replace_managed_connection_profile",
        "replace_managed_invitation",
        "rebootstrap_managed_identity",
        "replace_managed_trust",
        "restore_managed_trust",
        "retire_consumed_managed_invitation",
        "retry_exact_enrollment_with_bounded_backoff",
        "retry_local_credential_promotion",
        "retry_with_bounded_backoff",
    }
)
CONTROLLER_ACTION_METADATA = {
    "none": {"authority": "none", "retryable": False, "terminal": False},
    "retry_exact_enrollment_with_bounded_backoff": {
        "authority": "controller",
        "retryable": True,
        "terminal": False,
    },
    "retry_local_credential_promotion": {
        "authority": "controller",
        "retryable": True,
        "terminal": False,
    },
    "retry_with_bounded_backoff": {
        "authority": "controller",
        "retryable": True,
        "terminal": False,
    },
    "retire_consumed_managed_invitation": {
        "authority": "controller",
        "retryable": True,
        "terminal": False,
    },
    "rebootstrap_managed_identity": {
        "authority": "independent_recovery_authority",
        "retryable": False,
        "terminal": True,
    },
}
for _controller_action in CONTROLLER_ACTIONS:
    CONTROLLER_ACTION_METADATA.setdefault(
        _controller_action,
        {
            "authority": (
                "independent_recovery_authority"
                if _controller_action.startswith(
                    ("install_", "repair_", "replace_", "reconcile_", "restore_", "rebootstrap_")
                )
                else "controller"
                if _controller_action.startswith("retry_")
                else "none"
            ),
            "retryable": _controller_action.startswith("retry_"),
            "terminal": not _controller_action.startswith("retry_")
            and _controller_action != "none",
        },
    )
__all__ = (
    "AGENT_CREDENTIAL_SCHEMA",
    "CONTROLLER_ACTIONS",
    "CONTROLLER_ACTION_METADATA",
    "MANAGED_INVITE_SCHEMA",
    "MANAGED_ENROLLMENT_KIND",
    "MANAGED_FALLBACK_POLICY",
    "MANAGED_PROFILE_SCHEMA",
    "MANAGED_PROFILE_PURPOSE",
    "MANAGED_RUNTIME_CLASS_PER_USER",
    "MANAGED_RUNTIME_CLASS_UNATTENDED_SERVICE",
    "MANAGED_CONTROLLER_STATE_SCHEMA",
    "MANAGED_RECONCILIATION_RESULT_SCHEMA",
    "MANAGED_RECOVERY_REQUEST_SCHEMA",
    "MANAGED_RECOVERY_DIRECTIVE_SCHEMA",
    "MANAGED_RECOVERY_ACTIONS",
    "MANAGED_RESULT_SCHEMA",
    "DurableStateCAS",
    "FileDurableStateCAS",
    "ManagedProfileLocator",
    "ManagedRecoveryAuthority",
    "ManagedServiceContext",
    "OnboardingError",
    "SecretProtector",
    "SignedProfileVerifier",
    "WINDOWS_USER_PROTECTION_ID",
    "connect_managed_agent",
    "initialize_managed_controller_state",
    "parse_managed_reconciliation_result",
    "reconcile_managed_connection",
    "provision_managed_connection",
    "parse_managed_connection_result",
    "main",
)

_AGENT_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PROFILE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{7,63}$")
_BOUND_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_CLIENT_KIND_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PROTECTION_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_SAFE_CODE_PATTERN = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_INVITE_PATTERN = re.compile(
    r"^me_invite_v1\.[A-Za-z0-9_-]{3,160}\.[A-Za-z0-9_-]{32,128}$"
)
_AGENT_TOKEN_PATTERN = re.compile(
    r"^me_agent_v1\.[A-Za-z0-9_-]{3,160}\.[A-Za-z0-9_-]{32,128}$"
)
_CONTROLLER_PHASES = frozenset(
    {"pending", "connecting", "retry_wait", "active", "quarantined", "halted"}
)
_UNBOUND = object()


class OnboardingError(RuntimeError):
    """A public-safe error that contains no credential or tenant identifier."""

    def __init__(
        self,
        code,
        message=None,
        action=None,
        retryable=False,
        state=None,
        retry_after_seconds=None,
    ):
        if message is None:
            message = code
            code = "agent_onboarding_failed"
        super().__init__(message)
        candidate_code = str(code)
        self.code = (
            candidate_code
            if _SAFE_CODE_PATTERN.fullmatch(candidate_code)
            else "agent_onboarding_failed"
        )
        requested_action = str(action or "halt_managed_connection_controller")
        self.action = (
            requested_action
            if requested_action in CONTROLLER_ACTIONS
            else "halt_managed_connection_controller"
        )
        self.retryable = bool(retryable)
        self.state = (
            "retry_wait"
            if retryable
            else "quarantined"
            if "quarantine" in self.action
            else "recovery_required"
        )
        self.retry_after_seconds = None
        if retryable:
            self.retry_after_seconds = (
                retry_after_seconds
                if type(retry_after_seconds) is int
                and 1 <= retry_after_seconds <= 86400
                else 30
            )


class _OutcomeUnknown(RuntimeError):
    """Internal marker for a request whose result could not be established."""


class SecretProtector:
    """A named non-interactive secret protector supplied by the consuming identity."""

    def __init__(
        self,
        protection_id,
        protect,
        unprotect,
        workload_identity_id=None,
    ):
        if (
            type(protection_id) is not str
            or not _PROTECTION_ID_PATTERN.fullmatch(protection_id)
            or not callable(protect)
            or not callable(unprotect)
            or (
                workload_identity_id is not None
                and (
                    type(workload_identity_id) is not str
                    or not _BOUND_ID_PATTERN.fullmatch(workload_identity_id)
                )
            )
        ):
            raise ValueError("invalid secret protector")
        self.protection_id = protection_id
        self.protect = protect
        self.unprotect = unprotect
        self.workload_identity_id = workload_identity_id


@dataclass(frozen=True)
class ManagedServiceContext:
    """Immutable identity and retry policy expected by one unattended service."""

    client_kind: str
    service_instance_id: str
    workload_identity_id: str
    project_id: str
    profile_verifier_id: str
    recovery_authority_id: str
    runtime_class: str = MANAGED_RUNTIME_CLASS_UNATTENDED_SERVICE
    purpose: str = MANAGED_PROFILE_PURPOSE
    max_attempts: int = 8
    base_retry_seconds: int = 15
    max_retry_seconds: int = 900
    attempt_lease_seconds: int = 120

    def __post_init__(self):
        if (
            self.runtime_class != MANAGED_RUNTIME_CLASS_UNATTENDED_SERVICE
            or self.purpose != MANAGED_PROFILE_PURPOSE
            or type(self.client_kind) is not str
            or not _CLIENT_KIND_PATTERN.fullmatch(self.client_kind)
            or type(self.service_instance_id) is not str
            or not _BOUND_ID_PATTERN.fullmatch(self.service_instance_id)
            or type(self.workload_identity_id) is not str
            or not _BOUND_ID_PATTERN.fullmatch(self.workload_identity_id)
            or type(self.project_id) is not str
            or not _BOUND_ID_PATTERN.fullmatch(self.project_id)
            or type(self.profile_verifier_id) is not str
            or not _PROTECTION_ID_PATTERN.fullmatch(self.profile_verifier_id)
            or self.profile_verifier_id == "protected-state-binding"
            or type(self.recovery_authority_id) is not str
            or not _PROTECTION_ID_PATTERN.fullmatch(self.recovery_authority_id)
            or self.recovery_authority_id == "protected-state-binding"
            or type(self.max_attempts) is not int
            or not 1 <= self.max_attempts <= 64
            or type(self.base_retry_seconds) is not int
            or not 1 <= self.base_retry_seconds <= 3600
            or type(self.max_retry_seconds) is not int
            or not self.base_retry_seconds <= self.max_retry_seconds <= 86400
            or type(self.attempt_lease_seconds) is not int
            or not 5 <= self.attempt_lease_seconds <= 3600
        ):
            raise ValueError("invalid managed service context")


class ManagedProfileLocator:
    """Resolve exactly one installer-owned profile for a fixed service context."""

    def __init__(self, locate):
        if not callable(locate):
            raise ValueError("invalid managed profile locator")
        self._locate = locate

    def locate(self, context):
        return self._locate(context)


class SignedProfileVerifier:
    """Verify profiles under an externally pinned authority, never profile choice."""

    def __init__(self, verifier_id, verify, minimum_generation):
        if (
            type(verifier_id) is not str
            or not _PROTECTION_ID_PATTERN.fullmatch(verifier_id)
            or verifier_id == "protected-state-binding"
            or not callable(verify)
            or not callable(minimum_generation)
        ):
            raise ValueError("invalid signed profile verifier")
        self.verifier_id = verifier_id
        self._verify = verify
        self._minimum_generation = minimum_generation

    def verify(self, payload, context):
        return self._verify(self.verifier_id, dict(payload), context)

    def minimum_generation(self, context):
        value = self._minimum_generation(self.verifier_id, context)
        if type(value) is not int or value < 1:
            raise OnboardingError(
                "managed_profile_generation_unavailable",
                "The current managed profile generation could not be verified.",
                "quarantine_profile_conflict",
            )
        return value


class DurableStateCAS:
    """Closed compare-and-swap adapter for crash-durable controller state."""

    def __init__(self, durability_id, read, compare_exchange):
        if (
            type(durability_id) is not str
            or not _PROTECTION_ID_PATTERN.fullmatch(durability_id)
            or not callable(read)
            or not callable(compare_exchange)
        ):
            raise ValueError("invalid durable state CAS")
        self.durability_id = durability_id
        self._read = read
        self._compare_exchange = compare_exchange

    def read(self, key):
        return self._read(key)

    def compare_exchange(self, key, expected_revision, next_state):
        return self._compare_exchange(key, expected_revision, dict(next_state))


class FileDurableStateCAS(DurableStateCAS):
    """One-record crash-durable CAS for a service-owned local state directory."""

    def __init__(self, path):
        self.durability_id = "file-durable-state-v1"
        path = Path(path).expanduser()
        _assert_managed_path_not_redirected(path)
        self.path = path.resolve()

    def _read_locked(self, key):
        if not self.path.exists():
            return 0, None
        payload = _read_private_json(self.path)
        if (
            type(payload) is not dict
            or set(payload) != {"schemaVersion", "key", "revision", "state"}
            or payload.get("schemaVersion") != MANAGED_CONTROLLER_STATE_SCHEMA
            or payload.get("key") != key
            or type(payload.get("revision")) is not int
            or payload["revision"] < 1
            or type(payload.get("state")) is not dict
        ):
            raise OnboardingError(
                "managed_controller_state_invalid",
                "Managed controller state is unavailable or invalid.",
                "quarantine_identity",
            )
        return payload["revision"], dict(payload["state"])

    def read(self, key):
        _validate_controller_key(key)
        with _managed_profile_lock(self.path, timeout_milliseconds=0):
            _assert_managed_path_not_redirected(self.path)
            return self._read_locked(key)

    def compare_exchange(self, key, expected_revision, next_state):
        _validate_controller_key(key)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("invalid expected revision")
        _validate_controller_state(next_state)
        with _managed_profile_lock(self.path, timeout_milliseconds=0):
            _assert_managed_path_not_redirected(self.path)
            current_revision, _current = self._read_locked(key)
            if current_revision != expected_revision:
                raise OnboardingError(
                    "managed_controller_state_conflict",
                    "Managed controller state changed concurrently.",
                    "retry_with_bounded_backoff",
                    retryable=True,
                    retry_after_seconds=1,
                )
            revision = current_revision + 1
            _private_write(
                self.path,
                {
                    "schemaVersion": MANAGED_CONTROLLER_STATE_SCHEMA,
                    "key": key,
                    "revision": revision,
                    "state": dict(next_state),
                },
            )
            return revision


class ManagedRecoveryAuthority:
    """Separately protected machine authority for bounded recovery decisions."""

    def __init__(self, authority_id, reconcile):
        if (
            type(authority_id) is not str
            or not _PROTECTION_ID_PATTERN.fullmatch(authority_id)
            or not callable(reconcile)
        ):
            raise ValueError("invalid managed recovery authority")
        self.authority_id = authority_id
        self._reconcile = reconcile

    def reconcile(self, request):
        return self._reconcile(dict(request))


def _secret_protector(protector=None, protect_secret=None, unprotect_secret=None):
    if protector is not None and (protect_secret is not None or unprotect_secret is not None):
        raise OnboardingError(
            "credential_protection_invalid",
            "Exactly one managed credential protection provider is required.",
            "install_supported_credential_provider",
        )
    if protector is None:
        protector = SecretProtector(
            WINDOWS_USER_PROTECTION_ID,
            protect_secret or _windows_protect_secret,
            unprotect_secret or _windows_unprotect_secret,
        )
    if not isinstance(protector, SecretProtector):
        raise OnboardingError(
            "credential_protection_invalid",
            "The managed credential protection provider is invalid.",
            "install_supported_credential_provider",
        )
    return protector


def _validate_agent_id(value):
    if type(value) is not str:
        raise OnboardingError(
            "managed_agent_id_invalid",
            "The managed connection profile has an invalid agent identifier.",
            "replace_managed_connection_profile",
        )
    agent_id = value.strip().lower()
    if not (3 <= len(agent_id) <= 64) or not _AGENT_ID_PATTERN.fullmatch(agent_id):
        raise OnboardingError(
            "managed_agent_id_invalid",
            "The managed connection profile has an invalid agent identifier.",
            "replace_managed_connection_profile",
        )
    return agent_id


def _validate_profile_id(value):
    if type(value) is not str:
        raise OnboardingError(
            "managed_profile_invalid",
            "The managed connection profile has an invalid profile identifier.",
            "replace_managed_connection_profile",
        )
    profile_id = value.strip().lower()
    if not _PROFILE_ID_PATTERN.fullmatch(profile_id):
        raise OnboardingError(
            "managed_profile_invalid",
            "The managed connection profile has an invalid profile identifier.",
            "replace_managed_connection_profile",
        )
    return profile_id


def _validate_base_url(value):
    if type(value) is not str or len(value) > 2048:
        raise OnboardingError(
            "managed_origin_invalid",
            "The managed service origin is invalid.",
            "replace_managed_connection_profile",
        )
    base_url = value.strip().rstrip("/")
    parsed = urlparse(base_url)
    hostname = (parsed.hostname or "").lower()
    loopback = hostname == "localhost"
    if hostname and not loopback:
        try:
            loopback = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            loopback = False
    if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
        raise OnboardingError(
            "managed_origin_invalid",
            "The managed service origin must use HTTPS.",
            "replace_managed_connection_profile",
        )
    if (
        not hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise OnboardingError(
            "managed_origin_invalid",
            "The managed service URL must be a credential-free canonical origin.",
            "replace_managed_connection_profile",
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise OnboardingError(
            "managed_origin_invalid",
            "The managed service origin contains an invalid port.",
            "replace_managed_connection_profile",
        ) from exc
    default_port = 443 if parsed.scheme == "https" else 80
    host_for_url = "[%s]" % hostname if ":" in hostname else hostname
    authority = (
        host_for_url
        if not port or port == default_port
        else "%s:%s" % (host_for_url, port)
    )
    return "%s://%s" % (parsed.scheme, authority)


def _credential_paths(project_root, agent_id):
    root = Path(project_root).expanduser().resolve()
    secret_dir = root / ".local-secrets" / "agents"
    return (
        secret_dir / (agent_id + ".json"),
        secret_dir / ("." + agent_id + ".pending.json"),
    )


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_ulong),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _blob(value):
    raw = bytes(value)
    buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    return _DataBlob(len(raw), buffer), buffer


def _validate_bound_id(value, field, allow_none=False):
    if value is None and allow_none:
        return None
    if type(value) is not str or not _BOUND_ID_PATTERN.fullmatch(value):
        raise OnboardingError(
            "managed_profile_invalid",
            "The managed connection profile has an invalid %s binding." % field,
            "replace_managed_connection_profile",
        )
    return value


def _validate_controller_key(value):
    if type(value) is not str or not _SHA256_PATTERN.fullmatch(value):
        raise ValueError("invalid managed controller key")
    return value


def _validate_controller_state(payload):
    required = {
        "schemaVersion",
        "profileId",
        "serviceInstanceId",
        "profileGeneration",
        "policyRevision",
        "activeProfileDigest",
        "activeTrustSha256",
        "phase",
        "attemptCount",
        "maxAttempts",
        "attemptLeaseExpiresAtEpoch",
        "nextAttemptAtEpoch",
        "lastFailureCode",
        "operationDigest",
        "quarantined",
    }
    if (
        type(payload) is not dict
        or set(payload) != required
        or payload.get("schemaVersion") != MANAGED_CONTROLLER_STATE_SCHEMA
        or type(payload.get("profileId")) is not str
        or not _PROFILE_ID_PATTERN.fullmatch(payload["profileId"])
        or type(payload.get("serviceInstanceId")) is not str
        or not _BOUND_ID_PATTERN.fullmatch(payload["serviceInstanceId"])
        or type(payload.get("profileGeneration")) is not int
        or payload["profileGeneration"] < 1
        or type(payload.get("policyRevision")) is not int
        or payload["policyRevision"] < 1
        or type(payload.get("activeProfileDigest")) is not str
        or not _SHA256_PATTERN.fullmatch(payload["activeProfileDigest"])
        or type(payload.get("activeTrustSha256")) is not str
        or not _SHA256_PATTERN.fullmatch(payload["activeTrustSha256"])
        or payload.get("phase") not in _CONTROLLER_PHASES
        or type(payload.get("attemptCount")) is not int
        or payload["attemptCount"] < 0
        or type(payload.get("maxAttempts")) is not int
        or not 1 <= payload["maxAttempts"] <= 64
        or payload["attemptCount"] > payload["maxAttempts"]
        or (
            payload.get("attemptLeaseExpiresAtEpoch") is not None
            and (
                type(payload["attemptLeaseExpiresAtEpoch"]) is not int
                or payload["attemptLeaseExpiresAtEpoch"] < 0
            )
        )
        or (
            payload.get("nextAttemptAtEpoch") is not None
            and (
                type(payload["nextAttemptAtEpoch"]) is not int
                or payload["nextAttemptAtEpoch"] < 0
            )
        )
        or (
            payload.get("lastFailureCode") is not None
            and (
                type(payload["lastFailureCode"]) is not str
                or not _SAFE_CODE_PATTERN.fullmatch(payload["lastFailureCode"])
            )
        )
        or (
            payload.get("operationDigest") is not None
            and (
                type(payload["operationDigest"]) is not str
                or not _SHA256_PATTERN.fullmatch(payload["operationDigest"])
            )
        )
        or type(payload.get("quarantined")) is not bool
        or (payload["phase"] == "quarantined") is not payload["quarantined"]
    ):
        raise OnboardingError(
            "managed_controller_state_invalid",
            "Managed controller state is unavailable or invalid.",
            "quarantine_identity",
        )
    phase = payload["phase"]
    attempt_count = payload["attemptCount"]
    lease = payload["attemptLeaseExpiresAtEpoch"]
    next_attempt = payload["nextAttemptAtEpoch"]
    failure = payload["lastFailureCode"]
    operation = payload["operationDigest"]
    coherent = (
        (
            phase == "pending"
            and attempt_count == 0
            and lease is None
            and next_attempt is None
            and failure is None
            and operation is None
        )
        or (
            phase == "connecting"
            and 1 <= attempt_count <= payload["maxAttempts"]
            and lease is not None
            and next_attempt is None
            and failure is None
            and operation is not None
        )
        or (
            phase == "retry_wait"
            and 1 <= attempt_count <= payload["maxAttempts"]
            and lease is None
            and next_attempt is not None
            and failure is not None
            and operation is not None
        )
        or (
            phase == "active"
            and attempt_count == 0
            and lease is None
            and next_attempt is None
            and failure is None
            and operation is not None
        )
        or (
            phase in {"quarantined", "halted"}
            and lease is None
            and next_attempt is None
            and failure is not None
            and operation is not None
        )
    )
    if not coherent:
        raise OnboardingError(
            "managed_controller_state_invalid",
            "Managed controller state is unavailable or invalid.",
            "quarantine_identity",
        )
    return dict(payload)


def _service_context_digest(context):
    material = json.dumps(
        {
            "clientKind": context.client_kind,
            "profilePurpose": context.purpose,
            "runtimeClass": context.runtime_class,
            "profileVerifierId": context.profile_verifier_id,
            "recoveryAuthorityId": context.recovery_authority_id,
            "projectId": context.project_id,
            "maxAttempts": context.max_attempts,
            "baseRetrySeconds": context.base_retry_seconds,
            "maxRetrySeconds": context.max_retry_seconds,
            "attemptLeaseSeconds": context.attempt_lease_seconds,
            "serviceInstanceId": context.service_instance_id,
            "workloadIdentityId": context.workload_identity_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(
        b"multiagentmemory.managed-service-context.v1\0" + material
    ).hexdigest()


def _profile_binding(
    profile_id,
    base_url,
    agent_id,
    ca_sha256,
    company_id="",
    workspace_id="",
    project_id=None,
    device_id="",
    policy_revision=0,
    profile_generation=0,
    profile_purpose="",
    client_kind="",
    runtime_class=MANAGED_RUNTIME_CLASS_PER_USER,
    enrollment_kind="",
    protection_id=WINDOWS_USER_PROTECTION_ID,
    service_instance_id="",
    workload_identity_id="",
):
    material = json.dumps(
        {
            "agentId": agent_id,
            "baseUrl": base_url,
            "caSha256": ca_sha256,
            "clientKind": client_kind,
            "companyId": company_id,
            "deviceId": device_id,
            "enrollmentKind": enrollment_kind,
            "policyRevision": policy_revision,
            "profileId": profile_id,
            "profileGeneration": profile_generation,
            "profilePurpose": profile_purpose,
            "runtimeClass": runtime_class,
            "projectId": project_id,
            "protectionId": protection_id,
            "serviceInstanceId": service_instance_id,
            "workloadIdentityId": workload_identity_id,
            "workspaceId": workspace_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(
        b"multiagentmemory.managed-profile-binding.v1\0" + material
    ).hexdigest()


def _secret_entropy(profile_id, agent_id, profile_binding):
    return hashlib.sha256(
        (
            "MultiAgentMemory managed credential\0"
            + profile_id
            + "\0"
            + agent_id
            + "\0"
            + profile_binding
        ).encode("utf-8")
    ).digest()


def _windows_protect_secret(secret, profile_id, agent_id, profile_binding):
    """Protect one credential for the current Windows user without UI."""
    if os.name != "nt":
        raise OnboardingError(
            "protected_storage_unavailable",
            "Managed credential protection is unavailable on this operating system.",
            "install_supported_credential_provider",
        )
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    input_blob, input_buffer = _blob(secret.encode("utf-8"))
    entropy_blob, entropy_buffer = _blob(
        _secret_entropy(profile_id, agent_id, profile_binding)
    )
    output_blob = _DataBlob()
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.c_wchar_p,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = ctypes.c_int
    if not crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        0x1,
        ctypes.byref(output_blob),
    ):
        raise OnboardingError(
            "credential_protection_failed",
            "The managed credential could not be protected.",
            "repair_protected_credential_store",
        )
    try:
        protected = ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(output_blob.pbData)
        del input_buffer, entropy_buffer
    return base64.b64encode(protected).decode("ascii")


def _windows_unprotect_secret(protected, profile_id, agent_id, profile_binding):
    """Recover one current-user Windows protected credential without UI."""
    if os.name != "nt":
        raise OnboardingError(
            "protected_storage_unavailable",
            "Managed credential protection is unavailable on this operating system.",
            "install_supported_credential_provider",
        )
    try:
        ciphertext = base64.b64decode(protected, validate=True)
    except (ValueError, TypeError) as exc:
        raise OnboardingError(
            "credential_corrupt",
            "The managed credential is corrupt.",
            "quarantine_credential_state",
        ) from exc
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    input_blob, input_buffer = _blob(ciphertext)
    entropy_blob, entropy_buffer = _blob(
        _secret_entropy(profile_id, agent_id, profile_binding)
    )
    output_blob = _DataBlob()
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(ctypes.c_wchar_p),
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = ctypes.c_int
    if not crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        0x1,
        ctypes.byref(output_blob),
    ):
        raise OnboardingError(
            "credential_unavailable",
            "The managed credential cannot be opened by this Windows identity.",
            "quarantine_identity",
        )
    try:
        raw = ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(output_blob.pbData)
        del input_buffer, entropy_buffer
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OnboardingError(
            "credential_corrupt",
            "The managed credential is corrupt.",
            "quarantine_credential_state",
        ) from exc


def _durable_replace(staged, path):
    """Replace one staged file with platform write-through durability."""
    staged = Path(staged)
    path = Path(path)
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.MoveFileExW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_ulong,
        ]
        kernel32.MoveFileExW.restype = ctypes.c_int
        if not kernel32.MoveFileExW(
            os.path.abspath(str(staged)),
            os.path.abspath(str(path)),
            0x1 | 0x8,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return
    os.replace(str(staged), str(path))
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory = os.open(str(path.parent), flags)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _private_write(path, payload):
    """Atomically replace one private JSON file, preserving its prior state on failure."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _assert_managed_path_not_redirected(path)
    handle, temporary = tempfile.mkstemp(
        prefix=".memoryendpoints-agent-", dir=str(path.parent)
    )
    staged = Path(temporary)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(handle, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        _durable_replace(staged, path)
        staged = None
        try:
            os.chmod(str(path), 0o600)
        except OSError:
            pass
    finally:
        if staged is not None:
            try:
                staged.unlink()
            except OSError:
                pass


def _private_write_bytes(path, content):
    """Atomically write one installer-owned support file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _assert_managed_path_not_redirected(path)
    handle, temporary = tempfile.mkstemp(
        prefix=".memoryendpoints-install-", dir=str(path.parent)
    )
    staged = Path(temporary)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(handle, 0o600)
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        _durable_replace(staged, path)
        staged = None
        try:
            os.chmod(str(path), 0o600)
        except OSError:
            pass
    finally:
        if staged is not None:
            try:
                staged.unlink()
            except OSError:
                pass


def _promote_pending(pending_path, target_path):
    if target_path.exists():
        raise OnboardingError(
            "credential_state_conflict",
            "Final and pending managed credential state conflict.",
            "quarantine_credential_state",
        )
    os.replace(str(pending_path), str(target_path))
    try:
        os.chmod(str(target_path), 0o600)
    except OSError:
        pass


def _read_private_json(path):
    try:
        raw = Path(path).read_bytes()
        if len(raw) > MAX_LOCAL_JSON_BYTES:
            raise ValueError("oversized local JSON")
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OnboardingError(
            "local_state_invalid",
            "A local onboarding state file is unavailable or invalid.",
            "quarantine_enrollment_state",
        ) from exc
    except ValueError as exc:
        raise OnboardingError(
            "local_state_invalid",
            "A local onboarding state file is unavailable or invalid.",
            "quarantine_enrollment_state",
        ) from exc
    if not isinstance(payload, dict):
        raise OnboardingError(
            "local_state_invalid",
            "A local onboarding state file has an invalid schema.",
            "quarantine_enrollment_state",
        )
    return payload


def _credential_document(
    base_url,
    company_id,
    workspace_id,
    project_id,
    agent_id,
    token,
    profile_id,
    profile_binding,
    protector=None,
):
    protector = _secret_protector(protector)
    return {
        "schemaVersion": AGENT_CREDENTIAL_SCHEMA,
        "profileId": profile_id,
        "profileBinding": profile_binding,
        "baseUrl": base_url,
        "companyId": company_id,
        "workspaceId": workspace_id,
        "projectId": project_id,
        "agentId": agent_id,
        "credentialProtection": protector.protection_id,
        "protectedAgentToken": protector.protect(
            token, profile_id, agent_id, profile_binding
        ),
    }


def _validated_credential_document(
    payload,
    base_url,
    agent_id,
    profile_id,
    profile_binding,
    protector=None,
):
    protector = _secret_protector(protector)
    if payload.get("schemaVersion") != AGENT_CREDENTIAL_SCHEMA:
        raise OnboardingError(
            "credential_schema_invalid",
            "The managed credential has an invalid schema.",
            "quarantine_credential_state",
        )
    required = (
        "baseUrl",
        "profileId",
        "profileBinding",
        "companyId",
        "workspaceId",
        "projectId",
        "agentId",
        "credentialProtection",
        "protectedAgentToken",
    )
    required_strings = tuple(key for key in required if key != "projectId")
    if any(type(payload.get(key)) is not str or not payload.get(key).strip() for key in required_strings):
        raise OnboardingError(
            "credential_schema_invalid",
            "The managed credential is incomplete.",
            "quarantine_credential_state",
        )
    if payload.get("projectId") is not None and (
        type(payload.get("projectId")) is not str
        or not payload.get("projectId").strip()
    ):
        raise OnboardingError(
            "credential_schema_invalid",
            "The managed credential has an invalid project binding.",
            "quarantine_credential_state",
        )
    if set(payload) != {"schemaVersion", *required}:
        raise OnboardingError(
            "credential_schema_invalid",
            "The managed credential has unexpected fields.",
            "quarantine_credential_state",
        )
    if _validate_base_url(payload["baseUrl"]) != base_url:
        raise OnboardingError(
            "credential_binding_mismatch",
            "The managed credential belongs to a different service origin.",
            "quarantine_identity",
        )
    if _validate_profile_id(payload["profileId"]) != profile_id:
        raise OnboardingError(
            "credential_profile_mismatch",
            "The managed credential belongs to a different connection profile.",
            "quarantine_identity",
        )
    if (
        not isinstance(payload.get("profileBinding"), str)
        or not _SHA256_PATTERN.fullmatch(payload["profileBinding"])
        or not secrets.compare_digest(payload["profileBinding"], profile_binding)
    ):
        raise OnboardingError(
            "credential_profile_mismatch",
            "The managed credential belongs to a different trust profile.",
            "quarantine_identity",
        )
    if payload["agentId"].strip().lower() != agent_id:
        raise OnboardingError(
            "credential_binding_mismatch",
            "The managed credential belongs to a different agent.",
            "quarantine_identity",
        )
    if payload["credentialProtection"] != protector.protection_id:
        raise OnboardingError(
            "credential_protection_invalid",
            "The managed credential uses an unsupported protection method.",
            "quarantine_credential_state",
        )
    if (
        len(payload["companyId"]) > 160
        or len(payload["workspaceId"]) > 160
        or (payload["projectId"] is not None and len(payload["projectId"]) > 160)
        or len(payload["protectedAgentToken"]) > MAX_LOCAL_JSON_BYTES // 2
    ):
        raise OnboardingError(
            "credential_schema_invalid",
            "The managed credential contains an invalid field size.",
            "quarantine_credential_state",
        )
    token = protector.unprotect(
        payload["protectedAgentToken"].strip(),
        profile_id,
        agent_id,
        profile_binding,
    )
    if type(token) is not str:
        raise OnboardingError(
            "credential_corrupt",
            "The managed credential protector returned an invalid value.",
            "quarantine_credential_state",
        )
    token = token.strip()
    if not _AGENT_TOKEN_PATTERN.fullmatch(token):
        raise OnboardingError(
            "credential_corrupt",
            "The managed credential is not a governed agent credential.",
            "quarantine_credential_state",
        )
    return {
        "baseUrl": base_url,
        "companyId": payload["companyId"].strip(),
        "workspaceId": payload["workspaceId"].strip(),
        "projectId": payload["projectId"].strip() if payload["projectId"] is not None else None,
        "agentId": agent_id,
        "agentTokenSecret": token,
    }


def _invite_fingerprint(invite_secret):
    return "sha256:" + hashlib.sha256(invite_secret.encode("utf-8")).hexdigest()


def _new_agent_token_secret():
    return "me_agent_v1.agenttoken-%s.%s" % (
        secrets.token_hex(10),
        secrets.token_urlsafe(32),
    )


def _new_idempotency_key():
    return secrets.token_urlsafe(32)


def _pending_marker(
    base_url,
    profile_id,
    agent_id,
    invite_secret,
    candidate_token,
    idempotency_key,
    profile_binding,
    protector=None,
    state="redemption_pending",
):
    protector = _secret_protector(protector)
    return {
        "schemaVersion": PENDING_SCHEMA,
        "profileId": profile_id,
        "profileBinding": profile_binding,
        "baseUrl": base_url,
        "agentId": agent_id,
        "state": state,
        "inviteFingerprint": _invite_fingerprint(invite_secret),
        "credentialProtection": protector.protection_id,
        "protectedAgentToken": protector.protect(
            candidate_token, profile_id, agent_id, profile_binding
        ),
        "protectedIdempotencyKey": protector.protect(
            idempotency_key, profile_id, agent_id, profile_binding
        ),
        "containsCredential": True,
    }


def _extract_invite_secret(value, base_url, agent_id):
    if type(value) is not str or len(value.encode("utf-8")) > MAX_LOCAL_JSON_BYTES:
        raise OnboardingError(
            "managed_invitation_invalid",
            "The managed invitation source is invalid.",
            "replace_managed_invitation",
        )
    raw = value.strip()
    if not raw:
        raise OnboardingError(
            "managed_invitation_invalid",
            "The managed invitation source is empty.",
            "replace_managed_invitation",
        )
    payload = None
    if raw.startswith("{"):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OnboardingError(
                "managed_invitation_invalid",
                "The managed invitation source contains invalid JSON.",
                "replace_managed_invitation",
            ) from exc
        if not isinstance(payload, dict):
            raise OnboardingError(
                "managed_invitation_invalid",
                "The managed invitation source must contain a JSON object.",
                "replace_managed_invitation",
            )
        source_agent_id = payload.get("agentId")
        if source_agent_id is not None and type(source_agent_id) is not str:
            raise OnboardingError(
                "managed_invitation_invalid",
                "The managed invitation source has an invalid agent binding.",
                "replace_managed_invitation",
            )
        source_agent_id = (source_agent_id or "").strip().lower()
        if source_agent_id and source_agent_id != agent_id:
            raise OnboardingError(
                "managed_invitation_mismatch",
                "The managed invitation belongs to a different agent.",
                "quarantine_enrollment_state",
            )
        source_base_url = payload.get("baseUrl")
        if source_base_url is not None and type(source_base_url) is not str:
            raise OnboardingError(
                "managed_invitation_invalid",
                "The managed invitation source has an invalid origin binding.",
                "replace_managed_invitation",
            )
        source_base_url = (source_base_url or "").strip()
        if source_base_url and _validate_base_url(source_base_url) != base_url:
            raise OnboardingError(
                "managed_invitation_mismatch",
                "The managed invitation belongs to a different service origin.",
                "quarantine_enrollment_state",
            )
        raw_value = payload.get("inviteSecret") or payload.get("inviteUrl") or ""
        if type(raw_value) is not str:
            raise OnboardingError(
                "managed_invitation_invalid",
                "The managed invitation source has an invalid credential field.",
                "replace_managed_invitation",
            )
        raw = raw_value.strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        parsed = urlparse(raw)
        if _validate_base_url("%s://%s" % (parsed.scheme, parsed.netloc)) != base_url:
            raise OnboardingError(
                "managed_invitation_mismatch",
                "The managed invitation URL belongs to a different service origin.",
                "quarantine_enrollment_state",
            )
        try:
            fragment = parse_qs(parsed.fragment, strict_parsing=True)
        except ValueError as exc:
            raise OnboardingError(
                "managed_invitation_invalid",
                "The managed invitation URL has an invalid fragment.",
                "replace_managed_invitation",
            ) from exc
        if set(fragment) != {"invite"} or len(fragment["invite"]) != 1:
            raise OnboardingError(
                "managed_invitation_invalid",
                "The managed invitation URL has an invalid fragment.",
                "replace_managed_invitation",
            )
        raw = fragment["invite"][0]
    if not _INVITE_PATTERN.fullmatch(raw):
        raise OnboardingError(
            "managed_invitation_invalid",
            "The managed invitation source does not contain a governed invitation.",
            "replace_managed_invitation",
        )
    return raw


def _read_invite_source(invite_file, invite_environment, environ, base_url, agent_id):
    environment = os.environ if environ is None else environ
    environment_name = str(invite_environment or DEFAULT_INVITE_ENVIRONMENT).strip()
    environment_value = environment.get(environment_name) if environment_name else None
    if invite_file and environment_value:
        raise OnboardingError(
            "managed_invitation_conflict",
            "Exactly one managed invitation source is required.",
            "quarantine_enrollment_state",
        )
    if invite_file:
        try:
            raw = Path(invite_file).expanduser().read_bytes()
            if len(raw) > MAX_LOCAL_JSON_BYTES:
                raise ValueError("oversized invitation source")
            value = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise OnboardingError(
                "managed_invitation_invalid",
                "The managed invitation source is unavailable or invalid.",
                "replace_managed_invitation",
            ) from exc
        except ValueError as exc:
            raise OnboardingError(
                "managed_invitation_invalid",
                "The managed invitation source is unavailable or invalid.",
                "replace_managed_invitation",
            ) from exc
    elif environment_value:
        value = environment_value
    else:
        raise OnboardingError(
            "managed_invitation_missing",
            "No installer-managed invitation is available.",
            "install_managed_invitation",
        )
    return _extract_invite_secret(value, base_url, agent_id)


def _windows_local_app_data():
    """Resolve LocalAppData through the Windows shell, not process environment."""
    if os.name != "nt":
        raise OnboardingError(
            "managed_profile_discovery_unavailable",
            "Installer-managed profile discovery is unavailable on this platform.",
            "install_supported_connection_controller",
        )
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.SHGetFolderPathW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_wchar_p,
    ]
    shell32.SHGetFolderPathW.restype = ctypes.c_long
    buffer = ctypes.create_unicode_buffer(32768)
    # CSIDL_LOCAL_APPDATA. Do not create folders during read-only discovery.
    result = shell32.SHGetFolderPathW(None, 0x001C, None, 0, buffer)
    if result != 0 or not buffer.value:
        raise OnboardingError(
            "managed_profile_discovery_unavailable",
            "Windows could not locate the installer-managed profile directory.",
            "repair_managed_connection_installation",
        )
    return Path(buffer.value)


def _managed_profile_candidates():
    """Return the single per-user installer location; never scan disks or repos."""
    return (
        _windows_local_app_data()
        / MANAGED_USER_DIRECTORY
        / MANAGED_PROFILE_FILE,
    )


def _path_is_link_or_junction(path):
    path = Path(path)
    return path.is_symlink() or (
        hasattr(path, "is_junction") and path.is_junction()
    )


def _assert_managed_path_not_redirected(path):
    current = Path(path)
    while current != Path(current.anchor):
        if current.exists() and _path_is_link_or_junction(current):
            raise OnboardingError(
                "managed_profile_invalid",
                "Managed connection state cannot use links or junctions.",
                "quarantine_profile_conflict",
            )
        current = current.parent


def _resolve_managed_profile(profile_path=None, candidates=None):
    if profile_path is not None:
        choices = (Path(profile_path).expanduser(),)
    else:
        choices = tuple(candidates or _managed_profile_candidates())
    existing = []
    for candidate in choices:
        candidate = Path(candidate)
        if candidate.is_file():
            existing.append(candidate)
    if not existing:
        raise OnboardingError(
            "managed_profile_missing",
            "No installer-managed MemoryEndpoints connection is available.",
            "install_managed_connection_profile",
        )
    if len(existing) != 1:
        raise OnboardingError(
            "managed_profile_conflict",
            "More than one managed MemoryEndpoints connection profile is installed.",
            "quarantine_profile_conflict",
        )
    profile = existing[0]
    _assert_managed_path_not_redirected(profile)
    return profile.resolve()


def _validate_managed_profile_payload(payload, profile_verifier=None):
    required = {
        "schemaVersion",
        "profileId",
        "profilePurpose",
        "clientKind",
        "runtimeClass",
        "enrollmentKind",
        "commonsFallback",
        "identityFallback",
        "baseUrl",
        "agentId",
        "companyId",
        "workspaceId",
        "projectId",
        "deviceId",
        "serviceInstanceId",
        "workloadIdentityId",
        "policyRevision",
        "profileGeneration",
        "trustMode",
        "caSha256",
        "protectionId",
        "profileVerifierId",
    }
    if set(payload) != required or payload.get("schemaVersion") != MANAGED_PROFILE_SCHEMA:
        raise OnboardingError(
            "managed_profile_invalid",
            "The managed connection profile has an invalid schema.",
            "replace_managed_connection_profile",
        )
    profile_id = _validate_profile_id(payload.get("profileId"))
    agent_id = _validate_agent_id(payload.get("agentId"))
    base_url = _validate_base_url(payload.get("baseUrl"))
    if not base_url.startswith("https://"):
        raise OnboardingError(
            "managed_profile_invalid",
            "A managed LAN connection must use HTTPS.",
            "replace_managed_connection_profile",
        )
    if payload.get("profilePurpose") != MANAGED_PROFILE_PURPOSE:
        raise OnboardingError(
            "managed_profile_invalid",
            "The managed connection profile has an invalid purpose.",
            "replace_managed_connection_profile",
        )
    client_kind = payload.get("clientKind")
    if type(client_kind) is not str or not _CLIENT_KIND_PATTERN.fullmatch(client_kind):
        raise OnboardingError(
            "managed_profile_invalid",
            "The managed connection profile has an invalid client kind.",
            "replace_managed_connection_profile",
        )
    runtime_class = payload.get("runtimeClass")
    if runtime_class not in MANAGED_RUNTIME_CLASSES:
        raise OnboardingError(
            "managed_profile_invalid",
            "The managed connection profile has an invalid runtime class.",
            "replace_managed_connection_profile",
        )
    if (
        payload.get("enrollmentKind") != MANAGED_ENROLLMENT_KIND
        or payload.get("commonsFallback") != MANAGED_FALLBACK_POLICY
        or payload.get("identityFallback") != MANAGED_FALLBACK_POLICY
    ):
        raise OnboardingError(
            "managed_profile_invalid",
            "The managed connection profile permits an unsupported identity fallback.",
            "quarantine_profile_conflict",
        )
    company_id = _validate_bound_id(payload.get("companyId"), "company")
    workspace_id = _validate_bound_id(payload.get("workspaceId"), "workspace")
    project_id = _validate_bound_id(payload.get("projectId"), "project", allow_none=True)
    device_id = _validate_bound_id(payload.get("deviceId"), "device")
    service_instance_id = _validate_bound_id(
        payload.get("serviceInstanceId"), "service instance"
    )
    workload_identity_id = _validate_bound_id(
        payload.get("workloadIdentityId"), "workload identity"
    )
    for field in ("policyRevision", "profileGeneration"):
        if type(payload.get(field)) is not int or payload[field] < 1:
            raise OnboardingError(
                "managed_profile_invalid",
                "The managed connection profile has an invalid revision.",
                "replace_managed_connection_profile",
            )
    if payload.get("trustMode") != MANAGED_TRUST_MODE:
        raise OnboardingError(
            "managed_profile_invalid",
            "The managed connection profile has an unsupported trust mode.",
            "replace_managed_connection_profile",
        )
    ca_sha256 = payload.get("caSha256")
    if type(ca_sha256) is not str or not _SHA256_PATTERN.fullmatch(ca_sha256):
        raise OnboardingError(
            "managed_profile_invalid",
            "The managed connection profile has an invalid trust digest.",
            "replace_managed_connection_profile",
        )
    protection_id = payload.get("protectionId")
    verifier_id = payload.get("profileVerifierId")
    if (
        type(protection_id) is not str
        or not _PROTECTION_ID_PATTERN.fullmatch(protection_id)
        or type(verifier_id) is not str
        or not _PROTECTION_ID_PATTERN.fullmatch(verifier_id)
    ):
        raise OnboardingError(
            "managed_profile_invalid",
            "The managed connection profile has an invalid trust provider binding.",
            "replace_managed_connection_profile",
        )
    if runtime_class == MANAGED_RUNTIME_CLASS_UNATTENDED_SERVICE and (
        project_id is None
        or protection_id == WINDOWS_USER_PROTECTION_ID
        or verifier_id == "protected-state-binding"
    ):
        raise OnboardingError(
            "managed_service_profile_invalid",
            "An unattended service profile requires project, workload-vault, and external verifier bindings.",
            "quarantine_profile_conflict",
        )
    if verifier_id != "protected-state-binding":
        if not callable(profile_verifier):
            raise OnboardingError(
                "managed_profile_verifier_missing",
                "The managed connection profile requires its preauthorized verifier.",
                "rebootstrap_managed_identity",
            )
        try:
            verified = profile_verifier(verifier_id, dict(payload))
        except Exception as exc:
            raise OnboardingError(
                "managed_profile_verification_failed",
                "The managed connection profile could not be verified.",
                "rebootstrap_managed_identity",
            ) from exc
        if verified is not True:
            raise OnboardingError(
                "managed_profile_verification_failed",
                "The managed connection profile failed independent verification.",
                "rebootstrap_managed_identity",
            )
    profile = {
        key: payload[key]
        for key in required
        if key != "schemaVersion"
    }
    profile.update(
        {
            "profileId": profile_id,
            "agentId": agent_id,
            "baseUrl": base_url,
            "companyId": company_id,
            "workspaceId": workspace_id,
            "projectId": project_id,
            "deviceId": device_id,
            "serviceInstanceId": service_instance_id,
            "workloadIdentityId": workload_identity_id,
            "caSha256": ca_sha256,
        }
    )
    profile["profileBinding"] = _profile_binding(
        profile_id,
        base_url,
        agent_id,
        ca_sha256,
        company_id=company_id,
        workspace_id=workspace_id,
        project_id=project_id,
        device_id=device_id,
        policy_revision=profile["policyRevision"],
        profile_generation=profile["profileGeneration"],
        profile_purpose=profile["profilePurpose"],
        client_kind=profile["clientKind"],
        runtime_class=profile["runtimeClass"],
        enrollment_kind=profile["enrollmentKind"],
        protection_id=profile["protectionId"],
        service_instance_id=profile["serviceInstanceId"],
        workload_identity_id=profile["workloadIdentityId"],
    )
    return profile


def _load_managed_profile(path, profile_verifier=None):
    try:
        payload = _read_private_json(path)
    except OnboardingError as exc:
        raise OnboardingError(
            "managed_profile_invalid",
            "The managed connection profile is unreadable or invalid.",
            "replace_managed_connection_profile",
        ) from exc
    return _validate_managed_profile_payload(payload, profile_verifier)


def _managed_state_paths(profile_path):
    root_path = Path(profile_path).parent
    _assert_managed_path_not_redirected(root_path)
    root = root_path.resolve()
    paths = {
        "ca": root / MANAGED_TRUST_FILE,
        "invite": root / MANAGED_INVITE_FILE,
        "credential": root / MANAGED_CREDENTIAL_FILE,
        "pending": root / MANAGED_PENDING_FILE,
    }
    for path in paths.values():
        resolved = path.resolve()
        if resolved != root and root not in resolved.parents:
            raise OnboardingError(
                "managed_profile_invalid",
                "Managed connection state escapes its installer-owned directory.",
                "replace_managed_connection_profile",
            )
        current = path
        while current != root:
            if current.exists() and _path_is_link_or_junction(current):
                raise OnboardingError(
                    "managed_profile_invalid",
                    "Managed connection state cannot use links or junctions.",
                    "replace_managed_connection_profile",
                )
            current = current.parent
    return paths


def _read_managed_invitation(
    path,
    profile_id,
    agent_id,
    profile_binding,
    protector=None,
):
    protector = _secret_protector(protector)
    try:
        payload = _read_private_json(path)
    except OnboardingError as exc:
        raise OnboardingError(
            "managed_invitation_invalid",
            "The managed invitation is unreadable or invalid.",
            "replace_managed_invitation",
        ) from exc
    required = {
        "schemaVersion",
        "profileId",
        "profileBinding",
        "agentId",
        "credentialProtection",
        "protectedInviteSecret",
    }
    if set(payload) != required or payload.get("schemaVersion") != MANAGED_INVITE_SCHEMA:
        raise OnboardingError(
            "managed_invitation_invalid",
            "The managed invitation has an invalid schema.",
            "replace_managed_invitation",
        )
    if (
        _validate_profile_id(payload.get("profileId")) != profile_id
        or _validate_agent_id(payload.get("agentId")) != agent_id
        or not isinstance(payload.get("profileBinding"), str)
        or not secrets.compare_digest(
            payload.get("profileBinding"), profile_binding
        )
        or payload.get("credentialProtection") != protector.protection_id
    ):
        raise OnboardingError(
            "managed_invitation_mismatch",
            "The managed invitation does not match this connection profile.",
            "quarantine_profile_conflict",
        )
    protected = payload.get("protectedInviteSecret")
    if type(protected) is not str or not protected.strip():
        raise OnboardingError(
            "managed_invitation_invalid",
            "The managed invitation has an invalid protected value.",
            "replace_managed_invitation",
        )
    invite = protector.unprotect(
        protected.strip(), profile_id, agent_id, profile_binding
    )
    if type(invite) is not str:
        raise OnboardingError(
            "managed_invitation_invalid",
            "The managed invitation protector returned an invalid value.",
            "replace_managed_invitation",
        )
    invite = invite.strip()
    if not _INVITE_PATTERN.fullmatch(invite):
        raise OnboardingError(
            "managed_invitation_invalid",
            "The managed invitation is not a governed invitation.",
            "replace_managed_invitation",
        )
    return invite


def _validate_managed_ca(path, expected_sha256):
    try:
        content = Path(path).read_bytes()
    except OSError as exc:
        raise OnboardingError(
            "managed_trust_unavailable",
            "The installer-managed LAN trust bundle is unavailable.",
            "restore_managed_trust",
        ) from exc
    if not content or len(content) > MAX_CA_BYTES:
        raise OnboardingError(
            "managed_trust_invalid",
            "The installer-managed LAN trust bundle has an invalid size.",
            "replace_managed_trust",
        )
    actual = hashlib.sha256(content).hexdigest()
    if not secrets.compare_digest(actual, expected_sha256):
        raise OnboardingError(
            "managed_trust_mismatch",
            "The installer-managed LAN trust bundle failed integrity validation.",
            "replace_managed_trust",
        )
    return content


def _ssl_context(base_url, ca_bundle=None, ca_content=None):
    if not base_url.startswith("https://"):
        return None
    if ca_bundle and ca_content is not None:
        raise OnboardingError(
            "managed_trust_invalid",
            "Exactly one managed trust source is required.",
            "replace_managed_trust",
        )
    if ca_content is None and ca_bundle:
        bundle = Path(ca_bundle).expanduser().resolve()
        if not bundle.is_file():
            raise OnboardingError(
                "managed_trust_unavailable",
                "The installer-managed LAN trust bundle is unavailable.",
                "restore_managed_trust",
            )
        try:
            ca_content = bundle.read_bytes()
        except OSError as exc:
            raise OnboardingError(
                "managed_trust_unavailable",
                "The installer-managed LAN trust bundle is unavailable.",
                "restore_managed_trust",
            ) from exc
    if ca_content is not None:
        if not ca_content or len(ca_content) > MAX_CA_BYTES:
            raise OnboardingError(
                "managed_trust_invalid",
                "The installer-managed LAN trust bundle has an invalid size.",
                "replace_managed_trust",
            )
        try:
            pem = bytes(ca_content).decode("ascii")
            return ssl.create_default_context(cadata=pem)
        except (UnicodeDecodeError, OSError, ssl.SSLError) as exc:
            raise OnboardingError(
                "managed_trust_invalid",
                "The installer-managed LAN trust bundle could not be loaded.",
                "replace_managed_trust",
            ) from exc
    return ssl.create_default_context()


def _read_json_response(response):
    try:
        raw = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
        if len(raw) > MAX_HTTP_RESPONSE_BYTES:
            raise _OutcomeUnknown("response_oversized")
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _OutcomeUnknown("response_unreadable") from exc
    if not isinstance(payload, dict):
        raise _OutcomeUnknown("response_invalid")
    return payload


def _request_json(
    base_url,
    path,
    method,
    body,
    token,
    context,
    open_url,
    idempotency_key=None,
):
    headers = {"Accept": "application/json"}
    data = None
    if token:
        headers["Authorization"] = "Bearer " + token
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    request = Request(base_url + path, data=data, headers=headers, method=method)
    kwargs = {"timeout": 30}
    if context is not None:
        kwargs["context"] = context
    try:
        with open_url(request, **kwargs) as response:
            return int(getattr(response, "status", 200)), _read_json_response(response)
    except HTTPError as exc:
        try:
            return int(exc.code), _read_json_response(exc)
        except _OutcomeUnknown:
            return int(exc.code), {}
    except (URLError, TimeoutError, OSError) as exc:
        raise _OutcomeUnknown("transport_unavailable") from exc


def _verify_credential(base_url, document, context, open_url):
    try:
        status, payload = _request_json(
            base_url,
            ME_ROUTE,
            "GET",
            None,
            document["agentTokenSecret"],
            context,
            open_url,
        )
    except _OutcomeUnknown as exc:
        raise OnboardingError(
            "credential_verification_unavailable",
            "The managed credential could not be verified; it remains protected for retry.",
            "retry_with_bounded_backoff",
            retryable=True,
        ) from exc
    if status in (429,) or status >= 500:
        raise OnboardingError(
            "credential_verification_deferred",
            "The managed service is temporarily unable to verify the protected credential.",
            "retry_with_bounded_backoff",
            retryable=True,
        )
    if status in (404, 405, 406, 415, 426):
        raise OnboardingError(
            "managed_server_contract_incompatible",
            "The managed service does not expose the required credential verification contract.",
            "hold_for_compatible_server_release",
        )
    if status in (401, 403):
        raise OnboardingError(
            "credential_rejected",
            "The managed credential was rejected and remains protected.",
            "reconcile_credential_with_recovery_authority",
        )
    principal = payload.get("principal") if isinstance(payload, dict) else None
    if status < 200 or status >= 300 or payload.get("ok") is not True or not isinstance(principal, dict):
        raise OnboardingError(
            "credential_verification_protocol_invalid",
            "The managed service returned an invalid credential verification response.",
            "hold_for_compatible_server_release",
        )
    principal_agent_id = principal.get("agentId")
    principal_company_id = principal.get("companyId")
    principal_workspace_id = principal.get("workspaceId")
    principal_project_id = principal.get("projectId")
    if (
        principal.get("credentialType") not in ("agent", "agent_token")
        or type(principal_agent_id) is not str
        or principal_agent_id.strip().lower() != document["agentId"]
        or type(principal_company_id) is not str
        or principal_company_id.strip() != document["companyId"]
        or type(principal_workspace_id) is not str
        or principal_workspace_id.strip() != document["workspaceId"]
        or principal_project_id != document["projectId"]
    ):
        raise OnboardingError(
            "credential_binding_mismatch",
            "The managed credential returned a mismatched principal.",
            "quarantine_identity",
        )


def _assert_expected_principal_binding(
    document,
    expected_company_id,
    expected_workspace_id,
    expected_project_id,
):
    if (
        (expected_company_id is not _UNBOUND and document["companyId"] != expected_company_id)
        or (expected_workspace_id is not _UNBOUND and document["workspaceId"] != expected_workspace_id)
        or (expected_project_id is not _UNBOUND and document["projectId"] != expected_project_id)
    ):
        raise OnboardingError(
            "credential_binding_mismatch",
            "The protected credential is outside the managed profile binding.",
            "quarantine_identity",
        )


def _public_result(status, agent_id):
    return {
        "schemaVersion": MANAGED_RESULT_SCHEMA,
        "ok": True,
        "state": "active",
        "code": "managed_connection_active",
        "controllerAction": "none",
        "requiredAuthority": "none",
        "retryable": False,
        "retryAfterSeconds": None,
        "terminal": False,
        "status": status,
        "agentId": agent_id,
        "credentialPersisted": True,
        "credentialVerified": True,
        "managedProfile": False,
        "credentialValuesPrinted": False,
        "tenantIdentifiersPrinted": False,
        "valuesRedacted": True,
    }


def _public_error_result(exc):
    metadata = CONTROLLER_ACTION_METADATA[exc.action]
    return {
        "schemaVersion": MANAGED_RESULT_SCHEMA,
        "ok": False,
        "state": exc.state,
        "code": exc.code,
        "controllerAction": exc.action,
        "requiredAuthority": metadata["authority"],
        "retryable": exc.retryable,
        "retryAfterSeconds": exc.retry_after_seconds,
        "terminal": bool(metadata["terminal"]),
        "error": "The managed connection failed safely; use the typed code and controller action.",
        "credentialValuesPrinted": False,
        "tenantIdentifiersPrinted": False,
        "valuesRedacted": True,
    }


def parse_managed_connection_result(payload):
    """Validate the public-safe controller result without accepting extensions."""
    if type(payload) is not dict or payload.get("schemaVersion") != MANAGED_RESULT_SCHEMA:
        raise ValueError("invalid managed connection result")
    common = {
        "schemaVersion",
        "ok",
        "state",
        "code",
        "controllerAction",
        "requiredAuthority",
        "retryable",
        "retryAfterSeconds",
        "terminal",
        "credentialValuesPrinted",
        "tenantIdentifiersPrinted",
        "valuesRedacted",
    }
    expected = (
        common | {"status", "agentId", "credentialPersisted", "credentialVerified", "managedProfile"}
        if payload.get("ok") is True
        else common | {"error"}
    )
    if set(payload) != expected:
        raise ValueError("invalid managed connection result")
    action = payload.get("controllerAction")
    metadata = CONTROLLER_ACTION_METADATA.get(action)
    if (
        metadata is None
        or type(payload.get("ok")) is not bool
        or type(payload.get("state")) is not str
        or not payload["state"]
        or type(payload.get("code")) is not str
        or not _SAFE_CODE_PATTERN.fullmatch(payload["code"])
        or type(payload.get("retryable")) is not bool
        or payload.get("retryable") is not metadata["retryable"]
        or payload.get("requiredAuthority") != metadata["authority"]
        or payload.get("terminal") is not metadata["terminal"]
        or payload.get("credentialValuesPrinted") is not False
        or payload.get("tenantIdentifiersPrinted") is not False
        or payload.get("valuesRedacted") is not True
    ):
        raise ValueError("invalid managed connection result")
    if payload["ok"]:
        if (
            payload["state"] != "active"
            or payload["code"] != "managed_connection_active"
            or action != "none"
            or payload["retryAfterSeconds"] is not None
            or type(payload.get("status")) is not str
            or not payload["status"]
            or type(payload.get("agentId")) is not str
            or not _AGENT_ID_PATTERN.fullmatch(payload["agentId"])
            or payload.get("credentialPersisted") is not True
            or payload.get("credentialVerified") is not True
            or type(payload.get("managedProfile")) is not bool
        ):
            raise ValueError("incoherent managed connection result")
    elif (
        type(payload.get("error")) is not str
        or not payload["error"]
        or len(payload["error"]) > 512
        or (
            payload["retryable"]
            and (
                type(payload.get("retryAfterSeconds")) is not int
                or not 1 <= payload["retryAfterSeconds"] <= 86400
            )
        )
        or (not payload["retryable"] and payload["retryAfterSeconds"] is not None)
    ):
        raise ValueError("incoherent managed connection result")
    return dict(payload)


def onboard_agent(
    agent_id,
    profile_id,
    project_root=".",
    base_url=DEFAULT_BASE_URL,
    invite_file=None,
    invite_environment=DEFAULT_INVITE_ENVIRONMENT,
    ca_bundle=None,
    environ=None,
    open_url=urlopen,
    credential_paths=None,
    protect_secret=None,
    unprotect_secret=None,
    protector=None,
    profile_binding=None,
    ca_content=None,
    expected_company_id=_UNBOUND,
    expected_workspace_id=_UNBOUND,
    expected_project_id=_UNBOUND,
):
    """Redeem, persist, verify, or reconcile one exact agent credential."""
    agent_id = _validate_agent_id(agent_id)
    profile_id = _validate_profile_id(profile_id)
    base_url = _validate_base_url(base_url)
    if credential_paths is None:
        target_path, pending_path = _credential_paths(project_root, agent_id)
    else:
        target_path, pending_path = (Path(path).resolve() for path in credential_paths)
    if profile_binding is None:
        if ca_content is not None:
            trust_digest = hashlib.sha256(bytes(ca_content)).hexdigest()
        elif ca_bundle:
            try:
                ca_content = Path(ca_bundle).expanduser().resolve().read_bytes()
            except OSError as exc:
                raise OnboardingError(
                    "managed_trust_unavailable",
                    "The installer-managed LAN trust bundle is unavailable.",
                    "restore_managed_trust",
                ) from exc
            trust_digest = hashlib.sha256(ca_content).hexdigest()
            ca_bundle = None
        else:
            trust_digest = hashlib.sha256(b"system-trust").hexdigest()
        profile_binding = _profile_binding(
            profile_id, base_url, agent_id, trust_digest
        )
    if not _SHA256_PATTERN.fullmatch(str(profile_binding or "")):
        raise OnboardingError(
            "managed_profile_invalid",
            "The managed connection profile binding is invalid.",
            "quarantine_profile_conflict",
        )
    context = _ssl_context(base_url, ca_bundle, ca_content)
    protector = _secret_protector(
        protector,
        protect_secret=protect_secret,
        unprotect_secret=unprotect_secret,
    )

    if target_path.exists():
        if pending_path.exists():
            raise OnboardingError(
                "credential_state_conflict",
                "Final and pending managed credential state both exist.",
                "quarantine_credential_state",
            )
        document = _validated_credential_document(
            _read_private_json(target_path),
            base_url,
            agent_id,
            profile_id,
            profile_binding,
            protector=protector,
        )
        _assert_expected_principal_binding(
            document,
            expected_company_id,
            expected_workspace_id,
            expected_project_id,
        )
        _verify_credential(base_url, document, context, open_url)
        return _public_result("verified_existing", agent_id)

    marker = None
    if pending_path.exists():
        pending = _read_private_json(pending_path)
        if pending.get("schemaVersion") == AGENT_CREDENTIAL_SCHEMA:
            document = _validated_credential_document(
                pending,
                base_url,
                agent_id,
                profile_id,
                profile_binding,
                protector=protector,
            )
            _assert_expected_principal_binding(
                document,
                expected_company_id,
                expected_workspace_id,
                expected_project_id,
            )
            try:
                _promote_pending(pending_path, target_path)
            except OSError as exc:
                raise OnboardingError(
                    "credential_promotion_deferred",
                    "The pending managed credential could not be promoted and remains protected.",
                    "retry_local_credential_promotion",
                    retryable=True,
                ) from exc
            _verify_credential(base_url, document, context, open_url)
            return _public_result("reconciled_pending_credential", agent_id)
        expected_pending_keys = {
            "schemaVersion",
            "profileId",
            "profileBinding",
            "baseUrl",
            "agentId",
            "state",
            "inviteFingerprint",
            "credentialProtection",
            "protectedAgentToken",
            "protectedIdempotencyKey",
            "containsCredential",
        }
        if (
            pending.get("schemaVersion") != PENDING_SCHEMA
            or set(pending) != expected_pending_keys
        ):
            raise OnboardingError(
                "pending_enrollment_invalid",
                "Protected pending enrollment state has an invalid schema.",
                "quarantine_enrollment_state",
            )
        if (
            _validate_base_url(pending.get("baseUrl")) != base_url
            or _validate_profile_id(pending.get("profileId")) != profile_id
            or not isinstance(pending.get("profileBinding"), str)
            or not secrets.compare_digest(
                pending.get("profileBinding"), profile_binding
            )
            or type(pending.get("agentId")) is not str
            or pending.get("agentId").strip().lower() != agent_id
            or pending.get("containsCredential") is not True
            or pending.get("credentialProtection")
            != protector.protection_id
            or type(pending.get("protectedAgentToken")) is not str
            or not pending.get("protectedAgentToken").strip()
            or type(pending.get("protectedIdempotencyKey")) is not str
            or not pending.get("protectedIdempotencyKey").strip()
        ):
            raise OnboardingError(
                "pending_enrollment_mismatch",
                "Protected pending enrollment state does not match this profile.",
                "quarantine_enrollment_state",
            )
        marker = pending
        if marker.get("state") not in {
            "redemption_pending",
            "redemption_outcome_unknown",
            "redemption_reconciliation_required",
            "redemption_response_invalid",
        }:
            raise OnboardingError(
                "pending_enrollment_invalid",
                "Protected pending enrollment state has an invalid lifecycle state.",
                "quarantine_enrollment_state",
            )

    invite_secret = _read_invite_source(
        invite_file, invite_environment, environ, base_url, agent_id
    )
    if marker:
        if marker.get("inviteFingerprint") != _invite_fingerprint(invite_secret):
            raise OnboardingError(
                "pending_enrollment_mismatch",
                "The pending enrollment belongs to a different invitation.",
                "quarantine_enrollment_state",
            )
        token = protector.unprotect(
            marker["protectedAgentToken"],
            profile_id,
            agent_id,
            profile_binding,
        )
        idempotency_key = protector.unprotect(
            marker["protectedIdempotencyKey"],
            profile_id,
            agent_id,
            profile_binding,
        )
        if type(token) is not str or type(idempotency_key) is not str:
            raise OnboardingError(
                "pending_enrollment_invalid",
                "Protected pending enrollment state contains invalid retry material.",
                "quarantine_enrollment_state",
            )
        token = token.strip()
        idempotency_key = idempotency_key.strip()
        if (
            not _AGENT_TOKEN_PATTERN.fullmatch(token)
            or not 16 <= len(idempotency_key) <= 200
            or any(ord(character) < 33 or ord(character) > 126 for character in idempotency_key)
        ):
            raise OnboardingError(
                "pending_enrollment_invalid",
                "Protected pending enrollment state contains invalid retry material.",
                "quarantine_enrollment_state",
            )
    else:
        token = _new_agent_token_secret()
        idempotency_key = _new_idempotency_key()
        marker = _pending_marker(
            base_url,
            profile_id,
            agent_id,
            invite_secret,
            token,
            idempotency_key,
            profile_binding,
            protector=protector,
        )
        try:
            _private_write(pending_path, marker)
        except OSError as exc:
            raise OnboardingError(
                "enrollment_state_prepare_failed",
                "Protected enrollment state could not be prepared; no request was sent.",
                "repair_protected_credential_store",
            ) from exc

    try:
        status, payload = _request_json(
            base_url,
            REDEEM_ROUTE,
            "POST",
            {
                "schemaVersion": "memoryendpoints.agent_invite_redemption.v1",
                "inviteSecret": invite_secret,
                "candidateAgentTokenSecret": token,
            },
            None,
            context,
            open_url,
            idempotency_key=idempotency_key,
        )
    except _OutcomeUnknown as exc:
        try:
            _private_write(
                pending_path,
                dict(marker, state="redemption_outcome_unknown"),
            )
        except OSError:
            pass
        raise OnboardingError(
            "enrollment_outcome_unknown",
            "The enrollment outcome is unknown; protected exact-retry state was retained.",
            "retry_exact_enrollment_with_bounded_backoff",
            retryable=True,
        ) from exc
    if status < 200 or status >= 300 or payload.get("ok") is not True:
        error = payload.get("error") if isinstance(payload, dict) else None
        error_code = (
            error.get("code")
            if isinstance(error, dict) and type(error.get("code")) is str
            else ""
        )
        if status == 429 or status >= 500:
            code = "enrollment_temporarily_unavailable"
            action = "retry_exact_enrollment_with_bounded_backoff"
            retryable = True
            marker_state = "redemption_outcome_unknown"
        elif status in (404, 405, 406, 415, 422, 426):
            code = "managed_server_contract_incompatible"
            action = "hold_for_compatible_server_release"
            retryable = False
            marker_state = "redemption_reconciliation_required"
        elif status == 409 or error_code in (
            "idempotency_conflict",
            "candidate_agent_token_conflict",
        ):
            code = "enrollment_binding_conflict"
            action = "quarantine_enrollment_state"
            retryable = False
            marker_state = "redemption_reconciliation_required"
        else:
            code = "enrollment_authority_required"
            action = "reconcile_enrollment_with_recovery_authority"
            retryable = False
            marker_state = "redemption_reconciliation_required"
        try:
            _private_write(
                pending_path,
                dict(marker, state=marker_state),
            )
        except OSError:
            pass
        raise OnboardingError(
            code,
            "Enrollment was not completed; protected exact-retry state was retained.",
            action,
            retryable=retryable,
        )

    principal = payload.get("principal") if isinstance(payload.get("principal"), dict) else {}
    onboarding = payload.get("onboarding") if isinstance(payload.get("onboarding"), dict) else {}
    returned_agent_id = principal.get("agentId")
    company_id = principal.get("companyId")
    workspace_id = principal.get("workspaceId")
    project_id = principal.get("projectId")
    candidate_token_id = token.split(".", 2)[1]
    if (
        type(returned_agent_id) is not str
        or returned_agent_id.strip().lower() != agent_id
        or type(company_id) is not str
        or not company_id.strip()
        or type(workspace_id) is not str
        or not workspace_id.strip()
        or (project_id is not None and type(project_id) is not str)
        or principal.get("credentialType") not in ("agent", "agent_token")
        or type(principal.get("credentialId") or principal.get("agentTokenId")) is not str
        or (principal.get("credentialId") or principal.get("agentTokenId")) != candidate_token_id
        or payload.get("candidateCredentialAccepted") is not True
        or payload.get("credentialReturnedOnce") is not False
        or payload.get("idempotencySupported") is not True
        or payload.get("replaySafe") is not True
        or payload.get("rawCredentialExposed") is not False
        or "agentTokenSecret" in payload
    ):
        try:
            _private_write(
                pending_path,
                dict(marker, state="redemption_response_invalid"),
            )
        except OSError:
            pass
        raise OnboardingError(
            "enrollment_response_invalid",
            "Enrollment returned an invalid receipt; protected exact-retry state was retained.",
            "retry_exact_enrollment_with_bounded_backoff",
            retryable=True,
        )
    company_id = company_id.strip()
    workspace_id = workspace_id.strip()
    project_id = project_id.strip() if project_id is not None else None
    if (
        (expected_company_id is not _UNBOUND and company_id != expected_company_id)
        or (expected_workspace_id is not _UNBOUND and workspace_id != expected_workspace_id)
        or (expected_project_id is not _UNBOUND and project_id != expected_project_id)
    ):
        try:
            _private_write(
                pending_path,
                dict(marker, state="redemption_response_invalid"),
            )
        except OSError:
            pass
        raise OnboardingError(
            "enrollment_binding_mismatch",
            "Enrollment returned a principal outside the managed profile binding.",
            "quarantine_identity",
        )

    stored_document = _credential_document(
        base_url,
        company_id,
        workspace_id,
        project_id,
        agent_id,
        token,
        profile_id,
        profile_binding,
        protector=protector,
    )
    document = {
        "baseUrl": base_url,
        "companyId": company_id,
        "workspaceId": workspace_id,
        "projectId": project_id,
        "agentId": agent_id,
        "agentTokenSecret": token,
    }
    try:
        _private_write(pending_path, stored_document)
    except OSError as exc:
        raise OnboardingError(
            "credential_persistence_failed",
            "The redeemed credential could not replace protected pending state.",
            "repair_protected_credential_store",
        ) from exc
    try:
        _promote_pending(pending_path, target_path)
    except OSError as exc:
        raise OnboardingError(
            "credential_promotion_deferred",
            "The redeemed credential remains protected in pending state.",
            "retry_local_credential_promotion",
            retryable=True,
        ) from exc

    _verify_credential(base_url, document, context, open_url)
    return _public_result("onboarded", agent_id)


def _managed_invitation_document(
    invite_secret,
    profile_id,
    agent_id,
    profile_binding,
    protector=None,
):
    protector = _secret_protector(protector)
    if type(invite_secret) is not str:
        raise OnboardingError(
            "managed_invitation_invalid",
            "The managed invitation is not a governed invitation.",
            "replace_managed_invitation",
        )
    invite_secret = invite_secret.strip()
    if not _INVITE_PATTERN.fullmatch(invite_secret):
        raise OnboardingError(
            "managed_invitation_invalid",
            "The managed invitation is not a governed invitation.",
            "replace_managed_invitation",
        )
    normalized_profile_id = _validate_profile_id(profile_id)
    normalized_agent_id = _validate_agent_id(agent_id)
    if not _SHA256_PATTERN.fullmatch(str(profile_binding or "")):
        raise OnboardingError(
            "managed_profile_invalid",
            "The managed connection profile binding is invalid.",
            "quarantine_profile_conflict",
        )
    return {
        "schemaVersion": MANAGED_INVITE_SCHEMA,
        "profileId": normalized_profile_id,
        "profileBinding": profile_binding,
        "agentId": normalized_agent_id,
        "credentialProtection": protector.protection_id,
        "protectedInviteSecret": protector.protect(
            invite_secret,
            normalized_profile_id,
            normalized_agent_id,
            profile_binding,
        ),
    }


def _connect_managed_agent_unlocked(
    profile_path,
    profile,
    open_url=urlopen,
    protector=None,
):
    paths = _managed_state_paths(profile_path)
    ca_content = _validate_managed_ca(paths["ca"], profile["caSha256"])

    invite_environment = ""
    private_environment = {}
    pending_payload = None
    if paths["pending"].is_file():
        pending_payload = _read_private_json(paths["pending"])
    pending_is_final = (
        isinstance(pending_payload, dict)
        and pending_payload.get("schemaVersion") == AGENT_CREDENTIAL_SCHEMA
    )
    needs_invite = not paths["credential"].is_file() and not pending_is_final
    if needs_invite:
        if not paths["invite"].is_file():
            raise OnboardingError(
                "managed_invitation_missing",
                "No installer-managed agent invitation is available.",
                "install_managed_invitation",
            )
        invite_environment = "_MEMORYENDPOINTS_MANAGED_INVITE"
        private_environment[invite_environment] = _read_managed_invitation(
            paths["invite"],
            profile["profileId"],
            profile["agentId"],
            profile["profileBinding"],
            protector=protector,
        )

    result = onboard_agent(
        profile["agentId"],
        profile["profileId"],
        base_url=profile["baseUrl"],
        invite_environment=invite_environment,
        environ=private_environment,
        open_url=open_url,
        credential_paths=(paths["credential"], paths["pending"]),
        protector=protector,
        profile_binding=profile["profileBinding"],
        ca_content=ca_content,
        expected_company_id=profile["companyId"],
        expected_workspace_id=profile["workspaceId"],
        expected_project_id=profile["projectId"],
    )
    if paths["invite"].is_file():
        try:
            paths["invite"].unlink()
        except OSError as exc:
            raise OnboardingError(
                "managed_invitation_retirement_failed",
                "The obsolete protected invitation could not be retired.",
                "retire_consumed_managed_invitation",
                retryable=True,
            ) from exc
    result["managedProfile"] = True
    return result


@contextmanager
def _managed_profile_lock(profile_path, timeout_milliseconds=30000):
    """Serialize one managed profile across users, sessions, and processes."""
    lock_path = Path(profile_path).parent / ".connection.lock"
    _assert_managed_path_not_redirected(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")
    acquired = False
    deadline = time.monotonic() + max(0, timeout_milliseconds) / 1000.0
    try:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"0")
            handle.flush()
            os.fsync(handle.fileno())
        while not acquired:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                if time.monotonic() >= deadline:
                    raise OnboardingError(
                        "managed_connection_busy",
                        "Another managed connection operation is still active.",
                        "retry_with_bounded_backoff",
                        retryable=True,
                    )
                time.sleep(0.05)
        yield
    finally:
        if acquired:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


def provision_managed_connection(
    profile_document,
    ca_content,
    invite_secret,
    profile_path,
    protector=None,
    profile_verifier=None,
):
    """Install preauthorized material for the eventual consuming identity.

    This function never creates authority or an identity.  It accepts only an
    already-authorized governed invitation and makes the profile visible last,
    after trust and the protected invitation are durable.
    """
    if type(profile_document) is not dict:
        raise OnboardingError(
            "managed_profile_invalid",
            "The managed connection profile has an invalid schema.",
            "replace_managed_connection_profile",
        )
    profile = _validate_managed_profile_payload(
        dict(profile_document), profile_verifier
    )
    protector = _secret_protector(protector)
    if (
        protector.protection_id != profile["protectionId"]
        or (
            protector.workload_identity_id is not None
            and protector.workload_identity_id != profile["workloadIdentityId"]
        )
        or (
            profile["profileVerifierId"] != "protected-state-binding"
            and protector.workload_identity_id != profile["workloadIdentityId"]
        )
    ):
        raise OnboardingError(
            "credential_protection_invalid",
            "The installer is not running as the profile's consuming identity.",
            "rebootstrap_managed_identity",
        )
    if not isinstance(ca_content, (bytes, bytearray)):
        raise OnboardingError(
            "managed_trust_invalid",
            "The installer-managed LAN trust bundle is invalid.",
            "replace_managed_trust",
        )
    ca_content = bytes(ca_content)
    if (
        not ca_content
        or len(ca_content) > MAX_CA_BYTES
        or not secrets.compare_digest(
            hashlib.sha256(ca_content).hexdigest(), profile["caSha256"]
        )
    ):
        raise OnboardingError(
            "managed_trust_mismatch",
            "The installer-managed LAN trust bundle failed integrity validation.",
            "replace_managed_trust",
        )
    path = Path(profile_path).expanduser()
    _assert_managed_path_not_redirected(path)
    root = path.parent.resolve()
    if path.name != MANAGED_PROFILE_FILE or path.resolve() != root / MANAGED_PROFILE_FILE:
        raise OnboardingError(
            "managed_profile_invalid",
            "The installer target is not a canonical managed profile path.",
            "repair_managed_connection_installation",
        )
    paths = _managed_state_paths(path)
    invitation = _managed_invitation_document(
        invite_secret,
        profile["profileId"],
        profile["agentId"],
        profile["profileBinding"],
        protector=protector,
    )
    try:
        wrote_state = False
        with _managed_profile_lock(path):
            if paths["credential"].exists() or paths["pending"].exists():
                raise OnboardingError(
                    "managed_installation_conflict",
                    "Managed identity state already exists and requires governed reconciliation.",
                    "rebootstrap_managed_identity",
                )
            if paths["ca"].exists():
                existing_ca = paths["ca"].read_bytes()
                if not secrets.compare_digest(existing_ca, ca_content):
                    raise OnboardingError(
                        "managed_installation_conflict",
                        "Managed trust state conflicts with the authorized installation.",
                        "rebootstrap_managed_identity",
                    )
            else:
                _private_write_bytes(paths["ca"], ca_content)
                wrote_state = True
            if paths["invite"].exists():
                existing_invite = _read_managed_invitation(
                    paths["invite"],
                    profile["profileId"],
                    profile["agentId"],
                    profile["profileBinding"],
                    protector=protector,
                )
                if not secrets.compare_digest(existing_invite, invite_secret):
                    raise OnboardingError(
                        "managed_installation_conflict",
                        "Managed invitation state conflicts with the authorized installation.",
                        "rebootstrap_managed_identity",
                    )
            else:
                _private_write(paths["invite"], invitation)
                wrote_state = True
            if path.exists():
                existing_profile = _read_private_json(path)
                if existing_profile != profile_document:
                    raise OnboardingError(
                        "managed_installation_conflict",
                        "Managed profile state conflicts with the authorized installation.",
                        "rebootstrap_managed_identity",
                    )
            else:
                _private_write(path, profile_document)
                wrote_state = True
    except OnboardingError:
        raise
    except (OSError, ValueError) as exc:
        raise OnboardingError(
            "managed_installation_incomplete",
            "The managed connection installation did not complete.",
            "rebootstrap_managed_identity",
        ) from exc
    return {
        "schemaVersion": "multiagentmemory.managed_connection_install_result.v1",
        "ok": True,
        "profileInstalled": True,
        "trustInstalled": True,
        "invitationProtected": True,
        "identityCreated": False,
        "humanInputRequired": False,
        "idempotentReplay": not wrote_state,
        "valuesRedacted": True,
    }


def connect_managed_agent(
    profile_path=None,
    profile_candidates=None,
    open_url=urlopen,
    protect_secret=None,
    unprotect_secret=None,
    protector=None,
    profile_locator=None,
    profile_verifier=None,
    lock_factory=None,
):
    """Connect a per-user managed profile without cwd or environment input."""
    if profile_locator is not None:
        if profile_path is not None or profile_candidates is not None or not callable(profile_locator):
            raise OnboardingError(
                "managed_profile_invalid",
                "Exactly one managed profile locator is required.",
                "repair_managed_connection_installation",
            )
        try:
            profile_candidates = tuple(profile_locator())
        except Exception as exc:
            raise OnboardingError(
                "managed_profile_discovery_unavailable",
                "The managed profile locator failed.",
                "repair_managed_connection_installation",
            ) from exc
    profile_path = _resolve_managed_profile(profile_path, profile_candidates)
    profile = _load_managed_profile(profile_path, profile_verifier)
    if profile["runtimeClass"] != MANAGED_RUNTIME_CLASS_PER_USER:
        raise OnboardingError(
            "managed_service_controller_required",
            "Unattended service profiles require the prompt-free service reconciliation controller.",
            "install_supported_connection_controller",
        )
    protector = _secret_protector(
        protector,
        protect_secret=protect_secret,
        unprotect_secret=unprotect_secret,
    )
    if protector.protection_id != profile["protectionId"]:
        raise OnboardingError(
            "credential_protection_invalid",
            "The managed profile requires a different protected-storage identity.",
            "rebootstrap_managed_identity",
        )
    lock = lock_factory or _managed_profile_lock
    with lock(profile_path):
        return _connect_managed_agent_unlocked(
            profile_path,
            profile,
            open_url=open_url,
            protector=protector,
        )


def _profile_digest(profile_document):
    return hashlib.sha256(
        b"multiagentmemory.managed-profile-document.v1\0"
        + json.dumps(
            profile_document, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _controller_operation_digest(context_digest, profile_binding, attempt_count):
    return hashlib.sha256(
        (
            "multiagentmemory.managed-reconciliation-operation.v1\0"
            + context_digest
            + "\0"
            + profile_binding
            + "\0"
            + str(attempt_count)
        ).encode("utf-8")
    ).hexdigest()


def _reconciliation_result(
    *,
    ok,
    phase,
    code,
    action,
    action_authority,
    retryable,
    terminal,
    attempt_count,
    max_attempts,
    operation_digest,
    retry_after_seconds=None,
    next_attempt_at_epoch=None,
):
    payload = {
        "schemaVersion": MANAGED_RECONCILIATION_RESULT_SCHEMA,
        "ok": bool(ok),
        "phase": phase,
        "code": code,
        "action": action,
        "actionAuthority": action_authority,
        "retryable": bool(retryable),
        "terminal": bool(terminal),
        "attemptCount": attempt_count,
        "maxAttempts": max_attempts,
        "retryAfterSeconds": retry_after_seconds,
        "nextAttemptAtEpoch": next_attempt_at_epoch,
        "operationDigest": operation_digest,
        "humanInputRequired": False,
        "valuesRedacted": True,
    }
    return parse_managed_reconciliation_result(payload)


def parse_managed_reconciliation_result(payload):
    """Validate a closed, redacted result for an unattended supervisor."""
    expected = {
        "schemaVersion",
        "ok",
        "phase",
        "code",
        "action",
        "actionAuthority",
        "retryable",
        "terminal",
        "attemptCount",
        "maxAttempts",
        "retryAfterSeconds",
        "nextAttemptAtEpoch",
        "operationDigest",
        "humanInputRequired",
        "valuesRedacted",
    }
    if (
        type(payload) is not dict
        or set(payload) != expected
        or payload.get("schemaVersion") != MANAGED_RECONCILIATION_RESULT_SCHEMA
        or type(payload.get("ok")) is not bool
        or payload.get("phase") not in _CONTROLLER_PHASES
        or type(payload.get("code")) is not str
        or not _SAFE_CODE_PATTERN.fullmatch(payload["code"])
        or payload.get("action") not in MANAGED_RECOVERY_ACTIONS | {"none"}
        or payload.get("actionAuthority")
        not in {"none", "controller", "independent_recovery_authority", "fleet_controller"}
        or type(payload.get("retryable")) is not bool
        or type(payload.get("terminal")) is not bool
        or type(payload.get("attemptCount")) is not int
        or payload["attemptCount"] < 0
        or type(payload.get("maxAttempts")) is not int
        or not 1 <= payload["maxAttempts"] <= 64
        or payload["attemptCount"] > payload["maxAttempts"]
        or (
            payload.get("retryAfterSeconds") is not None
            and (
                type(payload["retryAfterSeconds"]) is not int
                or not 1 <= payload["retryAfterSeconds"] <= 86400
            )
        )
        or (
            payload.get("nextAttemptAtEpoch") is not None
            and (
                type(payload["nextAttemptAtEpoch"]) is not int
                or payload["nextAttemptAtEpoch"] < 0
            )
        )
        or type(payload.get("operationDigest")) is not str
        or not _SHA256_PATTERN.fullmatch(payload["operationDigest"])
        or payload.get("humanInputRequired") is not False
        or payload.get("valuesRedacted") is not True
    ):
        raise ValueError("invalid managed reconciliation result")
    action = payload["action"]
    if action == "none":
        coherent = (
            payload["ok"] is True
            and payload["phase"] == "active"
            and payload["actionAuthority"] == "none"
            and payload["retryable"] is False
            and payload["terminal"] is False
            and payload["retryAfterSeconds"] is None
            and payload["nextAttemptAtEpoch"] is None
        )
    elif action == "retry_after":
        coherent = (
            payload["ok"] is False
            and payload["phase"] == "retry_wait"
            and payload["actionAuthority"]
            in {"controller", "independent_recovery_authority"}
            and payload["retryable"] is True
            and payload["terminal"] is False
            and payload["retryAfterSeconds"] is not None
            and payload["nextAttemptAtEpoch"] is not None
        )
    else:
        coherent = (
            payload["ok"] is False
            and (
                (
                    action == "halt"
                    and payload["phase"] == "halted"
                    and payload["actionAuthority"]
                    == "independent_recovery_authority"
                )
                or (
                    action == "quarantine_replace"
                    and payload["phase"] == "quarantined"
                    and payload["actionAuthority"] == "fleet_controller"
                )
            )
            and payload["retryable"] is False
            and payload["terminal"] is True
            and payload["retryAfterSeconds"] is None
            and payload["nextAttemptAtEpoch"] is None
        )
    if not coherent:
        raise ValueError("incoherent managed reconciliation result")
    return dict(payload)


def _parse_recovery_directive(
    payload,
    *,
    authority_id,
    context_digest,
    state_revision,
    operation_digest,
    failure_code,
    request_digest,
):
    expected = {
        "schemaVersion",
        "action",
        "authorityId",
        "contextDigest",
        "stateRevision",
        "operationDigest",
        "failureCode",
        "requestDigest",
        "reasonCode",
        "retryAfterSeconds",
        "valuesRedacted",
    }
    if (
        type(payload) is not dict
        or set(payload) != expected
        or payload.get("schemaVersion") != MANAGED_RECOVERY_DIRECTIVE_SCHEMA
        or payload.get("action") not in MANAGED_RECOVERY_ACTIONS
        or payload.get("authorityId") != authority_id
        or payload.get("contextDigest") != context_digest
        or payload.get("stateRevision") != state_revision
        or payload.get("operationDigest") != operation_digest
        or payload.get("failureCode") != failure_code
        or payload.get("requestDigest") != request_digest
        or type(payload.get("reasonCode")) is not str
        or not _SAFE_CODE_PATTERN.fullmatch(payload["reasonCode"])
        or payload.get("valuesRedacted") is not True
    ):
        raise OnboardingError(
            "managed_recovery_directive_invalid",
            "The independent recovery authority returned an invalid directive.",
            "quarantine_identity",
        )
    retry_after = payload.get("retryAfterSeconds")
    if payload["action"] == "retry_after":
        if type(retry_after) is not int or not 1 <= retry_after <= 86400:
            raise OnboardingError(
                "managed_recovery_directive_invalid",
                "The independent recovery authority returned an invalid directive.",
                "quarantine_identity",
            )
    elif retry_after is not None:
        raise OnboardingError(
            "managed_recovery_directive_invalid",
            "The independent recovery authority returned an invalid directive.",
            "quarantine_identity",
        )
    return dict(payload)


def _verified_service_profile(context, profile_document, verifier):
    if (
        type(profile_document) is not dict
        or profile_document.get("profileVerifierId") != context.profile_verifier_id
        or verifier.verifier_id != context.profile_verifier_id
    ):
        raise OnboardingError(
            "managed_profile_verifier_mismatch",
            "The managed profile is not signed by the pinned service authority.",
            "quarantine_profile_conflict",
        )

    def verify_profile(verifier_id, payload):
        return verifier_id == verifier.verifier_id and verifier.verify(payload, context) is True

    profile = _validate_managed_profile_payload(
        profile_document, profile_verifier=verify_profile
    )
    if (
        profile["runtimeClass"] != context.runtime_class
        or profile["profilePurpose"] != context.purpose
        or profile["clientKind"] != context.client_kind
        or profile["serviceInstanceId"] != context.service_instance_id
        or profile["workloadIdentityId"] != context.workload_identity_id
        or profile["projectId"] != context.project_id
        or profile["profileGeneration"] < verifier.minimum_generation(context)
    ):
        raise OnboardingError(
            "managed_service_binding_mismatch",
            "The managed profile does not belong to the current service identity and generation.",
            "quarantine_identity",
        )
    return profile, verify_profile


def _initial_controller_state(profile, profile_digest, context):
    return {
        "schemaVersion": MANAGED_CONTROLLER_STATE_SCHEMA,
        "profileId": profile["profileId"],
        "serviceInstanceId": context.service_instance_id,
        "profileGeneration": profile["profileGeneration"],
        "policyRevision": profile["policyRevision"],
        "activeProfileDigest": profile_digest,
        "activeTrustSha256": profile["caSha256"],
        "phase": "pending",
        "attemptCount": 0,
        "maxAttempts": context.max_attempts,
        "attemptLeaseExpiresAtEpoch": None,
        "nextAttemptAtEpoch": None,
        "lastFailureCode": None,
        "operationDigest": None,
        "quarantined": False,
    }


def initialize_managed_controller_state(
    context,
    *,
    profile_document,
    verifier,
    state_cas,
    recovery_authority,
):
    """Authorize first boot in an installer/fleet transaction, never at runtime."""
    if (
        not isinstance(context, ManagedServiceContext)
        or not isinstance(verifier, SignedProfileVerifier)
        or not isinstance(recovery_authority, ManagedRecoveryAuthority)
        or not isinstance(state_cas, DurableStateCAS)
        or recovery_authority.authority_id != context.recovery_authority_id
    ):
        raise ValueError("invalid managed controller initialization adapters")
    profile, _verify_profile = _verified_service_profile(
        context, dict(profile_document), verifier
    )
    context_digest = _service_context_digest(context)
    revision, state = state_cas.read(context_digest)
    if type(revision) is not int or revision < 0:
        raise OnboardingError(
            "managed_controller_state_invalid",
            "Managed controller state is unavailable or invalid.",
            "quarantine_identity",
        )
    initial = _initial_controller_state(
        profile, _profile_digest(profile_document), context
    )
    if state is None:
        if revision != 0:
            raise OnboardingError(
                "managed_controller_state_invalid",
                "Managed controller state is unavailable or invalid.",
                "quarantine_identity",
            )
        revision = state_cas.compare_exchange(context_digest, 0, initial)
        installed = True
    else:
        state = _validate_controller_state(state)
        for field in (
            "profileId",
            "serviceInstanceId",
            "profileGeneration",
            "policyRevision",
            "activeProfileDigest",
            "activeTrustSha256",
            "maxAttempts",
        ):
            if state[field] != initial[field]:
                raise OnboardingError(
                    "managed_controller_state_conflict",
                    "Managed controller state conflicts with the authorized installation.",
                    "quarantine_identity",
                )
        installed = False
    return {
        "schemaVersion": "multiagentmemory.managed_controller_install_result.v1",
        "ok": True,
        "controllerStateInstalled": installed,
        "stateRevision": revision,
        "humanInputRequired": False,
        "valuesRedacted": True,
    }


def _recovery_request(
    authority,
    context_digest,
    profile_binding,
    state_revision,
    failure_code,
    operation_digest,
    state,
):
    payload = {
        "schemaVersion": MANAGED_RECOVERY_REQUEST_SCHEMA,
        "authorityId": authority.authority_id,
        "contextDigest": context_digest,
        "profileBinding": profile_binding,
        "stateRevision": state_revision,
        "failureCode": failure_code,
        "operationDigest": operation_digest,
        "attemptCount": state["attemptCount"],
        "maxAttempts": state["maxAttempts"],
        "valuesRedacted": True,
    }
    payload["requestDigest"] = hashlib.sha256(
        b"multiagentmemory.managed-recovery-request.v1\0"
        + json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


def _terminal_recovery_result(
    *,
    state_cas,
    state_key,
    state_revision,
    state,
    profile_binding,
    context_digest,
    failure_code,
    operation_digest,
    authority,
    now,
):
    request = _recovery_request(
        authority,
        context_digest,
        profile_binding,
        state_revision,
        failure_code,
        operation_digest,
        state,
    )
    try:
        directive = _parse_recovery_directive(
            authority.reconcile(request),
            authority_id=authority.authority_id,
            context_digest=context_digest,
            state_revision=state_revision,
            operation_digest=operation_digest,
            failure_code=failure_code,
            request_digest=request["requestDigest"],
        )
    except Exception:
        directive = {
            "action": "quarantine_replace",
            "reasonCode": "managed_recovery_authority_unavailable",
            "retryAfterSeconds": None,
        }
    action = directive["action"]
    if action == "retry_after" and state["attemptCount"] < state["maxAttempts"]:
        recovery_attempt_count = state["attemptCount"] + 1
        retry_after = directive["retryAfterSeconds"]
        phase = "retry_wait"
        action_authority = "independent_recovery_authority"
        terminal = False
        retryable = True
        next_attempt = now + retry_after
        quarantined = False
    else:
        recovery_attempt_count = state["attemptCount"]
        if action == "retry_after":
            action = "quarantine_replace"
            directive["reasonCode"] = "managed_retry_budget_exhausted"
        phase = "halted" if action == "halt" else "quarantined"
        action_authority = (
            "independent_recovery_authority" if action == "halt" else "fleet_controller"
        )
        terminal = True
        retryable = False
        retry_after = None
        next_attempt = None
        quarantined = phase == "quarantined"
    next_state = dict(state)
    next_state.update(
        {
            "phase": phase,
            "attemptCount": recovery_attempt_count,
            "attemptLeaseExpiresAtEpoch": None,
            "nextAttemptAtEpoch": next_attempt,
            "lastFailureCode": directive["reasonCode"],
            "operationDigest": operation_digest,
            "quarantined": quarantined,
        }
    )
    _validate_controller_state(next_state)
    try:
        state_cas.compare_exchange(state_key, state_revision, next_state)
    except OnboardingError as exc:
        if not exc.retryable:
            return _reconciliation_result(
                ok=False,
                phase="quarantined",
                code="managed_controller_state_unavailable",
                action="quarantine_replace",
                action_authority="fleet_controller",
                retryable=False,
                terminal=True,
                attempt_count=state["attemptCount"],
                max_attempts=state["maxAttempts"],
                operation_digest=operation_digest,
            )
        return _reconciliation_result(
            ok=False,
            phase="retry_wait",
            code="managed_controller_state_conflict",
            action="retry_after",
            action_authority="controller",
            retryable=True,
            terminal=False,
            attempt_count=state["attemptCount"],
            max_attempts=state["maxAttempts"],
            retry_after_seconds=1,
            next_attempt_at_epoch=now + 1,
            operation_digest=operation_digest,
        )
    except Exception:
        return _reconciliation_result(
            ok=False,
            phase="quarantined",
            code="managed_controller_state_unavailable",
            action="quarantine_replace",
            action_authority="fleet_controller",
            retryable=False,
            terminal=True,
            attempt_count=state["attemptCount"],
            max_attempts=state["maxAttempts"],
            operation_digest=operation_digest,
        )
    return _reconciliation_result(
        ok=False,
        phase=phase,
        code=directive["reasonCode"],
        action=action,
        action_authority=action_authority,
        retryable=retryable,
        terminal=terminal,
        attempt_count=recovery_attempt_count,
        max_attempts=state["maxAttempts"],
        retry_after_seconds=retry_after,
        next_attempt_at_epoch=next_attempt,
        operation_digest=operation_digest,
    )


def reconcile_managed_connection(
    context,
    *,
    locator,
    protector,
    verifier,
    state_cas,
    recovery_authority,
    transport=urlopen,
    clock=time.time,
):
    """Perform one prompt-free service reconciliation using durable intent."""
    if (
        not isinstance(context, ManagedServiceContext)
        or not isinstance(locator, ManagedProfileLocator)
        or not isinstance(protector, SecretProtector)
        or not isinstance(verifier, SignedProfileVerifier)
        or not isinstance(recovery_authority, ManagedRecoveryAuthority)
        or not callable(transport)
        or not callable(clock)
        or not isinstance(state_cas, DurableStateCAS)
    ):
        raise ValueError("invalid managed reconciliation adapters")
    context_digest = _service_context_digest(context)
    state_key = context_digest
    fallback_operation = hashlib.sha256(
        b"multiagentmemory.managed-reconciliation-unbound.v1\0"
        + context_digest.encode("ascii")
    ).hexdigest()
    try:
        now = int(clock())
        if now < 0:
            raise ValueError("invalid clock")
        if recovery_authority.authority_id != context.recovery_authority_id:
            raise OnboardingError(
                "managed_recovery_authority_mismatch",
                "The managed recovery authority does not match the service policy.",
                "quarantine_identity",
            )
        profile_path = Path(locator.locate(context)).expanduser()
        profile_document = _read_private_json(profile_path)
        profile, verify_profile = _verified_service_profile(
            context, profile_document, verifier
        )
        if (
            protector.protection_id != profile["protectionId"]
            or protector.workload_identity_id != context.workload_identity_id
        ):
            raise OnboardingError(
                "managed_service_binding_mismatch",
                "The managed profile does not belong to this service identity.",
                "quarantine_identity",
            )
        profile_digest = _profile_digest(profile_document)
        profile_binding = profile["profileBinding"]
        state_revision, state = state_cas.read(state_key)
        if type(state_revision) is not int or state_revision < 0:
            raise OnboardingError(
                "managed_controller_state_invalid",
                "Managed controller state is unavailable or invalid.",
                "quarantine_identity",
            )
        if state is None:
            raise OnboardingError(
                "managed_controller_state_missing",
                "The installer-authorized managed controller state is missing.",
                "quarantine_identity",
            )
        state = _validate_controller_state(state)
        operation_digest = _controller_operation_digest(
            context_digest, profile_binding, max(1, state["attemptCount"])
        )
        if state["phase"] in {"quarantined", "halted"}:
            action = "quarantine_replace" if state["phase"] == "quarantined" else "halt"
            return _reconciliation_result(
                ok=False,
                phase=state["phase"],
                code=state["lastFailureCode"],
                action=action,
                action_authority=("fleet_controller" if action == "quarantine_replace" else "independent_recovery_authority"),
                retryable=False,
                terminal=True,
                attempt_count=state["attemptCount"],
                max_attempts=state["maxAttempts"],
                operation_digest=state["operationDigest"],
            )
        if (
            state["phase"] == "retry_wait"
            and now < state["nextAttemptAtEpoch"]
        ):
            retry_after = state["nextAttemptAtEpoch"] - now
            return _reconciliation_result(
                ok=False,
                phase="retry_wait",
                code=state["lastFailureCode"],
                action="retry_after",
                action_authority="controller",
                retryable=True,
                terminal=False,
                attempt_count=state["attemptCount"],
                max_attempts=state["maxAttempts"],
                retry_after_seconds=retry_after,
                next_attempt_at_epoch=state["nextAttemptAtEpoch"],
                operation_digest=state["operationDigest"],
            )
        if (
            state["profileId"] != profile["profileId"]
            or state["serviceInstanceId"] != context.service_instance_id
            or state["activeProfileDigest"] != profile_digest
            or state["activeTrustSha256"] != profile["caSha256"]
            or state["profileGeneration"] != profile["profileGeneration"]
            or state["policyRevision"] != profile["policyRevision"]
            or state["maxAttempts"] != context.max_attempts
        ):
            return _terminal_recovery_result(
                state_cas=state_cas,
                state_key=state_key,
                state_revision=state_revision,
                state=state,
                profile_binding=profile_binding,
                context_digest=context_digest,
                failure_code="managed_profile_state_conflict",
                operation_digest=operation_digest,
                authority=recovery_authority,
                now=now,
            )
        if state["phase"] == "connecting":
            if now < state["attemptLeaseExpiresAtEpoch"]:
                retry_after = state["attemptLeaseExpiresAtEpoch"] - now
                return _reconciliation_result(
                    ok=False,
                    phase="retry_wait",
                    code="managed_connection_attempt_in_progress",
                    action="retry_after",
                    action_authority="controller",
                    retryable=True,
                    terminal=False,
                    attempt_count=state["attemptCount"],
                    max_attempts=state["maxAttempts"],
                    retry_after_seconds=retry_after,
                    next_attempt_at_epoch=state["attemptLeaseExpiresAtEpoch"],
                    operation_digest=state["operationDigest"],
                )
            if state["attemptCount"] >= state["maxAttempts"]:
                return _terminal_recovery_result(
                    state_cas=state_cas,
                    state_key=state_key,
                    state_revision=state_revision,
                    state=state,
                    profile_binding=profile_binding,
                    context_digest=context_digest,
                    failure_code="managed_connection_outcome_unknown",
                    operation_digest=state["operationDigest"],
                    authority=recovery_authority,
                    now=now,
                )
        attempt_count = state["attemptCount"] + 1
        operation_digest = _controller_operation_digest(
            context_digest, profile_binding, attempt_count
        )
        connecting = dict(state)
        connecting.update(
            {
                "phase": "connecting",
                "attemptCount": attempt_count,
                "attemptLeaseExpiresAtEpoch": now + context.attempt_lease_seconds,
                "nextAttemptAtEpoch": None,
                "lastFailureCode": None,
                "operationDigest": operation_digest,
                "quarantined": False,
            }
        )
        _validate_controller_state(connecting)
        state_revision = state_cas.compare_exchange(
            state_key, state_revision, connecting
        )
        state = connecting
        try:
            with _managed_profile_lock(profile_path, timeout_milliseconds=0):
                _connect_managed_agent_unlocked(
                    profile_path,
                    profile,
                    open_url=transport,
                    protector=protector,
                )
        except OnboardingError as exc:
            if exc.retryable and state["attemptCount"] < state["maxAttempts"]:
                exponent = min(state["attemptCount"] - 1, 16)
                retry_after = min(
                    context.max_retry_seconds,
                    max(
                        context.base_retry_seconds * (2**exponent),
                        int(exc.retry_after_seconds or 1),
                    ),
                )
                retry_state = dict(state)
                retry_state.update(
                    {
                        "phase": "retry_wait",
                        "attemptLeaseExpiresAtEpoch": None,
                        "nextAttemptAtEpoch": now + retry_after,
                        "lastFailureCode": exc.code,
                        "operationDigest": operation_digest,
                        "quarantined": False,
                    }
                )
                _validate_controller_state(retry_state)
                state_cas.compare_exchange(state_key, state_revision, retry_state)
                return _reconciliation_result(
                    ok=False,
                    phase="retry_wait",
                    code=exc.code,
                    action="retry_after",
                    action_authority="controller",
                    retryable=True,
                    terminal=False,
                    attempt_count=state["attemptCount"],
                    max_attempts=state["maxAttempts"],
                    retry_after_seconds=retry_after,
                    next_attempt_at_epoch=now + retry_after,
                    operation_digest=operation_digest,
                )
            return _terminal_recovery_result(
                state_cas=state_cas,
                state_key=state_key,
                state_revision=state_revision,
                state=state,
                profile_binding=profile_binding,
                context_digest=context_digest,
                failure_code=exc.code,
                operation_digest=operation_digest,
                authority=recovery_authority,
                now=now,
            )
        active_state = dict(state)
        active_state.update(
            {
                "phase": "active",
                "attemptCount": 0,
                "attemptLeaseExpiresAtEpoch": None,
                "nextAttemptAtEpoch": None,
                "lastFailureCode": None,
                "operationDigest": operation_digest,
                "quarantined": False,
            }
        )
        _validate_controller_state(active_state)
        state_cas.compare_exchange(state_key, state_revision, active_state)
        return _reconciliation_result(
            ok=True,
            phase="active",
            code="managed_connection_active",
            action="none",
            action_authority="none",
            retryable=False,
            terminal=False,
            attempt_count=0,
            max_attempts=state["maxAttempts"],
            operation_digest=operation_digest,
        )
    except OnboardingError as exc:
        action = "retry_after" if exc.retryable else "quarantine_replace"
        retry_after = max(1, int(exc.retry_after_seconds or 1)) if exc.retryable else None
        return _reconciliation_result(
            ok=False,
            phase="retry_wait" if exc.retryable else "quarantined",
            code=exc.code,
            action=action,
            action_authority="controller" if exc.retryable else "fleet_controller",
            retryable=exc.retryable,
            terminal=not exc.retryable,
            attempt_count=0,
            max_attempts=context.max_attempts,
            retry_after_seconds=retry_after,
            next_attempt_at_epoch=(now + retry_after if exc.retryable else None),
            operation_digest=fallback_operation,
        )
    except Exception:
        return _reconciliation_result(
            ok=False,
            phase="quarantined",
            code="managed_reconciliation_internal_error",
            action="quarantine_replace",
            action_authority="fleet_controller",
            retryable=False,
            terminal=True,
            attempt_count=0,
            max_attempts=context.max_attempts,
            operation_digest=fallback_operation,
        )


def _parser():
    parser = argparse.ArgumentParser(
        description="Diagnose one per-user installer-managed MemoryEndpoints profile."
    )
    parser.add_argument(
        "--profile",
        help="Diagnostic override for a per-user managed profile; unattended services must not use this command.",
    )
    return parser


def main(argv=None, environ=None):
    args = _parser().parse_args(argv)
    try:
        result = connect_managed_agent(profile_path=args.profile)
    except OnboardingError as exc:
        payload = _public_error_result(exc)
        print(json.dumps(payload, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    except Exception:
        payload = _public_error_result(
            OnboardingError(
                "managed_connection_internal_error",
                "The managed connection controller failed safely without exposing local details.",
                "repair_managed_connection_controller",
            )
        )
        print(json.dumps(payload, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
