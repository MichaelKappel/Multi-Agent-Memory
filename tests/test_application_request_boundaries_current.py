"""Shared parser, bearer, CORS, and request-safety boundary coverage."""

from __future__ import annotations

import io
import json
import os
import unittest
from unittest.mock import patch

from memoryendpoints import app


class ApplicationRequestBoundaryTests(unittest.TestCase):
    @staticmethod
    def _response(function, *args, **kwargs):
        captured = {}

        def start_response(status, headers, exc_info=None):
            captured["status"] = status
            captured["headers"] = dict(headers)

        body = b"".join(function(start_response, *args, **kwargs))
        captured["body"] = json.loads(body.decode("utf-8")) if body else {}
        return captured

    @staticmethod
    def _environ(raw=b"", content_type="application/json", content_length=None):
        return {
            "wsgi.input": io.BytesIO(raw),
            "CONTENT_LENGTH": str(len(raw) if content_length is None else content_length),
            "CONTENT_TYPE": content_type,
        }

    def test_body_query_bearer_and_idempotency_boundaries_are_typed(self):
        self.assertEqual({}, app._read_body(self._environ()))
        self.assertEqual({"ok": True}, app._read_body(self._environ(b'{"ok": true}')))
        self.assertIsNone(app._read_body(self._environ(b"not-json")))
        self.assertEqual({}, app._read_body(self._environ(b"ignored", content_length=0)))
        self.assertEqual({"a": "1"}, app._query({"QUERY_STRING": "a=1&a=2&empty="}))
        self.assertFalse(app._is_knowledge_page_route("/knowledge/"))
        self.assertTrue(app._is_knowledge_page_route("/knowledge/project/operations"))
        self.assertFalse(app._is_tour_knowledge_page_route("/tour/knowledge/project/operations/"))

        self.assertEqual("me_live_token", app._token({"HTTP_AUTHORIZATION": "Bearer me_live_token"}))
        self.assertEqual("me_live_header", app._token({"HTTP_X_MEMORYENDPOINTS_KEY": "me_live_header"}))
        self.assertEqual("", app._token({"HTTP_AUTHORIZATION": "Basic value"}))
        self.assertEqual("key-1", app._idempotency_key({"HTTP_IDEMPOTENCY_KEY": " key-1 "}))
        auths = (
            ({"credentialType": "company_master", "masterKeyId": "master-1"}, "company_master"),
            ({"credentialType": "agent", "agentIdentityId": "agent-1"}, "agent"),
            ({"credentialType": "connector", "connectorCredentialId": "connector-1"}, "connector"),
        )
        keys = {app._principal_scoped_idempotency_key(auth, "same-key") for auth, _ in auths}
        self.assertEqual(3, len(keys))
        self.assertEqual("", app._principal_scoped_idempotency_key({}, ""))

        key, rejected = app._validated_idempotency_key_or_problem(
            {"HTTP_IDEMPOTENCY_KEY": "k" * 16},
            lambda *_args, **_kwargs: None,
        )
        self.assertEqual("k" * 16, key)
        self.assertIsNone(rejected)
        self.assertEqual(("", None), app._validated_idempotency_key_or_problem({}, lambda *_args: None, required=False))
        captured = {}
        def start_response(status, headers, exc_info=None):
            captured["status"] = status
        key, rejected = app._validated_idempotency_key_or_problem({}, start_response)
        self.assertEqual("", key)
        self.assertEqual("422 Unprocessable Entity", captured["status"])
        self.assertIsNotNone(rejected)

    def test_cors_and_cookie_boundaries_fail_closed(self):
        with patch.dict(os.environ, {"MEMORYENDPOINTS_CORS_ALLOWED_ORIGINS": "https://one.test, https://two.test"}, clear=False):
            self.assertEqual("https://one.test", app._cors_allowed_origin({"HTTP_ORIGIN": " https://one.test "}))
            self.assertEqual("", app._cors_allowed_origin({}))
            self.assertIsNone(app._cors_allowed_origin({"HTTP_ORIGIN": "https://other.test"}))
            self.assertTrue(app._cors_headers({"HTTP_ORIGIN": "https://one.test"}))
            self.assertEqual([], app._cors_headers({"HTTP_ORIGIN": "https://other.test"}))
        with patch.dict(os.environ, {"MEMORYENDPOINTS_CORS_ALLOWED_ORIGINS": "*"}, clear=False):
            self.assertEqual("*", app._cors_allowed_origin({"HTTP_ORIGIN": "https://other.test"}))
        captured = {}
        with patch.dict(os.environ, {"MEMORYENDPOINTS_CORS_ALLOWED_ORIGINS": "https://allowed.test"}, clear=False):
            body = b"".join(app._route_cors_preflight(
                {"HTTP_ORIGIN": "https://other.test"},
                lambda status, headers, exc_info=None: captured.setdefault("status", status),
            ))
        self.assertTrue(captured["status"].startswith("403"))

        self.assertEqual("", app._request_cookie({}, "session"))
        self.assertEqual("value", app._request_cookie({"HTTP_COOKIE": "other=x; session=value"}, "session"))
        self.assertEqual("", app._request_cookie({"HTTP_COOKIE": "bad; cookie"}, "session"))
        self.assertFalse(app._human_same_origin({"HTTP_SEC_FETCH_SITE": "cross-site"}))

    def test_connector_boundary_helpers_reject_oversized_and_malformed_inputs(self):
        start = lambda *_args, **_kwargs: None
        valid = self._environ(b'{"ok": true}')
        self.assertEqual({"ok": True}, app._connector_body_or_problem(valid, start)[0])
        for environ in (
            self._environ(b"{}", "text/plain"),
            self._environ(b"{}", content_length="bad"),
            self._environ(b"[]"),
            self._environ(b"not-json"),
        ):
            with self.subTest(environ=environ):
                self.assertIsNone(app._connector_body_or_problem(environ, start)[0])
        with patch.object(app, "_CONNECTOR_MAX_JSON_REQUEST_BYTES", 1):
            self.assertIsNone(app._connector_body_or_problem(self._environ(b"{}"), start)[0])
        self.assertEqual(("k" * 16, None), app._connector_idempotency_or_problem({"HTTP_IDEMPOTENCY_KEY": "k" * 16}, start))
        self.assertIsNone(app._connector_idempotency_or_problem({}, start)[0])
        self.assertIsNone(app._connector_idempotency_or_problem({"HTTP_IDEMPOTENCY_KEY": "bad"}, start)[0])
        self.assertEqual("200 OK", self._response(app._connector_json, {"ok": True})["status"])
        self.assertEqual("201 Created", self._response(app._connector_one_time_secret, {"secret": "one-time"})["status"])
        with patch.object(app, "_CONNECTOR_MAX_JSON_RESPONSE_BYTES", 1):
            self.assertEqual("503 Service Unavailable", self._response(app._connector_json, {"too": "large"})["status"])
        for code, status in (("invalid_token", "401 Unauthorized"), ("connector_scope_forbidden", "403 Forbidden"), ("pairing_not_found", "404 Not Found"), ("rate_limited", "429 Too Many Requests"), ("unknown", "422 Unprocessable Entity")):
            with self.subTest(code=code):
                self.assertEqual(status, self._response(app._connector_problem, code)["status"])

    def test_agent_binding_and_store_selection_cover_identity_fallbacks(self):
        start = lambda *_args, **_kwargs: None
        self.assertEqual(("agent-1", None), app._bound_agent_id_or_problem({"credentialType": "agent", "agentId": "agent-1"}, start))
        self.assertIsNone(app._bound_agent_id_or_problem({}, start)[0])
        self.assertIsNone(app._bound_agent_id_or_problem({"agentId": "agent-1"}, start, "other-agent")[0])
        self.assertEqual("None", str(app._diagnostic_fingerprint(None)))
        self.assertEqual(12, len(app._diagnostic_fingerprint("problem")))
        with patch("memoryendpoints.app.configured_store_backend", return_value="sqlite"):
            self.assertEqual("SQLiteStore", app._store().__class__.__name__)
        with patch("memoryendpoints.app.configured_store_backend", return_value="file"):
            self.assertEqual("FileStore", app._store().__class__.__name__)


if __name__ == "__main__":
    unittest.main()
