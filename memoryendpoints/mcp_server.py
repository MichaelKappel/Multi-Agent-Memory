"""Standards-oriented OAuth 2.1 and Streamable HTTP MCP surface.

This module is intentionally dependency-free.  It is separate from the
LocalEndpoint connector protocol: OAuth credentials issued here are short-lived,
resource-bound, human-approved, and valid only for the selected workspace.
"""

import base64
import getpass
import hashlib
import hmac
import html
import ipaddress
import json
import math
import os
import re
import secrets
import socket
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from .config import COMPANION_DOCS_URL, DATA_DIR, ROOT, SITE_NAME, SITE_URL
from .security import redact_text
from .storage import _credential_pepper


MCP_PROTOCOL_VERSION = "2025-11-25"
MCP_SUPPORTED_PROTOCOL_VERSIONS = (
    MCP_PROTOCOL_VERSION,
    "2025-06-18",
    "2025-03-26",
)
MCP_SCOPES = ("memory:read", "memory:write")
HUMAN_SESSION_COOKIE = "__Host-memoryendpoints-human"
_MAX_JSON_BYTES = 64 * 1024
_MAX_FORM_BYTES = 32 * 1024
_AUTHORIZATION_TTL_SECONDS = 10 * 60
_CODE_TTL_SECONDS = 2 * 60
_ACCESS_TTL_SECONDS = 60 * 60
_REFRESH_TTL_SECONDS = 30 * 24 * 60 * 60
_CHATGPT_REDIRECT = re.compile(
    r"^https://chatgpt\.com/connector/oauth/[A-Za-z0-9_-]{1,160}$"
)
_OPENAI_TUNNEL_ID = re.compile(r"^tunnel_[0-9a-f]{32}$")
_OPENAI_TUNNEL_GATEWAY_HOST = re.compile(
    r"^tunnel-service\.gateway\.[a-z0-9-]{1,64}\.internal\.api\.openai\.org$"
)
_PKCE_VALUE = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
_PKCE_CHALLENGE = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
_LOCK = threading.RLock()
_RATE_LOCK = threading.Lock()
_RATE_BUCKETS = {}


def _local_host_config():
    configured = str(os.environ.get("MEMORYENDPOINTS_MCP_HOST_CONFIG_PATH") or "").strip()
    path = Path(configured) if configured else ROOT / ".local-secrets" / "mcp-host.json"
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _configured_https_url(value, suffix=""):
    candidate = str(value or "").strip().rstrip("/")
    if not candidate:
        return ""
    parsed = urlsplit(candidate)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return ""
    return candidate + suffix


def _resource_url():
    host_config = _local_host_config()
    configured = os.environ.get("MEMORYENDPOINTS_MCP_PUBLIC_URL") or host_config.get(
        "mcpPublicUrl"
    )
    return _configured_https_url(configured) or SITE_URL.rstrip("/") + "/mcp"


def _configured_openai_tunnel_id():
    host_config = _local_host_config()
    candidate = str(
        os.environ.get("MEMORYENDPOINTS_MCP_OPENAI_TUNNEL_ID")
        or host_config.get("openAiTunnelId")
        or ""
    ).strip()
    return candidate if _OPENAI_TUNNEL_ID.fullmatch(candidate) else ""


def _accepted_resource_url(value):
    candidate = str(value or "").strip()
    if candidate == _resource_url():
        return candidate
    tunnel_id = _configured_openai_tunnel_id()
    if not tunnel_id:
        return ""
    parsed = urlsplit(candidate)
    try:
        port = parsed.port
    except ValueError:
        return ""
    hostname = str(parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() != "https"
        or parsed.username
        or parsed.password
        or port is not None
        or parsed.query
        or parsed.fragment
        or not _OPENAI_TUNNEL_GATEWAY_HOST.fullmatch(hostname)
        or parsed.path != "/v1/mcp/" + tunnel_id
    ):
        return ""
    return candidate


def _issuer_url():
    host_config = _local_host_config()
    configured = os.environ.get("MEMORYENDPOINTS_MCP_ISSUER_URL") or host_config.get(
        "oauthIssuerUrl"
    )
    candidate = _configured_https_url(configured)
    if candidate and urlsplit(candidate).path not in ("", "/"):
        candidate = ""
    return candidate or SITE_URL.rstrip("/")


def _metadata_url():
    return _issuer_url() + "/.well-known/oauth-protected-resource/mcp"


def _oauth_path():
    configured = str(os.environ.get("MEMORYENDPOINTS_MCP_OAUTH_PATH") or "").strip()
    if configured:
        return Path(configured)
    configured_data_dir = str(os.environ.get("MEMORYENDPOINTS_DATA_DIR") or "").strip()
    return (Path(configured_data_dir) if configured_data_dir else DATA_DIR) / "mcp_oauth.sqlite3"


def _now():
    return int(time.time())


def _json_bytes(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _response(start_response, status, body=b"", content_type=None, headers=None):
    if isinstance(body, str):
        body = body.encode("utf-8")
    response_headers = list(headers or [])
    if content_type:
        response_headers.append(("Content-Type", content_type))
    response_headers.extend(
        [
            ("Content-Length", str(len(body))),
            ("X-Content-Type-Options", "nosniff"),
        ]
    )
    start_response(status, response_headers)
    return [body]


def _json_response(start_response, status, value, headers=None):
    return _response(
        start_response,
        status,
        _json_bytes(value),
        "application/json; charset=utf-8",
        headers=headers,
    )


def _oauth_error(start_response, status, code, description):
    return _json_response(
        start_response,
        status,
        {"error": code, "error_description": description},
        headers=[("Cache-Control", "no-store"), ("Pragma", "no-cache")],
    )


def _mcp_error(request_id, code, message, data=None):
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _sensitive_headers(extra=None, referrer_policy="no-referrer"):
    return list(extra or []) + [
        ("Cache-Control", "no-store, no-cache, must-revalidate, private"),
        ("Pragma", "no-cache"),
        ("Referrer-Policy", referrer_policy),
        ("X-Frame-Options", "DENY"),
        (
            "Content-Security-Policy",
            "default-src 'none'; base-uri 'none'; object-src 'none'; "
            "frame-ancestors 'none'; form-action 'self'; script-src 'self'; "
            "style-src 'self'; img-src 'self'; connect-src 'self'",
        ),
    ]


def _redirect(start_response, location):
    return _response(
        start_response,
        "302 Found",
        b"",
        headers=_sensitive_headers([("Location", location)]),
    )


def _human_session_cookie(secret, max_age=30 * 60):
    return "%s=%s; Path=/; Max-Age=%d; Secure; HttpOnly; SameSite=Strict" % (
        HUMAN_SESSION_COOKIE,
        secret,
        max_age,
    )


def _read_body(environ, maximum):
    try:
        length = int(str(environ.get("CONTENT_LENGTH") or "0"))
    except ValueError:
        raise ValueError("invalid_content_length")
    if length < 0 or length > maximum:
        raise ValueError("request_too_large")
    raw = environ.get("wsgi.input").read(length) if length else b""
    if len(raw) > maximum:
        raise ValueError("request_too_large")
    return raw


def _read_json(environ):
    content_type = str(environ.get("CONTENT_TYPE") or "").split(";", 1)[0].lower()
    if content_type != "application/json":
        raise TypeError("json_content_type_required")
    try:
        value = json.loads(
            _read_body(environ, _MAX_JSON_BYTES).decode("utf-8"),
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non_finite_json_number")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_json") from exc
    if not isinstance(value, dict):
        raise ValueError("json_object_required")
    return value


def _read_form(environ):
    content_type = str(environ.get("CONTENT_TYPE") or "").split(";", 1)[0].lower()
    if content_type != "application/x-www-form-urlencoded":
        raise TypeError("form_content_type_required")
    try:
        raw = _read_body(environ, _MAX_FORM_BYTES).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("invalid_form") from exc
    return parse_qs(raw, keep_blank_values=True, max_num_fields=40)


def _one(params, name, required=True):
    values = params.get(name) or []
    if len(values) > 1:
        raise ValueError("duplicate_%s" % name)
    value = str(values[0] if values else "")
    if required and not value:
        raise ValueError("missing_%s" % name)
    return value


def _cookie(environ, name):
    cookie = SimpleCookie()
    try:
        cookie.load(str(environ.get("HTTP_COOKIE") or ""))
    except Exception:
        return ""
    morsel = cookie.get(name)
    return morsel.value if morsel else ""


def _origin(url):
    parsed = urlsplit(str(url or ""))
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        return ""
    return "%s://%s" % (parsed.scheme.lower(), parsed.netloc.lower())


def _origin_allowed(environ):
    supplied = str(environ.get("HTTP_ORIGIN") or "").strip()
    if not supplied:
        return True
    allowed = {
        _origin(SITE_URL),
        _origin(_issuer_url()),
        _origin(_resource_url()),
        "https://chatgpt.com",
        "https://chat.openai.com",
    }
    configured = str(os.environ.get("MEMORYENDPOINTS_MCP_ALLOWED_ORIGINS") or "")
    allowed.update(_origin(item.strip()) for item in configured.split(",") if item.strip())
    return supplied.lower().rstrip("/") in {item for item in allowed if item}


def _oauth_page_headers(extra=None):
    """Keep same-origin referrers available for opaque embedded-browser origins."""
    return _sensitive_headers(extra, referrer_policy="same-origin")


def _rate_allowed(environ, bucket, limit, window=60):
    key = "%s|%s" % (bucket, str(environ.get("REMOTE_ADDR") or "unknown"))
    now = _now()
    with _RATE_LOCK:
        values = [stamp for stamp in _RATE_BUCKETS.get(key, []) if stamp > now - window]
        if len(values) >= limit:
            _RATE_BUCKETS[key] = values
            return False
        values.append(now)
        _RATE_BUCKETS[key] = values
        if len(_RATE_BUCKETS) > 2048:
            for old_key in list(_RATE_BUCKETS)[:512]:
                if not any(stamp > now - window for stamp in _RATE_BUCKETS[old_key]):
                    _RATE_BUCKETS.pop(old_key, None)
    return True


def _connect():
    path = _oauth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS mcp_oauth_clients (
          client_id TEXT PRIMARY KEY,
          client_name TEXT NOT NULL,
          redirect_uris_json TEXT NOT NULL,
          created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mcp_oauth_authorizations (
          authorization_id TEXT PRIMARY KEY,
          secret_hash TEXT NOT NULL,
          client_id TEXT NOT NULL,
          redirect_uri TEXT NOT NULL,
          state_value TEXT NOT NULL,
          resource_url TEXT NOT NULL,
          scopes TEXT NOT NULL,
          code_challenge TEXT NOT NULL,
          human_account_id TEXT NOT NULL,
          choices_json TEXT NOT NULL,
          created_at INTEGER NOT NULL,
          expires_at INTEGER NOT NULL,
          consumed_at INTEGER,
          FOREIGN KEY (client_id) REFERENCES mcp_oauth_clients (client_id)
        );
        CREATE TABLE IF NOT EXISTS mcp_oauth_codes (
          code_id TEXT PRIMARY KEY,
          secret_hash TEXT NOT NULL,
          client_id TEXT NOT NULL,
          redirect_uri TEXT NOT NULL,
          resource_url TEXT NOT NULL,
          scopes TEXT NOT NULL,
          code_challenge TEXT NOT NULL,
          human_account_id TEXT NOT NULL,
          company_id TEXT NOT NULL,
          workspace_id TEXT NOT NULL,
          created_at INTEGER NOT NULL,
          expires_at INTEGER NOT NULL,
          consumed_at INTEGER,
          FOREIGN KEY (client_id) REFERENCES mcp_oauth_clients (client_id)
        );
        CREATE TABLE IF NOT EXISTS mcp_oauth_access_tokens (
          token_id TEXT PRIMARY KEY,
          secret_hash TEXT NOT NULL,
          family_id TEXT NOT NULL,
          client_id TEXT NOT NULL,
          resource_url TEXT NOT NULL,
          scopes TEXT NOT NULL,
          human_account_id TEXT NOT NULL,
          company_id TEXT NOT NULL,
          workspace_id TEXT NOT NULL,
          created_at INTEGER NOT NULL,
          expires_at INTEGER NOT NULL,
          revoked_at INTEGER,
          FOREIGN KEY (client_id) REFERENCES mcp_oauth_clients (client_id)
        );
        CREATE TABLE IF NOT EXISTS mcp_oauth_refresh_tokens (
          token_id TEXT PRIMARY KEY,
          secret_hash TEXT NOT NULL,
          family_id TEXT NOT NULL,
          client_id TEXT NOT NULL,
          resource_url TEXT NOT NULL,
          scopes TEXT NOT NULL,
          human_account_id TEXT NOT NULL,
          company_id TEXT NOT NULL,
          workspace_id TEXT NOT NULL,
          created_at INTEGER NOT NULL,
          expires_at INTEGER NOT NULL,
          revoked_at INTEGER,
          FOREIGN KEY (client_id) REFERENCES mcp_oauth_clients (client_id)
        );
        CREATE INDEX IF NOT EXISTS ix_mcp_access_expiry
          ON mcp_oauth_access_tokens (expires_at, revoked_at);
        CREATE INDEX IF NOT EXISTS ix_mcp_refresh_expiry
          ON mcp_oauth_refresh_tokens (expires_at, revoked_at);
        """
    )
    for table in ("mcp_oauth_access_tokens", "mcp_oauth_refresh_tokens"):
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(%s)" % table)
        }
        if "family_id" not in columns:
            connection.execute(
                "ALTER TABLE %s ADD COLUMN family_id TEXT NOT NULL DEFAULT ''" % table
            )
        connection.execute(
            """
            UPDATE %s
            SET family_id = 'legacy-revoked-' || token_id,
                revoked_at = COALESCE(revoked_at, ?)
            WHERE family_id = '' OR family_id = token_id
            """ % table,
            (int(time.time()),),
        )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_mcp_access_family ON mcp_oauth_access_tokens (family_id, revoked_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_mcp_refresh_family ON mcp_oauth_refresh_tokens (family_id, revoked_at)"
    )
    return connection


@contextmanager
def _database():
    connection = _connect()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _secret_hash(kind, identifier, secret):
    context = "mcp-oauth|v1|%s|%s|%s" % (kind, identifier, secret)
    return "v1:" + hmac.new(
        _credential_pepper(), context.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _new_secret(prefix, kind):
    identifier = uuid.uuid4().hex
    secret = secrets.token_urlsafe(32)
    return "%s.%s.%s" % (prefix, identifier, secret), identifier, _secret_hash(
        kind, identifier, secret
    )


def _parse_secret(value, prefix):
    parts = str(value or "").split(".")
    if (
        len(parts) != 3
        or parts[0] != prefix
        or not re.fullmatch(r"[0-9a-f]{32}", parts[1])
        or not re.fullmatch(r"[A-Za-z0-9_-]{43}", parts[2])
    ):
        return None, None
    return parts[1], parts[2]


def _valid_redirect(uri):
    return bool(_CHATGPT_REDIRECT.fullmatch(str(uri or "")))


def _client(connection, client_id):
    row = connection.execute(
        "SELECT * FROM mcp_oauth_clients WHERE client_id = ?", (client_id,)
    ).fetchone()
    return row


def _scopes(value):
    requested = [item for item in str(value or "").split() if item]
    if not requested or len(requested) != len(set(requested)):
        raise ValueError("invalid_scope")
    if any(item not in MCP_SCOPES for item in requested):
        raise ValueError("invalid_scope")
    return tuple(item for item in MCP_SCOPES if item in requested)


def _protected_resource_metadata():
    return {
        "resource": _resource_url(),
        "authorization_servers": [_issuer_url()],
        "scopes_supported": list(MCP_SCOPES),
        "bearer_methods_supported": ["header"],
        "resource_documentation": COMPANION_DOCS_URL.rstrip("/")
        + "/docs/chatgpt-mcp.html",
    }


def _authorization_server_metadata():
    issuer = _issuer_url()
    return {
        "issuer": issuer,
        "authorization_endpoint": issuer + "/oauth/authorize",
        "token_endpoint": issuer + "/oauth/token",
        "revocation_endpoint": issuer + "/oauth/revoke",
        "registration_endpoint": issuer + "/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none"],
        "revocation_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": list(MCP_SCOPES),
        "resource_parameter_supported": True,
    }


def _oauth_browser_same_origin(environ):
    expected = _origin(_issuer_url())
    raw_origin = str(environ.get("HTTP_ORIGIN") or "").strip()
    supplied = _origin(raw_origin)
    fetch_site = str(environ.get("HTTP_SEC_FETCH_SITE") or "").strip().lower()
    if supplied:
        return fetch_site == "same-origin" and supplied == expected
    referer_matches = _origin(environ.get("HTTP_REFERER")) == expected
    if raw_origin.lower() == "null":
        return referer_matches
    return fetch_site == "same-origin" and referer_matches


def _host_local_operator_auto_sign_in_enabled():
    """Allow an explicit kill switch while keeping Windows-host setup automatic."""
    if os.name != "nt":
        return False
    configured = str(
        os.environ.get("MEMORYENDPOINTS_MCP_HOST_LOCAL_AUTO_SIGN_IN") or ""
    ).strip().lower()
    if configured in ("0", "false", "no", "off", "disabled"):
        return False
    if configured in ("1", "true", "yes", "on", "enabled"):
        return True
    return True


def _current_windows_username():
    if os.name != "nt":
        return ""
    try:
        return str(getpass.getuser() or "").strip()
    except (ImportError, KeyError, OSError):
        return ""


def _request_origin_matches_issuer(environ):
    scheme = str(environ.get("wsgi.url_scheme") or "").strip().lower()
    raw_host = str(environ.get("HTTP_HOST") or "").strip()
    if (
        scheme not in ("http", "https")
        or not raw_host
        or "@" in raw_host
        or any(character in raw_host for character in "\r\n/\\")
    ):
        return False
    return _origin("%s://%s" % (scheme, raw_host)) == _origin(_issuer_url())


def _request_is_directly_from_this_host(environ):
    """Use only the socket peer; forwarded identity headers are never trusted."""
    if not _host_local_operator_auto_sign_in_enabled():
        return False
    if any(
        str(environ.get(name) or "").strip()
        for name in (
            "HTTP_FORWARDED",
            "HTTP_X_FORWARDED_FOR",
            "HTTP_X_FORWARDED_HOST",
            "HTTP_X_FORWARDED_PROTO",
            "HTTP_X_REAL_IP",
        )
    ):
        return False
    if not _request_origin_matches_issuer(environ):
        return False
    try:
        remote_address = ipaddress.ip_address(
            str(environ.get("REMOTE_ADDR") or "").strip()
        )
    except ValueError:
        return False
    try:
        issuer_address = ipaddress.ip_address(
            str(urlsplit(_issuer_url()).hostname or "").strip()
        )
    except ValueError:
        return False
    if issuer_address.is_loopback:
        return remote_address.is_loopback
    if remote_address != issuer_address:
        return False
    try:
        local_addresses = {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(socket.gethostname(), None)
        }
    except (OSError, ValueError):
        return False
    return issuer_address in local_addresses


def _host_local_operator_session(environ, store):
    """Open a normal session only for the matching Windows user on this host."""
    if not _request_is_directly_from_this_host(environ):
        return {"ok": False}
    username = _current_windows_username()
    if not username:
        return {"ok": False}
    return store.open_host_local_human_session(username, 30 * 60)


def _oauth_session(environ, start_response, store_factory):
    if environ.get("REQUEST_METHOD") != "POST":
        return _oauth_error(start_response, "405 Method Not Allowed", "invalid_request", "Use POST to sign in.")
    if not _oauth_browser_same_origin(environ):
        return _oauth_error(start_response, "403 Forbidden", "access_denied", "Same-origin browser login is required.")
    if not _rate_allowed(environ, "mcp-human-login", 20):
        return _oauth_error(start_response, "429 Too Many Requests", "temporarily_unavailable", "Login rate limit reached.")
    try:
        body = _read_json(environ)
    except TypeError:
        return _oauth_error(start_response, "415 Unsupported Media Type", "invalid_request", "JSON is required.")
    except ValueError:
        return _oauth_error(start_response, "400 Bad Request", "invalid_request", "The login request is invalid.")
    if set(body) != {"username", "password"}:
        return _oauth_error(start_response, "400 Bad Request", "invalid_request", "Username and password are required.")
    username = body.get("username")
    password = body.get("password")
    if not isinstance(username, str) or not username.strip() or not isinstance(password, str) or not password:
        return _oauth_error(start_response, "400 Bad Request", "invalid_request", "Username and password are required.")
    result = store_factory().login_human_account(username, password, 30 * 60)
    if not result.get("ok") or not result.get("sessionSecret"):
        return _oauth_error(start_response, "401 Unauthorized", "access_denied", "The username or password was not accepted.")
    return _json_response(
        start_response,
        "200 OK",
        {
            "ok": True,
            "signedIn": True,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        },
        headers=_sensitive_headers(
            [("Set-Cookie", _human_session_cookie(result["sessionSecret"]))]
        ),
    )


def _register(environ, start_response):
    if environ.get("REQUEST_METHOD") != "POST":
        return _oauth_error(start_response, "405 Method Not Allowed", "invalid_request", "Use POST for client registration.")
    if not _rate_allowed(environ, "mcp-register", 20):
        return _oauth_error(start_response, "429 Too Many Requests", "temporarily_unavailable", "Registration rate limit reached.")
    try:
        body = _read_json(environ)
    except TypeError:
        return _oauth_error(start_response, "415 Unsupported Media Type", "invalid_client_metadata", "JSON is required.")
    except ValueError:
        return _oauth_error(start_response, "400 Bad Request", "invalid_client_metadata", "The registration document is invalid.")
    redirects = body.get("redirect_uris")
    if (
        not isinstance(redirects, list)
        or not 1 <= len(redirects) <= 8
        or any(not isinstance(item, str) or not _valid_redirect(item) for item in redirects)
        or len(redirects) != len(set(redirects))
    ):
        return _oauth_error(start_response, "400 Bad Request", "invalid_redirect_uri", "Only exact ChatGPT connector callback URLs are accepted.")
    if body.get("token_endpoint_auth_method", "none") != "none":
        return _oauth_error(start_response, "400 Bad Request", "invalid_client_metadata", "This server accepts public PKCE clients only.")
    grant_types = body.get("grant_types") or ["authorization_code"]
    response_types = body.get("response_types") or ["code"]
    if (
        not isinstance(grant_types, list)
        or not grant_types
        or any(item not in ("authorization_code", "refresh_token") for item in grant_types)
        or "authorization_code" not in grant_types
        or response_types != ["code"]
    ):
        return _oauth_error(start_response, "400 Bad Request", "invalid_client_metadata", "Authorization code with PKCE is required.")
    client_name = redact_text(
        " ".join(str(body.get("client_name") or "ChatGPT").split())[:96]
    )
    client_id = "mcpclient-" + uuid.uuid4().hex
    now = _now()
    with _LOCK:
        with _database() as connection:
            connection.execute(
                "INSERT INTO mcp_oauth_clients (client_id, client_name, redirect_uris_json, created_at) VALUES (?, ?, ?, ?)",
                (client_id, client_name or "ChatGPT", json.dumps(redirects), now),
            )
    return _json_response(
        start_response,
        "201 Created",
        {
            "client_id": client_id,
            "client_id_issued_at": now,
            "client_name": client_name or "ChatGPT",
            "redirect_uris": redirects,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
        headers=[("Cache-Control", "no-store")],
    )


def _authorize_parameters(environ):
    params = parse_qs(
        str(environ.get("QUERY_STRING") or ""), keep_blank_values=True, max_num_fields=30
    )
    response_type = _one(params, "response_type")
    client_id = _one(params, "client_id")
    redirect_uri = _one(params, "redirect_uri")
    scope_value = _one(params, "scope")
    state = _one(params, "state")
    resource = _one(params, "resource")
    code_challenge = _one(params, "code_challenge")
    method = _one(params, "code_challenge_method")
    if response_type != "code" or method != "S256":
        raise ValueError("unsupported_authorization_request")
    if not _PKCE_CHALLENGE.fullmatch(code_challenge) or len(state) > 1024:
        raise ValueError("invalid_authorization_request")
    if not _accepted_resource_url(resource):
        raise ValueError("invalid_resource")
    requested_scopes = _scopes(scope_value)
    with _LOCK:
        with _database() as connection:
            client = _client(connection, client_id)
    if not client or redirect_uri not in json.loads(client["redirect_uris_json"]):
        raise PermissionError("invalid_client_or_redirect")
    return {
        "client_id": client_id,
        "client_name": client["client_name"],
        "redirect_uri": redirect_uri,
        "state": state,
        "resource": resource,
        "scopes": requested_scopes,
        "code_challenge": code_challenge,
    }


def _page(title, main, script=False):
    script_tag = '<script defer src="/static/js/mcp-authorize.js"></script>' if script else ""
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s · %s</title><link rel="stylesheet" href="/static/css/site.css">%s</head>
<body><main class="content-shell"><section class="content-section"><p class="eyebrow">ChatGPT MCP connection</p>%s</section></main></body></html>""" % (
        html.escape(title), html.escape(SITE_NAME), script_tag, main
    )


def _login_page(client_name):
    main = """
<h1>Sign in to connect ChatGPT</h1>
<p><strong>%s</strong> is requesting access to one Multi-Agent Memory workspace. Your password stays on this server and is never shared with ChatGPT.</p>
<form data-mcp-login>
  <label>Username <input name="username" autocomplete="username" required></label>
  <label>Password <input name="password" type="password" autocomplete="current-password" required></label>
  <button class="button primary" type="submit">Sign in securely</button>
  <p role="status" aria-live="polite" data-mcp-login-status></p>
</form>
""" % html.escape(client_name)
    return _page("Sign in", main, script=True)


def _consent_page(
    client_name,
    catalog,
    pending_id,
    pending_secret,
    scopes,
    host_local_session=False,
):
    options = []
    choices = {}
    for company in catalog.get("items") or []:
        for workspace in company.get("workspaces") or []:
            choice = secrets.token_urlsafe(18)
            choices[choice] = {
                "companyId": company.get("companyId"),
                "workspaceId": workspace.get("workspaceId"),
            }
            label = "%s — %s" % (
                company.get("companyLabel") or "Company",
                workspace.get("label") or "Workspace",
            )
            options.append((choice, label))
    only_choice = len(options) == 1
    rendered_options = []
    for choice, label in options:
        rendered_options.append(
            '<option value="%s">%s</option>'
            % (
                html.escape(choice, quote=True),
                html.escape(label),
            )
        )
    placeholder = "" if only_choice else '<option value="">Choose a workspace</option>'
    scope_rows = []
    if "memory:read" in scopes:
        scope_rows.append("Search and read public-safe memory in the selected workspace")
    if "memory:write" in scopes:
        scope_rows.append("Submit public-safe memory for the normal review workflow")
    main = """
<h1>Allow ChatGPT to use Multi-Agent Memory?</h1>
<p>Signed in as <strong>%s</strong>. <strong>%s</strong> will receive only the permissions listed below for one workspace.</p>
%s
<ul>%s</ul>
<form method="post" action="/oauth/authorize">
  <input type="hidden" name="authorization_id" value="%s">
  <input type="hidden" name="authorization_secret" value="%s">
  <label>Workspace <select name="choice" required>%s%s</select></label>
  <div><button class="button primary" name="decision" value="allow" type="submit">Allow connection</button>
  <button class="button" name="decision" value="deny" type="submit">Cancel</button></div>
</form>
<p>No company master credential, agent credential, password, or raw private payload is sent to ChatGPT.</p>
""" % (
        html.escape(catalog.get("displayName") or catalog.get("username") or "human user"),
        html.escape(client_name),
        (
            '<p class="callout">Signed in automatically as the Windows operator on this computer. Other computers still require an account password.</p>'
            if host_local_session
            else ""
        ),
        "".join("<li>%s</li>" % html.escape(item) for item in scope_rows),
        html.escape(pending_id, quote=True),
        html.escape(pending_secret, quote=True),
        placeholder,
        "".join(rendered_options),
    )
    return _page("Approve connection", main), choices


def _error_page(title, detail):
    return _page(
        title,
        "<h1>%s</h1><p>%s</p>" % (html.escape(title), html.escape(detail)),
    )


def _authorize_get(environ, start_response, store_factory):
    if not _rate_allowed(environ, "mcp-authorize", 120):
        return _response(start_response, "429 Too Many Requests", _error_page("Please wait", "Too many authorization attempts."), "text/html; charset=utf-8", _sensitive_headers())
    try:
        request = _authorize_parameters(environ)
    except PermissionError:
        return _response(start_response, "400 Bad Request", _error_page("Connection request rejected", "The client or callback is not registered."), "text/html; charset=utf-8", _sensitive_headers())
    except (ValueError, TypeError):
        return _response(start_response, "400 Bad Request", _error_page("Connection request rejected", "The OAuth request is incomplete or invalid."), "text/html; charset=utf-8", _sensitive_headers())
    session_secret = _cookie(environ, HUMAN_SESSION_COOKIE)
    store = store_factory()
    catalog = store.mcp_human_authorization_catalog(session_secret) if session_secret else {"ok": False}
    response_headers = []
    host_local_session = False
    if not catalog.get("ok"):
        local_session = _host_local_operator_session(environ, store)
        if local_session.get("ok") and local_session.get("sessionSecret"):
            session_secret = local_session["sessionSecret"]
            catalog = store.mcp_human_authorization_catalog(session_secret)
            if catalog.get("ok"):
                host_local_session = True
                response_headers.append(
                    ("Set-Cookie", _human_session_cookie(session_secret))
                )
    if not catalog.get("ok"):
        return _response(start_response, "200 OK", _login_page(request["client_name"]), "text/html; charset=utf-8", _oauth_page_headers())
    if not any(item.get("workspaces") for item in catalog.get("items") or []):
        return _response(start_response, "403 Forbidden", _error_page("No workspace available", "This account has no active linked workspace to authorize."), "text/html; charset=utf-8", _sensitive_headers())
    authorization_id = uuid.uuid4().hex
    pending_secret = secrets.token_urlsafe(32)
    page, choices = _consent_page(
        request["client_name"],
        catalog,
        authorization_id,
        pending_secret,
        request["scopes"],
        host_local_session=host_local_session,
    )
    now = _now()
    with _LOCK:
        with _database() as connection:
            connection.execute(
                """
                INSERT INTO mcp_oauth_authorizations (
                  authorization_id, secret_hash, client_id, redirect_uri, state_value,
                  resource_url, scopes, code_challenge, human_account_id, choices_json,
                  created_at, expires_at, consumed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    authorization_id,
                    _secret_hash("authorization", authorization_id, pending_secret),
                    request["client_id"],
                    request["redirect_uri"],
                    request["state"],
                    request["resource"],
                    " ".join(request["scopes"]),
                    request["code_challenge"],
                    catalog["humanAccountId"],
                    json.dumps(choices, sort_keys=True),
                    now,
                    now + _AUTHORIZATION_TTL_SECONDS,
                ),
            )
    return _response(
        start_response,
        "200 OK",
        page,
        "text/html; charset=utf-8",
        _oauth_page_headers(response_headers),
    )


def _authorization_redirect(row, values):
    query = dict(values)
    query["state"] = row["state_value"]
    query["iss"] = _issuer_url()
    separator = "&" if "?" in row["redirect_uri"] else "?"
    return row["redirect_uri"] + separator + urlencode(query)


def _authorize_post(environ, start_response, store_factory):
    if not _oauth_browser_same_origin(environ):
        return _response(start_response, "403 Forbidden", _error_page("Request rejected", "The request origin is not trusted."), "text/html; charset=utf-8", _sensitive_headers())
    try:
        params = _read_form(environ)
        authorization_id = _one(params, "authorization_id")
        authorization_secret = _one(params, "authorization_secret")
        decision = _one(params, "decision")
        choice = _one(params, "choice", required=decision == "allow")
    except TypeError:
        return _oauth_error(start_response, "415 Unsupported Media Type", "invalid_request", "Form encoding is required.")
    except ValueError:
        return _oauth_error(start_response, "400 Bad Request", "invalid_request", "The approval form is invalid.")
    if not re.fullmatch(r"[0-9a-f]{32}", authorization_id):
        return _oauth_error(start_response, "400 Bad Request", "invalid_request", "The approval request is invalid.")
    session_secret = _cookie(environ, HUMAN_SESSION_COOKIE)
    store = store_factory()
    session = store.authenticate_human_account_session(session_secret) if session_secret else None
    now = _now()
    with _LOCK:
        with _database() as connection:
            row = connection.execute(
                "SELECT * FROM mcp_oauth_authorizations WHERE authorization_id = ?",
                (authorization_id,),
            ).fetchone()
            valid = bool(
                row
                and not row["consumed_at"]
                and row["expires_at"] >= now
                and session
                and session.get("humanAccountId") == row["human_account_id"]
                and hmac.compare_digest(
                    row["secret_hash"],
                    _secret_hash("authorization", authorization_id, authorization_secret),
                )
            )
            if not valid:
                return _oauth_error(start_response, "400 Bad Request", "invalid_request", "The approval request expired or is not valid for this session.")
            if decision == "deny":
                connection.execute(
                    "UPDATE mcp_oauth_authorizations SET consumed_at = ? WHERE authorization_id = ? AND consumed_at IS NULL",
                    (now, authorization_id),
                )
                return _redirect(start_response, _authorization_redirect(row, {"error": "access_denied"}))
            if decision != "allow":
                return _oauth_error(start_response, "400 Bad Request", "invalid_request", "Choose Allow or Cancel.")
            selected = (json.loads(row["choices_json"]) or {}).get(choice)
            if not selected:
                return _oauth_error(start_response, "400 Bad Request", "invalid_request", "Choose an authorized workspace.")
            principal = store.mcp_human_principal(
                row["human_account_id"], selected.get("companyId"), selected.get("workspaceId")
            )
            if not principal:
                return _oauth_error(start_response, "403 Forbidden", "access_denied", "The selected workspace is no longer available.")
            code, code_id, code_hash = _new_secret("mam_code_v1", "code")
            consumed = connection.execute(
                "UPDATE mcp_oauth_authorizations SET consumed_at = ? WHERE authorization_id = ? AND consumed_at IS NULL",
                (now, authorization_id),
            )
            if consumed.rowcount != 1:
                return _oauth_error(start_response, "400 Bad Request", "invalid_request", "The approval request was already used.")
            connection.execute(
                """
                INSERT INTO mcp_oauth_codes (
                  code_id, secret_hash, client_id, redirect_uri, resource_url, scopes,
                  code_challenge, human_account_id, company_id, workspace_id,
                  created_at, expires_at, consumed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    code_id, code_hash, row["client_id"], row["redirect_uri"], row["resource_url"],
                    row["scopes"], row["code_challenge"], row["human_account_id"],
                    selected["companyId"], selected["workspaceId"], now, now + _CODE_TTL_SECONDS,
                ),
            )
    return _redirect(start_response, _authorization_redirect(row, {"code": code}))


def _pkce_s256(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")


def _issue_tokens(connection, binding, now):
    access, access_id, access_hash = _new_secret("mam_at_v1", "access")
    refresh, refresh_id, refresh_hash = _new_secret("mam_rt_v1", "refresh")
    family_id = (
        binding["family_id"]
        if "family_id" in binding.keys() and binding["family_id"]
        else uuid.uuid4().hex
    )
    common = (
        family_id, binding["client_id"], binding["resource_url"], binding["scopes"],
        binding["human_account_id"], binding["company_id"], binding["workspace_id"], now,
    )
    connection.execute(
        "INSERT INTO mcp_oauth_access_tokens (token_id, secret_hash, family_id, client_id, resource_url, scopes, human_account_id, company_id, workspace_id, created_at, expires_at, revoked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
        (access_id, access_hash) + common + (now + _ACCESS_TTL_SECONDS,),
    )
    connection.execute(
        "INSERT INTO mcp_oauth_refresh_tokens (token_id, secret_hash, family_id, client_id, resource_url, scopes, human_account_id, company_id, workspace_id, created_at, expires_at, revoked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
        (refresh_id, refresh_hash) + common + (now + _REFRESH_TTL_SECONDS,),
    )
    return access, refresh


def _revoke_family(connection, family_id, now):
    connection.execute(
        "UPDATE mcp_oauth_access_tokens SET revoked_at = COALESCE(revoked_at, ?) WHERE family_id = ?",
        (now, family_id),
    )
    connection.execute(
        "UPDATE mcp_oauth_refresh_tokens SET revoked_at = COALESCE(revoked_at, ?) WHERE family_id = ?",
        (now, family_id),
    )


def _token(environ, start_response, store_factory):
    if environ.get("REQUEST_METHOD") != "POST":
        return _oauth_error(start_response, "405 Method Not Allowed", "invalid_request", "Use POST for token exchange.")
    if not _rate_allowed(environ, "mcp-token", 40):
        return _oauth_error(start_response, "429 Too Many Requests", "temporarily_unavailable", "Token rate limit reached.")
    if str(environ.get("HTTP_AUTHORIZATION") or "").strip():
        return _oauth_error(start_response, "401 Unauthorized", "invalid_client", "Public PKCE clients must not send client authentication.")
    try:
        params = _read_form(environ)
        grant_type = _one(params, "grant_type")
        client_id = _one(params, "client_id")
        resource = _one(params, "resource")
    except TypeError:
        return _oauth_error(start_response, "415 Unsupported Media Type", "invalid_request", "Form encoding is required.")
    except ValueError:
        return _oauth_error(start_response, "400 Bad Request", "invalid_request", "The token request is incomplete.")
    if not _accepted_resource_url(resource):
        return _oauth_error(start_response, "400 Bad Request", "invalid_target", "The resource does not match this MCP server.")
    now = _now()
    with _LOCK:
        with _database() as connection:
            if not _client(connection, client_id):
                return _oauth_error(start_response, "401 Unauthorized", "invalid_client", "The client is not registered.")
            if grant_type == "authorization_code":
                try:
                    code = _one(params, "code")
                    redirect_uri = _one(params, "redirect_uri")
                    verifier = _one(params, "code_verifier")
                except ValueError:
                    return _oauth_error(start_response, "400 Bad Request", "invalid_request", "Code, callback, and PKCE verifier are required.")
                code_id, code_secret = _parse_secret(code, "mam_code_v1")
                row = connection.execute("SELECT * FROM mcp_oauth_codes WHERE code_id = ?", (code_id,)).fetchone() if code_id else None
                valid = bool(
                    row and not row["consumed_at"] and row["expires_at"] >= now
                    and row["client_id"] == client_id and row["redirect_uri"] == redirect_uri
                    and row["resource_url"] == resource and _PKCE_VALUE.fullmatch(verifier)
                    and hmac.compare_digest(row["secret_hash"], _secret_hash("code", code_id, code_secret))
                    and hmac.compare_digest(row["code_challenge"], _pkce_s256(verifier))
                )
                if not valid:
                    return _oauth_error(start_response, "400 Bad Request", "invalid_grant", "The code is invalid, expired, used, or not bound to this request.")
                principal = store_factory().mcp_human_principal(row["human_account_id"], row["company_id"], row["workspace_id"])
                if not principal:
                    return _oauth_error(start_response, "400 Bad Request", "invalid_grant", "The approved human authority is no longer active.")
                consumed = connection.execute("UPDATE mcp_oauth_codes SET consumed_at = ? WHERE code_id = ? AND consumed_at IS NULL", (now, code_id))
                if consumed.rowcount != 1:
                    return _oauth_error(start_response, "400 Bad Request", "invalid_grant", "The code was already used.")
                access, refresh = _issue_tokens(connection, row, now)
                scopes = row["scopes"]
            elif grant_type == "refresh_token":
                try:
                    raw_refresh = _one(params, "refresh_token")
                except ValueError:
                    return _oauth_error(start_response, "400 Bad Request", "invalid_request", "A refresh token is required.")
                refresh_id, refresh_secret = _parse_secret(raw_refresh, "mam_rt_v1")
                row = connection.execute("SELECT * FROM mcp_oauth_refresh_tokens WHERE token_id = ?", (refresh_id,)).fetchone() if refresh_id else None
                matched = bool(
                    row and row["client_id"] == client_id and row["resource_url"] == resource
                    and hmac.compare_digest(row["secret_hash"], _secret_hash("refresh", refresh_id, refresh_secret))
                )
                if matched and row["revoked_at"]:
                    _revoke_family(connection, row["family_id"], now)
                    return _oauth_error(start_response, "400 Bad Request", "invalid_grant", "Refresh-token reuse revoked this connection.")
                valid = bool(matched and row["expires_at"] >= now)
                if not valid:
                    return _oauth_error(start_response, "400 Bad Request", "invalid_grant", "The refresh token is invalid, expired, or revoked.")
                principal = store_factory().mcp_human_principal(row["human_account_id"], row["company_id"], row["workspace_id"])
                if not principal:
                    return _oauth_error(start_response, "400 Bad Request", "invalid_grant", "The approved human authority is no longer active.")
                rotated = connection.execute("UPDATE mcp_oauth_refresh_tokens SET revoked_at = ? WHERE token_id = ? AND revoked_at IS NULL", (now, refresh_id))
                if rotated.rowcount != 1:
                    return _oauth_error(start_response, "400 Bad Request", "invalid_grant", "The refresh token was already used.")
                access, refresh = _issue_tokens(connection, row, now)
                scopes = row["scopes"]
            else:
                return _oauth_error(start_response, "400 Bad Request", "unsupported_grant_type", "Use authorization_code or refresh_token.")
    return _json_response(
        start_response,
        "200 OK",
        {"access_token": access, "token_type": "Bearer", "expires_in": _ACCESS_TTL_SECONDS, "refresh_token": refresh, "scope": scopes},
        headers=[("Cache-Control", "no-store"), ("Pragma", "no-cache")],
    )


def _revoke(environ, start_response):
    if environ.get("REQUEST_METHOD") != "POST":
        return _oauth_error(start_response, "405 Method Not Allowed", "invalid_request", "Use POST for token revocation.")
    if not _rate_allowed(environ, "mcp-revoke", 40):
        return _oauth_error(start_response, "429 Too Many Requests", "temporarily_unavailable", "Revocation rate limit reached.")
    if str(environ.get("HTTP_AUTHORIZATION") or "").strip():
        return _oauth_error(start_response, "401 Unauthorized", "invalid_client", "Public clients must not send client authentication.")
    try:
        params = _read_form(environ)
        token = _one(params, "token")
        client_id = _one(params, "client_id")
    except TypeError:
        return _oauth_error(start_response, "415 Unsupported Media Type", "invalid_request", "Form encoding is required.")
    except ValueError:
        return _oauth_error(start_response, "400 Bad Request", "invalid_request", "Token and client_id are required.")
    now = _now()
    with _LOCK:
        with _database() as connection:
            if not _client(connection, client_id):
                return _oauth_error(start_response, "401 Unauthorized", "invalid_client", "The client is not registered.")
            for prefix, kind, table in (
                ("mam_at_v1", "access", "mcp_oauth_access_tokens"),
                ("mam_rt_v1", "refresh", "mcp_oauth_refresh_tokens"),
            ):
                token_id, token_secret = _parse_secret(token, prefix)
                if not token_id:
                    continue
                row = connection.execute(
                    "SELECT * FROM %s WHERE token_id = ?" % table, (token_id,)
                ).fetchone()
                if (
                    row
                    and row["client_id"] == client_id
                    and hmac.compare_digest(
                        row["secret_hash"],
                        _secret_hash(kind, token_id, token_secret),
                    )
                ):
                    _revoke_family(connection, row["family_id"], now)
                break
    return _response(
        start_response,
        "200 OK",
        b"",
        headers=[("Cache-Control", "no-store"), ("Pragma", "no-cache")],
    )


def _challenge_value(scopes=MCP_SCOPES, error=None):
    challenge = 'Bearer resource_metadata="%s", scope="%s"' % (
        _metadata_url(),
        " ".join(scopes),
    )
    if error == "insufficient_scope":
        challenge += ', error="insufficient_scope", error_description="Additional tool permission is required"'
    return challenge


def _challenge_headers(scopes=MCP_SCOPES, error=None):
    challenge = _challenge_value(scopes, error)
    return [("WWW-Authenticate", challenge), ("Cache-Control", "no-store")]


def _bearer_principal(environ, store_factory):
    value = str(environ.get("HTTP_AUTHORIZATION") or "").strip()
    if not value.lower().startswith("bearer ") or " " not in value:
        return None
    raw = value.split(" ", 1)[1].strip()
    token_id, token_secret = _parse_secret(raw, "mam_at_v1")
    if not token_id:
        return None
    now = _now()
    with _LOCK:
        with _database() as connection:
            row = connection.execute("SELECT * FROM mcp_oauth_access_tokens WHERE token_id = ?", (token_id,)).fetchone()
    if not row or row["revoked_at"] or row["expires_at"] < now or not _accepted_resource_url(row["resource_url"]):
        return None
    if not hmac.compare_digest(row["secret_hash"], _secret_hash("access", token_id, token_secret)):
        return None
    core = store_factory().mcp_human_principal(row["human_account_id"], row["company_id"], row["workspace_id"])
    if not core:
        return None
    return dict(
        core,
        clientId=row["client_id"],
        accessTokenId=token_id,
        tokenFamilyId=row["family_id"],
        scopes=tuple(row["scopes"].split()),
        expiresAt=row["expires_at"],
    )


def _tool_security(scopes):
    return [{"type": "oauth2", "scopes": list(scopes)}]


def _tools():
    read_security = _tool_security(("memory:read",))
    write_security = _tool_security(("memory:write",))
    return [
        {
            "name": "memory_search",
            "title": "Search Multi-Agent Memory",
            "description": "Search public-safe memory in the human-approved workspace.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "maxLength": 500},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 25, "default": 10},
                    "scope": {"type": "string", "enum": ["company", "workspace", "project"]},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
            "securitySchemes": read_security,
            "_meta": {"securitySchemes": read_security},
        },
        {
            "name": "memory_remember",
            "title": "Remember a public-safe note",
            "description": "Submit a public-safe workspace memory through the normal firewall and review workflow.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "minLength": 1, "maxLength": 200},
                    "summary": {"type": "string", "minLength": 1, "maxLength": 2000},
                    "tags": {"type": "array", "maxItems": 12, "items": {"type": "string", "minLength": 1, "maxLength": 64}},
                    "memoryType": {"type": "string", "enum": ["note", "decision", "status", "preference", "instruction"]},
                },
                "required": ["title", "summary"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
            "securitySchemes": write_security,
            "_meta": {"securitySchemes": write_security},
        },
        {
            "name": "workspace_status",
            "title": "Approved workspace status",
            "description": "Show the company and workspace currently approved for this ChatGPT connection.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
            "securitySchemes": read_security,
            "_meta": {"securitySchemes": read_security},
        },
    ]


def _tool_result(value, error=False, auth_challenge=None):
    result = {
        "content": [{"type": "text", "text": json.dumps(value, sort_keys=True)}],
        "structuredContent": value,
        "isError": bool(error),
    }
    if auth_challenge:
        result["_meta"] = {"mcp/www_authenticate": auth_challenge}
    return result


def _mcp_mutation_key(principal, request_id):
    material = json.dumps(
        {
            "tokenFamilyId": principal["tokenFamilyId"],
            "clientId": principal["clientId"],
            "requestId": request_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "mcp-" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def _idempotency_tool_replay(claim):
    replay = dict(claim)
    replay.pop("_httpStatus", None)
    replay.pop("idempotencyKeyExposed", None)
    replay.pop("idempotentReplay", None)
    structured = replay.get("structuredContent")
    if isinstance(structured, dict):
        structured = dict(structured)
        structured["idempotentReplay"] = True
        replay["structuredContent"] = structured
        replay["content"] = [
            {"type": "text", "text": json.dumps(structured, sort_keys=True)}
        ]
    return replay


def _call_tool(store, principal, name, arguments, request_id):
    if not isinstance(arguments, dict):
        return _tool_result({"error": "invalid_arguments", "valuesRedacted": True}, True)
    if name == "workspace_status":
        if "memory:read" not in principal["scopes"]:
            return _tool_result(
                {"error": "memory_read_scope_required", "valuesRedacted": True},
                True,
                _challenge_value(("memory:read",), "insufficient_scope"),
            )
        if arguments:
            return _tool_result({"error": "invalid_arguments", "valuesRedacted": True}, True)
        return _tool_result(
            {
                "company": {"companyId": principal["companyId"], "label": principal.get("companyLabel")},
                "workspace": {"workspaceId": principal["workspaceId"], "label": principal.get("workspaceLabel"), "status": "active"},
                "signedInAs": principal.get("displayName") or principal.get("username"),
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            }
        )
    if name == "memory_search":
        if "memory:read" not in principal["scopes"]:
            return _tool_result(
                {"error": "memory_read_scope_required", "valuesRedacted": True},
                True,
                _challenge_value(("memory:read",), "insufficient_scope"),
            )
        allowed = {"query", "limit", "scope"}
        query = arguments.get("query")
        limit = arguments.get("limit", 10)
        scope = arguments.get("scope")
        if (
            set(arguments) - allowed or not isinstance(query, str) or not 1 <= len(query.strip()) <= 500
            or not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 25
            or (scope is not None and scope not in ("company", "workspace", "project"))
        ):
            return _tool_result({"error": "invalid_arguments", "valuesRedacted": True}, True)
        filters = {"scope": scope} if scope else {}
        found = store.search_memory(principal["workspaceId"], query.strip(), filters)
        items = found.get("items", []) if isinstance(found, dict) else found
        safe_items = list(items or [])[:limit]
        return _tool_result({"items": safe_items, "count": len(safe_items), "valuesRedacted": True, "rawPayloadExposed": False})
    if name == "memory_remember":
        if "memory:write" not in principal["scopes"]:
            return _tool_result(
                {"error": "memory_write_scope_required", "valuesRedacted": True},
                True,
                _challenge_value(("memory:write",), "insufficient_scope"),
            )
        allowed = {"title", "summary", "tags", "memoryType"}
        title = arguments.get("title")
        summary = arguments.get("summary")
        tags = arguments.get("tags", [])
        memory_type = arguments.get("memoryType", "note")
        if (
            set(arguments) - allowed or not isinstance(title, str) or not 1 <= len(title.strip()) <= 200
            or not isinstance(summary, str) or not 1 <= len(summary.strip()) <= 2000
            or not isinstance(tags, list) or len(tags) > 12
            or any(not isinstance(tag, str) or not 1 <= len(tag.strip()) <= 64 for tag in tags)
            or memory_type not in ("note", "decision", "status", "preference", "instruction")
        ):
            return _tool_result({"error": "invalid_arguments", "valuesRedacted": True}, True)
        normalized = {
            "title": title.strip(),
            "summary": summary.strip(),
            "tags": [tag.strip() for tag in tags],
            "memoryType": memory_type,
        }
        workspace_id = principal["workspaceId"]
        operation = "mcp-public-safe-memory-submit"
        idempotency_key = _mcp_mutation_key(principal, request_id)
        claim = store.claim_idempotency(
            workspace_id, idempotency_key, operation, normalized
        )
        if not claim or not claim.pop("_idempotencyClaimed", False):
            if claim and claim.get("status") not in (
                "idempotency_conflict",
                "idempotency_in_progress",
            ):
                return _idempotency_tool_replay(claim)
            return _tool_result(
                {
                    "error": (claim or {}).get("status") or "idempotency_unavailable",
                    "valuesRedacted": True,
                },
                True,
            )
        claim_id = claim.get("_claimId")
        quota_payload = {
            "title": normalized["title"],
            "summary": normalized["summary"],
            "tags": normalized["tags"],
        }
        if not store.has_quota_for(workspace_id, quota_payload):
            store.release_idempotency_claim(
                workspace_id, idempotency_key, operation, claim_id
            )
            return _tool_result(
                {"error": "workspace_storage_quota_reached", "valuesRedacted": True},
                True,
            )
        actor = "mcp-human-" + hashlib.sha256(principal["humanAccountId"].encode("utf-8")).hexdigest()[:20]
        try:
            event = store.submit_memory(
                workspace_id, actor, "workspace", normalized["title"],
                normalized["summary"], normalized["tags"], "mcp://chatgpt",
                memory_type, subject=normalized["title"], confidence=0.75,
                scope_id=workspace_id,
            )
        except Exception:
            store.release_idempotency_claim(
                workspace_id, idempotency_key, operation, claim_id
            )
            raise
        readback = store.search_memory(
            workspace_id,
            "",
            {"eventId": event.get("eventId"), "_includeReviewStatuses": True},
        )
        if not any(
            item.get("eventId") == event.get("eventId") for item in (readback or [])
        ):
            return _tool_result(
                {
                    "error": "mutation_readback_uncertain",
                    "retryWouldDuplicate": False,
                    "valuesRedacted": True,
                },
                True,
            )
        result = _tool_result(
            {
                "eventId": event.get("eventId"), "reviewId": event.get("reviewId"),
                "status": event.get("status"), "reviewStatus": event.get("reviewStatus"),
                "firewallDecision": (event.get("firewall") or {}).get("decision"),
                "idempotentReplay": False, "readbackVerified": True,
                "valuesRedacted": True, "rawPayloadExposed": False,
            }
        )
        if not store.record_idempotency(
            workspace_id,
            idempotency_key,
            operation,
            normalized,
            result,
            "200 OK",
            claim_id=claim_id,
        ):
            return _tool_result(
                {
                    "error": "idempotency_finalization_uncertain",
                    "retryWouldDuplicate": False,
                    "valuesRedacted": True,
                },
                True,
            )
        return result
    return None


def _mcp(environ, start_response, store_factory):
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    if not _origin_allowed(environ):
        return _json_response(start_response, "403 Forbidden", _mcp_error(None, -32000, "Request origin rejected."))
    if method == "OPTIONS":
        return _response(start_response, "204 No Content", b"", headers=[("Allow", "POST, OPTIONS")])
    if method != "POST":
        return _response(start_response, "405 Method Not Allowed", b"", headers=[("Allow", "POST")])
    principal = _bearer_principal(environ, store_factory)
    if not principal:
        return _json_response(
            start_response, "401 Unauthorized",
            _mcp_error(None, -32001, "OAuth authorization is required.", {"_meta": {"mcp/www_authenticate": _challenge_headers()[0][1]}}),
            headers=_challenge_headers(),
        )
    if not _rate_allowed(environ, "mcp-jsonrpc", 240):
        return _json_response(start_response, "429 Too Many Requests", _mcp_error(None, -32002, "MCP rate limit reached."), headers=[("Retry-After", "60")])
    protocol_header = str(environ.get("HTTP_MCP_PROTOCOL_VERSION") or "").strip()
    if protocol_header and protocol_header not in MCP_SUPPORTED_PROTOCOL_VERSIONS:
        return _json_response(start_response, "400 Bad Request", _mcp_error(None, -32600, "Unsupported MCP protocol version."))
    try:
        request = _read_json(environ)
    except TypeError:
        return _json_response(start_response, "415 Unsupported Media Type", _mcp_error(None, -32600, "application/json is required."))
    except ValueError:
        return _json_response(start_response, "400 Bad Request", _mcp_error(None, -32700, "Invalid JSON request."))
    request_id = request.get("id")
    if request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
        return _json_response(start_response, "400 Bad Request", _mcp_error(request_id, -32600, "Invalid JSON-RPC request."))
    method_name = request["method"]
    params = request.get("params", {})
    if not isinstance(params, dict):
        return _json_response(start_response, "200 OK", _mcp_error(request_id, -32602, "MCP parameters must be an object."))
    if method_name.startswith("notifications/"):
        return _response(start_response, "202 Accepted", b"", headers=[("Cache-Control", "no-store")])
    if "id" not in request or request_id is None:
        return _response(start_response, "202 Accepted", b"", headers=[("Cache-Control", "no-store")])
    if (
        isinstance(request_id, bool)
        or not isinstance(request_id, (str, int, float))
        or (isinstance(request_id, float) and not math.isfinite(request_id))
    ):
        return _json_response(start_response, "400 Bad Request", _mcp_error(None, -32600, "JSON-RPC request id is invalid."))
    if method_name == "initialize":
        requested = params.get("protocolVersion")
        client_info = params.get("clientInfo")
        capabilities = params.get("capabilities")
        if (
            set(params) != {"protocolVersion", "capabilities", "clientInfo"}
            or not isinstance(requested, str)
            or not isinstance(capabilities, dict)
            or not isinstance(client_info, dict)
            or set(client_info) - {"name", "version", "title", "description", "websiteUrl", "icons"}
            or not isinstance(client_info.get("name"), str)
            or not client_info.get("name").strip()
            or not isinstance(client_info.get("version"), str)
            or not client_info.get("version").strip()
        ):
            return _json_response(start_response, "200 OK", _mcp_error(request_id, -32602, "Initialize parameters are incomplete or invalid."))
        version = requested if requested in MCP_SUPPORTED_PROTOCOL_VERSIONS else MCP_PROTOCOL_VERSION
        result = {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "multi-agent-memory", "title": SITE_NAME, "version": "1"},
            "instructions": "Use the approved workspace only. Submit only public-safe memory; writes enter the normal firewall and review workflow.",
        }
    elif method_name == "ping":
        if params:
            return _json_response(start_response, "200 OK", _mcp_error(request_id, -32602, "Ping does not accept parameters."))
        result = {}
    elif method_name == "tools/list":
        if set(params) - {"cursor"} or (
            "cursor" in params
            and params["cursor"] is not None
            and not isinstance(params["cursor"], str)
        ):
            return _json_response(start_response, "200 OK", _mcp_error(request_id, -32602, "Tool list parameters are invalid."))
        if params.get("cursor"):
            return _json_response(start_response, "200 OK", _mcp_error(request_id, -32602, "This tool list has no continuation cursor."))
        result = {"tools": _tools()}
    elif method_name == "tools/call":
        if set(params) - {"name", "arguments", "_meta"} or not isinstance(params.get("name"), str):
            return _json_response(start_response, "200 OK", _mcp_error(request_id, -32602, "Tool name and arguments are required."))
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            return _json_response(start_response, "200 OK", _mcp_error(request_id, -32602, "Tool arguments must be an object."))
        result = _call_tool(store_factory(), principal, params["name"], arguments, request_id)
        if result is None:
            return _json_response(start_response, "200 OK", _mcp_error(request_id, -32601, "Unknown tool."))
    else:
        return _json_response(start_response, "200 OK", _mcp_error(request_id, -32601, "Method not found."))
    return _json_response(
        start_response,
        "200 OK",
        {"jsonrpc": "2.0", "id": request_id, "result": result},
        headers=[
            ("Cache-Control", "no-store"),
            ("MCP-Protocol-Version", result.get("protocolVersion", protocol_header or MCP_PROTOCOL_VERSION) if isinstance(result, dict) else MCP_PROTOCOL_VERSION),
        ],
    )


def _private_host(url):
    hostname = urlsplit(url).hostname or ""
    if hostname.lower() in ("localhost", "localhost.localdomain"):
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return bool(address.is_private or address.is_loopback or address.is_link_local)


def _setup_status():
    resource = _resource_url()
    issuer = _issuer_url()
    transport_public = not _private_host(resource) and urlsplit(resource).scheme == "https"
    issuer_public = not _private_host(issuer) and urlsplit(issuer).scheme == "https"
    return {
        "ok": True,
        "mcpTransport": resource,
        "oauthIssuer": issuer,
        "protectedResourceMetadata": _metadata_url(),
        "authorizationServerMetadata": issuer + "/.well-known/oauth-authorization-server",
        "streamableHttp": True,
        "oauth21PkceS256": True,
        "dynamicClientRegistration": True,
        "humanLoginAndConsent": True,
        "hostLocalWindowsOperatorAutoSignIn": _host_local_operator_auto_sign_in_enabled(),
        "hostLocalAutoSignInBoundary": "direct_same_host_socket_only",
        "remoteHumanPasswordRequired": True,
        "externalHttpsConfigurationPresent": transport_public and issuer_public,
        "externalReachabilityVerified": False,
        "mcpTransportPublicHttps": transport_public,
        "oauthIssuerPublicHttps": issuer_public,
        "oauthIssuerReachabilityRequired": True,
        "openAiTunnelResourceBindingConfigured": bool(
            _configured_openai_tunnel_id()
        ),
        "openAiTunnelResourceBindingExact": True,
        "requiresSecureMcpTunnelOrPublicHttps": _private_host(resource),
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


def _setup_page():
    status = _setup_status()
    readiness = (
        "Public HTTPS-shaped MCP and OAuth URLs are configured, but external reachability still needs end-to-end verification."
        if status["externalHttpsConfigurationPresent"]
        else "The MCP server is ready on this network, but ChatGPT still needs OpenAI Secure MCP Tunnel or another public HTTPS route."
    )
    main = """
<h1>Connect ChatGPT to Multi-Agent Memory</h1>
<p>%s</p>
<ol><li>On this host, run <code>powershell -ExecutionPolicy Bypass -File scripts/setup_chatgpt_mcp.ps1 -Status</code>.</li>
<li>If the status says an external route is needed, create an OpenAI Secure MCP Tunnel and run the command shown by the script.</li>
<li>In ChatGPT developer mode, add the MCP URL shown below. On this Windows host, a matching existing human account signs in automatically; other computers require a password. You still approve one workspace.</li></ol>
<dl><dt>MCP URL</dt><dd><code>%s</code></dd><dt>OAuth issuer</dt><dd><code>%s</code></dd></dl>
<p>Connection is proven only after <code>initialize</code>, <code>tools/list</code>, and <code>workspace_status</code> succeed.</p>
""" % (html.escape(readiness), html.escape(status["mcpTransport"]), html.escape(status["oauthIssuer"]))
    return _page("Connect ChatGPT", main)


def route_mcp(environ, start_response, path, store_factory):
    """Route MCP/OAuth paths; return ``None`` for all unrelated paths."""
    if path in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"):
        if environ.get("REQUEST_METHOD") != "GET":
            return _response(start_response, "405 Method Not Allowed", b"", headers=[("Allow", "GET")])
        return _json_response(start_response, "200 OK", _protected_resource_metadata(), headers=[("Cache-Control", "public, max-age=300")])
    if path == "/.well-known/oauth-authorization-server":
        if environ.get("REQUEST_METHOD") != "GET":
            return _response(start_response, "405 Method Not Allowed", b"", headers=[("Allow", "GET")])
        return _json_response(start_response, "200 OK", _authorization_server_metadata(), headers=[("Cache-Control", "public, max-age=300")])
    if path == "/oauth/register":
        return _register(environ, start_response)
    if path == "/oauth/session":
        return _oauth_session(environ, start_response, store_factory)
    if path == "/oauth/authorize":
        if environ.get("REQUEST_METHOD") == "GET":
            return _authorize_get(environ, start_response, store_factory)
        if environ.get("REQUEST_METHOD") == "POST":
            return _authorize_post(environ, start_response, store_factory)
        return _response(start_response, "405 Method Not Allowed", b"", headers=[("Allow", "GET, POST")])
    if path == "/oauth/token":
        return _token(environ, start_response, store_factory)
    if path == "/oauth/revoke":
        return _revoke(environ, start_response)
    if path == "/mcp":
        return _mcp(environ, start_response, store_factory)
    if path == "/mcp/setup":
        if environ.get("REQUEST_METHOD") != "GET":
            return _response(start_response, "405 Method Not Allowed", b"", headers=[("Allow", "GET")])
        return _response(start_response, "200 OK", _setup_page(), "text/html; charset=utf-8", _sensitive_headers())
    if path == "/mcp/setup/status":
        if environ.get("REQUEST_METHOD") != "GET":
            return _response(start_response, "405 Method Not Allowed", b"", headers=[("Allow", "GET")])
        return _json_response(start_response, "200 OK", _setup_status(), headers=[("Cache-Control", "no-store")])
    return None
