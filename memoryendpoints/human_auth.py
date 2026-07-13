"""Security primitives for human account authentication.

The functions in this module deliberately do not know about HTTP handlers or a
storage backend.  They provide one strict policy implementation that the file,
SQLite, and MySQL adapters can share without persisting raw credentials.
"""

import base64
import datetime
import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit

from .config import ROOT


USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 64
PASSWORD_MIN_LENGTH = 15
PASSWORD_MAX_BYTES = 1024
PASSWORD_KDF_VERSION = 1
PASSWORD_SCRYPT_N = 1 << 14
PASSWORD_SCRYPT_R = 8
PASSWORD_SCRYPT_P = 1
PASSWORD_DERIVED_KEY_BYTES = 32
PASSWORD_SALT_BYTES = 16
PASSWORD_SCRYPT_MAXMEM_BYTES = 64 * 1024 * 1024
OPAQUE_SECRET_BYTES = 32
MIN_CREDENTIAL_PEPPER_BYTES = 32
MAX_CREDENTIAL_PEPPER_BYTES = 4096
MAX_RECENT_REAUTH_SECONDS = 15 * 60
DEFAULT_RECENT_REAUTH_SECONDS = 5 * 60
MAX_CLOCK_SKEW_SECONDS = 60

_USERNAME_PATTERN = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
_SECRET_PATTERN = re.compile(r"[A-Za-z0-9_-]{32,256}")
_SECRET_PURPOSE_PATTERN = re.compile(r"[a-z][a-z0-9._-]{0,63}")
_VERIFIER_PREFIX = "me_scrypt_v1"
_HMAC_PREFIX = "hmac-sha256-v1:"
_COMMON_PASSWORDS = {
    "correcthorsebatterystaple",
    "letmeinletmeinletmein",
    "passwordpasswordpassword",
    "qwertyuiopqwertyuiop",
    "thisisaverybadpassword",
}


class HumanAuthPolicyError(ValueError):
    """A stable, public-safe human-auth policy failure."""

    def __init__(self, code):
        self.code = str(code)
        super().__init__(self.code)


class HumanAuthConfigurationError(RuntimeError):
    """Human authentication cannot start with unsafe secret configuration."""


@dataclass(frozen=True)
class ParsedPasswordVerifier:
    version: int
    n: int
    r: int
    p: int
    dklen: int
    salt: bytes = field(repr=False)
    digest: bytes = field(repr=False)


@dataclass(frozen=True)
class IssuedBoundSecret:
    """A newly issued raw secret and its persistence-safe HMAC verifier."""

    purpose: str
    subject_id: str
    secret: str = field(repr=False)
    verifier: str = field(repr=False)


def username_policy():
    """Return the public validation contract used by server and client UIs."""
    return {
        "minimumLength": USERNAME_MIN_LENGTH,
        "maximumLength": USERNAME_MAX_LENGTH,
        "allowedPattern": r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$",
        "canonicalization": "trim_ascii_whitespace_and_lowercase",
        "caseSensitive": False,
        "unicodeAllowed": False,
    }


def canonicalize_username(value):
    """Return one company-independent canonical human login name.

    Human account usernames are global login identifiers.  Agent display names
    have a separate company-scoped policy and must not use this function.
    """
    if not isinstance(value, str):
        raise HumanAuthPolicyError("username_required")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise HumanAuthPolicyError("username_invalid") from exc
    username = value.strip(" \t\r\n\f\v").lower()
    if not USERNAME_MIN_LENGTH <= len(username) <= USERNAME_MAX_LENGTH:
        raise HumanAuthPolicyError("username_invalid")
    if _USERNAME_PATTERN.fullmatch(username) is None:
        raise HumanAuthPolicyError("username_invalid")
    return username


def password_policy():
    """Return non-secret server policy metadata for account-creation guidance."""
    return {
        "minimumLength": PASSWORD_MIN_LENGTH,
        "maximumUtf8Bytes": PASSWORD_MAX_BYTES,
        "compositionRules": False,
        "usernameMatchAllowed": False,
        "commonPasswordBlocklist": True,
        "normalization": "none",
    }


def password_policy_errors(password, username=None):
    """Return stable validation codes without returning or transforming a password."""
    if not isinstance(password, str):
        return ("password_required",)
    errors = []
    try:
        encoded = password.encode("utf-8")
    except UnicodeEncodeError:
        return ("password_invalid_character",)
    if len(password) < PASSWORD_MIN_LENGTH:
        errors.append("password_too_short")
    if len(encoded) > PASSWORD_MAX_BYTES:
        errors.append("password_too_long")
    if "\x00" in password:
        errors.append("password_invalid_character")
    if password.casefold() in _COMMON_PASSWORDS:
        errors.append("password_common")
    if username is not None:
        try:
            canonical_username = canonicalize_username(username)
        except HumanAuthPolicyError:
            canonical_username = None
        if canonical_username and password.casefold() == canonical_username.casefold():
            errors.append("password_matches_username")
    return tuple(errors)


def validate_password(password, username=None):
    """Validate a new password and raise a stable policy code on failure."""
    errors = password_policy_errors(password, username=username)
    if errors:
        raise HumanAuthPolicyError(errors[0])
    return True


def _b64url_encode(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value):
    if not isinstance(value, str) or not value or "=" in value:
        raise ValueError("invalid base64url")
    if re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise ValueError("invalid base64url")
    decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if _b64url_encode(decoded) != value:
        raise ValueError("non-canonical base64url")
    return decoded


def _derive_scrypt(password_bytes, parsed):
    return hashlib.scrypt(
        password_bytes,
        salt=parsed.salt,
        n=parsed.n,
        r=parsed.r,
        p=parsed.p,
        dklen=parsed.dklen,
        maxmem=PASSWORD_SCRYPT_MAXMEM_BYTES,
    )


def _encode_parsed_password_verifier(parsed):
    return "$".join(
        (
            _VERIFIER_PREFIX,
            "n=%d" % parsed.n,
            "r=%d" % parsed.r,
            "p=%d" % parsed.p,
            "dk=%d" % parsed.dklen,
            _b64url_encode(parsed.salt),
            _b64url_encode(parsed.digest),
        )
    )


def encode_password_verifier(password, username=None):
    """Create a self-contained scrypt verifier with a fresh random salt."""
    validate_password(password, username=username)
    salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
    parameters = ParsedPasswordVerifier(
        version=PASSWORD_KDF_VERSION,
        n=PASSWORD_SCRYPT_N,
        r=PASSWORD_SCRYPT_R,
        p=PASSWORD_SCRYPT_P,
        dklen=PASSWORD_DERIVED_KEY_BYTES,
        salt=salt,
        digest=b"",
    )
    digest = _derive_scrypt(password.encode("utf-8"), parameters)
    return _encode_parsed_password_verifier(
        ParsedPasswordVerifier(
            version=parameters.version,
            n=parameters.n,
            r=parameters.r,
            p=parameters.p,
            dklen=parameters.dklen,
            salt=parameters.salt,
            digest=digest,
        )
    )


def parse_password_verifier(verifier):
    """Parse a verifier, returning ``None`` for every malformed/unsafe value."""
    if not isinstance(verifier, str) or len(verifier) > 512:
        return None
    parts = verifier.split("$")
    if len(parts) != 7 or parts[0] != _VERIFIER_PREFIX:
        return None
    try:
        labels = {}
        for part, required_key in zip(parts[1:5], ("n", "r", "p", "dk")):
            key, value = part.split("=", 1)
            if (
                key != required_key
                or
                key in labels
                or not value.isascii()
                or not value.isdecimal()
                or value != str(int(value))
            ):
                return None
            labels[key] = int(value)
        if labels != {
            "n": PASSWORD_SCRYPT_N,
            "r": PASSWORD_SCRYPT_R,
            "p": PASSWORD_SCRYPT_P,
            "dk": PASSWORD_DERIVED_KEY_BYTES,
        }:
            return None
        salt = _b64url_decode(parts[5])
        digest = _b64url_decode(parts[6])
        if len(salt) != PASSWORD_SALT_BYTES or len(digest) != PASSWORD_DERIVED_KEY_BYTES:
            return None
        return ParsedPasswordVerifier(
            version=PASSWORD_KDF_VERSION,
            n=labels["n"],
            r=labels["r"],
            p=labels["p"],
            dklen=labels["dk"],
            salt=salt,
            digest=digest,
        )
    except (TypeError, ValueError, UnicodeError):
        return None


def _password_bytes_for_verification(password):
    if not isinstance(password, str):
        return b"", False
    try:
        encoded = password.encode("utf-8")
    except UnicodeEncodeError:
        return b"", False
    if len(encoded) > PASSWORD_MAX_BYTES:
        return hashlib.sha256(encoded).digest(), False
    if password_policy_errors(password):
        return encoded, False
    return encoded, True


def _verify_with_parsed(password, parsed):
    password_bytes, candidate_valid = _password_bytes_for_verification(password)
    try:
        actual = _derive_scrypt(password_bytes, parsed)
    except (MemoryError, TypeError, ValueError):
        return False
    matches = hmac.compare_digest(parsed.digest, actual)
    return bool(candidate_valid and matches)


def verify_password(password, verifier):
    """Verify one candidate using constant-time derived-key comparison."""
    parsed = parse_password_verifier(verifier)
    if parsed is None:
        return False
    return _verify_with_parsed(password, parsed)


def _dummy_password_verifier():
    salt = hashlib.sha256(b"MemoryEndpoints human-auth dummy salt v1").digest()[:PASSWORD_SALT_BYTES]
    parameters = ParsedPasswordVerifier(
        version=PASSWORD_KDF_VERSION,
        n=PASSWORD_SCRYPT_N,
        r=PASSWORD_SCRYPT_R,
        p=PASSWORD_SCRYPT_P,
        dklen=PASSWORD_DERIVED_KEY_BYTES,
        salt=salt,
        digest=b"",
    )
    digest = _derive_scrypt(b"MemoryEndpoints unknown human account v1", parameters)
    return ParsedPasswordVerifier(
        version=parameters.version,
        n=parameters.n,
        r=parameters.r,
        p=parameters.p,
        dklen=parameters.dklen,
        salt=parameters.salt,
        digest=digest,
    )


_DUMMY_PASSWORD_VERIFIER = _dummy_password_verifier()


def verify_password_or_dummy(password, verifier):
    """Verify known users and spend the same KDF work for unknown users.

    The return value can only be true for a syntactically valid stored verifier.
    A missing or malformed verifier is replaced with a process-local dummy for
    the expensive calculation and always returns false.
    """
    parsed = parse_password_verifier(verifier)
    stored_verifier_valid = parsed is not None
    matches = _verify_with_parsed(password, parsed or _DUMMY_PASSWORD_VERIFIER)
    return bool(stored_verifier_valid and matches)


def resolve_credential_pepper(pepper=None, config_path=None):
    """Resolve the protected credential pepper or fail closed.

    Tests should inject ``pepper``.  Runtime may use the existing environment or
    protected JSON config convention shared by the credential system.
    """
    value = pepper
    if value is None:
        value = os.environ.get("MEMORYENDPOINTS_CREDENTIAL_PEPPER") or None
    if value is None:
        configured = config_path or os.environ.get("MEMORYENDPOINTS_CREDENTIAL_CONFIG_PATH")
        path = Path(configured) if configured else ROOT / ".local-secrets" / "credential-pepper.json"
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise HumanAuthConfigurationError("credential_pepper_unavailable") from exc
            if isinstance(payload, dict):
                value = payload.get("credentialPepper") or payload.get("pepper")
    if isinstance(value, str):
        try:
            resolved = value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise HumanAuthConfigurationError("credential_pepper_unavailable") from exc
    elif isinstance(value, (bytes, bytearray)):
        resolved = bytes(value)
    else:
        resolved = b""
    if not MIN_CREDENTIAL_PEPPER_BYTES <= len(resolved) <= MAX_CREDENTIAL_PEPPER_BYTES:
        raise HumanAuthConfigurationError("credential_pepper_unavailable")
    return resolved


def generate_opaque_secret(num_bytes=OPAQUE_SECRET_BYTES):
    """Generate a URL-safe opaque session or CSRF secret."""
    if not isinstance(num_bytes, int) or not OPAQUE_SECRET_BYTES <= num_bytes <= 64:
        raise HumanAuthPolicyError("opaque_secret_size_invalid")
    return secrets.token_urlsafe(num_bytes)


def _bound_secret_context(secret, purpose, subject_id):
    if not isinstance(secret, str) or _SECRET_PATTERN.fullmatch(secret) is None:
        raise HumanAuthPolicyError("opaque_secret_invalid")
    if not isinstance(purpose, str) or _SECRET_PURPOSE_PATTERN.fullmatch(purpose) is None:
        raise HumanAuthPolicyError("secret_purpose_invalid")
    if not isinstance(subject_id, str) or not 1 <= len(subject_id) <= 256 or "\x00" in subject_id:
        raise HumanAuthPolicyError("secret_subject_invalid")
    try:
        subject_bytes = subject_id.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise HumanAuthPolicyError("secret_subject_invalid") from exc
    return b"\x00".join(
        (
            b"memoryendpoints.human-auth.secret.v1",
            purpose.encode("ascii"),
            subject_bytes,
            secret.encode("ascii"),
        )
    )


def bound_secret_verifier(secret, purpose, subject_id, pepper=None):
    """Return a domain-separated HMAC verifier suitable for persistence."""
    context = _bound_secret_context(secret, purpose, subject_id)
    digest = hmac.new(resolve_credential_pepper(pepper), context, hashlib.sha256).hexdigest()
    return _HMAC_PREFIX + digest


def verify_bound_secret(secret, verifier, purpose, subject_id, pepper=None):
    """Verify an opaque secret without storing it in plaintext."""
    try:
        expected = bound_secret_verifier(secret, purpose, subject_id, pepper=pepper)
    except HumanAuthPolicyError:
        return False
    valid_format = isinstance(verifier, str) and re.fullmatch(
        r"hmac-sha256-v1:[a-f0-9]{64}", verifier
    ) is not None
    candidate = verifier if valid_format else _HMAC_PREFIX + ("0" * 64)
    matches = hmac.compare_digest(expected, candidate)
    return bool(valid_format and matches)


def issue_bound_secret(purpose, subject_id, pepper=None, num_bytes=OPAQUE_SECRET_BYTES):
    """Issue one raw secret and its purpose/subject-bound HMAC verifier."""
    secret = generate_opaque_secret(num_bytes=num_bytes)
    verifier = bound_secret_verifier(secret, purpose, subject_id, pepper=pepper)
    return IssuedBoundSecret(
        purpose=purpose,
        subject_id=subject_id,
        secret=secret,
        verifier=verifier,
    )


def _as_utc_datetime(value):
    if isinstance(value, datetime.datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(datetime.timezone.utc)


def reauthentication_is_recent(
    reauthenticated_at,
    now=None,
    max_age_seconds=DEFAULT_RECENT_REAUTH_SECONDS,
    clock_skew_seconds=MAX_CLOCK_SKEW_SECONDS,
):
    """Return whether a password reauthentication timestamp is still recent."""
    try:
        max_age = int(max_age_seconds)
        skew = int(clock_skew_seconds)
    except (TypeError, ValueError):
        return False
    if not 1 <= max_age <= MAX_RECENT_REAUTH_SECONDS or not 0 <= skew <= MAX_CLOCK_SKEW_SECONDS:
        return False
    reauthenticated = _as_utc_datetime(reauthenticated_at)
    current = _as_utc_datetime(now or datetime.datetime.now(datetime.timezone.utc))
    if reauthenticated is None or current is None:
        return False
    age = (current - reauthenticated).total_seconds()
    return -skew <= age <= max_age


def canonical_origin(value):
    """Canonicalize an HTTP(S) origin, returning an empty value when invalid."""
    if not isinstance(value, str) or not value or value == "null":
        return ""
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return ""
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        return ""
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return ""
    if parsed.path not in ("", "/"):
        return ""
    try:
        host = parsed.hostname.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return ""
    if ":" in host:
        host = "[" + host + "]"
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    port_suffix = "" if port in (None, default_port) else ":%d" % port
    return "%s://%s%s" % (parsed.scheme.lower(), host, port_suffix)


def origin_matches(origin, expected_origin):
    """Compare two HTTP(S) origins after strict canonicalization."""
    actual = canonical_origin(origin)
    expected = canonical_origin(expected_origin)
    return bool(actual and expected and hmac.compare_digest(actual, expected))


def human_browser_request_allowed(
    method,
    origin,
    expected_origin,
    sec_fetch_site,
    sec_fetch_mode="",
    sec_fetch_dest="",
):
    """Enforce the browser boundary for cookie-authenticated human routes.

    Protected UI requests must be same-origin JavaScript fetches.  Unsafe
    methods additionally require the browser ``Origin`` header.  This policy is
    used alongside a per-session CSRF secret, never as its replacement.
    """
    request_method = str(method or "").upper()
    if request_method not in ("GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"):
        return False
    if str(sec_fetch_site or "").lower() != "same-origin":
        return False
    mode = str(sec_fetch_mode or "").lower()
    if mode and mode not in ("cors", "same-origin"):
        return False
    destination = str(sec_fetch_dest or "").lower()
    if destination not in ("", "empty"):
        return False
    unsafe = request_method not in ("GET", "HEAD", "OPTIONS")
    if unsafe:
        return origin_matches(origin, expected_origin)
    return not origin or origin_matches(origin, expected_origin)
