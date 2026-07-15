import json
import os
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit


_CREDENTIAL_PEPPER_ENV = "MEMORYENDPOINTS_CREDENTIAL_PEPPER"
_MISSING = object()
_TEST_CREDENTIAL_PEPPER = "test-only-governed-agent-provisioner-v1-" + ("p" * 64)


@dataclass(frozen=True)
class GovernedTestAgent:
    agent_id: str
    agent_bearer: str = field(repr=False)

    @property
    def auth_headers(self):
        return {"HTTP_AUTHORIZATION": "Bearer " + self.agent_bearer}


class GovernedAgentProvisioner:
    """Exercise the production governed invitation flow for test principals."""

    def __init__(self, call_app):
        self._call_app = call_app
        self._previous_pepper = _MISSING
        self._installed = False

    def install(self):
        if not self._installed:
            self._previous_pepper = os.environ.get(_CREDENTIAL_PEPPER_ENV, _MISSING)
            os.environ[_CREDENTIAL_PEPPER_ENV] = _TEST_CREDENTIAL_PEPPER
            self._installed = True
        return self

    def restore(self):
        if not self._installed:
            return
        if self._previous_pepper is _MISSING:
            os.environ.pop(_CREDENTIAL_PEPPER_ENV, None)
        else:
            os.environ[_CREDENTIAL_PEPPER_ENV] = self._previous_pepper
        self._previous_pepper = _MISSING
        self._installed = False

    def provision(
        self,
        *,
        master_bearer,
        company_id,
        workspace_id,
        project_id,
        requested_name,
        display_name,
        grant_scope_type="workspace",
        grant_scope_id=None,
    ):
        if not self._installed:
            raise AssertionError("The deterministic test credential pepper is not installed.")
        scope_ids = {
            "company": company_id,
            "workspace": workspace_id,
            "project": project_id,
        }
        scope_id = grant_scope_id or scope_ids.get(grant_scope_type)
        if not scope_id:
            raise AssertionError("The requested governed test grant has no scope id.")
        master_headers = {"HTTP_AUTHORIZATION": "Bearer " + master_bearer}
        request_headers = dict(
            master_headers,
            HTTP_IDEMPOTENCY_KEY="governed-test-name-request-" + requested_name,
        )

        requested = self._json_call(
            "/api/matm/access/agent-name-requests",
            "POST",
            {
                "requestedName": requested_name,
                "displayName": display_name,
                "requestedGrant": {
                    "scopeType": grant_scope_type,
                    "scopeId": scope_id,
                },
                "assignmentContext": {
                    "projectId": project_id,
                    "taskId": "governed-test-fixture",
                    "taskLabel": "Governed test fixture",
                },
                "justification": "Provision a governed principal for an isolated contract test.",
            },
            request_headers,
            "201 Created",
            "agent name request",
        )
        request_id = ((requested.get("request") or {}).get("requestId") or "").strip()
        if not request_id:
            raise AssertionError("The governed agent name request returned no request id.")

        approved = self._json_call(
            "/api/matm/access/agent-name-requests/%s/decision" % request_id,
            "POST",
            {
                "decision": "approve",
                "decisionReason": "Approved for the isolated governed-principal contract test.",
            },
            dict(
                master_headers,
                HTTP_IDEMPOTENCY_KEY="governed-test-name-decision-" + request_id,
            ),
            "200 OK",
            "agent name approval",
        )
        if ((approved.get("request") or {}).get("status") or "") != "approved":
            raise AssertionError("The governed agent name request was not approved.")

        issued = self._json_call(
            "/api/matm/access/invites",
            "POST",
            {"approvedRequestId": request_id, "expiresInSeconds": 900},
            master_headers,
            "201 Created",
            "agent invitation issuance",
        )
        if "inviteSecret" in issued:
            raise AssertionError("The governed invitation exposed a secret outside the URL fragment.")
        invite_url = issued.get("inviteUrl") or ""
        parsed_invite_url = urlsplit(invite_url)
        if parsed_invite_url.query or not parsed_invite_url.fragment:
            raise AssertionError("The governed invitation was not fragment-only.")
        fragment = parse_qs(parsed_invite_url.fragment, strict_parsing=True)
        if set(fragment) != {"invite"} or len(fragment["invite"]) != 1:
            raise AssertionError("The governed invitation fragment was malformed.")
        invite_secret = fragment["invite"][0]

        redeemed = self._json_call(
            "/api/matm/access/invites/redeem",
            "POST",
            {"inviteSecret": invite_secret},
            {},
            "201 Created",
            "agent invitation redemption",
        )
        principal = redeemed.get("principal") or {}
        agent_id = str(principal.get("agentId") or "").strip()
        agent_bearer = redeemed.get("agentTokenSecret") or ""
        if not agent_id or not agent_bearer:
            raise AssertionError("The governed invitation redemption returned no canonical agent principal.")
        return GovernedTestAgent(agent_id=agent_id, agent_bearer=agent_bearer)

    def _json_call(self, path, method, body, headers, expected_status, operation):
        status, _response_headers, text = self._call_app(
            path,
            method=method,
            body=body,
            headers=headers,
        )
        if status != expected_status:
            raise AssertionError(
                "%s expected %s but received %s" % (operation, expected_status, status)
            )
        try:
            payload = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise AssertionError("%s returned invalid JSON" % operation) from exc
        if not payload.get("ok"):
            raise AssertionError("%s did not succeed" % operation)
        return payload
