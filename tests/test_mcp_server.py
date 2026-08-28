import base64
import hashlib
import html
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from memoryendpoints.mcp_server import route_mcp
from memoryendpoints.storage import FileStore


TEST_PEPPER = "mcp-server-test-pepper-0123456789-abcdefghijklmnopqrstuvwxyz"
RESOURCE = "https://memory.example.test/mcp"
ISSUER = "https://memory.example.test"
REDIRECT = "https://chatgpt.com/connector/oauth/test-callback"
OPENAI_TUNNEL_ID = "tunnel_" + "a" * 32
OPENAI_TUNNEL_RESOURCE = (
    "https://tunnel-service.gateway.unified-0.internal.api.openai.org/v1/mcp/"
    + OPENAI_TUNNEL_ID
)


class McpServerTests(unittest.TestCase):
    def setUp(self):
        self.previous = {
            key: os.environ.get(key)
            for key in (
                "MEMORYENDPOINTS_CREDENTIAL_PEPPER",
                "MEMORYENDPOINTS_MCP_OAUTH_PATH",
                "MEMORYENDPOINTS_MCP_PUBLIC_URL",
                "MEMORYENDPOINTS_MCP_ISSUER_URL",
                "MEMORYENDPOINTS_MCP_OPENAI_TUNNEL_ID",
            )
        }
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = TEST_PEPPER
        os.environ["MEMORYENDPOINTS_MCP_OAUTH_PATH"] = str(root / "oauth.sqlite3")
        os.environ["MEMORYENDPOINTS_MCP_PUBLIC_URL"] = RESOURCE
        os.environ["MEMORYENDPOINTS_MCP_ISSUER_URL"] = ISSUER
        self.store = FileStore(root / "store.json")
        setup = self.store.create_free_account("MCP Account", "MCP Company", "MCP Project")
        self.workspace_id, _master_id, master_secret, _account_id, self.company_id, _project_id, _recovery = setup
        proof = self.store.create_company_master_proof(master_secret)
        created = self.store.create_human_account(
            "mcp-owner", "Correct-Horse-Battery-Staple-2026", proof["masterProofSecret"]
        )
        self.assertTrue(created["ok"], created)
        login = self.store.login_human_account(
            "mcp-owner", "Correct-Horse-Battery-Staple-2026"
        )
        self.session_secret = login["sessionSecret"]

    def tearDown(self):
        self.tempdir.cleanup()
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def call(self, path, method="GET", body=b"", content_type=None, query="", headers=None):
        captured = {}

        def start_response(status, response_headers):
            captured["status"] = status
            captured["headers"] = dict(response_headers)

        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "CONTENT_LENGTH": str(len(body)),
            "wsgi.input": io.BytesIO(body),
            "REMOTE_ADDR": "127.0.0.1",
        }
        if content_type:
            environ["CONTENT_TYPE"] = content_type
        environ.update(headers or {})
        result = route_mcp(environ, start_response, path, lambda: self.store)
        self.assertIsNotNone(result)
        return captured["status"], captured["headers"], b"".join(result)

    def json_call(self, path, method="GET", payload=None, headers=None):
        raw = json.dumps(payload).encode("utf-8") if payload is not None else b""
        status, response_headers, body = self.call(
            path, method, raw, "application/json" if payload is not None else None, headers=headers
        )
        return status, response_headers, json.loads(body) if body else None

    def register(self):
        status, _headers, payload = self.json_call(
            "/oauth/register",
            "POST",
            {
                "client_name": "ChatGPT",
                "redirect_uris": [REDIRECT],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
        )
        self.assertEqual("201 Created", status, payload)
        return payload["client_id"]

    def authorize_and_exchange(self, scopes="memory:read memory:write", resource=RESOURCE):
        client_id = self.register()
        verifier = "v" * 64
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).decode("ascii").rstrip("=")
        query = urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": REDIRECT,
                "scope": scopes,
                "state": "state-0123456789",
                "resource": resource,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        status, _headers, page = self.call(
            "/oauth/authorize",
            query=query,
            headers={"HTTP_COOKIE": "__Host-memoryendpoints-human=" + self.session_secret},
        )
        self.assertEqual("200 OK", status)
        text = page.decode("utf-8")
        values = {
            name: html.unescape(re.search('name="%s" value="([^"]+)"' % name, text).group(1))
            for name in ("authorization_id", "authorization_secret")
        }
        values["choice"] = html.unescape(
            re.search('<option value="([^"]+)">MCP Company', text).group(1)
        )
        values["decision"] = "allow"
        status, headers, _body = self.call(
            "/oauth/authorize",
            "POST",
            urlencode(values).encode("utf-8"),
            "application/x-www-form-urlencoded",
            headers={
                "HTTP_COOKIE": "__Host-memoryendpoints-human=" + self.session_secret,
                "HTTP_ORIGIN": ISSUER,
            },
        )
        self.assertEqual("302 Found", status)
        redirected = urlsplit(headers["Location"])
        returned = parse_qs(redirected.query)
        self.assertEqual(["state-0123456789"], returned["state"])
        self.assertEqual([ISSUER], returned["iss"])
        token_body = urlencode(
            {
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": returned["code"][0],
                "redirect_uri": REDIRECT,
                "code_verifier": verifier,
                "resource": resource,
            }
        ).encode("utf-8")
        status, _headers, body = self.call(
            "/oauth/token", "POST", token_body, "application/x-www-form-urlencoded"
        )
        self.assertEqual("200 OK", status, body)
        return client_id, returned["code"][0], verifier, json.loads(body)

    def test_configured_openai_tunnel_resource_is_exactly_bound(self):
        os.environ["MEMORYENDPOINTS_MCP_OPENAI_TUNNEL_ID"] = OPENAI_TUNNEL_ID
        _client_id, _code, _verifier, tokens = self.authorize_and_exchange(
            resource=OPENAI_TUNNEL_RESOURCE
        )
        auth = {"HTTP_AUTHORIZATION": "Bearer " + tokens["access_token"]}
        status, _headers, initialized = self.json_call(
            "/mcp",
            "POST",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "tunnel-test", "version": "1"},
                },
            },
            auth,
        )
        self.assertEqual("200 OK", status, initialized)
        self.assertEqual("2025-11-25", initialized["result"]["protocolVersion"])

        rejected_resources = (
            OPENAI_TUNNEL_RESOURCE.replace(
                OPENAI_TUNNEL_ID, "tunnel_" + "b" * 32
            ),
            OPENAI_TUNNEL_RESOURCE.replace("internal.api.openai.org", "example.test"),
            OPENAI_TUNNEL_RESOURCE.replace("/v1/mcp/", ":443/v1/mcp/"),
            OPENAI_TUNNEL_RESOURCE + "?unexpected=true",
        )
        for rejected_resource in rejected_resources:
            with self.subTest(resource=rejected_resource):
                client_id = self.register()
                verifier = "v" * 64
                challenge = base64.urlsafe_b64encode(
                    hashlib.sha256(verifier.encode("ascii")).digest()
                ).decode("ascii").rstrip("=")
                query = urlencode(
                    {
                        "response_type": "code",
                        "client_id": client_id,
                        "redirect_uri": REDIRECT,
                        "scope": "memory:read",
                        "state": "state-rejected-resource",
                        "resource": rejected_resource,
                        "code_challenge": challenge,
                        "code_challenge_method": "S256",
                    }
                )
                status, _headers, _page = self.call("/oauth/authorize", query=query)
                self.assertEqual("400 Bad Request", status)

    def test_metadata_and_unauthorized_challenge_are_standard_shaped(self):
        status, _headers, metadata = self.json_call("/.well-known/oauth-protected-resource/mcp")
        self.assertEqual("200 OK", status)
        self.assertEqual(RESOURCE, metadata["resource"])
        self.assertEqual([ISSUER], metadata["authorization_servers"])
        status, _headers, server = self.json_call("/.well-known/oauth-authorization-server")
        self.assertEqual("200 OK", status)
        self.assertEqual(["S256"], server["code_challenge_methods_supported"])
        status, headers, body = self.json_call(
            "/mcp", "POST", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        )
        self.assertEqual("401 Unauthorized", status)
        self.assertIn("resource_metadata=", headers["WWW-Authenticate"])
        self.assertIn('scope="memory:read memory:write"', headers["WWW-Authenticate"])
        self.assertEqual(-32001, body["error"]["code"])

    def test_oauth_login_is_bound_to_the_configured_issuer_origin(self):
        payload = {"username": "mcp-owner", "password": "Correct-Horse-Battery-Staple-2026"}
        status, _headers, denied = self.json_call(
            "/oauth/session",
            "POST",
            payload,
            {"HTTP_ORIGIN": "https://other.example.test", "HTTP_SEC_FETCH_SITE": "same-origin"},
        )
        self.assertEqual("403 Forbidden", status)
        self.assertEqual("access_denied", denied["error"])
        status, headers, accepted = self.json_call(
            "/oauth/session",
            "POST",
            payload,
            {"HTTP_ORIGIN": ISSUER, "HTTP_SEC_FETCH_SITE": "same-origin"},
        )
        self.assertEqual("200 OK", status, accepted)
        self.assertTrue(accepted["signedIn"])
        self.assertIn("__Host-memoryendpoints-human=", headers["Set-Cookie"])
        self.assertIn("HttpOnly", headers["Set-Cookie"])

    def test_matching_windows_operator_auto_signs_in_only_from_direct_same_host(self):
        os.environ["MEMORYENDPOINTS_MCP_ISSUER_URL"] = "https://10.1.10.209:8088"
        client_id = self.register()
        verifier = "v" * 64
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).decode("ascii").rstrip("=")
        query = urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": REDIRECT,
                "scope": "memory:read memory:write",
                "state": "state-host-local-operator",
                "resource": RESOURCE,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        direct_headers = {
            "REMOTE_ADDR": "10.1.10.209",
            "HTTP_HOST": "10.1.10.209:8088",
            "wsgi.url_scheme": "https",
        }
        local_addresses = [
            (2, 1, 6, "", ("10.1.10.209", 0)),
        ]
        with patch(
            "memoryendpoints.mcp_server._host_local_operator_auto_sign_in_enabled",
            return_value=True,
        ), patch(
            "memoryendpoints.mcp_server._current_windows_username",
            return_value="mcp-owner",
        ), patch(
            "memoryendpoints.mcp_server.socket.getaddrinfo",
            return_value=local_addresses,
        ):
            status, headers, page = self.call(
                "/oauth/authorize", query=query, headers=direct_headers
            )
            self.assertEqual("200 OK", status)
            text = page.decode("utf-8")
            self.assertIn("Allow ChatGPT to use Multi-Agent Memory?", text)
            self.assertIn("Signed in automatically as the Windows operator", text)
            self.assertNotIn("data-mcp-login", text)
            self.assertIn("__Host-memoryendpoints-human=", headers["Set-Cookie"])
            self.assertIn("Secure", headers["Set-Cookie"])
            self.assertNotIn('value="">Choose a workspace', text)

            denied_cases = (
                dict(direct_headers, HTTP_X_FORWARDED_FOR="10.1.10.209"),
                dict(direct_headers, REMOTE_ADDR="10.1.10.77"),
                dict(
                    direct_headers,
                    REMOTE_ADDR="10.1.10.77",
                    HTTP_X_FORWARDED_FOR="10.1.10.209",
                ),
                dict(direct_headers, REMOTE_ADDR="127.0.0.1"),
                dict(direct_headers, HTTP_HOST="other.example.test"),
            )
            for request_headers in denied_cases:
                with self.subTest(headers=request_headers):
                    denied_status, denied_headers, denied_page = self.call(
                        "/oauth/authorize", query=query, headers=request_headers
                    )
                    self.assertEqual("200 OK", denied_status)
                    self.assertIn("data-mcp-login", denied_page.decode("utf-8"))
                    self.assertNotIn("Set-Cookie", denied_headers)

            with patch(
                "memoryendpoints.mcp_server._current_windows_username",
                return_value="different-user",
            ):
                mismatch_status, mismatch_headers, mismatch_page = self.call(
                    "/oauth/authorize", query=query, headers=direct_headers
                )
            self.assertEqual("200 OK", mismatch_status)
            self.assertIn("data-mcp-login", mismatch_page.decode("utf-8"))
            self.assertNotIn("Set-Cookie", mismatch_headers)

    def test_dcr_rejects_non_chatgpt_redirect(self):
        status, _headers, payload = self.json_call(
            "/oauth/register",
            "POST",
            {"redirect_uris": ["https://attacker.example/callback"]},
        )
        self.assertEqual("400 Bad Request", status)
        self.assertEqual("invalid_redirect_uri", payload["error"])
        status, _headers, payload = self.json_call(
            "/oauth/register",
            "POST",
            {"redirect_uris": ["https://chatgpt.com/connector_platform_oauth_redirect"]},
        )
        self.assertEqual("400 Bad Request", status)
        self.assertEqual("invalid_redirect_uri", payload["error"])

    def test_full_pkce_flow_initializes_lists_and_calls_bound_tools(self):
        client_id, _code, _verifier, tokens = self.authorize_and_exchange()
        auth = {"HTTP_AUTHORIZATION": "Bearer " + tokens["access_token"]}
        status, _headers, initialized = self.json_call(
            "/mcp", "POST",
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}},
            auth,
        )
        self.assertEqual("200 OK", status, initialized)
        self.assertEqual("2025-11-25", initialized["result"]["protocolVersion"])
        status, _headers, listed = self.json_call(
            "/mcp", "POST", {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, auth
        )
        self.assertEqual("200 OK", status)
        self.assertEqual(
            {"memory_search", "memory_remember", "workspace_status"},
            {item["name"] for item in listed["result"]["tools"]},
        )
        status, _headers, workspace = self.json_call(
            "/mcp", "POST",
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "workspace_status", "arguments": {}}},
            auth,
        )
        self.assertEqual("200 OK", status)
        self.assertEqual(self.workspace_id, workspace["result"]["structuredContent"]["workspace"]["workspaceId"])
        status, _headers, remembered = self.json_call(
            "/mcp", "POST",
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "memory_remember", "arguments": {"title": "MCP proof", "summary": "Public-safe MCP test memory.", "tags": ["mcp"]}}},
            auth,
        )
        self.assertEqual("200 OK", status)
        self.assertFalse(remembered["result"]["isError"])
        self.assertTrue(remembered["result"]["structuredContent"]["readbackVerified"])
        status, _headers, exact_replay = self.json_call(
            "/mcp", "POST",
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "memory_remember", "arguments": {"title": "MCP proof", "summary": "Public-safe MCP test memory.", "tags": ["mcp"]}}},
            auth,
        )
        self.assertEqual("200 OK", status)
        self.assertFalse(exact_replay["result"]["isError"])
        self.assertTrue(exact_replay["result"]["structuredContent"]["idempotentReplay"])
        self.assertEqual(
            remembered["result"]["structuredContent"]["eventId"],
            exact_replay["result"]["structuredContent"]["eventId"],
        )
        refresh_request = urlencode(
            {
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": tokens["refresh_token"],
                "resource": RESOURCE,
            }
        ).encode("utf-8")
        status, _headers, body = self.call(
            "/oauth/token", "POST", refresh_request, "application/x-www-form-urlencoded"
        )
        self.assertEqual("200 OK", status, body)
        refreshed = json.loads(body)
        status, _headers, refreshed_replay = self.json_call(
            "/mcp", "POST",
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "memory_remember", "arguments": {"title": "MCP proof", "summary": "Public-safe MCP test memory.", "tags": ["mcp"]}}},
            {"HTTP_AUTHORIZATION": "Bearer " + refreshed["access_token"]},
        )
        self.assertEqual("200 OK", status)
        self.assertTrue(refreshed_replay["result"]["structuredContent"]["idempotentReplay"])
        self.assertEqual(
            remembered["result"]["structuredContent"]["eventId"],
            refreshed_replay["result"]["structuredContent"]["eventId"],
        )
        self.assertEqual(
            1,
            len(self.store.search_memory(self.workspace_id, "MCP proof", {"_includeReviewStatuses": True})),
        )
        status, _headers, conflict = self.json_call(
            "/mcp", "POST",
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "memory_remember", "arguments": {"title": "Different payload", "summary": "Same request id must not mutate twice."}}},
            auth,
        )
        self.assertEqual("200 OK", status)
        self.assertTrue(conflict["result"]["isError"])
        self.assertEqual("idempotency_conflict", conflict["result"]["structuredContent"]["error"])
        status, _headers, searched = self.json_call(
            "/mcp", "POST",
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "memory_search", "arguments": {"query": "MCP proof"}}},
            auth,
        )
        self.assertEqual("200 OK", status)
        self.assertEqual(1, searched["result"]["structuredContent"]["count"])

    def test_authorization_code_is_one_use_and_access_is_scope_bound(self):
        client_id, code, verifier, tokens = self.authorize_and_exchange("memory:read")
        replay = urlencode(
            {"grant_type": "authorization_code", "client_id": client_id, "code": code, "redirect_uri": REDIRECT, "code_verifier": verifier, "resource": RESOURCE}
        ).encode("utf-8")
        status, _headers, body = self.call(
            "/oauth/token", "POST", replay, "application/x-www-form-urlencoded"
        )
        self.assertEqual("400 Bad Request", status)
        self.assertEqual("invalid_grant", json.loads(body)["error"])
        auth = {"HTTP_AUTHORIZATION": "Bearer " + tokens["access_token"]}
        status, _headers, denied = self.json_call(
            "/mcp", "POST",
            {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "memory_remember", "arguments": {"title": "Denied", "summary": "No write scope"}}},
            auth,
        )
        self.assertEqual("200 OK", status)
        self.assertTrue(denied["result"]["isError"])
        self.assertEqual("memory_write_scope_required", denied["result"]["structuredContent"]["error"])
        self.assertIn("mcp/www_authenticate", denied["result"]["_meta"])
        self.assertIn('error="insufficient_scope"', denied["result"]["_meta"]["mcp/www_authenticate"])
        self.assertIn('scope="memory:write"', denied["result"]["_meta"]["mcp/www_authenticate"])

    def test_refresh_reuse_and_revocation_disable_the_token_family(self):
        client_id, _code, _verifier, tokens = self.authorize_and_exchange()
        refresh_request = urlencode(
            {
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": tokens["refresh_token"],
                "resource": RESOURCE,
            }
        ).encode("utf-8")
        status, _headers, body = self.call(
            "/oauth/token", "POST", refresh_request, "application/x-www-form-urlencoded"
        )
        self.assertEqual("200 OK", status, body)
        descendant = json.loads(body)
        status, _headers, body = self.call(
            "/oauth/token", "POST", refresh_request, "application/x-www-form-urlencoded"
        )
        self.assertEqual("400 Bad Request", status)
        self.assertEqual("invalid_grant", json.loads(body)["error"])
        status, _headers, _payload = self.json_call(
            "/mcp",
            "POST",
            {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
            {"HTTP_AUTHORIZATION": "Bearer " + descendant["access_token"]},
        )
        self.assertEqual("401 Unauthorized", status)

        client_id, _code, _verifier, tokens = self.authorize_and_exchange()
        revoke_request = urlencode(
            {"client_id": client_id, "token": tokens["access_token"]}
        ).encode("utf-8")
        status, _headers, body = self.call(
            "/oauth/revoke", "POST", revoke_request, "application/x-www-form-urlencoded"
        )
        self.assertEqual("200 OK", status)
        self.assertEqual(b"", body)
        status, _headers, _payload = self.json_call(
            "/mcp",
            "POST",
            {"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}},
            {"HTTP_AUTHORIZATION": "Bearer " + tokens["access_token"]},
        )
        self.assertEqual("401 Unauthorized", status)

    def test_family_schema_migration_revokes_unlinkable_legacy_tokens(self):
        oauth_path = Path(os.environ["MEMORYENDPOINTS_MCP_OAUTH_PATH"])
        legacy_connection = sqlite3.connect(str(oauth_path))
        try:
            connection = legacy_connection
            connection.executescript(
                """
                CREATE TABLE mcp_oauth_access_tokens (
                  token_id TEXT PRIMARY KEY, secret_hash TEXT NOT NULL,
                  client_id TEXT NOT NULL, resource_url TEXT NOT NULL,
                  scopes TEXT NOT NULL, human_account_id TEXT NOT NULL,
                  company_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
                  created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
                  revoked_at INTEGER
                );
                CREATE TABLE mcp_oauth_refresh_tokens (
                  token_id TEXT PRIMARY KEY, secret_hash TEXT NOT NULL,
                  client_id TEXT NOT NULL, resource_url TEXT NOT NULL,
                  scopes TEXT NOT NULL, human_account_id TEXT NOT NULL,
                  company_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
                  created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
                  revoked_at INTEGER
                );
                """
            )
            values = (
                "v1:legacy", "legacy-client", RESOURCE, "memory:read",
                "legacy-human", "legacy-company", self.workspace_id, 1, 4102444800,
            )
            connection.execute(
                "INSERT INTO mcp_oauth_access_tokens VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                ("a" * 32,) + values,
            )
            connection.execute(
                "INSERT INTO mcp_oauth_refresh_tokens VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                ("b" * 32,) + values,
            )
            connection.commit()
        finally:
            legacy_connection.close()
        from memoryendpoints.mcp_server import _connect

        connection = _connect()
        try:
            for table in ("mcp_oauth_access_tokens", "mcp_oauth_refresh_tokens"):
                row = connection.execute(
                    "SELECT family_id, revoked_at FROM %s" % table
                ).fetchone()
                self.assertTrue(row["family_id"].startswith("legacy-revoked-"))
                self.assertIsNotNone(row["revoked_at"])
        finally:
            connection.close()

    def test_write_quota_failure_does_not_mutate_or_reserve_retry(self):
        _client_id, _code, _verifier, tokens = self.authorize_and_exchange()
        auth = {"HTTP_AUTHORIZATION": "Bearer " + tokens["access_token"]}
        original = self.store.has_quota_for
        self.store.has_quota_for = lambda _workspace_id, _candidate: False
        try:
            request = {
                "jsonrpc": "2.0",
                "id": "quota-write-1",
                "method": "tools/call",
                "params": {
                    "name": "memory_remember",
                    "arguments": {"title": "Quota denied", "summary": "This must not be stored."},
                },
            }
            status, _headers, denied = self.json_call("/mcp", "POST", request, auth)
            self.assertEqual("200 OK", status)
            self.assertEqual("workspace_storage_quota_reached", denied["result"]["structuredContent"]["error"])
        finally:
            self.store.has_quota_for = original
        self.assertEqual([], self.store.search_memory(self.workspace_id, "Quota denied", {"_includeReviewStatuses": True}))
        status, _headers, accepted = self.json_call("/mcp", "POST", request, auth)
        self.assertEqual("200 OK", status)
        self.assertFalse(accepted["result"]["isError"])

    def test_jsonrpc_validation_and_origin_fail_closed(self):
        _client_id, _code, _verifier, tokens = self.authorize_and_exchange()
        auth = {"HTTP_AUTHORIZATION": "Bearer " + tokens["access_token"]}
        status, _headers, invalid = self.json_call(
            "/mcp", "POST", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, auth
        )
        self.assertEqual("200 OK", status)
        self.assertEqual(-32602, invalid["error"]["code"])
        status, _headers, empty = self.json_call(
            "/mcp", "POST", {"jsonrpc": "2.0", "method": "tools/list", "params": {}}, auth
        )
        self.assertEqual("202 Accepted", status)
        self.assertIsNone(empty)
        status, _headers, invalid = self.json_call(
            "/mcp", "POST",
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "workspace_status", "arguments": []}},
            auth,
        )
        self.assertEqual("200 OK", status)
        self.assertEqual(-32602, invalid["error"]["code"])
        status, _headers, body = self.call(
            "/mcp", "OPTIONS", headers={"HTTP_ORIGIN": "https://attacker.example"}
        )
        self.assertEqual("403 Forbidden", status)
        self.assertEqual(-32000, json.loads(body)["error"]["code"])
        for invalid_id in (float("nan"), float("inf"), float("-inf")):
            status, _headers, invalid = self.json_call(
                "/mcp",
                "POST",
                {"jsonrpc": "2.0", "id": invalid_id, "method": "ping", "params": {}},
                auth,
            )
            self.assertEqual("400 Bad Request", status)
            self.assertEqual(-32700, invalid["error"]["code"])

    def test_setup_status_does_not_claim_private_url_is_externally_ready(self):
        os.environ["MEMORYENDPOINTS_MCP_PUBLIC_URL"] = "https://10.1.10.209:8088/mcp"
        status, _headers, payload = self.json_call("/mcp/setup/status")
        self.assertEqual("200 OK", status)
        self.assertFalse(payload["externalHttpsConfigurationPresent"])
        self.assertFalse(payload["externalReachabilityVerified"])
        self.assertTrue(payload["requiresSecureMcpTunnelOrPublicHttps"])
        os.environ["MEMORYENDPOINTS_MCP_PUBLIC_URL"] = "https://mcp.intranet.example/mcp"
        os.environ["MEMORYENDPOINTS_MCP_ISSUER_URL"] = "https://login.intranet.example"
        status, _headers, payload = self.json_call("/mcp/setup/status")
        self.assertEqual("200 OK", status)
        self.assertTrue(payload["externalHttpsConfigurationPresent"])
        self.assertFalse(payload["externalReachabilityVerified"])

    def test_windows_helper_prioritizes_local_readiness_before_tunnel_setup(self):
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            self.skipTest("Windows PowerShell is not available")
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "setup_chatgpt_mcp.ps1"
        command = r"""
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($env:MCP_SETUP_SCRIPT_TEST_PATH, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'setup_script_parse_failed' }
$definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-NextAction' }, $true)
if (-not $definition) { throw 'next_action_function_missing' }
Invoke-Expression $definition.Extent.Text
Get-NextAction -LocalMcpReady $false -TunnelClientInstalled $false -DcrSampleSupported $false -TunnelProfilePresent $false -TunnelIdProvided $false -ControlPlaneApiKeyPresent $false
"""
        process_environment = dict(os.environ)
        process_environment["MCP_SETUP_SCRIPT_TEST_PATH"] = str(script_path)
        completed = subprocess.run(
            [powershell, "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=process_environment,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("Start or restart the local Multi-Agent Memory host", completed.stdout)
        self.assertNotIn("Download tunnel-client", completed.stdout)

    def test_windows_helper_uses_an_explicit_ignored_profile_directory(self):
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "setup_chatgpt_mcp.ps1"
        script = script_path.read_text(encoding="utf-8")
        self.assertIn("[string]$TunnelProfileDir", script)
        self.assertIn(".local-secrets\\tunnel-client\\profiles", script)
        self.assertIn(".local-secrets\\tools\\tunnel-client", script)
        self.assertIn("$localCandidates.Count -eq 1", script)
        self.assertIn("--profile-dir $resolvedTunnelProfileDir", script)
        self.assertIn("tunnelProfilePresent = $tunnelProfilePresent", script)
        self.assertIn("function Write-McpHostConfig", script)
        self.assertIn("openAiTunnelId", script)
        self.assertIn("Write-McpHostConfig -OpenAiTunnelId $TunnelId", script)

    def test_windows_helper_preserves_urls_when_it_records_the_tunnel_id(self):
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            self.skipTest("Windows PowerShell is not available")
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "setup_chatgpt_mcp.ps1"
        command = r"""
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($env:MCP_SETUP_SCRIPT_TEST_PATH, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'setup_script_parse_failed' }
foreach ($name in @('Resolve-HttpsUrl', 'Write-McpHostConfig')) {
    $definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    if (-not $definition) { throw ('setup_function_missing_' + $name) }
    Invoke-Expression $definition.Extent.Text
}
$resolvedRoot = [IO.Path]::GetFullPath($env:MCP_SETUP_TEMP_ROOT)
Write-McpHostConfig -McpPublicUrl 'https://mcp.example.test/mcp' -IssuerUrl 'https://auth.example.test'
Write-McpHostConfig -OpenAiTunnelId ('tunnel_' + ('a' * 32))
$config = Get-Content -LiteralPath (Join-Path $resolvedRoot '.local-secrets\mcp-host.json') -Raw | ConvertFrom-Json
if ($config.mcpPublicUrl -cne 'https://mcp.example.test/mcp') { throw 'public_url_not_preserved' }
if ($config.oauthIssuerUrl -cne 'https://auth.example.test') { throw 'issuer_url_not_preserved' }
if ($config.openAiTunnelId -cne ('tunnel_' + ('a' * 32))) { throw 'tunnel_id_not_recorded' }
if (-not $config.valuesRedacted -or $config.rawCredentialExposed -or $config.rawPayloadExposed) { throw 'redaction_flags_invalid' }
"""
        with tempfile.TemporaryDirectory() as temporary:
            process_environment = dict(os.environ)
            process_environment["MCP_SETUP_SCRIPT_TEST_PATH"] = str(script_path)
            process_environment["MCP_SETUP_TEMP_ROOT"] = temporary
            completed = subprocess.run(
                [powershell, "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                env=process_environment,
            )
        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_windows_helper_reads_modern_www_authenticate_headers(self):
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            self.skipTest("Windows PowerShell is not available")
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "setup_chatgpt_mcp.ps1"
        command = r'''
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($env:MCP_SETUP_SCRIPT_TEST_PATH, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'setup_script_parse_failed' }
$definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-ResponseHeaderValue' }, $true)
if (-not $definition) { throw 'response_header_helper_missing' }
Invoke-Expression $definition.Extent.Text
Add-Type -AssemblyName System.Net.Http
$response = [System.Net.Http.HttpResponseMessage]::new([System.Net.HttpStatusCode]::Unauthorized)
$expected = 'Bearer resource_metadata="https://mcp.example/.well-known/oauth-protected-resource/mcp", scope="memory:read memory:write"'
$null = $response.Headers.TryAddWithoutValidation('WWW-Authenticate', $expected)
$actual = Get-ResponseHeaderValue -Response $response -Name 'WWW-Authenticate'
if ($actual -cne $expected) { throw 'modern_www_authenticate_header_not_read' }
'''
        process_environment = dict(os.environ)
        process_environment["MCP_SETUP_SCRIPT_TEST_PATH"] = str(script_path)
        completed = subprocess.run(
            [powershell, "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=process_environment,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)


if __name__ == "__main__":
    unittest.main()
