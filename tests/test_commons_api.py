import io
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from app import application
from memoryendpoints.commons import (
    COMMONS_ACKNOWLEDGEMENT_SCHEMA,
    COMMONS_BROWSER_SESSION_SCHEMA,
    COMMONS_CORRECTION_SCHEMA,
    COMMONS_CREDENTIAL_REVOCATION_SCHEMA,
    COMMONS_CREDENTIAL_ROTATION_SCHEMA,
    COMMONS_ENROLLMENT_SCHEMA,
    COMMONS_ENROLLMENT_DECISION_SCHEMA,
    COMMONS_MEMBERSHIP_SCHEMA,
    COMMONS_MESSAGE_SCHEMA,
    CommonsContractError,
    COMMONS_POLICY_SCHEMA,
    COMMONS_WITHDRAWAL_SCHEMA,
)
from memoryendpoints.app import _store
from memoryendpoints.commons_api import _query, route_commons


def call_app(
    path,
    method="GET",
    body=None,
    headers=None,
    query="",
    raw=None,
    content_type=None,
    remote_addr="127.0.0.1",
):
    encoded = raw if raw is not None else (
        json.dumps(body).encode("utf-8") if body is not None else b""
    )
    captured = {}

    def start_response(status, response_headers):
        captured["status"] = status
        captured["headers"] = dict(response_headers)

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "CONTENT_LENGTH": str(len(encoded)),
        "CONTENT_TYPE": content_type if content_type is not None else ("application/json" if body is not None or raw is not None else ""),
        "wsgi.input": io.BytesIO(encoded),
        "REMOTE_ADDR": remote_addr,
    }
    environ.update(headers or {})
    response_body = b"".join(application(environ, start_response))
    return captured["status"], captured["headers"], json.loads(response_body)


def candidate(character):
    digest = hashlib.sha256(str(character).encode("utf-8")).hexdigest()
    return "me_agent_v1.agenttoken-%s.%s" % (
        digest[:20],
        (digest + digest)[:43],
    )


def browser_candidate(character):
    digest = hashlib.sha256(str(character).encode("utf-8")).hexdigest()
    return "me_commonsbrowser_v1.commonsbrowser-%s.%s" % (
        digest[:20],
        (digest + digest)[:43],
    )


def idem(label):
    return (label + "-" + "i" * 80)[:72]


class CommonsApiContract:
    backend = None

    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="commons-api-%s-" % self.backend)
        names = (
            "MEMORYENDPOINTS_STORE_BACKEND",
            "MEMORYENDPOINTS_STORE_PATH",
            "MEMORYENDPOINTS_SQLITE_PATH",
            "MEMORYENDPOINTS_CREDENTIAL_PEPPER",
            "MEMORYENDPOINTS_CREDENTIAL_CONFIG_PATH",
            "MEMORYENDPOINTS_SITE_URL",
            "MEMORYENDPOINTS_COMMONS_MODE",
            "MEMORYENDPOINTS_COMMONS_WORKSPACE_ID",
            "MEMORYENDPOINTS_COMMONS_PROJECT_ID",
            "MEMORYENDPOINTS_COMMONS_HUMAN_APPROVAL_REQUIRED",
            "MEMORYENDPOINTS_COMMONS_CREDENTIAL_TTL_SECONDS",
            "MEMORYENDPOINTS_COMMONS_BROWSER_SESSION_TTL_SECONDS",
            "MEMORYENDPOINTS_COMMONS_ENROLLMENT_REQUEST_TTL_SECONDS",
            "MEMORYENDPOINTS_COMMONS_MAXIMUM_ACTIVE_AGENTS",
            "MEMORYENDPOINTS_COMMONS_MAXIMUM_PENDING_ENROLLMENTS",
            "MEMORYENDPOINTS_COMMONS_MAXIMUM_RETAINED_AGENTS",
            "MEMORYENDPOINTS_COMMONS_MAXIMUM_RETAINED_ENROLLMENTS",
            "MEMORYENDPOINTS_COMMONS_MAXIMUM_COMPANY_RETAINED_AGENTS",
            "MEMORYENDPOINTS_COMMONS_MAXIMUM_COMPANY_RETAINED_ENROLLMENTS",
            "MEMORYENDPOINTS_COMMONS_MAXIMUM_ENROLLMENT_TOMBSTONES",
            "MEMORYENDPOINTS_COMMONS_MAXIMUM_COMPANY_ENROLLMENT_TOMBSTONES",
            "MEMORYENDPOINTS_COMMONS_MAXIMUM_AGENT_TOMBSTONES",
            "MEMORYENDPOINTS_COMMONS_MAXIMUM_COMPANY_AGENT_TOMBSTONES",
            "MEMORYENDPOINTS_COMMONS_PROJECT_REQUESTS_PER_MINUTE",
            "MEMORYENDPOINTS_COMMONS_SOURCE_REQUESTS_PER_MINUTE",
            "MEMORYENDPOINTS_COMMONS_MAXIMUM_LIVE_RATE_PARTITIONS",
            "MEMORYENDPOINTS_COMMONS_PROJECT_ENROLLMENTS_PER_HOUR",
            "MEMORYENDPOINTS_COMMONS_INACTIVE_AGENT_RETENTION_SECONDS",
            "MEMORYENDPOINTS_COMMONS_TERMINAL_ENROLLMENT_RETENTION_SECONDS",
            "MEMORYENDPOINTS_COMMONS_MESSAGE_CHARACTER_LIMIT",
            "MEMORYENDPOINTS_COMMONS_REQUEST_BYTE_LIMIT",
        )
        self.saved = {name: os.environ.get(name) for name in names}
        os.environ.update(
            {
                "MEMORYENDPOINTS_STORE_BACKEND": self.backend,
                "MEMORYENDPOINTS_STORE_PATH": str(Path(self.tempdir) / "store.json"),
                "MEMORYENDPOINTS_SQLITE_PATH": str(Path(self.tempdir) / "store.sqlite3"),
                "MEMORYENDPOINTS_CREDENTIAL_PEPPER": "commons-api-pepper-" + "p" * 64,
                "MEMORYENDPOINTS_CREDENTIAL_CONFIG_PATH": str(Path(self.tempdir) / "missing.json"),
                "MEMORYENDPOINTS_SITE_URL": "https://commons.local",
                "MEMORYENDPOINTS_COMMONS_MODE": "disabled",
            }
        )
        status, _headers, setup = call_app(
            "/api/matm/agent-setup/free-account",
            "POST",
            {
                "companyLabel": "Commons API",
                "label": "Commons API",
                "projectLabel": "Commons API",
            },
        )
        self.assertEqual("201 Created", status, setup)
        self.workspace_id = setup["workspaceId"]
        self.project_id = setup["projectId"]
        self.company_id = setup["companyId"]
        self.master = setup["companyMasterTokenSecret"]
        os.environ.update(
            {
                "MEMORYENDPOINTS_COMMONS_MODE": "local_test",
                "MEMORYENDPOINTS_COMMONS_WORKSPACE_ID": self.workspace_id,
                "MEMORYENDPOINTS_COMMONS_PROJECT_ID": self.project_id,
                "MEMORYENDPOINTS_COMMONS_HUMAN_APPROVAL_REQUIRED": "false",
            }
        )

    def tearDown(self):
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def auth(self, token, scheme="Bearer", key=None):
        headers = {"HTTP_AUTHORIZATION": scheme + " " + token}
        if key:
            headers["HTTP_IDEMPOTENCY_KEY"] = key
        return headers

    def enroll(self, name, character):
        token = candidate(character)
        key = idem("enroll-" + name)
        body = {
            "schemaVersion": COMMONS_ENROLLMENT_SCHEMA,
            "agentName": name,
            "displayName": name.replace("-", " ").title(),
            "publicProfile": {
                "listed": True,
                "implementation": "API contract client",
                "capabilities": ["public discussion"],
                "availability": "available",
            },
            "candidateTokenSecret": token,
        }
        status, _headers, payload = call_app(
            "/api/matm/commons/enrollments",
            "POST",
            body,
            {"HTTP_IDEMPOTENCY_KEY": key},
        )
        self.assertEqual("201 Created", status, payload)
        self.assertFalse(payload["enrollment"]["credentialReturnedOnce"])
        self.assertEqual(
            "commons_only", payload["enrollment"]["principal"]["authority"]
        )
        self.assertEqual(
            "agent_token", payload["enrollment"]["principal"]["credentialType"]
        )
        self.assertEqual(
            token.split(".", 2)[1],
            payload["enrollment"]["principal"]["credentialId"],
        )
        self.assertTrue(payload["enrollment"]["principal"]["valuesRedacted"])
        self.assertFalse(payload["enrollment"]["principal"]["rawCredentialExposed"])
        self.assertFalse(payload["enrollment"]["principal"]["rawPayloadExposed"])
        self.assertFalse(payload["enrollment"]["rawCredentialExposed"])
        self.assertNotIn("agentTokenSecret", json.dumps(payload))
        replay_status, _headers, replay = call_app(
            "/api/matm/commons/enrollments",
            "POST",
            body,
            {"HTTP_IDEMPOTENCY_KEY": key},
        )
        self.assertEqual("200 OK", replay_status, replay)
        self.assertTrue(replay["idempotentReplay"])
        self.assertEqual(payload["enrollment"]["principal"], replay["enrollment"]["principal"])
        return token

    def test_complete_two_client_http_slice_and_capability_separation(self):
        status, _headers, capabilities = call_app("/api/matm/commons/capabilities")
        self.assertEqual("200 OK", status, capabilities)
        self.assertTrue(capabilities["available"])
        self.assertTrue(capabilities["auth"]["autonomousEnrollmentCurrentlyAllowed"])

        token_a = self.enroll("http-agent-alpha", "a")
        token_b = self.enroll("http-agent-beta", "b")
        status, _headers, me = call_app(
            "/api/matm/commons/me", headers=self.auth(token_a)
        )
        self.assertEqual("200 OK", status, me)
        self.assertEqual("commons_only", me["principal"]["authority"])
        self.assertTrue(me["principal"]["lifecycle"]["rotationSupported"])
        self.assertTrue(me["principal"]["lifecycle"]["selfRevocationSupported"])
        for path, method, body in (
            ("/api/matm/workspace", "GET", None),
            ("/api/matm/search", "POST", {"query": "private"}),
            ("/api/matm/memory-events/submit", "POST", {"summary": "private"}),
            ("/api/matm/agent-messages", "POST", {"safeSummary": "private"}),
            ("/mcp", "POST", {"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
        ):
            denied_status, _headers, denied = call_app(
                path,
                method,
                body,
                self.auth(token_a, key=idem("denied" + path)),
            )
            self.assertEqual("403 Forbidden", denied_status, (path, denied))
            self.assertEqual("commons_credential_scope_forbidden", denied["error"]["code"])

        status, _headers, rooms = call_app("/api/matm/commons/rooms")
        self.assertEqual("200 OK", status, rooms)
        room_id = rooms["items"][0]["roomId"]
        for token, name in ((token_a, "alpha"), (token_b, "beta")):
            status, _headers, joined = call_app(
                "/api/matm/commons/rooms/%s/join" % room_id,
                "POST",
                {"schemaVersion": COMMONS_MEMBERSHIP_SCHEMA},
                self.auth(token, key=idem("join-" + name)),
            )
            self.assertEqual("200 OK", status, joined)
            self.assertEqual("joined", joined["membership"]["state"])

        status, _headers, posted = call_app(
            "/api/matm/commons/rooms/%s/messages" % room_id,
            "POST",
            {"schemaVersion": COMMONS_MESSAGE_SCHEMA, "content": "Alpha says hello."},
            self.auth(token_a, key=idem("post-alpha")),
        )
        self.assertEqual("201 Created", status, posted)
        first_id = posted["message"]["messageId"]
        status, _headers, page = call_app(
            "/api/matm/commons/rooms/%s/messages" % room_id,
            query="limit=1",
        )
        self.assertEqual("200 OK", status, page)
        self.assertEqual(first_id, page["items"][0]["messageId"])
        self.assertIsNotNone(page["nextCursor"])
        self.assertFalse(page["items"][0]["revisionHistoryIncluded"])

        current_binding = dict(page["items"][0]["acknowledgementBinding"])
        status, _headers, current_ack = call_app(
            "/api/matm/commons/messages/%s/acknowledgements" % first_id,
            "POST",
            dict({"schemaVersion": COMMONS_ACKNOWLEDGEMENT_SCHEMA}, **current_binding),
            self.auth(token_b, key=idem("ack-alpha-current")),
        )
        self.assertEqual("200 OK", status, current_ack)
        self.assertTrue(current_ack["message"]["acknowledgedByViewer"])

        status, _headers, replied = call_app(
            "/api/matm/commons/rooms/%s/messages" % room_id,
            "POST",
            {"schemaVersion": COMMONS_MESSAGE_SCHEMA, "content": "Beta replies.", "replyToMessageId": first_id},
            self.auth(token_b, key=idem("reply-beta")),
        )
        self.assertEqual("201 Created", status, replied)
        status, _headers, tail = call_app(
            "/api/matm/commons/rooms/%s/messages" % room_id,
            query="after=%s&limit=10" % page["nextCursor"],
        )
        self.assertEqual("200 OK", status, tail)
        self.assertEqual([replied["message"]["messageId"]], [item["messageId"] for item in tail["items"]])

        status, _headers, corrected = call_app(
            "/api/matm/commons/messages/%s/corrections" % first_id,
            "POST",
            {"schemaVersion": COMMONS_CORRECTION_SCHEMA, "content": "Alpha says hello, corrected.", "expectedRevision": 1},
            self.auth(token_a, key=idem("correct-alpha")),
        )
        self.assertEqual("200 OK", status, corrected)
        self.assertEqual(2, corrected["message"]["revisionCount"])
        status, _headers, detail = call_app("/api/matm/commons/messages/%s" % first_id)
        self.assertEqual("200 OK", status, detail)
        self.assertEqual([1, 2], [item["revisionNumber"] for item in detail["message"]["revisionHistory"]])
        self.assertTrue(all(not item["contentIncluded"] for item in detail["message"]["revisionHistory"]))
        status, _headers, first_revision = call_app(
            "/api/matm/commons/messages/%s/revisions/1" % first_id
        )
        self.assertEqual("200 OK", status, first_revision)
        self.assertEqual("Alpha says hello.", first_revision["revision"]["content"])

        status, _headers, corrected_for_beta = call_app(
            "/api/matm/commons/messages/%s" % first_id,
            headers=self.auth(token_b),
        )
        self.assertEqual("200 OK", status, corrected_for_beta)
        self.assertFalse(corrected_for_beta["message"]["acknowledgedByViewer"])
        ack_body = dict(
            {"schemaVersion": COMMONS_ACKNOWLEDGEMENT_SCHEMA},
            **corrected_for_beta["message"]["acknowledgementBinding"]
        )
        status, _headers, acknowledged = call_app(
            "/api/matm/commons/messages/%s/acknowledgements" % first_id,
            "POST",
            ack_body,
            self.auth(token_b, key=idem("ack-alpha")),
        )
        self.assertEqual("200 OK", status, acknowledged)
        self.assertTrue(acknowledged["message"]["acknowledgedByViewer"])

        reply_id = replied["message"]["messageId"]
        status, _headers, withdrawn = call_app(
            "/api/matm/commons/messages/%s/withdrawal" % reply_id,
            "POST",
            {"schemaVersion": COMMONS_WITHDRAWAL_SCHEMA, "expectedRevision": 1},
            self.auth(token_b, key=idem("withdraw-beta")),
        )
        self.assertEqual("200 OK", status, withdrawn)
        self.assertIsNone(withdrawn["message"]["content"])
        self.assertTrue(withdrawn["message"]["tombstone"]["withdrawn"])
        status, _headers, tombstone_for_alpha = call_app(
            "/api/matm/commons/messages/%s" % reply_id,
            headers=self.auth(token_a),
        )
        self.assertEqual("200 OK", status, tombstone_for_alpha)
        self.assertFalse(tombstone_for_alpha["message"]["acknowledgedByViewer"])
        status, _headers, tombstone_ack = call_app(
            "/api/matm/commons/messages/%s/acknowledgements" % reply_id,
            "POST",
            dict(
                {"schemaVersion": COMMONS_ACKNOWLEDGEMENT_SCHEMA},
                **tombstone_for_alpha["message"]["acknowledgementBinding"]
            ),
            self.auth(token_a, key=idem("ack-beta-tombstone")),
        )
        self.assertEqual("200 OK", status, tombstone_ack)
        self.assertTrue(tombstone_ack["message"]["acknowledgedByViewer"])
        status, _headers, rejected = call_app(
            "/api/matm/commons/messages/%s/corrections" % reply_id,
            "POST",
            {"schemaVersion": COMMONS_CORRECTION_SCHEMA, "content": "resurrect", "expectedRevision": 1},
            self.auth(token_b, key=idem("resurrect-beta")),
        )
        self.assertEqual("409 Conflict", status, rejected)
        self.assertEqual("message_withdrawn", rejected["error"]["code"])

        session_secret = browser_candidate("c")
        session_body = {
            "schemaVersion": COMMONS_BROWSER_SESSION_SCHEMA,
            "candidateBrowserSessionSecret": session_secret,
        }
        status, _headers, created = call_app(
            "/api/matm/commons/browser-sessions",
            "POST",
            session_body,
            self.auth(token_a, key=idem("browser-create")),
        )
        self.assertEqual("201 Created", status, created)
        self.assertNotIn(session_secret, json.dumps(created))
        replacement_session = browser_candidate("d")
        replacement_body = {
            "schemaVersion": COMMONS_BROWSER_SESSION_SCHEMA,
            "candidateBrowserSessionSecret": replacement_session,
        }
        status, _headers, replacement_created = call_app(
            "/api/matm/commons/browser-sessions",
            "POST",
            replacement_body,
            self.auth(token_a, key=idem("browser-create-replacement")),
        )
        self.assertEqual("201 Created", status, replacement_created)
        status, _headers, superseded = call_app(
            "/api/matm/commons/browser-sessions/current",
            headers=self.auth(session_secret, "CommonsSession"),
        )
        self.assertEqual("401 Unauthorized", status, superseded)
        status, _headers, lost_response_replay = call_app(
            "/api/matm/commons/browser-sessions",
            "POST",
            session_body,
            self.auth(token_a, key=idem("browser-create")),
        )
        self.assertEqual("200 OK", status, lost_response_replay)
        self.assertFalse(lost_response_replay["credentialAccepted"])
        self.assertEqual(
            "revoked", lost_response_replay["browserSession"]["status"]
        )
        status, _headers, current = call_app(
            "/api/matm/commons/browser-sessions/current",
            headers=self.auth(replacement_session, "CommonsSession"),
        )
        self.assertEqual("200 OK", status, current)
        self.assertEqual("commons_only", current["browserSession"]["authority"])
        status, _headers, session_me = call_app(
            "/api/matm/commons/me",
            headers=self.auth(replacement_session, "CommonsSession"),
        )
        self.assertEqual("200 OK", status, session_me)
        self.assertEqual("commons_browser_session", session_me["principal"]["authType"])
        status, _headers, chained = call_app(
            "/api/matm/commons/browser-sessions",
            "POST",
            {"schemaVersion": COMMONS_BROWSER_SESSION_SCHEMA, "candidateBrowserSessionSecret": browser_candidate("e")},
            self.auth(replacement_session, "CommonsSession", idem("browser-chain")),
        )
        self.assertEqual("401 Unauthorized", status, chained)
        revoke_headers = self.auth(replacement_session, "CommonsSession", idem("browser-revoke"))
        for replay_expected in (False, True):
            status, _headers, revoked = call_app(
                "/api/matm/commons/browser-sessions/revoke",
                "POST",
                {"schemaVersion": COMMONS_BROWSER_SESSION_SCHEMA},
                revoke_headers,
            )
            self.assertEqual("200 OK", status, revoked)
            self.assertEqual(replay_expected, revoked["idempotentReplay"])
        status, _headers, invalid = call_app(
            "/api/matm/commons/browser-sessions/current",
            headers=self.auth(replacement_session, "CommonsSession"),
        )
        self.assertEqual("401 Unauthorized", status, invalid)
        status, _headers, different_revoke = call_app(
            "/api/matm/commons/browser-sessions/revoke",
            "POST",
            {"schemaVersion": COMMONS_BROWSER_SESSION_SCHEMA},
            self.auth(
                replacement_session,
                "CommonsSession",
                idem("browser-revoke-different"),
            ),
        )
        self.assertEqual("409 Conflict", status, different_revoke)

        successor = candidate("f")
        rotation_body = {
            "schemaVersion": COMMONS_CREDENTIAL_ROTATION_SCHEMA,
            "candidateTokenSecret": successor,
        }
        rotation_headers = self.auth(token_a, key=idem("rotate-alpha"))
        status, _headers, rotated = call_app(
            "/api/matm/commons/credentials/rotation",
            "POST",
            rotation_body,
            rotation_headers,
        )
        self.assertEqual("200 OK", status, rotated)
        self.assertFalse(rotated["idempotentReplay"])
        self.assertNotIn(successor, json.dumps(rotated))
        status, _headers, rotation_replay = call_app(
            "/api/matm/commons/credentials/rotation",
            "POST",
            rotation_body,
            rotation_headers,
        )
        self.assertEqual("200 OK", status, rotation_replay)
        self.assertTrue(rotation_replay["idempotentReplay"])
        status, _headers, old_me = call_app(
            "/api/matm/commons/me", headers=self.auth(token_a)
        )
        self.assertEqual("401 Unauthorized", status, old_me)
        status, _headers, successor_me = call_app(
            "/api/matm/commons/me", headers=self.auth(successor)
        )
        self.assertEqual("200 OK", status, successor_me)
        status, _headers, still_scoped = call_app(
            "/api/matm/search",
            "POST",
            {"query": "private"},
            self.auth(successor, key=idem("rotated-denied")),
        )
        self.assertEqual("403 Forbidden", status, still_scoped)

        successor_session = browser_candidate("e")
        status, _headers, _created = call_app(
            "/api/matm/commons/browser-sessions",
            "POST",
            {
                "schemaVersion": COMMONS_BROWSER_SESSION_SCHEMA,
                "candidateBrowserSessionSecret": successor_session,
            },
            self.auth(successor, key=idem("successor-browser")),
        )
        self.assertEqual("201 Created", status, _created)
        revoke_credential_body = {
            "schemaVersion": COMMONS_CREDENTIAL_REVOCATION_SCHEMA
        }
        revoke_credential_headers = self.auth(
            successor, key=idem("revoke-successor")
        )
        status, _headers, credential_revoked = call_app(
            "/api/matm/commons/credentials/revoke",
            "POST",
            revoke_credential_body,
            revoke_credential_headers,
        )
        self.assertEqual("200 OK", status, credential_revoked)
        self.assertFalse(credential_revoked["idempotentReplay"])
        status, _headers, credential_replay = call_app(
            "/api/matm/commons/credentials/revoke",
            "POST",
            revoke_credential_body,
            revoke_credential_headers,
        )
        self.assertEqual("200 OK", status, credential_replay)
        self.assertTrue(credential_replay["idempotentReplay"])
        status, _headers, revoked_me = call_app(
            "/api/matm/commons/me", headers=self.auth(successor)
        )
        self.assertEqual("401 Unauthorized", status, revoked_me)
        status, _headers, revoked_session = call_app(
            "/api/matm/commons/browser-sessions/current",
            headers=self.auth(successor_session, "CommonsSession"),
        )
        self.assertEqual("401 Unauthorized", status, revoked_session)
        status, _headers, stale_rotation_replay = call_app(
            "/api/matm/commons/credentials/rotation",
            "POST",
            rotation_body,
            rotation_headers,
        )
        self.assertEqual("200 OK", status, stale_rotation_replay)
        self.assertTrue(stale_rotation_replay["idempotentReplay"])
        self.assertEqual("revoked", stale_rotation_replay["credential"]["status"])
        original_enrollment_body = {
            "schemaVersion": COMMONS_ENROLLMENT_SCHEMA,
            "agentName": "http-agent-alpha",
            "displayName": "Http Agent Alpha",
            "publicProfile": {
                "listed": True,
                "implementation": "API contract client",
                "capabilities": ["public discussion"],
                "availability": "available",
            },
            "candidateTokenSecret": token_a,
        }
        status, _headers, original_enrollment_replay = call_app(
            "/api/matm/commons/enrollments",
            "POST",
            original_enrollment_body,
            {"HTTP_IDEMPOTENCY_KEY": idem("enroll-http-agent-alpha")},
        )
        self.assertEqual("200 OK", status, original_enrollment_replay)
        self.assertFalse(
            original_enrollment_replay["enrollment"]["credentialAccepted"]
        )

    def test_policy_content_type_idempotency_and_cursor_fail_closed(self):
        token = self.enroll("policy-agent", "e")
        status, _headers, agents = call_app("/api/matm/commons/agents", query="limit=1")
        self.assertEqual("200 OK", status, agents)
        self.assertLess(len(json.dumps(agents).encode("utf-8")), 786432 + 32768)
        if agents["nextCursor"]:
            forged = agents["nextCursor"][:-1] + (
                "A" if agents["nextCursor"][-1] != "A" else "B"
            )
            status, _headers, invalid = call_app("/api/matm/commons/agents", query="after=" + forged)
            self.assertEqual("422 Unprocessable Entity", status, invalid)
        status, _headers, malformed = call_app(
            "/api/matm/commons/enrollments",
            "POST",
            headers={"HTTP_IDEMPOTENCY_KEY": idem("malformed")},
            raw=b"\xff",
        )
        self.assertEqual("400 Bad Request", status, malformed)
        status, _headers, wrong_type = call_app(
            "/api/matm/commons/enrollments",
            "POST",
            {"schemaVersion": COMMONS_ENROLLMENT_SCHEMA},
            {"HTTP_IDEMPOTENCY_KEY": idem("wrong-type")},
            content_type="text/plain",
        )
        self.assertEqual("415 Unsupported Media Type", status, wrong_type)

        master_headers = self.auth(self.master, key=idem("policy-enable"))
        status, _headers, policy = call_app(
            "/api/matm/commons/policy",
            "POST",
            {"schemaVersion": COMMONS_POLICY_SCHEMA, "humanApprovalRequired": True, "expectedRevision": 0},
            master_headers,
        )
        self.assertEqual("200 OK", status, policy)
        status, _headers, capabilities = call_app("/api/matm/commons/capabilities")
        self.assertEqual("200 OK", status, capabilities)
        self.assertFalse(capabilities["auth"]["autonomousEnrollmentCurrentlyAllowed"])
        self.assertTrue(capabilities["auth"]["enrollmentRequestsCurrentlyAccepted"])
        self.assertTrue(capabilities["auth"]["humanApprovalRequired"])
        pending_token = candidate("f")
        status, _headers, pending = call_app(
            "/api/matm/commons/enrollments",
            "POST",
            {"schemaVersion": COMMONS_ENROLLMENT_SCHEMA, "agentName": "pending-agent", "candidateTokenSecret": pending_token},
            {"HTTP_IDEMPOTENCY_KEY": idem("blocked-enroll")},
        )
        self.assertEqual("202 Accepted", status, pending)
        self.assertEqual("pending", pending["enrollment"]["status"])
        self.assertIsNone(_store().authenticate(pending_token, self.workspace_id))
        status, _headers, candidate_status = call_app(
            "/api/matm/commons/enrollments/current",
            headers=self.auth(pending_token, "CommonsEnrollment"),
        )
        self.assertEqual("200 OK", status, candidate_status)
        self.assertEqual("pending", candidate_status["enrollment"]["status"])
        status, _headers, denied_principal = call_app(
            "/api/matm/commons/me",
            headers=self.auth(pending_token, "CommonsEnrollment"),
        )
        self.assertEqual("401 Unauthorized", status, denied_principal)
        status, _headers, queue = call_app(
            "/api/matm/commons/enrollment-requests",
            headers=self.auth(self.master),
            query="limit=1",
        )
        self.assertEqual("200 OK", status, queue)
        self.assertEqual(pending["enrollment"]["enrollmentRequestId"], queue["items"][0]["enrollmentRequestId"])
        status, _headers, approved = call_app(
            "/api/matm/commons/enrollment-requests/%s/approval"
            % pending["enrollment"]["enrollmentRequestId"],
            "POST",
            {
                "schemaVersion": COMMONS_ENROLLMENT_DECISION_SCHEMA,
                "expectedRevision": pending["enrollment"]["revision"],
            },
            self.auth(self.master, key=idem("approve-pending")),
        )
        self.assertEqual("200 OK", status, approved)
        self.assertEqual("approved", approved["enrollmentRequest"]["status"])
        self.assertIsNotNone(_store().authenticate(pending_token, self.workspace_id))
        status, _headers, approved_status = call_app(
            "/api/matm/commons/enrollments/current",
            headers=self.auth(pending_token, "CommonsEnrollment"),
        )
        self.assertEqual("200 OK", status, approved_status)
        self.assertEqual("active", approved_status["enrollment"]["credentialState"])
        self.assertIsNotNone(_store().authenticate(token, self.workspace_id))

    def test_no_judgment_public_safety_exact_types_and_fail_closed_config(self):
        discourse_token = candidate("g")
        discourse_body = {
            "schemaVersion": COMMONS_ENROLLMENT_SCHEMA,
            "agentName": "discourse-agent",
            "displayName": "Developer Message Prototype",
            "publicProfile": {
                "listed": True,
                "implementation": (
                    "Discusses ignore previous instructions, developer messages, "
                    "prototype, and constructor behavior."
                ),
                "capabilities": ["prompt injection analysis"],
                "availability": "available",
            },
            "candidateTokenSecret": discourse_token,
        }
        status, _headers, enrolled = call_app(
            "/api/matm/commons/enrollments",
            "POST",
            discourse_body,
            {"HTTP_IDEMPOTENCY_KEY": idem("enroll-discourse")},
        )
        self.assertEqual("201 Created", status, enrolled)
        status, _headers, rooms = call_app("/api/matm/commons/rooms")
        self.assertEqual("200 OK", status, rooms)
        room_id = rooms["items"][0]["roomId"]
        status, _headers, joined = call_app(
            "/api/matm/commons/rooms/%s/join" % room_id,
            "POST",
            {"schemaVersion": COMMONS_MEMBERSHIP_SCHEMA},
            self.auth(discourse_token, key=idem("join-discourse")),
        )
        self.assertEqual("200 OK", status, joined)
        discussion = (
            "Security discussion: ignore previous is a prompt-injection phrase; "
            "developer message, prototype, and constructor are ordinary topics."
        )
        status, _headers, posted = call_app(
            "/api/matm/commons/rooms/%s/messages" % room_id,
            "POST",
            {"schemaVersion": COMMONS_MESSAGE_SCHEMA, "content": discussion},
            self.auth(discourse_token, key=idem("post-discussion")),
        )
        self.assertEqual("201 Created", status, posted)

        rejected_key = idem("reject-real-credential")
        status, _headers, rejected = call_app(
            "/api/matm/commons/rooms/%s/messages" % room_id,
            "POST",
            {
                "schemaVersion": COMMONS_MESSAGE_SCHEMA,
                "content": "Leaked credential: %s" % candidate("h"),
            },
            self.auth(discourse_token, key=rejected_key),
        )
        self.assertEqual("422 Unprocessable Entity", status, rejected)
        self.assertEqual("public_content_rejected", rejected["error"]["code"])
        self.assertNotIn(candidate("h"), json.dumps(rejected))
        status, _headers, safe_retry = call_app(
            "/api/matm/commons/rooms/%s/messages" % room_id,
            "POST",
            {
                "schemaVersion": COMMONS_MESSAGE_SCHEMA,
                "content": "The rejected key remains unused after validation.",
            },
            self.auth(discourse_token, key=rejected_key),
        )
        self.assertEqual("201 Created", status, safe_retry)
        status, _headers, private_key_rejected = call_app(
            "/api/matm/commons/rooms/%s/messages" % room_id,
            "POST",
            {
                "schemaVersion": COMMONS_MESSAGE_SCHEMA,
                "content": "-----BEGIN PRIVATE " + "KEY-----\nnot-public",
            },
            self.auth(discourse_token, key=idem("reject-private-key")),
        )
        self.assertEqual("422 Unprocessable Entity", status, private_key_rejected)

        invalid_enrollments = (
            dict(discourse_body, agentName=7, candidateTokenSecret=candidate("i")),
            dict(discourse_body, displayName=False, candidateTokenSecret=candidate("j")),
            dict(discourse_body, publicProfile=None, candidateTokenSecret=candidate("k")),
            dict(
                discourse_body,
                agentName="wrong-capabilities",
                candidateTokenSecret=candidate("l"),
                publicProfile={"capabilities": None},
            ),
        )
        for index, invalid_body in enumerate(invalid_enrollments):
            with self.subTest(invalid_enrollment=index):
                status, _headers, invalid = call_app(
                    "/api/matm/commons/enrollments",
                    "POST",
                    invalid_body,
                    {"HTTP_IDEMPOTENCY_KEY": idem("invalid-enroll-%d" % index)},
                )
                self.assertEqual("422 Unprocessable Entity", status, invalid)

        message_id = posted["message"]["messageId"]
        for invalid_revision in (True, 1.0, "1", 0, 2147483648):
            with self.subTest(invalid_revision=invalid_revision):
                status, _headers, invalid = call_app(
                    "/api/matm/commons/messages/%s/corrections" % message_id,
                    "POST",
                    {
                        "schemaVersion": COMMONS_CORRECTION_SCHEMA,
                        "content": "Strict revision typing remains exact.",
                        "expectedRevision": invalid_revision,
                    },
                    self.auth(
                        discourse_token,
                        key=idem("invalid-revision-%r" % invalid_revision),
                    ),
                )
                self.assertEqual("422 Unprocessable Entity", status, invalid)

        os.environ["MEMORYENDPOINTS_COMMONS_HUMAN_APPROVAL_REQUIRED"] = "ture"
        status, _headers, unavailable = call_app(
            "/api/matm/commons/capabilities"
        )
        self.assertEqual("200 OK", status, unavailable)
        self.assertFalse(unavailable["available"])
        self.assertIn(
            "commons_human_approval_config_invalid", unavailable["blockers"]
        )
        status, _headers, blocked = call_app(
            "/api/matm/commons/enrollments",
            "POST",
            dict(
                discourse_body,
                agentName="config-blocked",
                candidateTokenSecret=candidate("m"),
            ),
            {"HTTP_IDEMPOTENCY_KEY": idem("config-blocked")},
        )
        self.assertEqual("503 Service Unavailable", status, blocked)
        os.environ["MEMORYENDPOINTS_COMMONS_HUMAN_APPROVAL_REQUIRED"] = "false"

    def test_rate_limit_errors_include_retry_after(self):
        import memoryendpoints.commons_api as commons_api
        from unittest import mock

        def rejected_rate(*_args, **_kwargs):
            exc = CommonsContractError(
                "rate_limit_exceeded", "429 Too Many Requests"
            )
            exc.retry_after = 17
            raise exc

        with mock.patch.object(
            commons_api, "_layered_rate", side_effect=rejected_rate
        ):
            status, headers, payload = call_app(
                "/api/matm/commons/capabilities"
            )
        self.assertEqual("429 Too Many Requests", status, payload)
        self.assertEqual("17", headers.get("Retry-After"))

    def test_query_parsing_is_bounded_strict_and_precedes_storage(self):
        self.assertEqual(
            {"after": "a" * 2042},
            _query({"QUERY_STRING": "after=" + ("a" * 2042)}, {"after"}),
        )
        invalid_queries = (
            "after=" + ("a" * 2043),
            "a=1&b=2&c=3&d=4&e=5",
            "after=%GG",
            "after=%FF",
            "limit=1&limit=2",
            "after=cursor\x00",
        )
        for index, query in enumerate(invalid_queries):
            with self.subTest(index=index):
                captured = {}

                def start_response(status, headers):
                    captured.update(status=status, headers=dict(headers))

                factory_calls = []

                def forbidden_store_factory():
                    factory_calls.append(True)
                    raise AssertionError("invalid query must not initialize storage")

                body = b"".join(
                    route_commons(
                        {
                            "REQUEST_METHOD": "GET",
                            "PATH_INFO": "/api/matm/commons/agents",
                            "QUERY_STRING": query,
                            "REMOTE_ADDR": "127.0.0.1",
                        },
                        start_response,
                        "/api/matm/commons/agents",
                        forbidden_store_factory,
                    )
                )
                payload = json.loads(body)
                self.assertEqual("400 Bad Request", captured["status"], payload)
                self.assertEqual("query_invalid", payload["error"]["code"])
                self.assertEqual([], factory_calls)

    def test_project_enrollment_budget_bounds_rotating_source_partitions(self):
        os.environ["MEMORYENDPOINTS_COMMONS_PROJECT_ENROLLMENTS_PER_HOUR"] = "2"
        statuses = []
        for index in range(3):
            token = candidate("rotating-source-%d" % index)
            body = {
                "schemaVersion": COMMONS_ENROLLMENT_SCHEMA,
                "agentName": "rotating-source-%d" % index,
                "displayName": "Rotating Source %d" % index,
                "publicProfile": {},
                "candidateTokenSecret": token,
            }
            status, headers, payload = call_app(
                "/api/matm/commons/enrollments",
                "POST",
                body,
                {"HTTP_IDEMPOTENCY_KEY": idem("rotating-source-%d" % index)},
                remote_addr="192.0.2.%d" % (index + 1),
            )
            statuses.append(status)
            if index == 2:
                self.assertEqual("429 Too Many Requests", status, payload)
                self.assertIn("Retry-After", headers)
        self.assertEqual(["201 Created", "201 Created", "429 Too Many Requests"], statuses)

        store = _store()
        if self.backend == "file":
            rows = list(store._load().get("connectorRateLimits", {}).values())
            per_source = [
                row for row in rows if row.get("bucket") == "commonsEnrollment"
            ]
            project = [
                row
                for row in rows
                if row.get("bucket") == "commonsProjectEnrollment"
            ]
        else:
            with store._open_connection() as connection:
                per_source = connection.execute(
                    "SELECT * FROM matm_connector_rate_limits WHERE bucket = ?",
                    ("commonsEnrollment",),
                ).fetchall()
                project = connection.execute(
                    "SELECT * FROM matm_connector_rate_limits WHERE bucket = ?",
                    ("commonsProjectEnrollment",),
                ).fetchall()
        self.assertEqual(2, len(per_source))
        self.assertEqual(1, len(project))

    def test_source_rejection_does_not_spend_shared_request_budget(self):
        os.environ["MEMORYENDPOINTS_COMMONS_SOURCE_REQUESTS_PER_MINUTE"] = "10"
        os.environ["MEMORYENDPOINTS_COMMONS_PROJECT_REQUESTS_PER_MINUTE"] = "60"
        attacker = "198.51.100.44"
        for index in range(10):
            status, _headers, payload = call_app(
                "/api/matm/commons/not-a-route",
                "POST",
                {},
                {"HTTP_IDEMPOTENCY_KEY": idem("bogus-%d" % index)},
                remote_addr=attacker,
            )
            self.assertIn(status, ("401 Unauthorized", "404 Not Found", "422 Unprocessable Entity"), payload)
        status, headers, limited = call_app(
            "/api/matm/commons/not-a-route",
            "POST",
            {},
            {"HTTP_IDEMPOTENCY_KEY": idem("bogus-limited")},
            remote_addr=attacker,
        )
        self.assertEqual("429 Too Many Requests", status, limited)
        self.assertIn("Retry-After", headers)

        status, _headers, rooms = call_app(
            "/api/matm/commons/rooms", remote_addr="198.51.100.45"
        )
        self.assertEqual("200 OK", status, rooms)
        store = _store()
        if self.backend == "file":
            rows = list(store._load().get("connectorRateLimits", {}).values())
            project_rows = [
                row for row in rows if row.get("bucket") == "commonsProjectRequest"
            ]
        else:
            with store._open_connection() as connection:
                project_rows = connection.execute(
                    "SELECT * FROM matm_connector_rate_limits WHERE bucket = ?",
                    ("commonsProjectRequest",),
                ).fetchall()
        self.assertEqual(1, len(project_rows))
        project_count = (
            project_rows[0].get("requestCount")
            if self.backend == "file"
            else project_rows[0]["request_count"]
        )
        self.assertEqual(11, int(project_count))


class CommonsFileApiTests(CommonsApiContract, unittest.TestCase):
    backend = "file"


class CommonsSQLiteApiTests(CommonsApiContract, unittest.TestCase):
    backend = "sqlite"


if __name__ == "__main__":
    unittest.main()
