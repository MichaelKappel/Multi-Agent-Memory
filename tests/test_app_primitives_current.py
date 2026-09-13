"""Focused current coverage for app boundary helpers shared by route handlers."""

import base64
import io
import json
import os
import unittest
from unittest.mock import Mock, patch

import memoryendpoints.app as app
from memoryendpoints import connector_pairing as pairing


def _response(iterable):
    captured = {}

    def start(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = b"".join(iterable(start))
    return captured, json.loads(body)


def _bootstrap_body():
    def secret(fill):
        return base64.urlsafe_b64encode(bytes([fill]) * 32).decode("ascii").rstrip("=")

    return {
        "schemaVersion": "memoryendpoints.bootstrap_account_request.v1",
        "companyLabel": "Example Company",
        "workspaceLabel": "Main Workspace",
        "projectLabel": "Memory Project",
        "candidateCompanyMasterTokenSecret": "me_master_v1.masterkey-" + "a" * 20 + "." + secret(1),
        "candidateHumanOwnerRecoverySecret": "me_human_v1.humancred-" + "d" * 20 + "." + secret(2),
    }


class AppPrimitivesCurrentTests(unittest.TestCase):
    def test_taxonomy_and_knowledge_scope_resolution_cover_wire_aliases(self):
        self.assertEqual(["A", "B"], app._knowledge_taxonomy_values({"taxonomyPaths": ["A", "B"]}))
        self.assertEqual(["A", "B"], app._knowledge_taxonomy_values({"taxonomyPath": " A ; B "}))
        self.assertEqual(["A", "B"], app._knowledge_taxonomy_values({"metadata": {"taxonomyPaths": ["A", "B"]}}))
        self.assertEqual(["A", "B"], app._knowledge_taxonomy_values({"metadata": {"taxonomyPath": "A;B"}}))
        self.assertEqual([], app._knowledge_taxonomy_values({"metadata": {}}))

        store = Mock()
        store.workspace_status.return_value = {
            "companyId": "company-1",
            "projects": [{"projectId": "project-1"}],
        }
        payload, error = app._resolve_knowledge_scope(store, "workspace-1", {})
        self.assertIsNone(error)
        self.assertEqual({"scope": "workspace", "scopeId": "workspace-1", "projectId": None}, {key: payload[key] for key in ("scope", "scopeId", "projectId")})
        payload, error = app._resolve_knowledge_scope(store, "workspace-1", {"scope": "company"})
        self.assertIsNone(error)
        self.assertEqual("company-1", payload["scopeId"])
        payload, error = app._resolve_knowledge_scope(store, "workspace-1", {"scope": "project", "projectId": "project-1"})
        self.assertIsNone(error)
        self.assertEqual("project-1", payload["scopeId"])
        for body, expected in (
            ({"scope": "nope"}, "unsupported_scope"),
            ({"scope": "company", "scopeId": "other-company"}, "scope_not_authorized"),
            ({"scope": "workspace", "scopeId": "other-workspace"}, "scope_not_authorized"),
            ({"scope": "project"}, "project_id_required"),
            ({"scope": "project", "projectId": "other-project"}, "project_not_found"),
        ):
            with self.subTest(body=body):
                self.assertEqual((None, expected), app._resolve_knowledge_scope(store, "workspace-1", body))
        store.workspace_status.return_value = None
        self.assertEqual((None, "workspace_not_found"), app._resolve_knowledge_scope(store, "workspace-1", {}))

    def test_connector_and_network_boundary_helpers_fail_closed(self):
        valid = {
            "publicCredentialType": "connector_agent",
            "approvedScopes": list(pairing.V1_REQUESTED_SCOPES),
            "scopeDigest": pairing.connector_scope_digest(list(pairing.V1_REQUESTED_SCOPES)),
        }
        self.assertEqual(list(pairing.V1_REQUESTED_SCOPES), app._connector_principal_scopes(valid))
        self.assertEqual([], app._connector_principal_scopes(dict(valid, scopeDigest="bad")))
        self.assertEqual([], app._connector_principal_scopes(dict(valid, approvedScopes=["admin"])))
        self.assertEqual([], app._connector_principal_scopes({"credentialType": "agent"}))

        self.assertTrue(app._request_is_direct_loopback({"HTTP_HOST": "localhost:8080", "REMOTE_ADDR": "127.0.0.1"}))
        self.assertTrue(app._request_is_direct_loopback({"HTTP_HOST": "[::1]:8080", "REMOTE_ADDR": "::1"}))
        self.assertFalse(app._request_is_direct_loopback({"HTTP_HOST": "localhost", "REMOTE_ADDR": "127.0.0.1", "HTTP_X_FORWARDED_FOR": "127.0.0.1"}))
        for environ in (
            {"HTTP_HOST": "evil.example", "REMOTE_ADDR": "127.0.0.1"},
            {"HTTP_HOST": "localhost/bad", "REMOTE_ADDR": "127.0.0.1"},
            {"HTTP_HOST": "localhost:bad", "REMOTE_ADDR": "127.0.0.1"},
            {"HTTP_HOST": "localhost", "REMOTE_ADDR": "not-an-ip"},
        ):
            with self.subTest(environ=environ):
                self.assertFalse(app._request_is_direct_loopback(environ))
        self.assertEqual("https://example.test", app._request_origin({"wsgi.url_scheme": "HTTPS", "HTTP_HOST": "Example.Test"}))
        self.assertEqual("", app._request_origin({"wsgi.url_scheme": "ftp", "HTTP_HOST": "example.test"}))
        self.assertEqual("", app._request_origin({"wsgi.url_scheme": "http", "HTTP_HOST": "bad/host"}))

    def test_same_origin_and_bootstrap_request_framing_cover_rejection_paths(self):
        configured = {"wsgi.url_scheme": "https", "HTTP_HOST": "memoryendpoints.com", "HTTP_SEC_FETCH_SITE": "same-origin"}
        with patch.dict(os.environ, {"MEMORYENDPOINTS_SITE_URL": "https://memoryendpoints.com"}, clear=False):
            self.assertTrue(app._bootstrap_account_same_origin(configured))
            wrong_scheme = dict(configured)
            wrong_scheme["wsgi.url_scheme"] = "http"
            self.assertFalse(app._bootstrap_account_same_origin(wrong_scheme))
            self.assertFalse(app._bootstrap_account_same_origin(dict(configured, HTTP_HOST="other.test")))
            self.assertFalse(app._bootstrap_account_same_origin(dict(configured, HTTP_ORIGIN="https://other.test")))
            self.assertTrue(app._human_same_origin({"HTTP_SEC_FETCH_SITE": "same-origin", "HTTP_ORIGIN": app._site_origin()}))
            self.assertFalse(app._human_same_origin({"HTTP_SEC_FETCH_SITE": "cross-site", "HTTP_ORIGIN": app._site_origin()}))
            self.assertFalse(app._human_same_origin({"HTTP_SEC_FETCH_SITE": "same-origin"}))

        body = _bootstrap_body()
        raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
        environ = {"CONTENT_TYPE": "application/json; charset=utf-8", "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}
        parsed, error = app._bootstrap_account_json(environ)
        self.assertIsNone(error)
        self.assertEqual(body, parsed)
        invalid_cases = (
            (dict(environ, HTTP_TRANSFER_ENCODING="chunked"), "bootstrap_account_request_invalid"),
            (dict(environ, CONTENT_TYPE="text/plain"), "bootstrap_account_request_invalid"),
            (dict(environ, CONTENT_LENGTH="1.0"), "bootstrap_account_request_invalid"),
            (dict(environ, CONTENT_LENGTH="0"), "bootstrap_account_request_invalid"),
            (dict(environ, CONTENT_LENGTH=str(app._BOOTSTRAP_ACCOUNT_MAX_REQUEST_BYTES + 1)), "bootstrap_account_request_too_large"),
        )
        for candidate, expected in invalid_cases:
            with self.subTest(expected=expected):
                self.assertEqual(expected, app._bootstrap_account_json(candidate)[1])
        duplicate = b'{"schemaVersion":"memoryendpoints.bootstrap_account_request.v1","schemaVersion":"memoryendpoints.bootstrap_account_request.v1"}'
        self.assertEqual("bootstrap_account_request_invalid", app._bootstrap_account_json({"CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(duplicate)), "wsgi.input": io.BytesIO(duplicate)})[1])

    def test_connector_body_and_static_projection_contracts(self):
        start = lambda status, headers: None
        valid = {"CONTENT_TYPE": "application/json", "CONTENT_LENGTH": "7", "wsgi.input": io.BytesIO(b'{"x":1}')}
        body, error = app._connector_body_or_problem(valid, start)
        self.assertEqual({"x": 1}, body)
        self.assertIsNone(error)
        for environ, expected in (
            ({"CONTENT_TYPE": "text/plain", "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO()}, "json_content_type_required"),
            ({"CONTENT_TYPE": "application/json", "CONTENT_LENGTH": "bad", "wsgi.input": io.BytesIO()}, "invalid_request"),
            ({"CONTENT_TYPE": "application/json", "CONTENT_LENGTH": "-1", "wsgi.input": io.BytesIO()}, "request_body_too_large"),
            ({"CONTENT_TYPE": "application/json", "CONTENT_LENGTH": "2", "wsgi.input": io.BytesIO(b"[]")}, "invalid_request"),
        ):
            with self.subTest(expected=expected):
                captured = {}

                def callback(status, headers):
                    captured.update(status=status, headers=dict(headers))

                _body, response = app._connector_body_or_problem(environ, callback)
                payload = json.loads(b"".join(response))
                self.assertEqual(expected, payload["error"]["code"])
        captured = {}
        response = app.route_static("/static/css/site.css", lambda status, headers: captured.update(status=status, headers=dict(headers)))
        self.assertEqual("200 OK", captured["status"])
        self.assertEqual("text/css; charset=utf-8", captured["headers"]["Content-Type"])
        self.assertTrue(b"".join(response))
        response = app.route_static("/static/no-such-file", lambda status, headers: captured.update(status=status, headers=dict(headers)))
        self.assertEqual("404 Not Found", captured["status"])
        self.assertEqual("not_found", json.loads(b"".join(response))["error"]["code"])

    def test_protected_route_common_auth_scope_identity_and_not_found_guards(self):
        def protected(path, method="GET", body=None, token="synthetic-token", auth=None, store=None, key=None, content_type="application/json"):
            captured = {}
            raw = json.dumps(body).encode("utf-8") if body is not None else b""
            environ = {
                "REQUEST_METHOD": method,
                "PATH_INFO": path,
                "CONTENT_TYPE": content_type,
                "CONTENT_LENGTH": str(len(raw)),
                "wsgi.input": io.BytesIO(raw),
                "REMOTE_ADDR": "127.0.0.1",
            }
            if key:
                environ["HTTP_IDEMPOTENCY_KEY"] = key

            def start(status, headers):
                captured.update(status=status, headers=dict(headers))

            actual_store = store or Mock()
            actual_store.authenticate_connector_token.return_value = None
            with patch.object(app, "_token", return_value=token), patch.object(app, "_store", return_value=actual_store), patch.object(app, "_require_auth", return_value=auth):
                result = app.route_protected(environ, start, path)
            return captured, json.loads(b"".join(result))

        captured, payload = protected("/api/matm/workspace", token="")
        self.assertEqual("401 Unauthorized", captured["status"])
        self.assertEqual("auth_required", payload["error"]["code"])
        captured, payload = protected("/api/matm/projects", method="POST", body={"workspaceId": 17}, auth={})
        self.assertEqual("403 Forbidden", captured["status"])
        self.assertEqual("insufficient_scope", payload["error"]["code"])
        store = Mock()
        store.authenticate.return_value = None
        captured, payload = protected("/api/matm/workspace", auth=None, store=store)
        self.assertEqual("401 Unauthorized", captured["status"])
        self.assertEqual("invalid_token", payload["error"]["code"])
        store.authenticate.return_value = {"credentialType": "agent"}
        captured, payload = protected("/api/matm/workspace", auth=None, store=store)
        self.assertEqual("403 Forbidden", captured["status"])
        self.assertEqual("insufficient_scope", payload["error"]["code"])
        auth = {"workspaceId": "workspace-1", "credentialType": "agent", "agentId": "agent-1", "agentIdentityId": "agent-1"}
        store = Mock()
        store.auth_allows_scope.return_value = False
        captured, payload = protected("/api/matm/sync/retention", auth=auth, store=store)
        self.assertEqual("403 Forbidden", captured["status"])
        self.assertEqual("insufficient_scope", payload["error"]["code"])
        captured, payload = protected("/api/matm/projects", method="POST", body={"actorAgentId": "other-agent", "label": "Project"}, auth=auth, store=Mock(), key="protected-route-key-1")
        self.assertEqual("403 Forbidden", captured["status"])
        self.assertEqual("principal_mismatch", payload["error"]["code"])
        store = Mock()
        store.projects.return_value = []
        store.auth_allows_scope.return_value = True
        captured, payload = protected("/api/matm/projects", auth=auth, store=store)
        self.assertEqual("200 OK", captured["status"])
        self.assertEqual([], payload["items"])
        captured, payload = protected("/api/matm/not-a-real-protected-route", auth=auth, store=store)
        self.assertEqual("404 Not Found", captured["status"])
        self.assertEqual("not_found", payload["error"]["code"])

    def test_connector_protected_route_rejects_inactive_and_wrongly_scoped_credentials(self):
        def connector(path, method="GET", content_type="application/json"):
            captured = {}
            store = Mock()
            store.authenticate_connector_token.return_value = {
                "active": False,
                "credentialId": "connector-1",
            }
            environ = {
                "REQUEST_METHOD": method,
                "PATH_INFO": path,
                "CONTENT_TYPE": content_type,
                "CONTENT_LENGTH": "0",
                "wsgi.input": io.BytesIO(b""),
                "REMOTE_ADDR": "127.0.0.1",
            }

            def start(status, headers):
                captured.update(status=status, headers=dict(headers))

            with patch.object(app, "_token", return_value="connector-token"), patch.object(app, "_store", return_value=store):
                result = app.route_protected(environ, start, path)
            return captured, json.loads(b"".join(result))

        captured, payload = connector("/api/matm/workspace")
        self.assertEqual("401 Unauthorized", captured["status"])
        self.assertEqual("pending_credential_not_active", payload["error"]["code"])

        def active(path, method="GET", content_type="application/json"):
            captured = {}
            store = Mock()
            store.authenticate_connector_token.return_value = {
                "active": True,
                "credentialId": "connector-1",
            }
            environ = {
                "REQUEST_METHOD": method,
                "PATH_INFO": path,
                "CONTENT_TYPE": content_type,
                "CONTENT_LENGTH": "0",
                "wsgi.input": io.BytesIO(b""),
                "REMOTE_ADDR": "127.0.0.1",
            }

            def start(status, headers):
                captured.update(status=status, headers=dict(headers))

            with patch.object(app, "_token", return_value="connector-token"), patch.object(app, "_store", return_value=store):
                result = app.route_protected(environ, start, path)
            return captured, json.loads(b"".join(result))

        captured, payload = active("/api/matm/projects")
        self.assertEqual("403 Forbidden", captured["status"])
        self.assertEqual("connector_scope_forbidden", payload["error"]["code"])
        captured, payload = active("/api/matm/agents/register", method="POST", content_type="text/plain")
        self.assertEqual("415 Unsupported Media Type", captured["status"])
        self.assertEqual("json_content_type_required", payload["error"]["code"])

    def test_human_route_boundary_matrix_rejects_wrong_method_origin_and_auth(self):
        def human(path, method="GET", body=None, headers=None, store=None, token=""):
            captured = {}
            raw = json.dumps(body).encode("utf-8") if body is not None else b""
            environ = {
                "REQUEST_METHOD": method,
                "PATH_INFO": path,
                "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": str(len(raw)),
                "wsgi.input": io.BytesIO(raw),
                "REMOTE_ADDR": "127.0.0.1",
            }
            environ.update(headers or {})

            def start(status, response_headers):
                captured.update(status=status, headers=dict(response_headers))

            with patch.object(app, "_store", return_value=store or Mock()), patch.object(app, "_token", return_value=token):
                result = app.route_human(environ, start, path)
            return captured, json.loads(b"".join(result))

        self.assertIsNone(app.route_human({}, lambda *_args: None, "/not-human"))
        captured, payload = human("/api/matm/human/recovery/closure-session")
        self.assertEqual("405 Method Not Allowed", captured["status"])
        self.assertEqual("method_not_allowed", payload["error"]["code"])
        captured, payload = human("/api/matm/human/company-master-proofs", method="POST", token="machine-token", headers={"HTTP_SEC_FETCH_SITE": "same-origin", "HTTP_ORIGIN": app._site_origin()})
        self.assertEqual("403 Forbidden", captured["status"])
        self.assertEqual("human_owner_required", payload["error"]["code"])
        captured, payload = human("/api/matm/human/accounts", method="POST", token="machine-token", headers={"HTTP_SEC_FETCH_SITE": "same-origin", "HTTP_ORIGIN": app._site_origin()})
        self.assertEqual("403 Forbidden", captured["status"])
        self.assertEqual("human_owner_required", payload["error"]["code"])
        captured, payload = human("/api/matm/human/session", method="PATCH", headers={"CONTENT_TYPE": "text/plain"})
        self.assertEqual("415 Unsupported Media Type", captured["status"])
        self.assertEqual("json_content_type_required", payload["error"]["code"])
        captured, payload = human("/api/matm/human/company-master-proofs", method="POST")
        self.assertEqual("403 Forbidden", captured["status"])
        self.assertEqual("trusted_origin_required", payload["error"]["code"])
        captured, payload = human(
            "/api/matm/human/session",
            method="POST",
            body={},
            headers={"HTTP_SEC_FETCH_SITE": "same-origin", "HTTP_ORIGIN": app._site_origin()},
        )
        self.assertEqual("400 Bad Request", captured["status"])
        self.assertEqual("username_password_required", payload["error"]["code"])
        captured, payload = human("/api/matm/human/session")
        self.assertEqual("401 Unauthorized", captured["status"])
        self.assertEqual("human_session_required", payload["error"]["code"])

    def test_idempotency_claim_finalization_and_cleanup_fail_closed(self):
        store = Mock()
        claim = {"store": store, "workspaceId": "workspace-1", "key": "key-1", "operation": "op", "claimId": "claim-1"}
        environ = {"memoryendpoints.idempotencyClaims": [dict(claim), claim]}
        self.assertIs(claim, app._request_idempotency_claim(environ, store, "workspace-1", "key-1", "op"))
        self.assertIsNone(app._request_idempotency_claim(environ, store, "workspace-1", "other", "op"))
        app._mark_idempotent_mutation_started(environ, store, "workspace-1", "", "op")
        app._mark_idempotent_mutation_started(environ, store, "workspace-1", "key-1", "op")
        self.assertTrue(claim["mutationStarted"])
        with self.assertRaises(app._IdempotencyFinalizationError):
            app._mark_idempotent_mutation_started({"memoryendpoints.idempotencyClaims": []}, store, "workspace-1", "missing-key", "op")
        self.assertTrue(app._record_request_idempotency(store, environ, "workspace-1", "", "op", {}, {}))
        store.record_idempotency.return_value = True
        self.assertTrue(app._record_request_idempotency(store, environ, "workspace-1", "key-1", "op", {"x": 1}, {"ok": True}))
        store.record_idempotency.assert_called_once()
        self.assertTrue(claim["finalized"])
        with self.assertRaises(app._IdempotencyFinalizationError):
            app._record_request_idempotency(store, {"memoryendpoints.idempotencyClaims": []}, "workspace-1", "key-1", "op", {}, {})
        claim["finalized"] = False
        store.record_idempotency.return_value = False
        with self.assertRaises(app._IdempotencyFinalizationError):
            app._record_request_idempotency(store, environ, "workspace-1", "key-1", "op", {}, {})
        store.record_idempotency.side_effect = OSError("synthetic")
        with self.assertRaises(app._IdempotencyFinalizationError):
            app._record_request_idempotency(store, environ, "workspace-1", "key-1", "op", {}, {})
        release_store = Mock()
        release_store.release_idempotency_claim.side_effect = OSError("cleanup")
        release_environ = {
            "memoryendpoints.idempotencyClaims": [
                {"store": release_store, "workspaceId": "w", "key": "a", "operation": "a", "claimId": "a", "finalized": True},
                {"store": release_store, "workspaceId": "w", "key": "b", "operation": "b", "claimId": "b", "mutationStarted": True},
                {"store": release_store, "workspaceId": "w", "key": "c", "operation": "c", "claimId": "c", "outcomeUncertain": True},
                {"store": release_store, "workspaceId": "w", "key": "d", "operation": "d", "claimId": "d"},
            ]
        }
        app._release_request_idempotency_claims(release_environ)
        self.assertNotIn("memoryendpoints.idempotencyClaims", release_environ)
        self.assertEqual(1, release_store.release_idempotency_claim.call_count)

    def test_access_route_dispatch_covers_master_agent_and_redemption_boundaries(self):
        def access(path, method="GET", body=None, headers=None, auth=None, store=None, token="synthetic-token"):
            captured = {}
            raw = json.dumps(body).encode("utf-8") if body is not None else b""
            environ = {
                "REQUEST_METHOD": method,
                "PATH_INFO": path,
                "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": str(len(raw)),
                "wsgi.input": io.BytesIO(raw),
                "REMOTE_ADDR": "127.0.0.1",
            }
            environ.update(headers or {})

            def start(status, response_headers):
                captured.update(status=status, headers=dict(response_headers))

            actual_store = store or Mock()
            with patch.object(app, "_store", return_value=actual_store), patch.object(app, "_token", return_value=token), patch.object(app, "_access_auth", return_value=(auth, None)):
                result = app.route_access(environ, start, path)
            payload = json.loads(b"".join(result)) if result else None
            return captured, payload

        store = Mock()
        self.assertIsNone(access("/api/matm/not-an-access-route", store=store)[1])
        captured, payload = access("/api/matm/me", method="POST", auth={"credentialType": "company_master"}, store=store)
        self.assertEqual("405 Method Not Allowed", captured["status"])
        self.assertEqual("method_not_allowed", payload["error"]["code"])
        master = {"credentialType": "company_master", "credentialId": "master-1", "companyId": "company-1", "workspaceId": "workspace-1"}
        captured, payload = access("/api/matm/me", auth=master, store=store)
        self.assertEqual("200 OK", captured["status"])
        self.assertEqual("company_master", payload["principal"]["credentialType"])
        captured, payload = access("/api/matm/access/scope-catalog", auth={"credentialType": "agent"}, store=store)
        self.assertEqual("403 Forbidden", captured["status"])
        self.assertEqual("company_master_required", payload["error"]["code"])
        store.company_scope_catalog.return_value = {"ok": True, "items": []}
        captured, payload = access("/api/matm/access/scope-catalog", auth=master, store=store)
        self.assertEqual("200 OK", captured["status"])
        self.assertEqual([], payload["items"])
        captured, payload = access("/api/matm/access/invites/redeem", method="GET", store=store)
        self.assertEqual("405 Method Not Allowed", captured["status"])
        captured, payload = access("/api/matm/access/invites/redeem", method="POST", body={}, store=store)
        self.assertEqual("422 Unprocessable Entity", captured["status"])
        self.assertEqual("idempotency_key_required", payload["error"]["code"])
        captured, payload = access("/api/matm/access/company-master-credentials", method="POST", auth={"credentialType": "agent", "companyId": "company-1", "grant": {}}, store=store)
        self.assertEqual("403 Forbidden", captured["status"])
        self.assertEqual("top_level_agent_required", payload["error"]["code"])

    def test_protected_route_dispatch_rejects_unsupported_methods_across_current_surface(self):
        paths = (
            "/api/matm/workspace", "/api/matm/projects", "/api/matm/mcp-connections",
            "/api/matm/external-links", "/api/matm/internet-search", "/api/matm/knowledge-tree",
            "/api/matm/knowledge-documents", "/api/matm/sync/retention", "/api/matm/sync/devices",
            "/api/matm/sync/devices/rotate", "/api/matm/sync/devices/revoke", "/api/matm/sync/mutations",
            "/api/matm/sync/receipts", "/api/matm/sync/changes", "/api/matm/sync/heads",
            "/api/matm/uai-memory/packages", "/api/matm/uai-memory/records", "/api/matm/uai-memory/startup",
            "/api/matm/uai-memory/instances", "/api/matm/uai-memory/leases", "/api/matm/uai-memory/leases/acquire",
            "/api/matm/uai-memory/commits", "/api/matm/uai-memory/branches", "/api/matm/memory-events/submit",
            "/api/matm/review-queue", "/api/matm/review-queue/decide", "/api/matm/memory-events",
            "/api/matm/search", "/api/matm/routing-decisions", "/api/matm/meeting-messages/promote",
            "/api/matm/meeting-rooms", "/api/matm/meeting-room-memberships", "/api/matm/meeting-messages",
            "/api/matm/meeting-rooms/read", "/api/matm/agent-messages", "/api/matm/agent-inbox",
            "/api/matm/current-message", "/api/matm/notifications/ack", "/api/matm/receipts",
        )
        auth = {"workspaceId": "workspace-1", "credentialType": "agent", "agentId": "agent-1", "agentIdentityId": "agent-1"}
        store = Mock()
        store.auth_allows_scope.return_value = True
        store.authenticate_connector_token.return_value = None
        for path in paths:
            with self.subTest(path=path):
                environ = {
                    "REQUEST_METHOD": "DELETE", "PATH_INFO": path, "QUERY_STRING": "",
                    "CONTENT_LENGTH": "0", "CONTENT_TYPE": "application/json",
                    "wsgi.input": io.BytesIO(b""), "REMOTE_ADDR": "127.0.0.1",
                }
                captured = {}

                def start(status, headers):
                    captured["status"] = status

                with patch.object(app, "_token", return_value="synthetic-token"), patch.object(app, "_store", return_value=store), patch.object(app, "_require_auth", return_value=auth):
                    result = app.route_protected(environ, start, path)
                self.assertEqual("404 Not Found", captured["status"])
                self.assertEqual("not_found", json.loads(b"".join(result))["error"]["code"])

    def test_protected_mutation_validation_matrix_stops_before_storage_side_effects(self):
        auth = {
            "workspaceId": "workspace-1",
            "credentialType": "agent",
            "agentId": "agent-1",
            "agentIdentityId": "agent-1",
        }

        def protected(path, body, expected, *, store=None):
            captured = {}
            raw = json.dumps(body).encode("utf-8")
            environ = {
                "REQUEST_METHOD": "POST",
                "PATH_INFO": path,
                "QUERY_STRING": "",
                "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": str(len(raw)),
                "wsgi.input": io.BytesIO(raw),
                "REMOTE_ADDR": "127.0.0.1",
                "HTTP_IDEMPOTENCY_KEY": "coverage-route-key-0001",
            }
            actual_store = store if store is not None else Mock()
            actual_store.auth_allows_scope.return_value = True
            actual_store.projects.return_value = []
            actual_store.knowledge_documents.return_value = []
            actual_store.authenticate_connector_token.return_value = None
            if store is None:
                actual_store.has_quota_for.return_value = True
                actual_store.meeting_rooms.return_value = []

            def start(status, headers):
                captured.update(status=status, headers=dict(headers))

            with patch.object(app, "_token", return_value="synthetic-token"), \
                 patch.object(app, "_store", return_value=actual_store), \
                 patch.object(app, "_require_auth", return_value=auth), \
                 patch.object(app, "_idempotency_replay_or_conflict", return_value=None), \
                 patch.object(app, "_mark_idempotent_mutation_started"), \
                 patch.object(app, "_record_request_idempotency"):
                result = app.route_protected(environ, start, path)
            self.assertEqual(expected, json.loads(b"".join(result))["error"]["code"])

        protected("/api/matm/projects", {}, "project_label_required")
        quota_store = Mock()
        quota_store.has_quota_for.return_value = False
        protected("/api/matm/projects", {"label": "Project"}, "quota_exceeded", store=quota_store)
        missing_workspace = Mock()
        missing_workspace.upsert_project.return_value = (None, "workspace_not_found")
        protected("/api/matm/projects", {"label": "Project"}, "workspace_not_found", store=missing_workspace)
        conflict = Mock()
        conflict.upsert_project.return_value = (None, "project_id_conflict")
        protected("/api/matm/projects", {"label": "Project"}, "project_id_conflict", store=conflict)
        protected("/api/matm/external-links", {}, "external_url_required")
        protected("/api/matm/external-links", {"url": "https://example.test"}, "external_link_site_name_required")
        protected("/api/matm/external-links", {"url": "https://example.test", "siteName": "Example"}, "external_link_page_title_required")
        protected("/api/matm/external-links", {"url": "https://example.test", "siteName": "Example", "pageTitle": "Guide"}, "external_link_description_required")
        protected("/api/matm/external-links", {"url": "https://example.test", "siteName": "Example", "pageTitle": "Guide", "description": "Reference"}, "external_link_keywords_required")
        protected("/api/matm/knowledge-documents", {}, "title_required")
        protected("/api/matm/knowledge-documents", {"title": "Reference"}, "description_required")
        protected("/api/matm/knowledge-documents", {"title": "Reference", "description": "Reference"}, "keywords_required")
        protected("/api/matm/knowledge-documents", {"title": "Reference", "description": "Reference", "keywords": ["guide"]}, "taxonomy_paths_required")
        protected("/api/matm/knowledge-documents", {"title": "Reference", "description": "Reference", "keywords": ["guide"], "taxonomyPaths": [["Operations"]], "content": "text", "knowledgeStatus": "unknown"}, "unsupported_knowledge_status")
        protected("/api/matm/knowledge-documents", {"title": "Reference", "description": "Reference", "keywords": ["guide"], "taxonomyPaths": [["Operations"]], "content": "text", "knowledgeStatus": "historical"}, "knowledge_status_reason_required")
        protected("/api/matm/routing-decisions", {}, "source_room_id_required")
        protected("/api/matm/routing-decisions", {"sourceRoomId": "room-1"}, "routed_agent_id_required")
        protected("/api/matm/routing-decisions", {"sourceRoomId": "room-1", "routedAgentId": "agent-2"}, "routing_lane_required")
        protected("/api/matm/routing-decisions", {"sourceRoomId": "room-1", "routedAgentId": "agent-2", "lane": "review"}, "specific_goal_required")
        protected("/api/matm/meeting-rooms", {}, "unsupported_meeting_room_scope")
        protected("/api/matm/meeting-rooms", {"scope": "goal"}, "scope_id_required")
        protected("/api/matm/meeting-rooms", {"scope": "goal", "scopeId": "goal-1", "parentScopeType": "workspace", "parentScopeId": "workspace-1"}, "scope_parent_invalid")
        protected("/api/matm/agent-messages", {}, "safe_summary_required")


if __name__ == "__main__":
    unittest.main()
