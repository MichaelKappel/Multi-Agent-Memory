import copy
import re


SECRET_PATTERNS = [
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |)?PRIVATE KEY-----", re.I)),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.I)),
    ("jwt", re.compile(r"\b[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b")),
    ("credential_assignment", re.compile(r"\b(password|passwd|pwd|secret|api[_ -]?key|token)\b\s*[:=]\s*([^\s,;\"']{8,})", re.I)),
    (
        "governed_credential",
        re.compile(r"\bme_(?:master|agent|invite|human|closure|hsession|csrf|accountsession|accountcsrf|masterproof|connector|paircode)(?:_v1)?\.[A-Za-z0-9_-]{3,160}\.[A-Za-z0-9_-]{20,}\b", re.I),
    ),
    (
        "invite_fragment",
        re.compile(r"#(?:invite|secret|code)=[A-Za-z0-9._~-]{12,}", re.I),
    ),
    ("inline_dsn", re.compile(r"\b(mysql|mariadb|postgres|ftp|ftps)://[^:\s]+:[^@\s]+@", re.I)),
]

PROMPT_INJECTION_MARKERS = [
    "ignore previous",
    "system override",
    "developer message",
    "exfiltrate",
    "send secrets",
    "bypass safety",
    "overwrite memory",
    "poison memory",
    "replace trusted fact",
]

BLOCKED_OBJECT_KEYS = {"__proto__", "prototype", "constructor"}
SENSITIVE_KEY_PARTS = ("password", "passwd", "secret", "apikey", "bearer", "credentialsecret", "privatekey")
SENSITIVE_KEY_NAMES = {
    "authorization",
    "companymastertoken",
    "companymastertokensecret",
    "mastertoken",
    "mastertokensecret",
    "agenttoken",
    "agenttokensecret",
    "invitetoken",
    "invitesecret",
    "invitecode",
    "redemptioncode",
    "humanownerrecoverysecret",
    "closureintentsecret",
    "csrftoken",
    "sessionsecret",
    "companymasterproofsecret",
    "connectorcredentialsecret",
    "authorizationcode",
    "credentialverifier",
    "secrethash",
    "tokenhash",
}
GOVERNED_BEARER_PATTERN = re.compile(
    r"^me_(?:master|agent|connector)_v1\.[A-Za-z0-9_-]{3,160}\.[A-Za-z0-9_-]{32,128}$"
)


def governed_bearer_token(authorization_header):
    """Return one strict governed bearer credential or an empty value."""
    value = str(authorization_header or "").strip()
    if not value:
        return ""
    parts = value.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return ""
    token = parts[1]
    return token if GOVERNED_BEARER_PATTERN.fullmatch(token) else ""


def _finding(rule, severity, reason):
    return {"rule": rule, "severity": severity, "reason": reason}


def _redact_match(match):
    if match.lastindex and match.lastindex >= 2:
        return "%s: [REDACTED_SECRET]" % match.group(1)
    if match.lastindex and match.lastindex >= 1 and "://" in match.group(0):
        return "%s://[REDACTED_CREDENTIALS]@" % match.group(1)
    return "[REDACTED_SECRET]"


def redact_text(value):
    text = str(value)
    for _name, pattern in SECRET_PATTERNS:
        text = pattern.sub(_redact_match, text)
    text = re.sub(r"<\s*script.*?>.*?<\s*/\s*script\s*>", "[REDACTED_SCRIPT]", text, flags=re.I | re.S)
    text = re.sub(r"javascript\s*:", "blocked-script:", text, flags=re.I)
    return text.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")


def _key_is_sensitive(key):
    compact = re.sub(r"[^a-z0-9]", "", str(key).lower())
    if not compact:
        return False
    if compact in SENSITIVE_KEY_NAMES:
        return True
    if compact.endswith("secret") or compact.endswith("password"):
        return True
    return any(part in compact for part in SENSITIVE_KEY_PARTS)


def redact_payload(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if key in BLOCKED_OBJECT_KEYS:
                continue
            if _key_is_sensitive(key):
                redacted[key] = "[REDACTED_SECRET]"
            else:
                redacted[key] = redact_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def _all_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(str(key) + " " + _all_text(item) for key, item in value.items())
    if isinstance(value, list):
        return " ".join(_all_text(item) for item in value)
    return str(value)


def evaluate_memory_firewall(payload):
    original = copy.deepcopy(payload or {})
    sanitized = redact_payload(original)
    original_text = _all_text(original)
    lowered = original_text.lower()
    findings = []

    for name, pattern in SECRET_PATTERNS:
        if pattern.search(original_text):
            findings.append(_finding(name, 22 if name != "private_key" else 45, "Secret-like material was redacted before persistence."))

    if "<script" in lowered or "javascript:" in lowered:
        findings.append(_finding("script_marker", 24, "Script-like content was neutralized before persistence."))

    for key in BLOCKED_OBJECT_KEYS:
        if key in lowered:
            findings.append(_finding("prototype_pollution_marker", 24, "Prototype-pollution key was removed before persistence."))

    for marker in PROMPT_INJECTION_MARKERS:
        if marker in lowered:
            findings.append(_finding("prompt_injection_marker", 28, "Prompt-injection or memory-poisoning marker requires review."))
            break

    risk_score = min(100, sum(item["severity"] for item in findings))
    if risk_score >= 60:
        decision = "quarantine_for_review"
    elif findings:
        decision = "review_required"
    else:
        decision = "accepted"

    return {
        "schemaVersion": "memoryendpoints.memory_firewall.v1",
        "passed": decision == "accepted",
        "decision": decision,
        "riskScore": risk_score,
        "findings": findings,
        "detectedThreats": sorted({item["rule"] for item in findings}),
        "valuesRedacted": sanitized != original or bool(findings),
        "rawPrivatePayloadStored": False,
        "sanitizedPayload": sanitized,
    }
