import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from app import application
from memoryendpoints.app import _store
from memoryendpoints import outbound_mcp
from memoryendpoints.outbound_mcp import SERVER_SCHEMA, config_digest
from tests.governed_test_support import GovernedAgentProvisioner


def call_app(path, method="GET", body=None, headers=None, query=""):
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    captured = {}

    def start_response(status, response_headers):
        captured["status"] = status
        captured["headers"] = dict(response_headers)

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "CONTENT_LENGTH": str(len(raw)),
        "CONTENT_TYPE": "application/json" if body is not None else "",
        "wsgi.input": io.BytesIO(raw),
        "REMOTE_ADDR": "127.0.0.1",
    }
    environ.update(headers or {})
    text = b"".join(application(environ, start_response)).decode("utf-8")
    return captured["status"], captured["headers"], text


def json_call(path, method="GET", body=None, headers=None, query=""):
    status, response_headers, text = call_app(
        path, method=method, body=body, headers=headers, query=query
    )
    return status, response_headers, json.loads(text)


def server(
    label="Build tools",
    endpoint="https://tools.example.test/mcp",
    requested_mode="inherit",
    tool_allowlist=None,
):
    return {
        "schemaVersion": SERVER_SCHEMA,
        "label": label,
        "endpoint": endpoint,
        "transport": "streamable_http",
        "authMode": "none",
        "requestedMode": requested_mode,
        "toolAllowlist": tool_allowlist
        if tool_allowlist is not None
        else ["memory.search", "tools.list"],
    }


class OutboundMcpApiContract:
    backend = None

    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="outbound-mcp-%s-" % self.backend)
        self.saved = {
            key: os.environ.get(key)
            for key in (
                "MEMORYENDPOINTS_STORE_BACKEND",
                "MEMORYENDPOINTS_STORE_PATH",
                "MEMORYENDPOINTS_SQLITE_PATH",
                "MEMORYENDPOINTS_CREDENTIAL_PEPPER",
                "MEMORYENDPOINTS_CREDENTIAL_CONFIG_PATH",
            )
        }
        os.environ.update(
            {
                "MEMORYENDPOINTS_STORE_BACKEND": self.backend,
                "MEMORYENDPOINTS_STORE_PATH": str(Path(self.tempdir) / "store.json"),
                "MEMORYENDPOINTS_SQLITE_PATH": str(Path(self.tempdir) / "store.sqlite3"),
                "MEMORYENDPOINTS_CREDENTIAL_PEPPER": "outbound-mcp-test-pepper-" + ("x" * 64),
                "MEMORYENDPOINTS_CREDENTIAL_CONFIG_PATH": str(Path(self.tempdir) / "missing.json"),
            }
        )
        self.provisioner = GovernedAgentProvisioner(call_app).install()
        status, _headers, payload = json_call(
            "/api/matm/agent-setup/free-account",
            "POST",
            {
                "companyLabel": "Outbound MCP Test",
                "label": "Outbound MCP Workspace",
                "projectLabel": "Registry",
            },
        )
        self.assertEqual("201 Created", status, payload)
        self.workspace_id = payload["workspaceId"]
        self.company_id = payload["companyId"]
        self.project_id = payload["projectId"]
        self.master = payload["companyMasterTokenSecret"]
        status, _headers, sibling = json_call(
            "/api/matm/projects",
            "POST",
            {
                "workspaceId": self.workspace_id,
                "projectId": "outbound-mcp-sibling-" + self.backend,
                "label": "Outbound MCP Sibling",
            },
            {
                "HTTP_AUTHORIZATION": "Bearer " + self.master,
                "HTTP_IDEMPOTENCY_KEY": "outbound-mcp-sibling-create-" + self.backend,
            },
        )
        self.assertEqual("201 Created", status, sibling)
        self.sibling_project_id = sibling["project"]["projectId"]
        self.owner = self.provisioner.provision(
            master_bearer=self.master,
            company_id=self.company_id,
            workspace_id=self.workspace_id,
            project_id=self.project_id,
            requested_name="outbound-registry-owner",
            display_name="Outbound Registry Owner",
            grant_scope_type="workspace",
        )
        self.other = self.provisioner.provision(
            master_bearer=self.master,
            company_id=self.company_id,
            workspace_id=self.workspace_id,
            project_id=self.project_id,
            requested_name="outbound-registry-other",
            display_name="Outbound Registry Other",
            grant_scope_type="workspace",
        )
        self.project_agent = self.provisioner.provision(
            master_bearer=self.master,
            company_id=self.company_id,
            workspace_id=self.workspace_id,
            project_id=self.project_id,
            requested_name="outbound-registry-project",
            display_name="Outbound Registry Project",
            grant_scope_type="project",
        )
        self.project_peer = self.provisioner.provision(
            master_bearer=self.master,
            company_id=self.company_id,
            workspace_id=self.workspace_id,
            project_id=self.project_id,
            requested_name="outbound-registry-project-peer",
            display_name="Outbound Registry Project Peer",
            grant_scope_type="project",
        )
        self.sibling_project_agent = self.provisioner.provision(
            master_bearer=self.master,
            company_id=self.company_id,
            workspace_id=self.workspace_id,
            project_id=self.sibling_project_id,
            requested_name="outbound-registry-sibling-project",
            display_name="Outbound Registry Sibling Project",
            grant_scope_type="project",
        )

    def tearDown(self):
        self.provisioner.restore()
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def _headers(self, agent=None, idem=None):
        headers = dict((agent or self.owner).auth_headers)
        if idem:
            headers["HTTP_IDEMPOTENCY_KEY"] = idem
        return headers

    def _create(
        self,
        configured=None,
        idem="outbound-create-0001",
        agent=None,
        project_id=None,
    ):
        project_id = project_id or self.project_id
        status, _headers, payload = json_call(
            "/api/matm/outbound-mcp/servers",
            "POST",
            {
                "workspaceId": self.workspace_id,
                "projectId": project_id,
                "server": configured or server(),
            },
            self._headers(agent=agent, idem=idem),
        )
        self.assertEqual("201 Created", status, payload)
        self.assertTrue(payload["ok"])
        return payload["server"]

    def _authorization_body(self, created, **overrides):
        body = {
            "workspaceId": self.workspace_id,
            "projectId": created["projectId"],
            "expectedServerRevision": created["revision"],
            "expectedConfigDigest": created["configDigest"],
            "expectedPolicyRevision": 0,
            "toolName": "memory.search",
            "argumentsDigest": "a" * 64,
        }
        body.update(overrides)
        return body

    def _set_project_status(self, status):
        store = _store()
        if self.backend == "file":
            data = store._load()
            data["projects"][self.project_id]["status"] = status
            store._save(data)
            return
        with store._open_connection() as connection:
            with connection:
                connection.execute(
                    "UPDATE matm_projects SET status = ? WHERE project_id = ?",
                    (status, self.project_id),
                )

    def test_project_policy_create_replay_allowlist_digest_and_owner_isolation(self):
        status, _headers, payload = json_call(
            "/api/matm/outbound-mcp/policy",
            headers=self._headers(),
            query="workspace_id=%s&project_id=%s"
            % (self.workspace_id, self.project_id),
        )
        self.assertEqual("200 OK", status, payload)
        self.assertEqual("autonomous", payload["policy"]["mode"])
        self.assertEqual(0, payload["policy"]["revision"])
        self.assertEqual(self.workspace_id, payload["policy"]["workspaceId"])
        self.assertEqual(self.project_id, payload["policy"]["projectId"])

        configured = server(
            tool_allowlist=[" tools.list ", "memory.search", "tools.list"]
        )
        created = self._create(configured)
        self.assertRegex(created["serverId"], r"^omcp-[a-f0-9]{32}$")
        self.assertEqual(1, created["revision"])
        self.assertEqual(self.owner.agent_id, created["ownerAgentId"])
        self.assertEqual(self.project_id, created["projectId"])
        self.assertEqual(
            ["memory.search", "tools.list"], created["config"]["toolAllowlist"]
        )
        self.assertEqual(config_digest(created["config"]), created["configDigest"])
        self.assertFalse(created["rawCredentialExposed"])

        status, _headers, replay = json_call(
            "/api/matm/outbound-mcp/servers",
            "POST",
            {
                "workspaceId": self.workspace_id,
                "projectId": self.project_id,
                "server": configured,
            },
            self._headers(idem="outbound-create-0001"),
        )
        self.assertEqual("201 Created", status, replay)
        self.assertTrue(replay["idempotentReplay"])
        self.assertEqual(created["serverId"], replay["server"]["serverId"])
        self.assertEqual(created["configDigest"], replay["server"]["configDigest"])

        status, _headers, readback = json_call(
            "/api/matm/outbound-mcp/servers/" + created["serverId"],
            headers=self._headers(),
            query="workspace_id=%s&project_id=%s"
            % (self.workspace_id, self.project_id),
        )
        self.assertEqual("200 OK", status, readback)
        self.assertEqual(created["config"], readback["server"]["config"])
        self.assertEqual(
            config_digest(readback["server"]["config"]),
            readback["server"]["configDigest"],
        )

        status, _headers, listing = json_call(
            "/api/matm/outbound-mcp/servers",
            headers=self._headers(agent=self.other),
            query="workspace_id=%s&project_id=%s"
            % (self.workspace_id, self.project_id),
        )
        self.assertEqual("200 OK", status, listing)
        self.assertEqual([], listing["items"])
        status, _headers, missing = json_call(
            "/api/matm/outbound-mcp/servers/" + created["serverId"],
            headers=self._headers(agent=self.other),
            query="workspace_id=%s&project_id=%s"
            % (self.workspace_id, self.project_id),
        )
        self.assertEqual("404 Not Found", status, missing)

    def test_exact_update_revision_authorization_and_disable(self):
        created = self._create(idem="outbound-create-update")
        changed_config = server(endpoint="https://other.example.test/mcp")
        status, _headers, updated = json_call(
            "/api/matm/outbound-mcp/servers/" + created["serverId"],
            "POST",
            {
                "workspaceId": self.workspace_id,
                "projectId": self.project_id,
                "expectedRevision": 1,
                "server": changed_config,
            },
            self._headers(idem="outbound-update-0001"),
        )
        self.assertEqual("200 OK", status, updated)
        self.assertEqual(2, updated["server"]["revision"])
        self.assertNotEqual(created["configDigest"], updated["server"]["configDigest"])
        self.assertIsNone(updated["server"]["approvalBinding"])

        status, _headers, conflict = json_call(
            "/api/matm/outbound-mcp/servers/" + created["serverId"],
            "POST",
            {
                "workspaceId": self.workspace_id,
                "projectId": self.project_id,
                "expectedRevision": 1,
                "server": changed_config,
            },
            self._headers(idem="outbound-update-stale"),
        )
        self.assertEqual("409 Conflict", status, conflict)
        self.assertEqual("outbound_mcp_revision_conflict", conflict["error"]["code"])

        status, _headers, decision = json_call(
            "/api/matm/outbound-mcp/servers/%s/authorization-checks" % created["serverId"],
            "POST",
            self._authorization_body(updated["server"]),
            self._headers(idem="outbound-check-0001"),
        )
        self.assertEqual("200 OK", status, decision)
        self.assertEqual("allowed", decision["authorization"]["state"])
        self.assertFalse(decision["authorization"]["networkRequestPerformed"])

        status, _headers, disabled = json_call(
            "/api/matm/outbound-mcp/servers/%s/disable" % created["serverId"],
            "POST",
            {
                "workspaceId": self.workspace_id,
                "projectId": self.project_id,
                "expectedRevision": 2,
            },
            self._headers(idem="outbound-disable-0001"),
        )
        self.assertEqual("200 OK", status, disabled)
        self.assertEqual("disabled", disabled["server"]["status"])

    def test_agent_requested_human_approval_and_security_boundaries(self):
        created = self._create(
            server(requested_mode="human_required"), "outbound-create-human-required"
        )
        status, _headers, decision = json_call(
            "/api/matm/outbound-mcp/servers/%s/authorization-checks" % created["serverId"],
            "POST",
            self._authorization_body(created),
            self._headers(idem="outbound-check-human-required"),
        )
        self.assertEqual("200 OK", status, decision)
        self.assertEqual("approval_required", decision["authorization"]["state"])

        status, _headers, denied = json_call(
            "/api/matm/outbound-mcp/servers",
            "POST",
            {
                "workspaceId": self.workspace_id,
                "projectId": self.project_id,
                "server": server(),
            },
            {"HTTP_AUTHORIZATION": "Bearer " + self.master, "HTTP_IDEMPOTENCY_KEY": "outbound-master-denied"},
        )
        self.assertEqual("403 Forbidden", status, denied)
        self.assertEqual("outbound_mcp_agent_required", denied["error"]["code"])

        status, _headers, invalid = json_call(
            "/api/matm/outbound-mcp/servers",
            "POST",
            {
                "workspaceId": self.workspace_id,
                "projectId": self.project_id,
                "server": server(endpoint="http://unsafe.example.test/mcp"),
            },
            self._headers(idem="outbound-invalid-http"),
        )
        self.assertEqual("422 Unprocessable Entity", status, invalid)
        self.assertEqual("outbound_mcp_https_required", invalid["error"]["code"])

    def test_project_scope_workspace_descendant_access_and_cross_project_owner_isolation(self):
        project_owned = self._create(
            idem="outbound-project-owner-create",
            agent=self.project_agent,
            project_id=self.project_id,
        )
        self.assertEqual(self.project_id, project_owned["projectId"])
        self.assertEqual(self.project_agent.agent_id, project_owned["ownerAgentId"])

        workspace_owned_sibling = self._create(
            idem="outbound-workspace-sibling-create",
            agent=self.owner,
            project_id=self.sibling_project_id,
        )
        self.assertEqual(self.sibling_project_id, workspace_owned_sibling["projectId"])
        self.assertEqual(self.owner.agent_id, workspace_owned_sibling["ownerAgentId"])

        status, _headers, peer_listing = json_call(
            "/api/matm/outbound-mcp/servers",
            headers=self._headers(agent=self.project_peer),
            query="workspace_id=%s&project_id=%s"
            % (self.workspace_id, self.project_id),
        )
        self.assertEqual("200 OK", status, peer_listing)
        self.assertEqual([], peer_listing["items"])

        status, _headers, peer_missing = json_call(
            "/api/matm/outbound-mcp/servers/" + project_owned["serverId"],
            headers=self._headers(agent=self.project_peer),
            query="workspace_id=%s&project_id=%s"
            % (self.workspace_id, self.project_id),
        )
        self.assertEqual("404 Not Found", status, peer_missing)

        for agent, forbidden_project_id in (
            (self.project_agent, self.sibling_project_id),
            (self.sibling_project_agent, self.project_id),
        ):
            with self.subTest(
                agent=agent.agent_id, forbidden_project_id=forbidden_project_id
            ):
                status, _headers, denied = json_call(
                    "/api/matm/outbound-mcp/servers",
                    "POST",
                    {
                        "workspaceId": self.workspace_id,
                        "projectId": forbidden_project_id,
                        "server": server(),
                    },
                    self._headers(
                        agent=agent,
                        idem="outbound-cross-project-%s" % agent.agent_id,
                    ),
                )
                self.assertEqual("403 Forbidden", status, denied)
                self.assertEqual(
                    "outbound_mcp_scope_forbidden", denied["error"]["code"]
                )

    def test_project_id_is_required_on_every_registry_and_policy_operation(self):
        created = self._create(idem="outbound-required-project-create")
        authorization_without_project = self._authorization_body(created)
        authorization_without_project.pop("projectId")
        cases = (
            (
                "policy-read",
                lambda: json_call(
                    "/api/matm/outbound-mcp/policy",
                    headers=self._headers(),
                    query="workspace_id=" + self.workspace_id,
                ),
            ),
            (
                "server-list",
                lambda: json_call(
                    "/api/matm/outbound-mcp/servers",
                    headers=self._headers(),
                    query="workspace_id=" + self.workspace_id,
                ),
            ),
            (
                "server-read",
                lambda: json_call(
                    "/api/matm/outbound-mcp/servers/" + created["serverId"],
                    headers=self._headers(),
                    query="workspace_id=" + self.workspace_id,
                ),
            ),
            (
                "server-create",
                lambda: json_call(
                    "/api/matm/outbound-mcp/servers",
                    "POST",
                    {"workspaceId": self.workspace_id, "server": server()},
                    self._headers(idem="outbound-missing-project-create"),
                ),
            ),
            (
                "server-update",
                lambda: json_call(
                    "/api/matm/outbound-mcp/servers/" + created["serverId"],
                    "POST",
                    {
                        "workspaceId": self.workspace_id,
                        "expectedRevision": created["revision"],
                        "server": server(label="Changed without project"),
                    },
                    self._headers(idem="outbound-missing-project-update"),
                ),
            ),
            (
                "server-disable",
                lambda: json_call(
                    "/api/matm/outbound-mcp/servers/%s/disable"
                    % created["serverId"],
                    "POST",
                    {
                        "workspaceId": self.workspace_id,
                        "expectedRevision": created["revision"],
                    },
                    self._headers(idem="outbound-missing-project-disable"),
                ),
            ),
            (
                "authorization-check",
                lambda: json_call(
                    "/api/matm/outbound-mcp/servers/%s/authorization-checks"
                    % created["serverId"],
                    "POST",
                    authorization_without_project,
                    self._headers(idem="outbound-missing-project-check"),
                ),
            ),
        )
        for name, request in cases:
            with self.subTest(operation=name):
                status, _headers, payload = request()
                self.assertEqual("422 Unprocessable Entity", status, payload)
                self.assertEqual(
                    "outbound_mcp_project_required", payload["error"]["code"]
                )

    def test_authorization_check_exact_binding_replay_and_changed_body_conflict(self):
        created = self._create(idem="outbound-binding-create")
        body = self._authorization_body(created)
        idempotency_key = "outbound-binding-check-0001"
        route = (
            "/api/matm/outbound-mcp/servers/%s/authorization-checks"
            % created["serverId"]
        )

        status, _headers, first = json_call(
            route,
            "POST",
            body,
            self._headers(idem=idempotency_key),
        )
        self.assertEqual("200 OK", status, first)
        authorization = first["authorization"]
        self.assertEqual(body["expectedServerRevision"], authorization["serverRevision"])
        self.assertEqual(
            body["expectedServerRevision"], authorization["expectedServerRevision"]
        )
        self.assertEqual(body["expectedConfigDigest"], authorization["configDigest"])
        self.assertEqual(
            body["expectedConfigDigest"], authorization["expectedConfigDigest"]
        )
        self.assertEqual(
            body["expectedPolicyRevision"], authorization["projectPolicyRevision"]
        )
        self.assertEqual(
            body["expectedPolicyRevision"], authorization["expectedPolicyRevision"]
        )
        self.assertEqual(body["toolName"], authorization["toolName"])
        self.assertEqual(body["argumentsDigest"], authorization["argumentsDigest"])

        status, _headers, replay = json_call(
            route,
            "POST",
            body,
            self._headers(idem=idempotency_key),
        )
        self.assertEqual("200 OK", status, replay)
        self.assertTrue(replay["idempotentReplay"])
        self.assertEqual(first["authorization"], replay["authorization"])

        changed_values = {
            "projectId": self.sibling_project_id,
            "expectedServerRevision": body["expectedServerRevision"] + 1,
            "expectedConfigDigest": "0" * 64,
            "expectedPolicyRevision": body["expectedPolicyRevision"] + 1,
            "toolName": "tools.list",
            "argumentsDigest": "b" * 64,
        }
        for field, value in changed_values.items():
            with self.subTest(changed_field=field):
                changed = dict(body)
                changed[field] = value
                status, _headers, conflict = json_call(
                    route,
                    "POST",
                    changed,
                    self._headers(idem=idempotency_key),
                )
                self.assertEqual("409 Conflict", status, conflict)

    def test_idempotency_conflict_and_missing_auth(self):
        self._create(idem="outbound-conflict-key")
        status, _headers, conflict = json_call(
            "/api/matm/outbound-mcp/servers",
            "POST",
            {
                "workspaceId": self.workspace_id,
                "projectId": self.project_id,
                "server": server(label="Different"),
            },
            self._headers(idem="outbound-conflict-key"),
        )
        self.assertEqual("409 Conflict", status, conflict)
        self.assertEqual("idempotency_conflict", conflict["status"])
        self.assertNotIn("_httpStatus", conflict)

        status, _headers, legacy_conflict = json_call(
            "/api/matm/projects",
            "POST",
            {
                "workspaceId": self.workspace_id,
                "projectId": self.sibling_project_id,
                "label": "Changed sibling label",
            },
            {
                "HTTP_AUTHORIZATION": "Bearer " + self.master,
                "HTTP_IDEMPOTENCY_KEY": "outbound-mcp-sibling-create-" + self.backend,
            },
        )
        self.assertEqual("409 Conflict", status, legacy_conflict)
        self.assertNotIn("_httpStatus", legacy_conflict)

        status, _headers, unauthenticated = json_call(
            "/api/matm/outbound-mcp/policy",
            query="workspace_id=%s&project_id=%s"
            % (self.workspace_id, self.project_id),
        )
        self.assertEqual("401 Unauthorized", status, unauthenticated)

    def test_authorization_replay_revalidates_disable_and_policy_changes(self):
        created = self._create(idem="outbound-revalidate-create")
        body = self._authorization_body(created)
        route = (
            "/api/matm/outbound-mcp/servers/%s/authorization-checks"
            % created["serverId"]
        )
        key = "outbound-revalidate-check"
        status, _headers, first = json_call(
            route, "POST", body, self._headers(idem=key)
        )
        self.assertEqual("200 OK", status, first)
        self.assertEqual("allowed", first["authorization"]["state"])

        status, _headers, disabled = json_call(
            "/api/matm/outbound-mcp/servers/%s/disable" % created["serverId"],
            "POST",
            {
                "workspaceId": self.workspace_id,
                "projectId": self.project_id,
                "expectedRevision": created["revision"],
            },
            self._headers(idem="outbound-revalidate-disable"),
        )
        self.assertEqual("200 OK", status, disabled)

        status, _headers, replay = json_call(
            route, "POST", body, self._headers(idem=key)
        )
        self.assertEqual("200 OK", status, replay)
        self.assertTrue(replay["idempotentReplay"])
        self.assertTrue(replay["authorizationRevalidated"])
        self.assertEqual("blocked", replay["authorization"]["state"])
        self.assertEqual("server_disabled", replay["authorization"]["reason"])

        policy_server = self._create(idem="outbound-revalidate-policy-create")
        policy_body = self._authorization_body(policy_server)
        policy_route = (
            "/api/matm/outbound-mcp/servers/%s/authorization-checks"
            % policy_server["serverId"]
        )
        policy_key = "outbound-revalidate-policy-check"
        status, _headers, first = json_call(
            policy_route,
            "POST",
            policy_body,
            self._headers(idem=policy_key),
        )
        self.assertEqual("200 OK", status, first)
        self.assertEqual("allowed", first["authorization"]["state"])

        policy, error = _store().set_outbound_mcp_project_policy(
            self.workspace_id,
            self.project_id,
            "human_required",
            0,
            forced_by_human=True,
            actor_id="human-policy-revalidator",
        )
        self.assertIsNone(error)
        self.assertEqual(1, policy["revision"])

        status, _headers, replay = json_call(
            policy_route,
            "POST",
            policy_body,
            self._headers(idem=policy_key),
        )
        self.assertEqual("200 OK", status, replay)
        self.assertEqual("blocked", replay["authorization"]["state"])
        self.assertEqual(
            "project_policy_revision_mismatch", replay["authorization"]["reason"]
        )

        audit = _store().company_audit_log(self.company_id)
        decisions = [
            item
            for item in audit
            if item.get("action") == "outbound_mcp.authorization.check"
        ]
        self.assertGreaterEqual(len(decisions), 4)
        self.assertTrue(all(not item.get("rawPayloadExposed") for item in decisions))

    def test_inactive_project_denies_every_outbound_surface(self):
        created = self._create(idem="outbound-inactive-create")
        self._set_project_status("soft_deleted")

        read_cases = (
            "/api/matm/outbound-mcp/policy",
            "/api/matm/outbound-mcp/servers",
            "/api/matm/outbound-mcp/servers/" + created["serverId"],
        )
        for path in read_cases:
            with self.subTest(path=path):
                status, _headers, payload = json_call(
                    path,
                    headers=self._headers(),
                    query="workspace_id=%s&project_id=%s"
                    % (self.workspace_id, self.project_id),
                )
                self.assertEqual("403 Forbidden", status, payload)
                self.assertEqual(
                    "outbound_mcp_scope_forbidden", payload["error"]["code"]
                )

        status, _headers, payload = json_call(
            "/api/matm/outbound-mcp/servers/%s/authorization-checks"
            % created["serverId"],
            "POST",
            self._authorization_body(created),
            self._headers(idem="outbound-inactive-check"),
        )
        self.assertEqual("403 Forbidden", status, payload)

    def test_outbound_rate_limit_is_persistent_and_fail_closed(self):
        original = outbound_mcp._RATE_POLICIES["outboundMcpRead"]
        outbound_mcp._RATE_POLICIES["outboundMcpRead"] = (1, 60)
        try:
            status, _headers, payload = json_call(
                "/api/matm/outbound-mcp/policy",
                headers=self._headers(),
                query="workspace_id=%s&project_id=%s"
                % (self.workspace_id, self.project_id),
            )
            self.assertEqual("200 OK", status, payload)
            status, response_headers, payload = json_call(
                "/api/matm/outbound-mcp/policy",
                headers=self._headers(),
                query="workspace_id=%s&project_id=%s"
                % (self.workspace_id, self.project_id),
            )
            self.assertEqual("429 Too Many Requests", status, payload)
            self.assertIn("Retry-After", response_headers)
            self.assertEqual(
                "outbound_mcp_rate_limited", payload["error"]["code"]
            )
        finally:
            outbound_mcp._RATE_POLICIES["outboundMcpRead"] = original

    def test_approval_cas_redacts_actor_and_authorizes_exact_revision(self):
        created = self._create(
            server(requested_mode="human_required"),
            idem="outbound-approval-cas-create",
        )
        denied, error = _store().set_outbound_mcp_project_policy(
            self.workspace_id,
            self.project_id,
            "human_required",
            0,
            forced_by_human=True,
        )
        self.assertIsNone(denied)
        self.assertEqual("outbound_mcp_human_actor_required", error)
        policy, error = _store().set_outbound_mcp_project_policy(
            self.workspace_id,
            self.project_id,
            "human_required",
            0,
            forced_by_human=True,
            actor_id="human-approval-reviewer",
        )
        self.assertIsNone(error)
        approved, error = _store().set_outbound_mcp_server_approval(
            self.workspace_id,
            self.project_id,
            created["serverId"],
            created["revision"],
            created["configDigest"],
            policy["revision"],
            created["approvalRevision"],
            "human-approval-reviewer",
            decision_reason="Approved exact bounded configuration",
        )
        self.assertIsNone(error)
        self.assertEqual(1, approved["approvalRevision"])
        self.assertNotIn("humanActorId", approved["approvalBinding"])

        stale, error = _store().set_outbound_mcp_server_approval(
            self.workspace_id,
            self.project_id,
            created["serverId"],
            created["revision"],
            created["configDigest"],
            policy["revision"],
            created["approvalRevision"],
            "human-stale-reviewer",
            status="denied",
        )
        self.assertIsNone(stale)
        self.assertEqual("outbound_mcp_revision_conflict", error)

        body = self._authorization_body(
            created, expectedPolicyRevision=policy["revision"]
        )
        status, _headers, payload = json_call(
            "/api/matm/outbound-mcp/servers/%s/authorization-checks"
            % created["serverId"],
            "POST",
            body,
            self._headers(idem="outbound-approval-cas-check"),
        )
        self.assertEqual("200 OK", status, payload)
        self.assertEqual("allowed", payload["authorization"]["state"])
        self.assertEqual(
            "exact_config_approved", payload["authorization"]["reason"]
        )

        snapshot = _store()._company_export_snapshot_data(
            _store()._load(), self.company_id
        )
        self.assertTrue(snapshot["collections"]["outboundMcpServers"])
        self.assertTrue(snapshot["collections"]["outboundMcpProjectPolicies"])
        audit = _store().company_audit_log(self.company_id)
        approvals = [
            item
            for item in audit
            if item.get("action") == "outbound_mcp.server.approval"
        ]
        self.assertEqual("human-approval-reviewer", approvals[-1]["actor"])


class FileOutboundMcpApiTests(OutboundMcpApiContract, unittest.TestCase):
    backend = "file"


class SQLiteOutboundMcpApiTests(OutboundMcpApiContract, unittest.TestCase):
    backend = "sqlite"


if __name__ == "__main__":
    unittest.main()
