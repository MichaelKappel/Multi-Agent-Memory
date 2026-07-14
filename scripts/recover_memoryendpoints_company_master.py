#!/usr/bin/env python3
"""Recover a company master by safely delegating a persisted successor.

The helper never prints a credential or identifier.  It writes a candidate to
the governed pending path before the network mutation, retries that exact
candidate after an unknown outcome, and promotes it only after `/api/matm/me`
proves that the candidate is an active company-master credential.
"""

import argparse
import hashlib
import ipaddress
import json
import os
import re
import secrets
import sys
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


PROJECT_SECRET_PATH = Path(".local-secrets/memoryendpoints-company-master.json")
PENDING_SECRET_NAME = "memoryendpoints-company-master.pending.json"
CREDENTIAL_FILE_SCHEMA = "memoryendpoints.company_master_credential_file.v1"
DELEGATION_SCHEMA = "memoryendpoints.company_master_delegation.v1"
TOP_LEVEL_AGENT_SCHEMA = "memoryendpoints.top_level_agent_company_master.v1"
DEFAULT_BASE_URL = "https://memoryendpoints.com"
DEFAULT_LABEL = "Human recovery master"
DEFAULT_PRINCIPAL_NAME = "human-recovery"
SOURCE_TOKEN_ENVIRONMENT = "MEMORYENDPOINTS_COMPANY_MASTER_TOKEN"
AGENT_TOKEN_ENVIRONMENT = "MEMORYENDPOINTS_AGENT_TOKEN"
WORKSPACE_ID_ENVIRONMENT = "MEMORYENDPOINTS_WORKSPACE_ID"
BASE_URL_ENVIRONMENT = "MEMORYENDPOINTS_BASE_URL"
ME_ROUTE = "/api/matm/me"
DELEGATION_ROUTE = "/api/matm/access/company-master-credentials"

_CANDIDATE_PATTERN = re.compile(
    r"^me_master_v1\.(masterkey-[a-f0-9]{20})\.[A-Za-z0-9_-]{43}$"
)
_GOVERNED_BEARER_PATTERN = re.compile(
    r"^me_(?:master|agent|connector)_v1\.[A-Za-z0-9_-]{3,160}\.[A-Za-z0-9_-]{32,128}$"
)


class RecoveryError(RuntimeError):
    """A public-safe recovery error that never contains private values."""


class _RequestOutcomeUnknown(RuntimeError):
    """Internal marker for a request whose result cannot be established."""


def _validate_base_url(value):
    base_url = str(value or "").strip().rstrip("/")
    parsed = urlparse(base_url)
    hostname = (parsed.hostname or "").lower()
    loopback = hostname == "localhost"
    if hostname and not loopback:
        try:
            loopback = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            loopback = False
    if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
        raise RecoveryError("Base URL must use HTTPS; loopback HTTP is allowed only for local testing.")
    if (
        not hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise RecoveryError("Base URL must be a credential-free origin.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise RecoveryError("Base URL must contain a valid port.") from exc
    default_port = 443 if parsed.scheme == "https" else 80
    host_for_url = "[%s]" % hostname if ":" in hostname else hostname
    authority = host_for_url if not port or port == default_port else "%s:%s" % (host_for_url, port)
    return "%s://%s" % (parsed.scheme, authority)


def _private_document(base_url, company_id, workspace_id, token):
    return {
        "schemaVersion": CREDENTIAL_FILE_SCHEMA,
        "baseUrl": base_url,
        "companyId": company_id,
        "workspaceId": workspace_id,
        "companyMasterTokenSecret": token,
    }


def _read_private_document(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryError("Credential file is unavailable or invalid.") from exc
    if not isinstance(payload, dict) or payload.get("schemaVersion") != CREDENTIAL_FILE_SCHEMA:
        raise RecoveryError("Credential file schema is invalid.")
    required = ("baseUrl", "companyId", "workspaceId", "companyMasterTokenSecret")
    if any(not isinstance(payload.get(name), str) or not payload.get(name).strip() for name in required):
        raise RecoveryError("Credential file is incomplete.")
    token = payload["companyMasterTokenSecret"].strip()
    if not _GOVERNED_BEARER_PATTERN.fullmatch(token):
        raise RecoveryError("Credential file does not contain a governed bearer credential.")
    return _private_document(
        _validate_base_url(payload["baseUrl"]),
        payload["companyId"].strip(),
        payload["workspaceId"].strip(),
        token,
    )


def _stage_private_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".memoryendpoints-master-", dir=str(path.parent))
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(handle, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        return Path(temporary)
    except Exception:
        try:
            os.close(handle)
        except OSError:
            pass
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _write_pending(path, payload):
    if path.exists():
        raise RecoveryError("A pending recovery already exists.")
    staged = None
    try:
        staged = _stage_private_json(path, payload)
        if path.exists():
            raise RecoveryError("A pending recovery already exists.")
        os.replace(str(staged), str(path))
        staged = None
        try:
            os.chmod(str(path), 0o600)
        except OSError:
            pass
    finally:
        if staged:
            try:
                staged.unlink()
            except OSError:
                pass


def _promote_pending(pending_path, target_path):
    if target_path.exists():
        raise RecoveryError("The final company-master credential file already exists.")
    os.replace(str(pending_path), str(target_path))
    try:
        os.chmod(str(target_path), 0o600)
    except OSError:
        pass


def _read_json_response(response):
    try:
        raw = response.read()
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
        raise _RequestOutcomeUnknown("response_unreadable") from exc
    return payload if isinstance(payload, dict) else {}


def _request_json(
    base_url,
    path,
    token,
    method="GET",
    body=None,
    idempotency_key=None,
    open_url=urlopen,
):
    headers = {"Accept": "application/json", "Authorization": "Bearer " + token}
    data = None
    if body is not None:
        data = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    request = Request(base_url + path, data=data, headers=headers, method=method)
    try:
        with open_url(request, timeout=30) as response:
            return int(getattr(response, "status", 200)), _read_json_response(response)
    except HTTPError as exc:
        try:
            return int(exc.code), _read_json_response(exc)
        except _RequestOutcomeUnknown:
            return int(exc.code), {}
    except (URLError, TimeoutError, OSError) as exc:
        raise _RequestOutcomeUnknown("transport_unavailable") from exc


def _inspect_principal(base_url, token, open_url):
    try:
        status, payload = _request_json(base_url, ME_ROUTE, token, open_url=open_url)
    except _RequestOutcomeUnknown as exc:
        raise RecoveryError("Credential validation could not be confirmed.") from exc
    if status == 401:
        return "invalid", None
    if status < 200 or status >= 300 or not payload.get("ok"):
        raise RecoveryError("Credential validation could not be confirmed.")
    principal = payload.get("principal")
    if not isinstance(principal, dict):
        raise RecoveryError("Credential validation returned an invalid principal.")
    credential_type = str(principal.get("credentialType") or "").strip()
    if credential_type not in ("company_master", "agent", "agent_token"):
        return "unsupported", principal
    company_id = principal.get("companyId")
    if not isinstance(company_id, str) or not company_id.strip():
        raise RecoveryError("Company-master validation omitted its company boundary.")
    return "valid", principal


def _inspect_company_master(base_url, token, open_url):
    state, principal = _inspect_principal(base_url, token, open_url)
    if state == "valid" and principal.get("credentialType") != "company_master":
        return "unsupported", principal
    return state, principal


def _source_mode(principal):
    credential_type = str(principal.get("credentialType") or "").strip()
    if credential_type == "company_master":
        return "company_master"
    if credential_type in ("agent", "agent_token"):
        grant = principal.get("grant") if isinstance(principal.get("grant"), dict) else {}
        scope_type = principal.get("scopeType") or grant.get("scopeType")
        scope_id = principal.get("scopeId") or grant.get("scopeId")
        company_id = principal.get("companyId")
        if scope_type == "company" and scope_id == company_id:
            return "top_level_agent"
    raise RecoveryError(
        "The source credential must be an active company master or company-scoped top-level agent."
    )


def _principal_workspace_id(principal):
    resource_context = principal.get("resourceContext") if isinstance(principal, dict) else None
    candidates = (
        principal.get("workspaceId") if isinstance(principal, dict) else None,
        resource_context.get("workspaceId") if isinstance(resource_context, dict) else None,
    )
    return next((str(item).strip() for item in candidates if isinstance(item, str) and item.strip()), None)


def _candidate_id(token):
    match = _CANDIDATE_PATTERN.fullmatch(str(token or ""))
    if not match:
        raise RecoveryError("Pending candidate credential format is invalid.")
    return match.group(1)


def _candidate_idempotency_key(token, schema_version=DELEGATION_SCHEMA):
    candidate_id = _candidate_id(token)
    digest = hashlib.sha256(
        (schema_version + "|" + candidate_id).encode("ascii")
    ).hexdigest()
    return "company-master-delegation-v1-" + digest[:40]


def _generate_candidate():
    return "me_master_v1.masterkey-%s.%s" % (secrets.token_hex(10), secrets.token_urlsafe(32))


def _success(status):
    return {
        "ok": True,
        "status": status,
        "credentialsPersisted": True,
        "credentialValuesPrinted": False,
        "identifiersPrinted": False,
        "valuesRedacted": True,
    }


def _document_base_url(document, requested_base_url):
    document_base = _validate_base_url(document["baseUrl"])
    if requested_base_url is None:
        return document_base
    requested = _validate_base_url(requested_base_url)
    if requested != document_base:
        raise RecoveryError("Configured base URL does not match the credential file origin.")
    return requested


def _validate_document_principal(document, principal):
    company_id = str(principal.get("companyId") or "").strip()
    if company_id != document["companyId"]:
        raise RecoveryError("Credential company boundary does not match its credential file.")


def recover_company_master(
    project_root=".",
    source_credential_file=None,
    base_url=None,
    workspace_id=None,
    environ=None,
    open_url=urlopen,
):
    """Validate, reconcile, or recover the standard project company master."""

    environment = os.environ if environ is None else environ
    project_root = Path(project_root).expanduser().resolve()
    target_path = project_root / PROJECT_SECRET_PATH
    pending_path = target_path.parent / PENDING_SECRET_NAME

    if target_path.exists():
        final_document = _read_private_document(target_path)
        final_base_url = _document_base_url(final_document, base_url)
        state, principal = _inspect_company_master(
            final_base_url, final_document["companyMasterTokenSecret"], open_url
        )
        if state != "valid":
            raise RecoveryError("The final company-master credential is not valid.")
        _validate_document_principal(final_document, principal)
        return _success("already_valid")

    pending_document = None
    if pending_path.exists():
        pending_document = _read_private_document(pending_path)
        _candidate_id(pending_document["companyMasterTokenSecret"])
        pending_base_url = _document_base_url(pending_document, base_url)
        state, principal = _inspect_company_master(
            pending_base_url, pending_document["companyMasterTokenSecret"], open_url
        )
        if state == "valid":
            _validate_document_principal(pending_document, principal)
            _promote_pending(pending_path, target_path)
            return _success("pending_promoted")
        if state != "invalid":
            raise RecoveryError("The pending credential is not a company-master candidate.")

    source_document = None
    if source_credential_file is not None:
        source_document = _read_private_document(Path(source_credential_file).expanduser().resolve())
        source_token = source_document["companyMasterTokenSecret"]
        operation_base_url = _document_base_url(source_document, base_url)
    else:
        source_token = str(
            environment.get(SOURCE_TOKEN_ENVIRONMENT)
            or environment.get(AGENT_TOKEN_ENVIRONMENT)
            or ""
        ).strip()
        if not source_token:
            raise RecoveryError("An explicit source credential file or governed environment credential is required.")
        if not _GOVERNED_BEARER_PATTERN.fullmatch(source_token):
            raise RecoveryError("The governed environment credential format is invalid.")
        operation_base_url = _validate_base_url(
            base_url or environment.get(BASE_URL_ENVIRONMENT) or DEFAULT_BASE_URL
        )

    if pending_document and operation_base_url != pending_document["baseUrl"]:
        raise RecoveryError("Pending and source credential origins do not match.")

    source_state, source_principal = _inspect_principal(operation_base_url, source_token, open_url)
    if source_state != "valid":
        raise RecoveryError(
            "The source credential must be an active company master or company-scoped top-level agent."
        )
    source_mode = _source_mode(source_principal)
    source_company_id = str(source_principal.get("companyId") or "").strip()
    if source_document and source_company_id != source_document["companyId"]:
        raise RecoveryError("Source credential company boundary does not match its credential file.")

    if pending_document:
        if source_company_id != pending_document["companyId"]:
            raise RecoveryError("Pending and source credentials do not belong to the same company.")
        operation_workspace_id = pending_document["workspaceId"]
        candidate_token = pending_document["companyMasterTokenSecret"]
    else:
        operation_workspace_id = (
            (source_document or {}).get("workspaceId")
            or workspace_id
            or environment.get(WORKSPACE_ID_ENVIRONMENT)
            or _principal_workspace_id(source_principal)
        )
        operation_workspace_id = str(operation_workspace_id or "").strip()
        if not operation_workspace_id:
            raise RecoveryError("A workspace boundary is required for company-master recovery.")
        candidate_token = _generate_candidate()
        candidate_document = _private_document(
            operation_base_url,
            source_company_id,
            operation_workspace_id,
            candidate_token,
        )
        _write_pending(pending_path, candidate_document)
        pending_document = candidate_document

    body = {
        "schemaVersion": (
            TOP_LEVEL_AGENT_SCHEMA
            if source_mode == "top_level_agent"
            else DELEGATION_SCHEMA
        ),
        "workspaceId": operation_workspace_id,
        "candidateTokenSecret": candidate_token,
        "label": DEFAULT_LABEL,
        "principalName": DEFAULT_PRINCIPAL_NAME,
    }
    idempotency_key = _candidate_idempotency_key(
        candidate_token, body["schemaVersion"]
    )

    post_status = None
    post_payload = None
    post_unknown = False
    try:
        post_status, post_payload = _request_json(
            operation_base_url,
            DELEGATION_ROUTE,
            source_token,
            method="POST",
            body=body,
            idempotency_key=idempotency_key,
            open_url=open_url,
        )
    except _RequestOutcomeUnknown:
        post_unknown = True

    try:
        candidate_state, candidate_principal = _inspect_company_master(
            operation_base_url, candidate_token, open_url
        )
    except RecoveryError as exc:
        raise RecoveryError("Recovery outcome is unknown; the pending credential was retained for exact retry.") from exc
    if candidate_state == "valid":
        _validate_document_principal(pending_document, candidate_principal)
        _promote_pending(pending_path, target_path)
        return _success("recovered")

    if post_unknown:
        raise RecoveryError("Recovery outcome is unknown; the pending credential was retained for exact retry.")
    if (
        post_status is None
        or post_status < 200
        or post_status >= 300
        or not isinstance(post_payload, dict)
        or not post_payload.get("ok")
    ):
        raise RecoveryError("Recovery was rejected; the pending credential was retained.")
    raise RecoveryError("Candidate activation was not visible; the pending credential was retained for exact retry.")


def _parser():
    parser = argparse.ArgumentParser(
        description="Recover a MemoryEndpoints company master without printing credentials or identifiers."
    )
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--source-credential-file")
    parser.add_argument("--base-url")
    parser.add_argument("--workspace-id")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        result = recover_company_master(
            project_root=args.project_root,
            source_credential_file=args.source_credential_file,
            base_url=args.base_url,
            workspace_id=args.workspace_id,
        )
    except RecoveryError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "credentialValuesPrinted": False,
                    "identifiersPrinted": False,
                    "valuesRedacted": True,
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
