import base64
import hashlib
import io
import inspect
import json
import os
import unittest
from urllib.parse import urlsplit
from unittest.mock import patch

import memoryendpoints.mcp_server as mcp


class McpSharedPrimitivesCurrentTests(unittest.TestCase):
    def setUp(self):
        self._environment = {
            name: os.environ.get(name)
            for name in (
                "MEMORYENDPOINTS_MCP_ALLOWED_ORIGINS",
                "MEMORYENDPOINTS_MCP_HOST_LOCAL_AUTO_SIGN_IN",
                "MEMORYENDPOINTS_MCP_OAUTH_PATH",
                "MEMORYENDPOINTS_MCP_PUBLIC_URL",
                "MEMORYENDPOINTS_MCP_ISSUER_URL",
                "MEMORYENDPOINTS_MCP_OPENAI_TUNNEL_ID",
                "MEMORYENDPOINTS_CREDENTIAL_PEPPER",
            )
        }
        os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = (
            "shared-mcp-test-pepper-0123456789-abcdefghijklmnopqrstuvwxyz"
        )
        mcp._RATE_BUCKETS.clear()

    def tearDown(self):
        mcp._RATE_BUCKETS.clear()
        for name, value in self._environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    @staticmethod
    def _body(raw, content_type="application/json"):
        return {
            "CONTENT_LENGTH": str(len(raw)),
            "CONTENT_TYPE": content_type,
            "wsgi.input": io.BytesIO(raw),
        }

    @staticmethod
    def _start_response_capture():
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        return captured, start_response

    def test_shared_jsonrpc_and_response_helpers_are_canonical_and_safe(self):
        self.assertEqual(b'{"a":1,"b":[true]}', mcp._json_bytes({"b": [True], "a": 1}))
        with self.assertRaises((ValueError, TypeError)):
            mcp._json_bytes({"bad": float("nan")})

        self.assertEqual(
            {"jsonrpc": "2.0", "id": "r1", "error": {"code": -1, "message": "bad"}},
            mcp._mcp_error("r1", -1, "bad"),
        )
        self.assertEqual(
            {"code": -1, "message": "bad", "data": {"reason": "closed"}},
            mcp._mcp_error("r1", -1, "bad", {"reason": "closed"})["error"],
        )

        captured, start_response = self._start_response_capture()
        body = mcp._response(
            start_response,
            "200 OK",
            "héllo",
            "text/plain",
            headers=[("X-Test", "yes")],
        )
        self.assertEqual(["héllo".encode("utf-8")], body)
        self.assertEqual("200 OK", captured["status"])
        self.assertEqual("yes", captured["headers"]["X-Test"])
        self.assertEqual("6", captured["headers"]["Content-Length"])
        self.assertEqual("nosniff", captured["headers"]["X-Content-Type-Options"])

        captured, start_response = self._start_response_capture()
        mcp._json_response(start_response, "200 OK", {"ok": True})
        self.assertEqual("application/json; charset=utf-8", captured["headers"]["Content-Type"])

        captured, start_response = self._start_response_capture()
        mcp._oauth_error(start_response, "400 Bad Request", "invalid_request", "bad")
        self.assertEqual("no-store", captured["headers"]["Cache-Control"])
        self.assertEqual("no-cache", captured["headers"]["Pragma"])

        captured, start_response = self._start_response_capture()
        mcp._redirect(start_response, "https://client.example/callback")
        self.assertEqual("302 Found", captured["status"])
        self.assertEqual("https://client.example/callback", captured["headers"]["Location"])
        sensitive = dict(mcp._sensitive_headers(referrer_policy="origin"))
        self.assertEqual("origin", sensitive["Referrer-Policy"])
        self.assertEqual("DENY", sensitive["X-Frame-Options"])
        self.assertIn("form-action 'self'", sensitive["Content-Security-Policy"])
        self.assertIn("__Host-memoryendpoints-human=secret", mcp._human_session_cookie("secret"))

    def test_shared_request_decoders_reject_ambiguous_or_oversized_input(self):
        self.assertEqual(b"abc", mcp._read_body(self._body(b"abc", "text/plain"), 3))
        with self.assertRaisesRegex(ValueError, "invalid_content_length"):
            mcp._read_body(dict(self._body(b""), CONTENT_LENGTH="not-a-number"), 3)
        with self.assertRaisesRegex(ValueError, "request_too_large"):
            mcp._read_body(self._body(b"abcd"), 3)

        self.assertEqual({"answer": 42}, mcp._read_json(self._body(b'{"answer":42}')))
        with self.assertRaises(TypeError):
            mcp._read_json(self._body(b"{}", "text/plain"))
        with self.assertRaises(ValueError):
            mcp._read_json(self._body(b"not-json"))
        with self.assertRaises(ValueError):
            mcp._read_json(self._body(b"[1,2]"))
        with self.assertRaises(ValueError):
            mcp._read_json(self._body(b'{"value":NaN}'))

        parsed = mcp._read_form(self._body(b"a=1&a=2&blank=", "application/x-www-form-urlencoded"))
        self.assertEqual(["1", "2"], parsed["a"])
        self.assertEqual([""], parsed["blank"])
        with self.assertRaises(TypeError):
            mcp._read_form(self._body(b"a=1"))
        with self.assertRaises(ValueError):
            mcp._read_form(self._body(b"\xff", "application/x-www-form-urlencoded"))

        self.assertEqual("one", mcp._one({"value": ["one"]}, "value"))
        self.assertEqual("", mcp._one({}, "optional", required=False))
        with self.assertRaisesRegex(ValueError, "missing_value"):
            mcp._one({}, "value")
        with self.assertRaisesRegex(ValueError, "duplicate_value"):
            mcp._one({"value": ["one", "two"]}, "value")

        self.assertEqual("abc", mcp._cookie({"HTTP_COOKIE": "session=abc; other=two"}, "session"))
        self.assertEqual("", mcp._cookie({}, "missing"))

    def test_shared_oauth_secret_pkce_scope_and_rate_helpers_fail_closed(self):
        token, identifier, stored_hash = mcp._new_secret("access", "access")
        parsed_identifier, parsed_secret = mcp._parse_secret(token, "access")
        self.assertEqual(identifier, parsed_identifier)
        self.assertEqual(stored_hash, mcp._secret_hash("access", identifier, parsed_secret))
        self.assertEqual((None, None), mcp._parse_secret(token, "refresh"))
        for malformed in ("", "access.bad.secret", token + ".extra", token.replace(".", "..", 1)):
            with self.subTest(malformed=malformed):
                self.assertEqual((None, None), mcp._parse_secret(malformed, "access"))

        verifier = "v" * 64
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
        self.assertEqual(expected, mcp._pkce_s256(verifier))

        if len(inspect.signature(mcp._scopes).parameters) == 2:
            profile = mcp._client_profile(mcp.LOCALENDPOINTS_OAUTH_CLIENT_ID)
            self.assertEqual(("memory:read",), mcp._scopes("memory:read", profile))
            with self.assertRaisesRegex(ValueError, "invalid_scope"):
                mcp._scopes("unknown", profile)
        else:
            self.assertEqual(("memory:read", "memory:write"), mcp._scopes("memory:write memory:read"))
            with self.assertRaisesRegex(ValueError, "invalid_scope"):
                mcp._scopes("memory:read memory:read")
            with self.assertRaisesRegex(ValueError, "invalid_scope"):
                mcp._scopes("unknown")

        environment = {"REMOTE_ADDR": "198.51.100.9"}
        with patch.object(mcp, "_now", return_value=100):
            self.assertTrue(mcp._rate_allowed(environment, "shared-helper", 1, window=60))
            self.assertFalse(mcp._rate_allowed(environment, "shared-helper", 1, window=60))
        with patch.object(mcp, "_now", return_value=161):
            self.assertTrue(mcp._rate_allowed(environment, "shared-helper", 1, window=60))

    def test_shared_origin_and_host_checks_cover_allowed_and_denied_lanes(self):
        issuer = mcp._issuer_url()
        issuer_origin = mcp._origin(issuer)
        self.assertTrue(issuer_origin)
        self.assertEqual(issuer_origin, mcp._origin(issuer + "/oauth/authorize"))
        self.assertEqual("", mcp._origin("javascript:alert(1)"))
        self.assertEqual("", mcp._origin("not a url"))
        self.assertEqual(mcp._resource_url(), mcp._accepted_resource_url(mcp._resource_url()))
        self.assertEqual("", mcp._accepted_resource_url("https://attacker.example/mcp"))

        configured_path = os.path.abspath("mcp-oauth-shared-test.sqlite3")
        with patch.dict(
            os.environ,
            {"MEMORYENDPOINTS_MCP_OAUTH_PATH": configured_path},
            clear=False,
        ):
            self.assertEqual(configured_path, str(mcp._oauth_path()))
        with patch.dict(
            os.environ,
            {
                "MEMORYENDPOINTS_MCP_OAUTH_PATH": "",
                "MEMORYENDPOINTS_DATA_DIR": os.path.abspath("mcp-data-shared"),
            },
            clear=False,
        ):
            self.assertEqual(
                os.path.join(os.path.abspath("mcp-data-shared"), "mcp_oauth.sqlite3"),
                str(mcp._oauth_path()),
            )

        page_headers = dict(mcp._oauth_page_headers([("X-Page", "yes")]))
        self.assertEqual("yes", page_headers["X-Page"])
        self.assertIn(page_headers["Referrer-Policy"], ("origin", "same-origin"))

        self.assertTrue(mcp._origin_allowed({}))
        self.assertTrue(mcp._origin_allowed({"HTTP_ORIGIN": issuer_origin}))
        self.assertFalse(mcp._origin_allowed({"HTTP_ORIGIN": "https://attacker.example"}))

        self.assertTrue(
            mcp._oauth_browser_same_origin(
                {"HTTP_ORIGIN": issuer_origin, "HTTP_SEC_FETCH_SITE": "same-origin"}
            )
        )
        self.assertFalse(
            mcp._oauth_browser_same_origin(
                {"HTTP_ORIGIN": issuer_origin, "HTTP_SEC_FETCH_SITE": "cross-site"}
            )
        )
        self.assertTrue(
            mcp._oauth_browser_same_origin(
                {"HTTP_REFERER": issuer + "/oauth/authorize", "HTTP_SEC_FETCH_SITE": "same-origin"}
            )
        )
        self.assertTrue(
            mcp._oauth_browser_same_origin(
                {"HTTP_ORIGIN": "null", "HTTP_REFERER": issuer + "/oauth/authorize"}
            )
        )
        self.assertFalse(mcp._oauth_browser_same_origin({}))

        parsed = urlsplit(issuer)
        matching = {"wsgi.url_scheme": parsed.scheme, "HTTP_HOST": parsed.netloc}
        self.assertTrue(mcp._request_origin_matches_issuer(matching))
        for invalid in (
            {},
            {"wsgi.url_scheme": "ftp", "HTTP_HOST": parsed.netloc},
            {"wsgi.url_scheme": parsed.scheme, "HTTP_HOST": "attacker.example"},
            {"wsgi.url_scheme": parsed.scheme, "HTTP_HOST": "user@" + parsed.netloc},
            {"wsgi.url_scheme": parsed.scheme, "HTTP_HOST": parsed.netloc + "/bad"},
        ):
            with self.subTest(invalid=invalid):
                self.assertFalse(mcp._request_origin_matches_issuer(invalid))

        with patch.object(mcp.os, "name", "posix"):
            self.assertFalse(mcp._host_local_operator_auto_sign_in_enabled())
            self.assertEqual("", mcp._current_windows_username())
        with patch.object(mcp.os, "name", "nt"):
            os.environ["MEMORYENDPOINTS_MCP_HOST_LOCAL_AUTO_SIGN_IN"] = "off"
            self.assertFalse(mcp._host_local_operator_auto_sign_in_enabled())
            os.environ["MEMORYENDPOINTS_MCP_HOST_LOCAL_AUTO_SIGN_IN"] = "on"
            self.assertTrue(mcp._host_local_operator_auto_sign_in_enabled())
        self.assertFalse(mcp._request_is_directly_from_this_host({}))

    def test_shared_metadata_and_client_policy_surfaces_are_stable(self):
        protected = mcp._protected_resource_metadata()
        self.assertEqual(mcp._resource_url(), protected["resource"])
        self.assertEqual([mcp._issuer_url()], protected["authorization_servers"])
        self.assertEqual(list(mcp.MCP_SCOPES), protected["scopes_supported"])
        self.assertEqual(["header"], protected["bearer_methods_supported"])

        server = mcp._authorization_server_metadata()
        self.assertEqual(mcp._issuer_url(), server["issuer"])
        self.assertEqual(["code"], server["response_types_supported"])
        self.assertEqual(["S256"], server["code_challenge_methods_supported"])
        self.assertTrue(server["resource_parameter_supported"])

        if hasattr(mcp, "_client_profile"):
            local = mcp._client_profile(mcp.LOCALENDPOINTS_OAUTH_CLIENT_ID)
            self.assertEqual("localendpoints", local["kind"])
            self.assertIsNone(mcp._client_profile("unrecognized-client"))
        else:
            self.assertTrue(mcp._valid_redirect("https://chatgpt.com/connector/oauth/abc_123"))
            self.assertFalse(mcp._valid_redirect("https://attacker.example/callback"))


if __name__ == "__main__":
    unittest.main()
