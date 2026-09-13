"""Current deterministic coverage for MCP protocol parsing and projections."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memoryendpoints import mcp_server as mcp


def _environ(raw=b"", content_type="application/json", **values):
    result = {
        "CONTENT_LENGTH": str(len(raw)),
        "CONTENT_TYPE": content_type,
        "wsgi.input": io.BytesIO(raw),
    }
    result.update(values)
    return result


class McpPrimitivesCurrentTests(unittest.TestCase):
    def test_body_json_form_cookie_and_parameter_parsers_fail_closed(self):
        self.assertEqual(b"abc", mcp._read_body(_environ(b"abc"), 8))
        with self.assertRaisesRegex(ValueError, "invalid_content_length"):
            mcp._read_body(_environ(b"abc", CONTENT_LENGTH="bad"), 8)
        with self.assertRaisesRegex(ValueError, "request_too_large"):
            mcp._read_body(_environ(b"123456789"), 8)
        self.assertEqual({"a": 1}, mcp._read_json(_environ(b'{"a":1}')))
        with self.assertRaisesRegex(TypeError, "json_content_type_required"):
            mcp._read_json(_environ(b"{}", "text/plain"))
        with self.assertRaisesRegex(ValueError, "invalid_json"):
            mcp._read_json(_environ(b"{"))
        with self.assertRaisesRegex(ValueError, "json_object_required"):
            mcp._read_json(_environ(b"[]"))
        with self.assertRaisesRegex(ValueError, "non_finite_json_number"):
            mcp._read_json(_environ(b'{"x":NaN}'))
        self.assertEqual({"a": ["1"]}, mcp._read_form(_environ(b"a=1", "application/x-www-form-urlencoded")))
        with self.assertRaisesRegex(TypeError, "form_content_type_required"):
            mcp._read_form(_environ(b"a=1"))
        with self.assertRaisesRegex(ValueError, "invalid_form"):
            mcp._read_form(_environ(b"\xff", "application/x-www-form-urlencoded"))
        self.assertEqual("one", mcp._one({"x": ["one"]}, "x"))
        self.assertEqual("", mcp._one({}, "x", required=False))
        with self.assertRaisesRegex(ValueError, "duplicate_x"):
            mcp._one({"x": ["one", "two"]}, "x")
        with self.assertRaisesRegex(ValueError, "missing_x"):
            mcp._one({}, "x")
        self.assertEqual("secret", mcp._cookie({"HTTP_COOKIE": "a=b; c=secret"}, "c"))
        self.assertEqual("", mcp._cookie({"HTTP_COOKIE": "bad;\x00"}, "c"))

    def test_origin_scope_secret_resource_and_metadata_helpers_are_exact(self):
        self.assertEqual("https://example.test", mcp._origin("HTTPS://Example.Test/path"))
        self.assertEqual("", mcp._origin("example.test/path"))
        self.assertTrue(mcp._configured_https_url("https://example.test/", "/mcp").endswith("/mcp"))
        for invalid in ("", "http://example.test", "https://user@example.test", "https://example.test?x=1"):
            self.assertEqual("", mcp._configured_https_url(invalid))
        with self.assertRaisesRegex(ValueError, "invalid_scope"):
            mcp._scopes("memory:read memory:read")
        with self.assertRaisesRegex(ValueError, "invalid_scope"):
            mcp._scopes("memory:admin")
        self.assertEqual(("memory:read", "memory:write"), mcp._scopes("memory:write memory:read"))
        self.assertTrue(mcp._valid_redirect("https://chatgpt.com/connector/oauth/abc"))
        self.assertFalse(mcp._valid_redirect("https://evil.example/connector/oauth/abc"))
        secret, identifier, digest = mcp._new_secret("mcp", "access")
        self.assertEqual((identifier, secret.split(".", 2)[2]), mcp._parse_secret(secret, "mcp"))
        self.assertEqual((None, None), mcp._parse_secret("bad", "mcp"))
        self.assertEqual((None, None), mcp._parse_secret(secret, "other"))
        self.assertTrue(digest.startswith("v1:"))
        self.assertEqual(["memory:read", "memory:write"], mcp._protected_resource_metadata()["scopes_supported"])
        self.assertEqual("code", mcp._authorization_server_metadata()["response_types_supported"][0])
        error = mcp._mcp_error("request-1", -1, "bad", {"safe": True})
        self.assertEqual(-1, error["error"]["code"])
        self.assertTrue(mcp._human_session_cookie("synthetic-secret").startswith(mcp.HUMAN_SESSION_COOKIE + "="))

    def test_origin_and_browser_guards_honor_exact_configured_allowlists(self):
        with patch.dict(os.environ, {"MEMORYENDPOINTS_MCP_ALLOWED_ORIGINS": "https://allowed.example"}, clear=False):
            self.assertTrue(mcp._origin_allowed({"HTTP_ORIGIN": "https://allowed.example/"}))
            self.assertFalse(mcp._origin_allowed({"HTTP_ORIGIN": "https://blocked.example"}))
        self.assertTrue(mcp._origin_allowed({}))
        issuer_origin = mcp._origin(mcp._issuer_url())
        same_origin = {
            "HTTP_ORIGIN": issuer_origin,
            "HTTP_SEC_FETCH_SITE": "same-origin",
        }
        self.assertTrue(mcp._oauth_browser_same_origin(same_origin))
        self.assertFalse(mcp._oauth_browser_same_origin({"HTTP_ORIGIN": issuer_origin, "HTTP_SEC_FETCH_SITE": "cross-site"}))
        self.assertFalse(mcp._request_origin_matches_issuer({"wsgi.url_scheme": "http", "HTTP_HOST": "bad.example"}))
        self.assertFalse(mcp._request_is_directly_from_this_host({"REMOTE_ADDR": "not-an-ip"}))

    def test_response_and_sensitive_header_helpers_never_expose_body_state(self):
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        body = mcp._json_response(start_response, "200 OK", {"valuesRedacted": True})
        self.assertEqual("200 OK", captured["status"])
        self.assertIn("application/json", captured["headers"]["Content-Type"])
        self.assertIn(b"valuesRedacted", body[0])
        headers = dict(mcp._sensitive_headers())
        self.assertEqual("no-store, no-cache, must-revalidate, private", headers["Cache-Control"])
        self.assertEqual("DENY", headers["X-Frame-Options"])
        self.assertEqual("no-referrer", headers["Referrer-Policy"])
        self.assertEqual("same-origin", dict(mcp._oauth_page_headers())["Referrer-Policy"])

    def test_host_resource_and_oauth_path_configuration_is_strict(self):
        tunnel_id = "tunnel_" + ("a" * 32)
        with tempfile.TemporaryDirectory(prefix="mcp-config-current-") as root:
            config_path = Path(root) / "host.json"
            config_path.write_text(
                json.dumps(
                    {
                        "mcpPublicUrl": "https://mcp.example",
                        "oauthIssuerUrl": "https://issuer.example/",
                        "openAiTunnelId": tunnel_id,
                    }
                ),
                encoding="utf-8",
            )
            oauth_path = Path(root) / "oauth.sqlite3"
            with patch.dict(
                os.environ,
                {
                    "MEMORYENDPOINTS_MCP_HOST_CONFIG_PATH": str(config_path),
                    "MEMORYENDPOINTS_MCP_PUBLIC_URL": "",
                    "MEMORYENDPOINTS_MCP_ISSUER_URL": "",
                    "MEMORYENDPOINTS_MCP_OAUTH_PATH": str(oauth_path),
                },
                clear=False,
            ):
                self.assertEqual("https://mcp.example", mcp._resource_url())
                self.assertEqual("https://issuer.example", mcp._issuer_url())
                self.assertEqual(
                    "https://issuer.example/.well-known/oauth-protected-resource/mcp",
                    mcp._metadata_url(),
                )
                self.assertEqual(tunnel_id, mcp._configured_openai_tunnel_id())
                tunnel_url = (
                    "https://tunnel-service.gateway.region.internal.api.openai.org/v1/mcp/"
                    + tunnel_id
                )
                self.assertEqual(tunnel_url, mcp._accepted_resource_url(tunnel_url))
                self.assertEqual("https://mcp.example", mcp._accepted_resource_url("https://mcp.example"))
                self.assertEqual("", mcp._accepted_resource_url(tunnel_url + "?bad=1"))
                self.assertEqual(oauth_path, mcp._oauth_path())

        with patch.dict(
            os.environ,
            {"MEMORYENDPOINTS_MCP_HOST_CONFIG_PATH": "Z:\\missing\\mcp-host.json"},
            clear=False,
        ):
            self.assertEqual({}, mcp._local_host_config())

    def test_response_error_redirect_and_rate_helpers_cover_public_boundaries(self):
        captured = {}

        def start_response(status, headers):
            captured.update(status=status, headers=dict(headers))

        self.assertEqual([b"text"], mcp._response(start_response, "200 OK", "text", content_type="text/plain"))
        self.assertEqual("4", captured["headers"]["Content-Length"])
        error = mcp._oauth_error(start_response, "400 Bad Request", "invalid_request", "safe")
        self.assertEqual("400 Bad Request", captured["status"])
        self.assertIn(b"invalid_request", error[0])
        redirect = mcp._redirect(start_response, "https://chatgpt.com/connector/oauth/state")
        self.assertEqual("302 Found", captured["status"])
        self.assertEqual("https://chatgpt.com/connector/oauth/state", captured["headers"]["Location"])
        with self.assertRaises(ValueError):
            mcp._json_bytes({"not": float("nan")})
        environ = {"REMOTE_ADDR": "198.51.100.77"}
        self.assertTrue(mcp._rate_allowed(environ, "current-mcp-boundary", 1, window=60))
        self.assertFalse(mcp._rate_allowed(environ, "current-mcp-boundary", 1, window=60))


if __name__ == "__main__":
    unittest.main()
