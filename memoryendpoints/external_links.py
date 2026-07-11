import hashlib
import ipaddress
import re
from urllib.parse import parse_qsl, quote, unquote, urlsplit, urlunsplit


ALLOWED_RELATIONSHIP_TYPES = {
    "citation",
    "evidence",
    "further_reading",
    "reference",
    "related",
    "source",
}

SENSITIVE_QUERY_KEY_PARTS = ("api_key", "apikey", "auth", "credential", "password", "secret", "signature", "token")


class ExternalLinkValidationError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _public_host(hostname):
    host = str(hostname or "").strip().rstrip(".").lower()
    if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "." in host
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def normalize_external_url(value):
    raw = str(value or "").strip()
    if not raw:
        raise ExternalLinkValidationError("external_url_required", "External link URL is required.")
    if len(raw) > 4096 or any(ord(character) < 32 for character in raw):
        raise ExternalLinkValidationError("external_url_invalid", "External link URL is invalid.")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise ExternalLinkValidationError("external_url_invalid", "External link URL is invalid.") from exc
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise ExternalLinkValidationError("external_url_scheme_unsupported", "External links must use HTTP or HTTPS.")
    if parsed.username is not None or parsed.password is not None:
        raise ExternalLinkValidationError("external_url_credentials_forbidden", "External link URLs cannot contain credentials.")
    for key, _value in parse_qsl(parsed.query, keep_blank_values=True):
        normalized_key = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
        if any(part in normalized_key for part in SENSITIVE_QUERY_KEY_PARTS):
            raise ExternalLinkValidationError("external_url_credentials_forbidden", "External link URLs cannot contain credential-like query parameters.")
    hostname = parsed.hostname or ""
    try:
        ascii_host = hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ExternalLinkValidationError("external_url_host_invalid", "External link host is invalid.") from exc
    if not _public_host(ascii_host):
        raise ExternalLinkValidationError("external_url_not_public", "External links must target a public internet host.")
    if port is not None and not (1 <= int(port) <= 65535):
        raise ExternalLinkValidationError("external_url_port_invalid", "External link port is invalid.")
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    display_host = "[%s]" % ascii_host if ":" in ascii_host else ascii_host
    netloc = display_host if port is None or default_port else "%s:%s" % (display_host, port)
    path = quote(unquote(parsed.path or "/"), safe="/%:@-._~!$&'()*+,;=")
    query = parsed.query
    fragment = parsed.fragment
    normalized_url = urlunsplit((scheme, netloc, path, query, fragment))
    page_url = urlunsplit((scheme, netloc, path, query, ""))
    return {
        "url": normalized_url,
        "normalizedUrl": normalized_url,
        "normalizedUrlHash": hashlib.sha256(normalized_url.encode("utf-8")).hexdigest(),
        "pageUrl": page_url,
        "fragment": fragment,
        "scheme": scheme,
        "host": ascii_host,
    }


def normalize_relationship_type(value):
    relationship = re.sub(r"[^a-z0-9]+", "_", str(value or "reference").strip().lower()).strip("_")
    if relationship not in ALLOWED_RELATIONSHIP_TYPES:
        raise ExternalLinkValidationError(
            "external_link_relationship_unsupported",
            "External link relationship type is unsupported.",
        )
    return relationship


def stable_external_link_id(workspace_id, normalized_url):
    value = "%s\n%s" % (workspace_id, normalized_url)
    return "link-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def stable_external_link_mention_id(workspace_id, external_link_id, document_id, relationship_type, citation_label, anchor_text):
    value = "\n".join(
        [workspace_id, external_link_id, document_id or "", relationship_type, citation_label or "", anchor_text or ""]
    )
    return "linkmention-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
