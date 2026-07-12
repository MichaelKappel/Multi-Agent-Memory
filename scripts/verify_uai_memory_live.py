import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUTH_FILE = ROOT / ".local-secrets" / "tinyrustlm-memoryendpoints-auth.json"
SYNTHETIC_LOCAL_PATH = ".uai/agents/memoryendpoints-live-claim-verifier.uai"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def request_json(base_url, path, method="GET", token="", body=None, query=None, idempotency_key=""):
    url = base_url.rstrip("/") + path
    if query:
        url += "?" + urlencode({key: value for key, value in query.items() if value not in (None, "")})
    payload = None
    headers = {"Accept": "application/json"}
    if body is not None:
        payload = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    request = Request(url, data=payload, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"ok": False, "error": {"code": "non_json_error"}}


def safe_hash(value):
    return "sha256:" + hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def valid_base_url(value):
    parsed = urlparse(str(value or ""))
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url")
    parser.add_argument("--auth-file", default=str(DEFAULT_AUTH_FILE))
    parser.add_argument("--public-only", action="store_true")
    parser.add_argument("--json-out")
    args = parser.parse_args(argv)

    auth = {}
    if not args.public_only:
        auth_path = Path(args.auth_file)
        if not auth_path.exists():
            raise SystemExit("Protected verification requires an ignored auth file.")
        auth = read_json(auth_path)
    base_url = args.base_url or auth.get("baseUrl") or "https://memoryendpoints.com"
    if not valid_base_url(base_url):
        raise SystemExit("A valid HTTP(S) base URL is required.")

    report = {
        "schemaVersion": "memoryendpoints.uai_memory_live_verifier.v1",
        "baseUrl": base_url.rstrip("/"),
        "publicOnly": bool(args.public_only),
        "checks": {},
        "ok": False,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }

    try:
        status, contract_payload = request_json(base_url, "/api/matm/uai-memory/contract")
        contract = contract_payload.get("data") or {}
        overlay = contract.get("localCollaborationOverlay") or {}
        report["checks"]["publicContract"] = {
            "ok": status == 200
            and contract.get("profile") == "uaix.accountless-browser-memory.v1"
            and contract.get("exceptionBoundary", {}).get("anonymousStorageAllowed") is False
            and overlay.get("truthBoundary", {}).get("localUaiContentsStored") is False
            and overlay.get("truthBoundary", {}).get("automaticMerge") is False,
            "httpStatus": status,
            "profile": contract.get("profile"),
            "virtualPackageIsAnonymous": contract.get("exceptionBoundary", {}).get("anonymousStorageAllowed"),
            "localUaiContentsStored": overlay.get("truthBoundary", {}).get("localUaiContentsStored"),
            "automaticMerge": overlay.get("truthBoundary", {}).get("automaticMerge"),
        }

        if not args.public_only:
            workspace_id = auth.get("workspaceId") or ""
            workspace_key = auth.get("workspaceKey") or auth.get("apiKeySecret") or ""
            agent_id = auth.get("agentId") or auth.get("codexAgentId") or ""
            if not workspace_id or not workspace_key or not agent_id:
                raise RuntimeError("Auth file is missing workspaceId, workspaceKey/apiKeySecret, or agentId.")
            run_id = uuid.uuid4().hex
            report["workspaceIdHash"] = safe_hash(workspace_id)
            report["agentIdHash"] = safe_hash(agent_id)

            status, register_payload = request_json(
                base_url,
                "/api/matm/agents/register",
                "POST",
                workspace_key,
                {"workspaceId": workspace_id, "agentId": agent_id, "displayName": "TinyRustLM Agent"},
                idempotency_key="uai-live-register-" + run_id,
            )
            report["checks"]["registeredAgent"] = {
                "ok": status in (200, 201) and register_payload.get("ok") is True,
                "httpStatus": status,
            }

            status, package_payload = request_json(
                base_url,
                "/api/matm/uai-memory/packages",
                "POST",
                workspace_key,
                {
                    "workspaceId": workspace_id,
                    "agentId": agent_id,
                    "clientClass": "accountless_browser_ai",
                    "localFilesystemAvailable": False,
                },
                idempotency_key="uai-live-package-" + run_id,
            )
            package = package_payload.get("package") or {}
            package_id = package_payload.get("canonicalPackageId") or package.get("packageId") or ""
            report["checks"]["virtualPackage"] = {
                "ok": status in (200, 201)
                and package_payload.get("persisted") is True
                and package_payload.get("visibleToSender") is True
                and bool(package_id),
                "httpStatus": status,
                "created": package_payload.get("created"),
                "status": package.get("status"),
                "readyForStartup": package.get("readyForStartup"),
                "packageIdHash": safe_hash(package_id),
            }

            status, workspace_payload = request_json(
                base_url,
                "/api/matm/workspace",
                token=workspace_key,
                query={"workspace_id": workspace_id},
            )
            workspace = workspace_payload.get("workspace") or {}
            project_id = auth.get("projectId") or workspace.get("primaryProjectId") or ""
            report["checks"]["projectResolved"] = {
                "ok": status == 200 and bool(project_id),
                "httpStatus": status,
                "projectIdHash": safe_hash(project_id),
            }

            status, heads_payload = request_json(
                base_url,
                "/api/matm/uai-memory/file-heads",
                token=workspace_key,
                query={
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "logical_path": SYNTHETIC_LOCAL_PATH,
                },
            )
            heads = heads_payload.get("items") or []
            base_hash = (heads[0].get("observedContentHash") if heads else None) or safe_hash("")
            report["checks"]["fileHeadRead"] = {
                "ok": status == 200 and heads_payload.get("localContentStored") is False,
                "httpStatus": status,
                "existingHeadCount": len(heads),
            }

            status, claim_payload = request_json(
                base_url,
                "/api/matm/uai-memory/edit-claims",
                "POST",
                workspace_key,
                {
                    "workspaceId": workspace_id,
                    "projectId": project_id,
                    "agentId": agent_id,
                    "logicalPath": SYNTHETIC_LOCAL_PATH,
                    "baseContentHash": base_hash,
                    "intentSummary": "Verify hash-only local active-memory coordination without changing a local file.",
                    "leaseSeconds": 60,
                },
                idempotency_key="uai-live-claim-" + run_id,
            )
            claim = claim_payload.get("claim") or {}
            claim_id = claim_payload.get("canonicalClaimId") or claim.get("claimId") or ""
            report["checks"]["claimAcquired"] = {
                "ok": status == 201
                and claim_payload.get("claimAcquired") is True
                and claim_payload.get("localContentStored") is False
                and bool(claim_id),
                "httpStatus": status,
                "claimIdHash": safe_hash(claim_id),
            }

            status, release_payload = request_json(
                base_url,
                "/api/matm/uai-memory/edit-claims/release",
                "POST",
                workspace_key,
                {
                    "workspaceId": workspace_id,
                    "agentId": agent_id,
                    "claimId": claim_id,
                    "releaseSummary": "Verified claim persistence and released it without changing the local file hash.",
                },
                idempotency_key="uai-live-release-" + run_id,
            )
            report["checks"]["claimReleased"] = {
                "ok": status == 200
                and release_payload.get("persisted") is True
                and (release_payload.get("claim") or {}).get("status") == "released"
                and release_payload.get("localContentStored") is False,
                "httpStatus": status,
                "headRevision": release_payload.get("headRevision"),
            }

        report["ok"] = all(item.get("ok") is True for item in report["checks"].values())
    except (RuntimeError, ValueError, URLError) as exc:
        report["error"] = {
            "type": exc.__class__.__name__,
            "messageFingerprint": safe_hash(str(exc)),
            "safeNoOp": True,
        }

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
