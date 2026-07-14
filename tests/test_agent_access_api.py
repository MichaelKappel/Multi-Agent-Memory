import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import tempfile
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from app import application
from memoryendpoints.app import HUMAN_SESSION_COOKIE
from memoryendpoints.storage import FileStore, SQLiteStore


GOVERNED_CREDENTIAL = re.compile(r"me_(?:master|agent|invite)_v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


def call_api(path, method="GET", body=None, token=None, query="", extra_headers=None):
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    captured = {}

    def start_response(status, response_headers):
        captured["status"] = status
        captured["headers"] = dict(response_headers)

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "wsgi.input": io.BytesIO(raw),
        "CONTENT_LENGTH": str(len(raw)),
    }
    if token:
        environ["HTTP_AUTHORIZATION"] = "Bearer " + token
    for key, value in (extra_headers or {}).items():
        environ[key] = value
    response_body = b"".join(application(environ, start_response)).decode("utf-8")
    return int(captured["status"].split(" ", 1)[0]), captured["headers"], json.loads(response_body)


class GovernedAgentAccessApiContract:
    backend = None

    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="memoryendpoints-agent-access-%s-" % self.backend)
        self.store_path = Path(self.tempdir) / "matm.json"
        self.sqlite_path = Path(self.tempdir) / "matm.sqlite3"
        self._saved_environment = {
            key: os.environ.get(key)
            for key in (
                "MEMORYENDPOINTS_STORE_BACKEND",
                "MEMORYENDPOINTS_STORE_PATH",
                "MEMORYENDPOINTS_SQLITE_PATH",
                "MEMORYENDPOINTS_CREDENTIAL_PEPPER",
                "MEMORYENDPOINTS_CREDENTIAL_CONFIG_PATH",
                "MEMORYENDPOINTS_MYSQL_CONFIG_PATH",
            )
        }
        os.environ.update(
            {
                "MEMORYENDPOINTS_STORE_BACKEND": self.backend,
                "MEMORYENDPOINTS_STORE_PATH": str(self.store_path),
                "MEMORYENDPOINTS_SQLITE_PATH": str(self.sqlite_path),
                "MEMORYENDPOINTS_CREDENTIAL_PEPPER": "test-only-agent-access-pepper-" + ("x" * 64),
                "MEMORYENDPOINTS_CREDENTIAL_CONFIG_PATH": str(Path(self.tempdir) / "missing-pepper.json"),
                "MEMORYENDPOINTS_MYSQL_CONFIG_PATH": str(Path(self.tempdir) / "missing-mysql.json"),
            }
        )
        self.account = self._create_account("GamesFor.me", "Escape.GamesFor.me", "mental Hospital")
        self.company_id = self.account["companyId"]
        self.workspace_id = self.account["workspaceId"]
        self.project_id = self.account["projectId"]
        self.master_token = self.account["companyMasterTokenSecret"]

    def tearDown(self):
        for key, value in self._saved_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def _create_account(self, company_label, workspace_label, project_label):
        status, headers, payload = call_api(
            "/api/matm/agent-setup/free-account",
            "POST",
            {
                "companyLabel": company_label,
                "label": workspace_label,
                "projectLabel": project_label,
            },
        )
        self.assertEqual(201, status, payload)
        self.assertTrue(payload["ok"])
        self.assertIn("companyMasterTokenSecret", payload)
        self.assertNotIn("apiKeySecret", payload)
        self.assertNotIn("keySecret", payload)
        self.assertRegex(payload["companyMasterTokenSecret"], r"^me_master_v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
        self._assert_one_time_secret_headers(headers)
        return payload

    def _request_body(
        self,
        requested_name="escape-game-agent",
        display_name="Escape Game Agent",
        scope_type="workspace",
        scope_id=None,
        supersedes_credential_id=None,
        memory_transfer_from_credential_id=None,
    ):
        body = {
            "requestedName": requested_name,
            "displayName": display_name,
            "requestedGrant": {
                "scopeType": scope_type,
                "scopeId": scope_id or self.workspace_id,
            },
            "assignmentContext": {
                "projectId": self.project_id,
                "taskId": "initial-game-setup",
                "taskLabel": "Initial game setup",
            },
            "justification": "Join Escape.GamesFor.me to perform the initial mental Hospital game setup.",
        }
        if supersedes_credential_id:
            body["supersedesCredentialId"] = supersedes_credential_id
        if memory_transfer_from_credential_id:
            body["memoryTransferFromCredentialId"] = memory_transfer_from_credential_id
        return body

    def _request_access(self, token=None, **overrides):
        status, _headers, payload = call_api(
            "/api/matm/access/agent-name-requests",
            "POST",
            self._request_body(**overrides),
            token or self.master_token,
        )
        self.assertEqual(201, status, payload)
        self.assertTrue(payload["ok"])
        self.assertEqual("pending", payload["request"]["status"])
        self._assert_no_governed_credential(payload)
        return payload["request"]

    def _approve(self, request_id, token=None):
        status, _headers, payload = call_api(
            "/api/matm/access/agent-name-requests/%s/decision" % request_id,
            "POST",
            {"decision": "approve", "decisionReason": "Approved for the initial game setup."},
            token or self.master_token,
        )
        self.assertEqual(200, status, payload)
        self.assertTrue(payload["ok"])
        self.assertEqual("approved", payload["request"]["status"])
        self._assert_no_governed_credential(payload)
        return payload["request"]

    def _issue(self, request_id, token=None, expires_in_seconds=900):
        status, headers, payload = call_api(
            "/api/matm/access/invites",
            "POST",
            {"approvedRequestId": request_id, "expiresInSeconds": expires_in_seconds},
            token or self.master_token,
        )
        self.assertEqual(201, status, payload)
        self.assertTrue(payload["ok"])
        self.assertNotIn("inviteSecret", payload)
        self.assertIn("inviteUrl", payload)
        self._assert_one_time_secret_headers(headers)
        invite_url = urlsplit(payload["inviteUrl"])
        self.assertEqual("https", invite_url.scheme)
        self.assertEqual("memoryendpoints.com", invite_url.netloc)
        self.assertEqual("/agent-setup", invite_url.path)
        self.assertEqual("", invite_url.query)
        fragment = parse_qs(invite_url.fragment, strict_parsing=True)
        self.assertEqual(["invite"], list(fragment))
        invite_secret = fragment["invite"][0]
        self.assertRegex(invite_secret, r"^me_invite_v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
        self.assertEqual(invite_secret, payload["inviteUrl"].split("#invite=", 1)[1])
        self.assertEqual("issued", payload["invite"]["status"])
        self.assertTrue(payload["invite"]["singleUse"])
        return payload, invite_secret

    def _redeem(self, invite_secret, expected_status=201):
        status, headers, payload = call_api(
            "/api/matm/access/invites/redeem",
            "POST",
            {"inviteSecret": invite_secret},
        )
        self.assertEqual(expected_status, status, payload)
        if expected_status == 201:
            self.assertTrue(payload["ok"])
            self.assertRegex(payload["agentTokenSecret"], r"^me_agent_v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
            self._assert_one_time_secret_headers(headers)
        return payload

    def _provision_agent(self, **request_overrides):
        request = self._request_access(**request_overrides)
        self._approve(request["requestId"])
        issued, invite_secret = self._issue(request["requestId"])
        redeemed = self._redeem(invite_secret)
        return {
            "request": request,
            "issued": issued,
            "inviteSecret": invite_secret,
            "redeemed": redeemed,
            "agentTokenSecret": redeemed["agentTokenSecret"],
            "principal": redeemed["principal"],
        }

    def _assert_one_time_secret_headers(self, headers):
        self.assertIn("no-store", headers.get("Cache-Control", ""))
        self.assertIn("private", headers.get("Cache-Control", ""))
        self.assertEqual("no-cache", headers.get("Pragma"))
        self.assertEqual("no-referrer", headers.get("Referrer-Policy"))

    def _assert_no_governed_credential(self, payload):
        encoded = json.dumps(payload, sort_keys=True)
        self.assertIsNone(GOVERNED_CREDENTIAL.search(encoded), encoded)
        self.assertNotIn("agentTokenSecret", encoded)
        self.assertNotIn("companyMasterTokenSecret", encoded)
        self.assertNotIn("inviteSecret", encoded)

    def _assert_error(self, status, payload, expected_status, code):
        self.assertEqual(expected_status, status, payload)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["safeNoOp"])
        self.assertEqual(code, payload["error"]["code"])
        self._assert_no_governed_credential(payload)

    def _expire_invite(self, invite_id):
        if self.backend == "sqlite":
            with closing(sqlite3.connect(self.sqlite_path)) as connection:
                with connection:
                    connection.execute(
                        "UPDATE matm_agent_invites SET expires_at = ? WHERE invite_id = ?",
                        ("2000-01-01T00:00:00.000000Z", invite_id),
                    )
            return
        data = json.loads(self.store_path.read_text(encoding="utf-8"))
        data["agentInvites"][invite_id]["expiresAt"] = "2000-01-01T00:00:00.000000Z"
        self.store_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def _access_counts(self):
        if self.backend == "sqlite":
            with closing(sqlite3.connect(self.sqlite_path)) as connection:
                return tuple(
                    connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                    for table in (
                        "matm_agent_identities",
                        "matm_agent_access_grants",
                        "matm_agent_tokens",
                        "matm_agent_invites",
                    )
                )
        data = json.loads(self.store_path.read_text(encoding="utf-8"))
        return tuple(
            len(data.get(key, {}))
            for key in ("agentIdentities", "agentAccessGrants", "agentTokens", "agentInvites")
        )

    def _assert_not_persisted(self, *credentials):
        persisted = b"\n".join(path.read_bytes() for path in Path(self.tempdir).rglob("*") if path.is_file())
        for credential in credentials:
            self.assertNotIn(credential.encode("utf-8"), persisted)
            secret_component = credential.rsplit(".", 1)[-1]
            self.assertNotIn(secret_component.encode("utf-8"), persisted)

    def _candidate_master(self):
        return "me_master_v1.masterkey-%s.%s" % (
            uuid.uuid4().hex[:20],
            secrets.token_urlsafe(32),
        )

    def _delegate_master(
        self,
        candidate=None,
        idempotency_key="company-master-recovery-00000001",
        workspace_id=None,
        token=None,
        body_overrides=None,
        expected_status=201,
    ):
        candidate = candidate or self._candidate_master()
        body = {
            "schemaVersion": "memoryendpoints.company_master_delegation.v1",
            "workspaceId": workspace_id or self.workspace_id,
            "candidateTokenSecret": candidate,
            "label": "Human recovery master",
            "principalName": "human-recovery",
        }
        body.update(body_overrides or {})
        status, headers, payload = call_api(
            "/api/matm/access/company-master-credentials",
            "POST",
            body,
            token or self.master_token,
            extra_headers={"HTTP_IDEMPOTENCY_KEY": idempotency_key}
            if idempotency_key is not None
            else None,
        )
        self.assertEqual(expected_status, status, payload)
        return candidate, headers, payload

    def test_free_setup_returns_master_secret_and_me_reports_master_capabilities(self):
        self.assertIn("credentialId", self.account)
        status, _headers, payload = call_api(
            "/api/matm/me",
            token=self.master_token,
            query="workspace_id=" + self.workspace_id,
        )
        self.assertEqual(200, status, payload)
        self.assertEqual("company_master", payload["principal"]["credentialType"])
        self.assertEqual(self.company_id, payload["principal"]["companyId"])
        self.assertTrue(payload["principal"]["permissions"]["canIssueAgentInvites"])
        self.assertTrue(payload["principal"]["permissions"]["canRevokeAgentTokens"])
        self.assertTrue(payload["principal"]["masterCompanyAgentCredential"])
        self.assertFalse(payload["principal"]["ordinaryAgentCredential"])
        self.assertTrue(
            payload["principal"]["permissions"][
                "canDelegateCompanyMasterCredentials"
            ]
        )
        self.assertIn(
            "company_master_credentials:delegate",
            payload["principal"]["capabilities"],
        )
        self._assert_no_governed_credential(payload)

    def test_company_master_can_delegate_crash_safe_sibling_for_human(self):
        candidate, headers, delegated = self._delegate_master()
        candidate_id = candidate.split(".", 2)[1]
        self.assertTrue(delegated["ok"])
        self.assertTrue(delegated["credentialAccepted"])
        self.assertFalse(delegated["credentialReturned"])
        self.assertFalse(delegated["rawCredentialPersisted"])
        self.assertFalse(delegated["idempotentReplay"])
        self.assertEqual(
            candidate_id,
            delegated["companyMasterCredential"]["masterKeyId"],
        )
        self.assertEqual(
            "delegated_recovery",
            delegated["companyMasterCredential"]["issuanceKind"],
        )
        self.assertEqual(
            self.workspace_id,
            delegated["companyMasterCredential"]["delegatedForWorkspaceId"],
        )
        self.assertIn("no-store", headers.get("Cache-Control", ""))
        self._assert_no_governed_credential(delegated)

        status, _headers, candidate_me = call_api(
            "/api/matm/me", token=candidate, query="workspace_id=" + self.workspace_id
        )
        self.assertEqual(200, status, candidate_me)
        self.assertEqual("company_master", candidate_me["principal"]["credentialType"])
        self.assertEqual(self.company_id, candidate_me["principal"]["companyId"])
        self.assertTrue(candidate_me["principal"]["masterCompanyAgentCredential"])

        status, _headers, issuer_me = call_api(
            "/api/matm/me", token=self.master_token
        )
        self.assertEqual(200, status, issuer_me)
        status, _headers, inventory = call_api(
            "/api/matm/access/company-master-credentials",
            token=candidate,
        )
        self.assertEqual(200, status, inventory)
        self.assertEqual(2, inventory["count"])
        self.assertEqual(
            {self.account["credentialId"], candidate_id},
            {item["masterKeyId"] for item in inventory["items"]},
        )
        self._assert_no_governed_credential(inventory)
        self._assert_not_persisted(self.master_token, candidate)

    def test_company_master_delegation_replays_exactly_and_conflicts_safely(self):
        candidate = self._candidate_master()
        key = "company-master-recovery-replay-0001"
        _candidate, _headers, first = self._delegate_master(
            candidate=candidate, idempotency_key=key
        )
        _candidate, _headers, replay = self._delegate_master(
            candidate=candidate,
            idempotency_key=key,
            expected_status=200,
        )
        self.assertFalse(first["idempotentReplay"])
        self.assertTrue(replay["idempotentReplay"])
        self.assertEqual(
            first["companyMasterCredential"], replay["companyMasterCredential"]
        )

        _candidate, _headers, conflict = self._delegate_master(
            candidate=self._candidate_master(),
            idempotency_key=key,
            expected_status=409,
        )
        self._assert_error(409, conflict, 409, "idempotency_conflict")
        status, _headers, inventory = call_api(
            "/api/matm/access/company-master-credentials", token=self.master_token
        )
        self.assertEqual(200, status, inventory)
        self.assertEqual(2, inventory["count"])
        self._assert_not_persisted(self.master_token, candidate)

    def test_company_master_delegation_rejects_spoofing_and_invalid_contracts(self):
        second = self._create_account(
            "Other Recovery Company", "Other Recovery Workspace", "Other Project"
        )
        candidate = self._candidate_master()
        _candidate, _headers, cross_company = self._delegate_master(
            candidate=candidate,
            workspace_id=second["workspaceId"],
            idempotency_key="company-master-cross-company-0001",
            expected_status=404,
        )
        self._assert_error(404, cross_company, 404, "workspace_not_found")

        cases = (
            (
                "missing-idempotency",
                None,
                {},
                422,
                "idempotency_key_required",
            ),
            (
                "weak-idempotency",
                "weak",
                {},
                422,
                "idempotency_key_invalid",
            ),
            (
                "wrong-schema",
                "company-master-invalid-schema-0001",
                {"schemaVersion": "memoryendpoints.company_master_delegation.v2"},
                422,
                "company_master_delegation_invalid",
            ),
            (
                "unknown-field",
                "company-master-unknown-field-0001",
                {"companyId": self.company_id},
                422,
                "company_master_delegation_invalid",
            ),
            (
                "wrong-kind",
                "company-master-wrong-kind-0001",
                {
                    "candidateTokenSecret": "me_agent_v1.agenttoken-%s.%s"
                    % (uuid.uuid4().hex[:20], secrets.token_urlsafe(32))
                },
                422,
                "company_master_candidate_invalid",
            ),
        )
        for name, key, overrides, expected_status, expected_code in cases:
            with self.subTest(name=name):
                _candidate, _headers, payload = self._delegate_master(
                    candidate=self._candidate_master(),
                    idempotency_key=key,
                    body_overrides=overrides,
                    expected_status=expected_status,
                )
                self._assert_error(
                    expected_status, payload, expected_status, expected_code
                )
        self._assert_not_persisted(candidate, second["companyMasterTokenSecret"])

    def test_company_is_auth_derived_and_approval_is_separate_from_issuance(self):
        invalid_body = self._request_body(requested_name="spoofed-company-agent")
        invalid_body["companyId"] = "company-attacker-controlled"
        status, _headers, payload = call_api(
            "/api/matm/access/agent-name-requests",
            "POST",
            invalid_body,
            self.master_token,
        )
        self.assertEqual(201, status, payload)
        self.assertEqual(self.company_id, payload["request"]["companyId"])
        self.assertNotEqual("company-attacker-controlled", payload["request"]["companyId"])

        request = self._request_access()
        status, _headers, payload = call_api(
            "/api/matm/access/invites",
            "POST",
            {"approvedRequestId": request["requestId"], "expiresInSeconds": 900},
            self.master_token,
        )
        self._assert_error(status, payload, 409, "agent_name_request_not_approved")

        approved = self._approve(request["requestId"])
        self.assertEqual(self.company_id, approved["companyId"])
        issued, _secret = self._issue(request["requestId"])
        self.assertEqual(self.workspace_id, issued["invite"]["scopeId"])
        self.assertEqual("workspace", issued["invite"]["scopeType"])
        self.assertEqual("initial-game-setup", issued["invite"]["assignmentContext"]["taskId"])

    def test_agent_tokens_cannot_manage_access_or_use_non_bearer_auth(self):
        provisioned = self._provision_agent()
        agent_token = provisioned["agentTokenSecret"]
        request_id = provisioned["request"]["requestId"]
        invite_id = provisioned["issued"]["invite"]["inviteId"]
        credential_id = provisioned["principal"]["credentialId"]
        management_calls = (
            ("POST", "/api/matm/access/agent-name-requests", self._request_body(requested_name="forbidden-agent"), "company_master_required"),
            ("POST", "/api/matm/access/agent-name-requests/%s/decision" % request_id, {"decision": "deny", "decisionReason": "forbidden"}, "company_master_required"),
            ("POST", "/api/matm/access/invites", {"approvedRequestId": request_id, "expiresInSeconds": 900}, "company_master_required"),
            ("GET", "/api/matm/access/invites", None, "company_master_required"),
            ("POST", "/api/matm/access/invites/%s/revoke" % invite_id, {}, "company_master_required"),
            ("GET", "/api/matm/access/agent-tokens", None, "company_master_required"),
            ("POST", "/api/matm/access/agent-tokens/%s/revoke" % credential_id, {}, "company_master_required"),
            ("GET", "/api/matm/access/company-master-credentials", None, "company_master_required"),
            (
                "POST",
                "/api/matm/access/company-master-credentials",
                {
                    "schemaVersion": "memoryendpoints.company_master_delegation.v1",
                    "workspaceId": self.workspace_id,
                    "candidateTokenSecret": self._candidate_master(),
                    "label": "Forbidden recovery",
                    "principalName": "ordinary-agent",
                },
                "top_level_agent_required",
            ),
        )
        for method, path, body, expected_code in management_calls:
            with self.subTest(method=method, path=path):
                status, _headers, payload = call_api(path, method, body, agent_token)
                self._assert_error(status, payload, 403, expected_code)

        status, _headers, payload = call_api(
            "/api/matm/access/invites",
            "GET",
            extra_headers={"HTTP_X_API_KEY": self.master_token},
        )
        self._assert_error(status, payload, 401, "invalid_token")

    def test_redeem_replay_is_gone_and_does_not_duplicate_identity_or_inventory(self):
        request = self._request_access()
        self._approve(request["requestId"])
        issued, invite_secret = self._issue(request["requestId"])
        redeemed = self._redeem(invite_secret)
        before_counts = self._access_counts()
        status, _headers, inventory_before = call_api(
            "/api/matm/access/agent-tokens", "GET", token=self.master_token
        )
        self.assertEqual(200, status, inventory_before)

        status, _headers, replay = call_api(
            "/api/matm/access/invites/redeem",
            "POST",
            {"inviteSecret": invite_secret},
        )
        self._assert_error(status, replay, 410, "invite_redeemed")
        self.assertNotIn("agentTokenSecret", replay)

        status, _headers, inventory_after = call_api(
            "/api/matm/access/agent-tokens", "GET", token=self.master_token
        )
        self.assertEqual(200, status, inventory_after)
        self.assertEqual(len(inventory_before["items"]), len(inventory_after["items"]))
        self.assertEqual(before_counts, self._access_counts())
        self._assert_not_persisted(self.master_token, invite_secret, redeemed["agentTokenSecret"])
        self.assertEqual(issued["invite"]["inviteId"], redeemed["invite"]["inviteId"])

    def test_expired_and_revoked_invites_never_issue_agent_credentials(self):
        expired_request = self._request_access(requested_name="expiring-escape-agent")
        self._approve(expired_request["requestId"])
        expired_issue, expired_secret = self._issue(expired_request["requestId"], expires_in_seconds=60)
        self._expire_invite(expired_issue["invite"]["inviteId"])
        status, _headers, expired = call_api(
            "/api/matm/access/invites/redeem", "POST", {"inviteSecret": expired_secret}
        )
        self._assert_error(status, expired, 410, "invite_expired")

        revoked_request = self._request_access(requested_name="revoked-invite-agent")
        self._approve(revoked_request["requestId"])
        revoked_issue, revoked_secret = self._issue(revoked_request["requestId"])
        invite_id = revoked_issue["invite"]["inviteId"]
        status, _headers, revoked = call_api(
            "/api/matm/access/invites/%s/revoke" % invite_id,
            "POST",
            {},
            self.master_token,
        )
        self.assertEqual(200, status, revoked)
        self.assertEqual("revoked", revoked["invite"]["status"])
        self._assert_no_governed_credential(revoked)
        status, _headers, rejected = call_api(
            "/api/matm/access/invites/redeem", "POST", {"inviteSecret": revoked_secret}
        )
        self._assert_error(status, rejected, 410, "invite_revoked")

    def test_workspace_agent_is_bound_to_name_scope_and_workspace_rooms_only(self):
        provisioned = self._provision_agent()
        principal = provisioned["principal"]
        agent_token = provisioned["agentTokenSecret"]
        self.assertEqual("agent_token", principal["credentialType"])
        self.assertEqual("escape-game-agent", principal["agentId"])
        self.assertNotEqual(principal["agentId"], principal["agentIdentityId"])
        self.assertEqual("workspace", principal["grant"]["scopeType"])
        self.assertEqual(self.workspace_id, principal["grant"]["scopeId"])
        self.assertFalse(principal["permissions"]["canIssueAgentInvites"])
        self.assertFalse(principal["permissions"]["canRevokeAgentTokens"])

        status, _headers, me = call_api(
            "/api/matm/me", token=agent_token, query="workspace_id=" + self.workspace_id
        )
        self.assertEqual(200, status, me)
        self.assertEqual(principal["agentIdentityId"], me["principal"]["agentIdentityId"])
        self.assertEqual(principal["credentialId"], me["principal"]["credentialId"])
        self._assert_no_governed_credential(me)

        status, _headers, master_rooms = call_api(
            "/api/matm/meeting-rooms",
            token=self.master_token,
            query="workspace_id=%s" % self.workspace_id,
        )
        self.assertEqual(200, status, master_rooms)
        company_room = next(room for room in master_rooms["items"] if room["scope"] == "company")

        status, _headers, agent_rooms = call_api(
            "/api/matm/meeting-rooms",
            token=agent_token,
            query="workspace_id=%s&agent_id=%s" % (self.workspace_id, principal["agentId"]),
        )
        self.assertEqual(200, status, agent_rooms)
        scopes = {room["scope"] for room in agent_rooms["items"]}
        self.assertNotIn("company", scopes)
        self.assertIn("workspace", scopes)
        self.assertIn("project", scopes)
        workspace_room = next(room for room in agent_rooms["items"] if room["scope"] == "workspace")

        status, _headers, denied = call_api(
            "/api/matm/meeting-messages",
            token=agent_token,
            query="workspace_id=%s&room_id=%s&agent_id=%s"
            % (self.workspace_id, company_room["roomId"], principal["agentId"]),
        )
        self._assert_error(status, denied, 403, "insufficient_scope")

        status, _headers, posted = call_api(
            "/api/matm/meeting-messages",
            "POST",
            {
                "workspaceId": self.workspace_id,
                "roomId": workspace_room["roomId"],
                "senderAgentId": principal["agentId"],
                "safeSummary": "Escape Game agent joined the workspace for initial setup.",
            },
            agent_token,
        )
        self.assertEqual(201, status, posted)
        self.assertEqual(principal["agentId"], posted["message"]["senderAgentId"])

        status, _headers, impersonation = call_api(
            "/api/matm/meeting-messages",
            "POST",
            {
                "workspaceId": self.workspace_id,
                "roomId": workspace_room["roomId"],
                "senderAgentId": "different-agent",
                "safeSummary": "This must not be persisted.",
            },
            agent_token,
        )
        self._assert_error(status, impersonation, 403, "principal_mismatch")

    def test_agent_scope_is_immutable_and_other_company_workspace_is_denied(self):
        provisioned = self._provision_agent()
        agent_token = provisioned["agentTokenSecret"]
        second = self._create_account("Other Company", "Other Workspace", "Other Project")
        status, _headers, payload = call_api(
            "/api/matm/workspace",
            token=agent_token,
            query="workspace_id=" + second["workspaceId"],
        )
        self._assert_error(status, payload, 403, "insufficient_scope")

        status, _headers, me = call_api(
            "/api/matm/me", token=agent_token, query="workspace_id=" + self.workspace_id
        )
        self.assertEqual(200, status, me)
        self.assertEqual("workspace", me["principal"]["grant"]["scopeType"])
        self.assertEqual(self.workspace_id, me["principal"]["grant"]["scopeId"])
        self._assert_not_persisted(
            self.master_token,
            second["companyMasterTokenSecret"],
            provisioned["inviteSecret"],
            agent_token,
        )

    def test_master_inventory_is_metadata_only_and_agent_token_revocation_is_immediate(self):
        provisioned = self._provision_agent()
        agent_token = provisioned["agentTokenSecret"]
        credential_id = provisioned["principal"]["credentialId"]

        status, _headers, invites = call_api(
            "/api/matm/access/invites", "GET", token=self.master_token
        )
        self.assertEqual(200, status, invites)
        self.assertTrue(any(item["inviteId"] == provisioned["issued"]["invite"]["inviteId"] for item in invites["items"]))
        self._assert_no_governed_credential(invites)

        status, _headers, credentials = call_api(
            "/api/matm/access/agent-tokens", "GET", token=self.master_token
        )
        self.assertEqual(200, status, credentials)
        self.assertTrue(any(item["credentialId"] == credential_id for item in credentials["items"]))
        self._assert_no_governed_credential(credentials)

        status, _headers, revoked = call_api(
            "/api/matm/access/agent-tokens/%s/revoke" % credential_id,
            "POST",
            {},
            self.master_token,
        )
        self.assertEqual(200, status, revoked)
        self.assertEqual(credential_id, revoked["credentialId"])
        self._assert_no_governed_credential(revoked)

        status, _headers, rejected = call_api(
            "/api/matm/me", token=agent_token, query="workspace_id=" + self.workspace_id
        )
        self._assert_error(status, rejected, 401, "invalid_token")

    def test_agent_name_uniqueness_is_company_scoped_and_invites_are_globally_unique(self):
        first = self._provision_agent()
        duplicate_body = self._request_body(display_name="Same Name, Different Display")
        status, _headers, duplicate = call_api(
            "/api/matm/access/agent-name-requests", "POST", duplicate_body, self.master_token
        )
        self._assert_error(status, duplicate, 409, "agent_name_unavailable")

        second_account = self._create_account("Second Games Company", "Second Workspace", "Second Project")
        second_request_body = self._request_body()
        second_request_body["requestedGrant"]["scopeId"] = second_account["workspaceId"]
        second_request_body["assignmentContext"]["projectId"] = second_account["projectId"]
        status, _headers, second_requested = call_api(
            "/api/matm/access/agent-name-requests",
            "POST",
            second_request_body,
            second_account["companyMasterTokenSecret"],
        )
        self.assertEqual(201, status, second_requested)
        second_request_id = second_requested["request"]["requestId"]
        status, _headers, second_approved = call_api(
            "/api/matm/access/agent-name-requests/%s/decision" % second_request_id,
            "POST",
            {"decision": "approve", "decisionReason": "Company-scoped name is available."},
            second_account["companyMasterTokenSecret"],
        )
        self.assertEqual(200, status, second_approved)
        status, _headers, second_issue = call_api(
            "/api/matm/access/invites",
            "POST",
            {"approvedRequestId": second_request_id, "expiresInSeconds": 900},
            second_account["companyMasterTokenSecret"],
        )
        self.assertEqual(201, status, second_issue)
        second_fragment = parse_qs(urlsplit(second_issue["inviteUrl"]).fragment)["invite"][0]
        second_redeemed = self._redeem(second_fragment)

        self.assertEqual("escape-game-agent", first["principal"]["agentId"])
        self.assertEqual("escape-game-agent", second_redeemed["principal"]["agentId"])
        self.assertNotEqual(first["principal"]["agentIdentityId"], second_redeemed["principal"]["agentIdentityId"])
        self.assertNotEqual(first["issued"]["invite"]["inviteId"], second_issue["invite"]["inviteId"])
        self.assertNotEqual(first["inviteSecret"], second_fragment)

    def test_replacement_preserves_identity_and_prior_memory_with_explicit_transfer_link(self):
        original = self._provision_agent()
        original_principal = original["principal"]
        status, _headers, submitted = call_api(
            "/api/matm/memory-events/submit",
            "POST",
            {
                "workspaceId": self.workspace_id,
                "actorAgentId": original_principal["agentId"],
                "scope": "workspace",
                "scopeId": self.workspace_id,
                "memoryType": "handoff",
                "title": "Initial game setup continuity",
                "summary": "The mental Hospital initial game setup remains assigned to the Escape Game agent.",
                "tags": ["credential-replacement", "initial-game-setup"],
            },
            original["agentTokenSecret"],
            extra_headers={"HTTP_IDEMPOTENCY_KEY": "replacement-memory-before-upgrade"},
        )
        self.assertEqual(201, status, submitted)
        event_id = submitted["event"]["eventId"]

        replacement_request = self._request_access(
            requested_name=original_principal["agentId"],
            scope_type="company",
            scope_id=self.company_id,
            supersedes_credential_id=original_principal["credentialId"],
            memory_transfer_from_credential_id=original_principal["credentialId"],
        )
        self._approve(replacement_request["requestId"])
        _issued, replacement_secret = self._issue(replacement_request["requestId"])
        replacement = self._redeem(replacement_secret)
        replacement_principal = replacement["principal"]

        self.assertEqual(original_principal["agentId"], replacement_principal["agentId"])
        self.assertEqual(original_principal["agentIdentityId"], replacement_principal["agentIdentityId"])
        self.assertNotEqual(original_principal["credentialId"], replacement_principal["credentialId"])
        self.assertEqual(original_principal["grant"]["grantId"], replacement_principal["grant"]["grantId"])
        self.assertEqual(original_principal["credentialId"], replacement_principal["grant"]["supersedesCredentialId"])
        self.assertEqual(original_principal["credentialId"], replacement_principal["grant"]["memoryTransferFromCredentialId"])
        self.assertEqual("company", replacement_principal["grant"]["scopeType"])

        status, _headers, retired = call_api("/api/matm/me", token=original["agentTokenSecret"])
        self.assertEqual(401, status, retired)
        self.assertEqual("invalid_token", retired["error"]["code"])

        status, _headers, review_queue = call_api(
            "/api/matm/review-queue",
            token=replacement["agentTokenSecret"],
            query="workspace_id=%s&actor_agent_id=%s" % (self.workspace_id, original_principal["agentId"]),
        )
        self.assertEqual(200, status, review_queue)
        self.assertTrue(any(item["memoryEventId"] == event_id for item in review_queue["items"]))

    def test_scope_catalog_requires_master_and_never_selects_a_workspace_implicitly(self):
        status, _headers, catalog = call_api(
            "/api/matm/access/scope-catalog", token=self.master_token
        )
        self.assertEqual(200, status, catalog)
        self.assertEqual(self.company_id, catalog["company"]["companyId"])
        self.assertTrue(any(item["workspaceId"] == self.workspace_id for item in catalog["workspaces"]))
        self.assertTrue(any(item["projectId"] == self.project_id for item in catalog["projects"]))
        self._assert_no_governed_credential(catalog)

        provisioned = self._provision_agent(requested_name="catalog-denied-agent")
        status, _headers, denied = call_api(
            "/api/matm/access/scope-catalog", token=provisioned["agentTokenSecret"]
        )
        self._assert_error(status, denied, 403, "company_master_required")

    def test_project_agent_receives_authorized_parent_resource_context(self):
        provisioned = self._provision_agent(
            requested_name="mental-hospital-project-agent",
            display_name="Mental Hospital Project Agent",
            scope_type="project",
            scope_id=self.project_id,
        )
        principal = provisioned["principal"]
        self.assertEqual("project", principal["grant"]["scopeType"])
        self.assertEqual(self.project_id, principal["resourceContext"]["projectId"])
        self.assertEqual(self.workspace_id, principal["resourceContext"]["workspaceId"])

        status, _headers, me = call_api("/api/matm/me", token=provisioned["agentTokenSecret"])
        self.assertEqual(200, status, me)
        self.assertEqual(self.project_id, me["principal"]["resourceContext"]["projectId"])
        self.assertEqual(self.workspace_id, me["principal"]["resourceContext"]["workspaceId"])

    def test_reusing_the_exact_same_invite_url_is_terminal(self):
        request = self._request_access(requested_name="exact-url-replay-agent")
        self._approve(request["requestId"])
        issued, _invite_secret = self._issue(request["requestId"])
        exact_invite_url = issued["inviteUrl"]

        first_secret = parse_qs(urlsplit(exact_invite_url).fragment, strict_parsing=True)["invite"][0]
        first = self._redeem(first_secret)
        counts_after_first = self._access_counts()

        second_secret = parse_qs(urlsplit(exact_invite_url).fragment, strict_parsing=True)["invite"][0]
        self.assertEqual(first_secret, second_secret)
        status, _headers, replay = call_api(
            "/api/matm/access/invites/redeem", "POST", {"inviteSecret": second_secret}
        )
        self._assert_error(status, replay, 410, "invite_redeemed")
        self.assertNotIn("agentTokenSecret", replay)
        self.assertEqual(counts_after_first, self._access_counts())
        self._assert_not_persisted(first_secret, first["agentTokenSecret"])

    def _top_level_master_candidate(self):
        return "me_master_v1.masterkey-%s.%s" % (
            uuid.uuid4().hex[:20],
            secrets.token_urlsafe(32),
        )

    def _register_top_level_master(self, agent_token, candidate=None, expected=201):
        candidate = candidate or self._top_level_master_candidate()
        status, headers, payload = call_api(
            "/api/matm/access/company-master-credentials",
            "POST",
            {
                "schemaVersion": "memoryendpoints.top_level_agent_company_master.v1",
                "workspaceId": self.workspace_id,
                "candidateTokenSecret": candidate,
                "label": "Human operator master",
                "principalName": "human-operator",
            },
            agent_token,
            extra_headers={"HTTP_IDEMPOTENCY_KEY": "top-level-agent-" + uuid.uuid4().hex},
        )
        self.assertEqual(expected, status, payload)
        return candidate, headers, payload

    def _selected_human_owner_session(self):
        store = SQLiteStore(self.sqlite_path) if self.backend == "sqlite" else FileStore(self.store_path)
        proof = store.create_company_master_proof(self.master_token)
        created = store.create_human_account_with_session(
            "operator-owner-" + uuid.uuid4().hex[:8],
            "Valid-human-password-%s!" % secrets.token_urlsafe(24),
            proof["masterProofSecret"],
            "Operator Owner",
        )
        self.assertTrue(created["ok"], created)
        selected = store.select_human_company_membership(
            created["sessionSecret"], created["membership"]["authorityId"]
        )
        self.assertTrue(selected["ok"], selected)
        return selected

    def test_company_scoped_agent_can_register_crash_safe_human_operator_master(self):
        top_level = self._provision_agent(
            requested_name="company-operator-agent",
            scope_type="company",
            scope_id=self.company_id,
        )
        candidate, headers, payload = self._register_top_level_master(
            top_level["agentTokenSecret"]
        )
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["topLevelAgentMasterCredentialEnabled"])
        self.assertEqual(
            "top_level_agent_human_operator",
            payload["companyMasterCredential"]["issuanceKind"],
        )
        self.assertEqual("agent", payload["companyMasterCredential"]["issuedByCredentialType"])
        self.assertNotIn(candidate, json.dumps(payload, sort_keys=True))
        self.assertIn("no-store", headers.get("Cache-Control", ""))
        status, _headers, me = call_api(
            "/api/matm/me",
            token=candidate,
            query="workspace_id=" + self.workspace_id,
        )
        self.assertEqual(200, status, me)
        self.assertEqual("company_master", me["principal"]["credentialType"])

        lower = self._provision_agent(requested_name="lower-scope-recovery-agent")
        _candidate, _headers, denied = self._register_top_level_master(
            lower["agentTokenSecret"], expected=403
        )
        self.assertEqual("top_level_agent_required", denied["error"]["code"])

    def test_human_admin_toggle_and_database_boolean_disable_agent_registration(self):
        top_level = self._provision_agent(
            requested_name="toggle-recovery-agent",
            scope_type="company",
            scope_id=self.company_id,
        )
        session = self._selected_human_owner_session()
        path = "/api/matm/human/companies/%s/top-level-agent-master-credential-setting" % self.company_id
        headers = {
            "HTTP_COOKIE": "%s=%s" % (HUMAN_SESSION_COOKIE, session["sessionSecret"]),
            "HTTP_X_CSRF_TOKEN": session["csrfToken"],
            "HTTP_ORIGIN": "https://memoryendpoints.com",
            "HTTP_SEC_FETCH_SITE": "same-origin",
            "HTTP_SEC_FETCH_MODE": "cors",
            "HTTP_SEC_FETCH_DEST": "empty",
            "CONTENT_TYPE": "application/json",
        }
        status, _response_headers, initial = call_api(path, extra_headers=headers)
        self.assertEqual(200, status, initial)
        self.assertTrue(initial["enabled"])
        self.assertEqual("top_level_agent_master_credential_enabled", initial["databaseColumn"])

        status, _response_headers, disabled = call_api(
            path, "PATCH", {"enabled": False}, extra_headers=headers
        )
        self.assertEqual(200, status, disabled)
        self.assertFalse(disabled["enabled"])
        if self.backend == "sqlite":
            with sqlite3.connect(self.sqlite_path) as connection:
                value = connection.execute(
                    "SELECT top_level_agent_master_credential_enabled FROM matm_companies WHERE company_id = ?",
                    (self.company_id,),
                ).fetchone()[0]
            self.assertEqual(0, value)
        else:
            stored = json.loads(self.store_path.read_text(encoding="utf-8"))
            self.assertIs(False, stored["companies"][self.company_id]["topLevelAgentMasterCredentialEnabled"])

        _candidate, _headers, denied = self._register_top_level_master(
            top_level["agentTokenSecret"], expected=403
        )
        self.assertEqual("top_level_agent_master_credential_disabled", denied["error"]["code"])

        status, _response_headers, enabled = call_api(
            path, "PATCH", {"enabled": True}, extra_headers=headers
        )
        self.assertEqual(200, status, enabled)
        self.assertTrue(enabled["enabled"])


class FileStoreAgentAccessApiTests(GovernedAgentAccessApiContract, unittest.TestCase):
    backend = "file"


class SQLiteAgentAccessApiTests(GovernedAgentAccessApiContract, unittest.TestCase):
    backend = "sqlite"


if __name__ == "__main__":
    unittest.main()
