import argparse
import hashlib
import json
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SECRET_OUT = ROOT / ".local-secrets" / "human-verifier-account.json"
DEFAULT_REPORT_OUT = ROOT / "docs" / "reports" / "human-verifier-account-report.json"


def call_json(base_url, path, method="GET", body=None, token=None, idempotency_key=None, query=None):
    url = base_url.rstrip("/") + path
    if query:
        url += "?" + query
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    data = None
    if body is not None:
        data = json.dumps(body, sort_keys=True).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {
                "ok": False,
                "error": {
                    "code": "non_json_http_error",
                    "status": exc.code,
                    "valuesRedacted": True,
                },
                "valuesRedacted": True,
            }
        return exc.code, payload


def require_ok(status, payload, step):
    if not (200 <= int(status) < 300) or not payload.get("ok"):
        raise RuntimeError("%s failed with status %s and code %s" % (step, status, ((payload.get("error") or {}).get("code") or "unknown")))
    return payload


def token_hash(token):
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def display_path(path):
    try:
        return str(Path(path).resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://memoryendpoints.com")
    parser.add_argument("--secret-out", default=str(DEFAULT_SECRET_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    run_tag = uuid.uuid4().hex[:12]
    steps = []

    status, setup = call_json(
        base_url,
        "/api/matm/agent-setup/free-account",
        method="POST",
        body={
            "companyLabel": "MemoryEndpoints Dogfood Company",
            "label": "Human Agent Verification Workspace",
            "projectLabel": "Multi-Agent Memory Human Verification Project",
        },
    )
    require_ok(status, setup, "create account")
    token = setup["apiKeySecret"]
    workspace_id = setup["workspaceId"]
    account_id = setup["accountId"]
    company_id = setup["companyId"]
    project_id = setup["projectId"]
    steps.append({"name": "create_account", "ok": True, "status": status})

    status, workspace = call_json(
        base_url,
        "/api/matm/workspace",
        token=token,
        query="workspace_id=%s" % workspace_id,
    )
    workspace = require_ok(status, workspace, "read workspace")
    hierarchy = workspace["workspace"]
    hierarchy_ok = bool(
        hierarchy.get("accountId") == account_id
        and hierarchy.get("companyId") == company_id
        and hierarchy.get("workspaceId") == workspace_id
        and hierarchy.get("primaryProjectId") == project_id
        and hierarchy.get("projects")
    )
    steps.append({"name": "verify_hierarchy", "ok": hierarchy_ok, "status": status})

    agents = {
        "human-verifier-agent": "Human-Side Verification Agent",
        "codex-agent": "Codex Coordination Agent",
        "swarm-observer-agent": "Swarm Observer Agent",
    }
    for agent_id, display_name in agents.items():
        status, payload = call_json(
            base_url,
            "/api/matm/agents/register",
            method="POST",
            token=token,
            idempotency_key="human-verifier-%s-%s" % (run_tag, agent_id),
            body={"workspaceId": workspace_id, "agentId": agent_id, "displayName": display_name},
        )
        require_ok(status, payload, "register %s" % agent_id)
    steps.append({"name": "register_agents", "ok": True, "status": 201, "count": len(agents)})

    memories = [
        (
            "company",
            company_id,
            "Company/account boundary verification seeded",
            "The company/account boundary is visible to the human verifier: the company is a distinct organization boundary linked to an account through account-company membership.",
            ["verification", "company", "account", "boundary", "hierarchy"],
        ),
        (
            "workspace",
            workspace_id,
            "Workspace verifier key prepared",
            "The human-side verifier can use the saved key to enter the browser console and inspect workspace memory.",
            ["workspace", "human-verification"],
        ),
        (
            "project",
            project_id,
            "Project verification memory seeded",
            "The project is linked to this workspace and contains the MemoryEndpoints human verification dogfood target.",
            ["project", "memoryendpoints"],
        ),
    ]
    memory_ids = []
    for scope, scope_id, title, summary, tags in memories:
        status, payload = call_json(
            base_url,
            "/api/matm/memory-events/submit",
            method="POST",
            token=token,
            idempotency_key="human-verifier-%s-memory-%s" % (run_tag, scope),
            body={
                "workspaceId": workspace_id,
                "actorAgentId": "MemoryEndpoints-Backend-Agent",
                "scope": scope,
                "scopeId": scope_id,
                "memoryType": "status",
                "subject": title,
                "title": title,
                "summary": summary,
                "tags": tags,
                "source": "scripts/create_human_verifier_account.py",
                "confidence": 0.9,
            },
        )
        payload = require_ok(status, payload, "submit %s memory" % scope)
        memory_ids.append(payload["event"]["eventId"])
    steps.append({"name": "seed_company_workspace_project_memory", "ok": True, "status": 201, "count": len(memory_ids)})

    messages = [
        {
            "name": "broadcast_to_swarm",
            "body": {
                "workspaceId": workspace_id,
                "senderAgentId": "codex-agent",
                "safeSummary": "Broadcast from Codex Agent: the human verification workspace is ready; check company, workspace, project, memory, inbox, receipts, and audit from the console.",
                "responseRequired": False,
            },
        },
        {
            "name": "target_human_verifier",
            "body": {
                "workspaceId": workspace_id,
                "senderAgentId": "codex-agent",
                "targetAgentId": "human-verifier-agent",
                "safeSummary": "Human verifier: use the saved key in /console, inspect the hierarchy and memory, then send a targeted response to codex-agent.",
                "responseRequired": True,
            },
        },
        {
            "name": "target_codex_agent",
            "body": {
                "workspaceId": workspace_id,
                "senderAgentId": "human-verifier-agent",
                "targetAgentId": "codex-agent",
                "safeSummary": "Targeted verification message to codex-agent proving a particular-agent lane is available.",
                "responseRequired": True,
            },
        },
    ]
    for item in messages:
        status, payload = call_json(
            base_url,
            "/api/matm/agent-messages",
            method="POST",
            token=token,
            idempotency_key="human-verifier-%s-%s" % (run_tag, item["name"]),
            body=item["body"],
        )
        require_ok(status, payload, item["name"])
    steps.append({"name": "seed_broadcast_and_targeted_messages", "ok": True, "status": 202, "count": len(messages)})

    status, search = call_json(
        base_url,
        "/api/matm/search",
        token=token,
        query="workspace_id=%s&q=verification" % workspace_id,
    )
    search = require_ok(status, search, "search verification memory")
    steps.append({"name": "search_memory", "ok": search.get("count", 0) >= 2, "status": status, "count": search.get("count", 0)})

    inbox_counts = {}
    for agent_id in agents:
        status, inbox = call_json(
            base_url,
            "/api/matm/current-message",
            token=token,
            query="workspace_id=%s&agent_id=%s" % (workspace_id, agent_id),
        )
        inbox = require_ok(status, inbox, "read inbox %s" % agent_id)
        inbox_counts[agent_id] = inbox.get("unreadCount", 0)
    messaging_ok = (
        inbox_counts.get("human-verifier-agent", 0) >= 2
        and inbox_counts.get("MemoryEndpoints-Backend-Agent", 0) >= 2
        and inbox_counts.get("swarm-observer-agent", 0) >= 1
    )
    steps.append({"name": "verify_broadcast_and_targeted_inboxes", "ok": messaging_ok, "status": 200, "inboxCounts": inbox_counts})

    status, audit_denial = call_json(
        base_url,
        "/api/matm/audit-log",
        token=token,
        query="workspace_id=%s&limit=50" % workspace_id,
    )
    agent_audit_access_denied = bool(
        status == 403
        and ((audit_denial.get("error") or {}).get("code") == "human_owner_required")
        and audit_denial.get("agentsCanAccess") is False
    )
    steps.append({"name": "verify_agent_audit_access_denied", "ok": agent_audit_access_denied, "status": status})

    secret_payload = {
        "baseUrl": base_url,
        "consoleUrl": base_url + "/console",
        "apiKeySecret": token,
        "accountId": account_id,
        "companyId": company_id,
        "workspaceId": workspace_id,
        "projectId": project_id,
        "humanAgentId": "human-verifier-agent",
        "codexAgentId": "codex-agent",
        "swarmObserverAgentId": "swarm-observer-agent",
        "instructions": [
            "Open consoleUrl.",
            "Paste apiKeySecret into Workspace key.",
            "Load workspace and verify accountId, companyId, workspaceId, and projectId.",
            "Search for verification memory.",
            "Refresh inbox for human-verifier-agent and codex-agent.",
            "Send a broadcast message by leaving Target agent blank.",
            "Send a targeted message to codex-agent.",
        ],
    }
    secret_out = Path(args.secret_out)
    write_json(secret_out, secret_payload)

    report = {
        "schemaVersion": "memoryendpoints.human_verifier_account.v1",
        "baseUrl": base_url,
        "consoleUrl": base_url + "/console",
        "secretFile": display_path(secret_out),
        "secretFileTrackedByGit": False,
        "rawCredentialValuesStoredInReport": False,
        "apiKeySecretHash": token_hash(token),
        "accountId": account_id,
        "companyId": company_id,
        "workspaceIdHash": token_hash(workspace_id),
        "projectId": project_id,
        "hierarchyVerified": hierarchy_ok,
        "seededMemoryCount": len(memory_ids),
        "searchReadbackCount": search.get("count", 0),
        "inboxCounts": inbox_counts,
        "messagingVerified": messaging_ok,
        "agentAuditAccessDenied": agent_audit_access_denied,
        "steps": steps,
        "ok": all(item.get("ok") for item in steps),
        "valuesRedacted": True,
    }
    report_text = json.dumps(report, sort_keys=True)
    report["rawCredentialValuesStoredInReport"] = token in report_text
    write_json(Path(args.report_out), report)
    print(json.dumps({"ok": report["ok"], "secretFile": display_path(secret_out), "report": display_path(args.report_out), "valuesRedacted": True}, indent=2, sort_keys=True))
    return 0 if report["ok"] and not report["rawCredentialValuesStoredInReport"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
