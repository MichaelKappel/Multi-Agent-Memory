#!/usr/bin/env python3
"""Create a MemoryEndpoints company and persist both one-time credentials safely.

This helper is the agent-facing setup path. It never prints either credential and
does not consider setup complete until the company master has been written to the
project's standard local-secret file and the owner recovery secret has been
written to its separate recovery file.
"""

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


PROJECT_SECRET_PATH = Path(".local-secrets/memoryendpoints-company-master.json")
SETUP_ROUTE = "/api/matm/agent-setup/free-account"


class SetupError(RuntimeError):
    """A public-safe setup error that never contains a credential value."""


def _slug(value):
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "company").lower()).strip("-")
    return normalized[:60] or "company"


def default_recovery_path(company_label):
    return (
        Path.home()
        / ".memoryendpoints"
        / "owner-recovery"
        / ("%s-human-owner-recovery.json" % _slug(company_label))
    )


def _validate_base_url(value):
    base_url = str(value or "").strip().rstrip("/")
    parsed = urlparse(base_url)
    local_http = parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost")
    if parsed.scheme != "https" and not local_http:
        raise SetupError("Base URL must use HTTPS (local loopback HTTP is allowed for testing).")
    if not parsed.netloc or parsed.username or parsed.password:
        raise SetupError("Base URL must be an origin without embedded credentials.")
    return base_url


def _prepare_target(path):
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise SetupError("Refusing setup because a target credential file already exists: %s" % path)
    probe = None
    try:
        handle, probe = tempfile.mkstemp(prefix=".memoryendpoints-write-check-", dir=str(path.parent))
        os.close(handle)
    except OSError as exc:
        raise SetupError("Credential target is not writable: %s" % path) from exc
    finally:
        if probe:
            try:
                os.unlink(probe)
            except OSError:
                pass
    return path


def _stage_private_json(path, payload):
    handle, temporary = tempfile.mkstemp(prefix=".memoryendpoints-secret-", dir=str(path.parent))
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(handle, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
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


def _commit_private_file(staged, target):
    if target.exists():
        raise SetupError("Refusing to overwrite credential file: %s" % target)
    os.replace(str(staged), str(target))
    try:
        os.chmod(str(target), 0o600)
    except OSError:
        pass


def _post_setup(base_url, labels, open_url=urlopen):
    request = Request(
        base_url + SETUP_ROUTE,
        data=json.dumps(labels).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with open_url(request, timeout=30) as response:
            status = int(getattr(response, "status", 200))
            raw = response.read()
    except HTTPError as exc:
        raise SetupError("MemoryEndpoints setup was rejected with HTTP %s; no credential was printed." % exc.code) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise SetupError("MemoryEndpoints setup could not be confirmed; do not retry automatically.") from exc
    if status < 200 or status >= 300:
        raise SetupError("MemoryEndpoints setup returned HTTP %s; no credential was printed." % status)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SetupError("MemoryEndpoints setup returned an unreadable response; do not retry automatically.") from exc
    if not isinstance(payload, dict):
        raise SetupError("MemoryEndpoints setup returned an invalid response; do not retry automatically.")
    return payload


def create_and_persist_company(
    company_label,
    workspace_label,
    project_label,
    project_root=".",
    recovery_out=None,
    base_url="https://memoryendpoints.com",
    open_url=urlopen,
):
    base_url = _validate_base_url(base_url)
    company_path = _prepare_target(Path(project_root) / PROJECT_SECRET_PATH)
    recovery_path = _prepare_target(recovery_out or default_recovery_path(company_label))
    if company_path == recovery_path:
        raise SetupError("Company-master and owner-recovery credentials must use separate files.")

    payload = _post_setup(
        base_url,
        {
            "companyLabel": str(company_label).strip(),
            "label": str(workspace_label).strip(),
            "projectLabel": str(project_label).strip(),
        },
        open_url=open_url,
    )
    required = (
        "companyId",
        "workspaceId",
        "companyMasterTokenSecret",
        "humanOwnerRecoverySecret",
    )
    if any(not isinstance(payload.get(name), str) or not payload.get(name) for name in required):
        raise SetupError("Setup returned incomplete one-time credential data; the outcome is unknown and must not be retried automatically.")

    company_document = {
        "schemaVersion": "memoryendpoints.company_master_credential_file.v1",
        "baseUrl": base_url,
        "companyId": payload["companyId"],
        "workspaceId": payload["workspaceId"],
        "companyMasterTokenSecret": payload["companyMasterTokenSecret"],
    }
    recovery_document = {
        "schemaVersion": "memoryendpoints.human_owner_recovery_file.v1",
        "baseUrl": base_url,
        "companyId": payload["companyId"],
        "humanOwnerCredentialId": payload.get("humanOwnerCredentialId"),
        "humanOwnerRecoverySecret": payload["humanOwnerRecoverySecret"],
    }

    staged_company = staged_recovery = None
    try:
        staged_company = _stage_private_json(company_path, company_document)
        staged_recovery = _stage_private_json(recovery_path, recovery_document)
        _commit_private_file(staged_recovery, recovery_path)
        staged_recovery = None
        _commit_private_file(staged_company, company_path)
        staged_company = None
    finally:
        for staged in (staged_company, staged_recovery):
            if staged:
                try:
                    staged.unlink()
                except OSError:
                    pass

    return {
        "ok": True,
        "companyId": payload["companyId"],
        "workspaceId": payload["workspaceId"],
        "projectId": payload.get("projectId"),
        "companyMasterPath": str(company_path),
        "ownerRecoveryPath": str(recovery_path),
        "credentialsPersisted": True,
        "credentialValuesPrinted": False,
        "valuesRedacted": True,
    }


def _parser():
    parser = argparse.ArgumentParser(
        description="Create a company and save its one-time credentials without printing them."
    )
    parser.add_argument("--company-label", required=True)
    parser.add_argument("--workspace-label", required=True)
    parser.add_argument("--project-label", required=True)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--recovery-out")
    parser.add_argument("--base-url", default="https://memoryendpoints.com")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        result = create_and_persist_company(
            args.company_label,
            args.workspace_label,
            args.project_label,
            project_root=args.project_root,
            recovery_out=args.recovery_out,
            base_url=args.base_url,
        )
    except SetupError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "valuesRedacted": True}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
