import io
import json
import unittest
from unittest.mock import patch

from memoryendpoints import human_operational as operational


class SharedHumanOperationalPrimitivesCurrentTests(unittest.TestCase):
    def _session(self, role="owner"):
        return {
            "humanAccountId": "human-1",
            "humanAccountSessionId": "session-1",
            "username": "alice",
            "role": role,
        }

    def _context(self, selected=True):
        return {
            "authorityId": "authority-1",
            "companyId": "company-1",
            "workspaceId": "workspace-1" if selected else None,
            "projectId": "project-1" if selected else None,
            "contextVersion": "context-v1",
        }

    def _environ(self, body=b"{}", content_type="application/json", length=None):
        environ = {
            "CONTENT_TYPE": content_type,
            "wsgi.input": io.BytesIO(body),
        }
        if length is not None:
            environ["CONTENT_LENGTH"] = str(length)
        return environ

    def test_shared_permissions_operations_and_envelope_are_tenant_bound(self):
        viewer = operational._permissions("viewer")
        owner = operational._permissions("owner")
        self.assertFalse(viewer["canReadWorkspace"])
        self.assertTrue(owner["canReadWorkspace"])
        self.assertTrue(owner["canSubmitPublicSafeMemory"])
        self.assertFalse(viewer["canSendMessages"])
        self.assertFalse(operational._permissions(None)["canUseCollaboration"])

        unselected = operational._operations(owner, False)
        selected = operational._operations(owner, True)
        self.assertTrue(unselected["contextCatalog"]["allowed"])
        self.assertFalse(unselected["workspace"]["allowed"])
        self.assertTrue(selected["workspace"]["allowed"])
        self.assertFalse(selected["collaboration"]["allowed"])
        self.assertIn("methods", selected["memorySubmit"])

        envelope = operational._envelope(
            self._session(), self._context(), extra="safe"
        )
        self.assertEqual("workspace-1", envelope["resourceContext"]["workspaceId"])
        self.assertEqual("human-1", envelope["auditActor"]["humanAccountId"])
        self.assertEqual("safe", envelope["extra"])
        self.assertTrue(envelope["valuesRedacted"])
        self.assertFalse(envelope["rawPayloadExposed"])

    def test_shared_cookie_json_query_and_context_helpers_fail_closed(self):
        self.assertEqual(
            "secret",
            operational._request_cookie(
                {"HTTP_COOKIE": operational.HUMAN_SESSION_COOKIE + "=secret"}
            ),
        )
        self.assertEqual("", operational._request_cookie({}))
        self.assertEqual("", operational._request_cookie({"HTTP_COOKIE": "broken;"}))
        cookie = operational._session_cookie("secret")
        self.assertIn("Secure", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)

        body, error = operational._read_json(
            self._environ(json.dumps({"ok": True}).encode(), "application/json; charset=utf-8")
        )
        self.assertEqual({"ok": True}, body)
        self.assertIsNone(error)
        cases = (
            (self._environ(b"{}", "text/plain"), "human_json_content_type_required"),
            (self._environ(b"{}", "application/json", "bad"), "human_json_body_invalid"),
            (self._environ(b"{}", "application/json", -1), "human_json_body_too_large"),
            (self._environ(b"not-json"), "human_json_body_invalid"),
            (self._environ(b"[]"), "human_json_body_invalid"),
        )
        for environ, expected in cases:
            with self.subTest(expected=expected):
                parsed, parsed_error = operational._read_json(environ)
                self.assertIsNone(parsed)
                self.assertEqual(expected, parsed_error)
        oversized = self._environ(b"x" * (operational.MAX_JSON_BODY_BYTES + 1))
        self.assertEqual("human_json_body_too_large", operational._read_json(oversized)[1])

        self.assertEqual({"q": "two"}, operational._query({"QUERY_STRING": "q=one&q=two&blank="}))
        self.assertEqual({}, operational._query({"QUERY_STRING": "x" * (operational.MAX_QUERY_BYTES + 1)}))
        self.assertEqual(50, operational._limit("bad"))
        self.assertEqual(1, operational._limit(-1))
        self.assertEqual(200, operational._limit(999))
        self.assertEqual("context-v1", operational._context_version({"HTTP_X_MEMORYENDPOINTS_CONTEXT_VERSION": " context-v1 "}))
        self.assertTrue(operational._context_is_current({"resourceContext": {"contextVersion": "v1"}}, "v1"))
        self.assertFalse(operational._context_is_current({}, "v1"))

    def test_shared_payload_route_and_catalog_helpers_cover_rejection_boundaries(self):
        catalog = {
            "workspaces": [
                {
                    "workspaceId": "workspace-1",
                    "projects": [{"projectId": "project-1", "label": "Project"}],
                }
            ]
        }
        workspace, project = operational._selected_catalog_item(catalog, self._context())
        self.assertEqual("workspace-1", workspace["workspaceId"])
        self.assertEqual("project-1", project["projectId"])
        self.assertEqual((None, None), operational._selected_catalog_item(catalog, self._context(False)))

        valid = operational._memory_payload(
            {"summary": "A safe note", "tags": ["safe"], "scope": "project", "scopeId": "project-1"},
            self._context(),
        )
        self.assertEqual("A safe note", valid["summary"])
        invalid = (
            {"summary": "safe", "extra": True},
            {"summary": "safe", "scope": "company"},
            {"summary": "", "tags": ["safe"]},
            {"summary": "safe", "tags": [1]},
        )
        for body in invalid:
            with self.subTest(body=body):
                self.assertIsNone(operational._memory_payload(body, self._context()))
        self.assertTrue(operational._denied_operation("/api/matm/human/operational/meetings"))
        self.assertFalse(operational._denied_operation("/api/matm/human/operational/search"))
        self.assertFalse(operational._denied_operation("/other/path/meetings"))

    def test_shared_error_cookie_and_reader_fail_closed(self):
        captured = {}

        def start(status, headers):
            captured.update(status=status, headers=dict(headers))

        response = operational._error(start, "unknown_current_error", allow="GET")
        self.assertEqual("422 Unprocessable Entity", captured["status"])
        self.assertEqual("GET", captured["headers"]["Allow"])
        self.assertEqual("unknown_current_error", json.loads(b"".join(response))["error"]["code"])
        error_response = operational._storage_error(start, {"status": "human_session_required"})
        self.assertEqual("human_operational_session_required", json.loads(b"".join(error_response))["error"]["code"])

        with patch.object(operational.SimpleCookie, "load", side_effect=ValueError("bad cookie")):
            self.assertEqual("", operational._request_cookie({"HTTP_COOKIE": "broken"}))

        class Broken:
            def read(self, _size):
                raise OSError("synthetic reader failure")

        broken = self._environ(b"", length=0)
        broken["wsgi.input"] = Broken()
        self.assertEqual("human_json_body_invalid", operational._read_json(broken)[1])

    def test_shared_catalog_and_memory_payload_boundaries_cover_defaults(self):
        catalog = {
            "workspaces": [
                {"workspaceId": "workspace-1", "projects": []},
                {"workspaceId": "workspace-1", "projects": [{"projectId": "project-1", "label": "Project"}]},
            ]
        }
        workspace, project = operational._selected_catalog_item(catalog, self._context())
        self.assertEqual("workspace-1", workspace["workspaceId"])
        self.assertEqual("project-1", project["projectId"])

        defaulted = operational._memory_payload({"summary": "safe"}, self._context())
        self.assertEqual("Human-submitted memory", defaulted["title"])
        self.assertEqual("Human-submitted memory", defaulted["subject"])
        self.assertEqual([], defaulted["tags"])
        with_confidence = operational._memory_payload({"summary": "safe", "confidence": 0.5}, self._context())
        self.assertEqual(0.5, with_confidence["confidence"])
        invalid = (
            {"summary": "safe", "title": " "},
            {"summary": "safe", "subject": "x" * 256},
            {"summary": "safe", "tags": [""]},
            {"summary": "safe", "tags": ["x"] * 21},
            {"summary": "safe", "tags": ["x" * 97]},
        )
        for body in invalid:
            with self.subTest(body=body):
                self.assertIsNone(operational._memory_payload(body, self._context()))


if __name__ == "__main__":
    unittest.main()
