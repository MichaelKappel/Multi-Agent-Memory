"""Shared current application boundary helpers for the two service editions."""

from __future__ import annotations

import json
import unittest

from memoryendpoints import app


class _CatalogStore:
    def company_scope_catalog(self, _token):
        return {
            "ok": True,
            "company": {"companyId": "company-1"},
            "workspaces": [{"workspaceId": "workspace-1"}],
            "projects": [{"projectId": "project-1", "workspaceId": "workspace-1"}],
            "scopeNodes": [{"scopeType": "goal", "scopeId": "goal-1", "workspaceId": "workspace-1"}],
        }


class ApplicationSharedBoundaryTests(unittest.TestCase):
    @staticmethod
    def _response(function, *args, **kwargs):
        captured = {}

        def start_response(status, headers, exc_info=None):
            captured["status"] = status
            captured["headers"] = dict(headers)

        body = b"".join(function(start_response, *args, **kwargs))
        captured["body"] = json.loads(body.decode("utf-8")) if body else {}
        return captured

    def test_uai_access_and_idempotency_error_mappings_preserve_safe_envelopes(self):
        for code, expected_status in (
            ("project_not_found", "404 Not Found"),
            ("uai_revision_conflict", "409 Conflict"),
            ("quota_exceeded", "413 Payload Too Large"),
            ("unknown_error", "422 Unprocessable Entity"),
        ):
            with self.subTest(code=code):
                result = self._response(app._uai_error_response, code, {"safe": True})
                self.assertEqual(expected_status, result["status"])
                self.assertEqual(code, result["body"]["error"]["code"])
                self.assertTrue(result["body"]["safeNoOp"])
                self.assertFalse(result["body"]["rawPayloadExposed"])

        for result, redemption, expected in (
            ({"status": "access_request_not_approved"}, False, "agent_name_request_not_approved"),
            ({"status": "invite_already_issued"}, False, "invite_already_active"),
            ({"status": "invite_unavailable"}, True, "invalid_invite"),
            ({}, False, "access_operation_failed"),
        ):
            with self.subTest(result=result, redemption=redemption):
                response = self._response(app._access_result_error, result, redemption)
                self.assertEqual(expected, response["body"]["error"]["code"])
                self.assertFalse(response["body"]["rawCredentialExposed"])

        uncertain = self._response(app._idempotency_uncertain_response)
        self.assertEqual("503 Service Unavailable", uncertain["status"])
        self.assertEqual("5", uncertain["headers"]["Retry-After"])
        self.assertTrue(uncertain["body"]["outcomeUncertain"])

    def test_access_scope_inventory_invite_and_query_helpers_cover_all_scope_kinds(self):
        store = _CatalogStore()
        expected = (
            ("workspace", "workspace-1", "workspace-1"),
            ("project", "project-1", "workspace-1"),
            ("goal", "goal-1", "workspace-1"),
            ("company", "company-1", "workspace-1"),
            ("task", "missing", ""),
            ("other", "workspace-1", ""),
        )
        for scope_type, scope_id, workspace_id in expected:
            with self.subTest(scope_type=scope_type, scope_id=scope_id):
                self.assertEqual(
                    workspace_id,
                    app._access_scope_workspace_id(store, "master", scope_type, scope_id),
                )
        class EmptyStore:
            def company_scope_catalog(self, _token):
                return {"ok": False}
        self.assertEqual("", app._access_scope_workspace_id(EmptyStore(), "master", "workspace", "workspace-1"))

        item = {"requestId": "request-1", "inviteId": "invite-1"}
        self.assertEqual(item, app._access_inventory_item({"ok": True, "items": [item]}, "invite-1", "inviteId"))
        self.assertIsNone(app._access_inventory_item({"ok": False, "items": [item]}, "invite-1", "inviteId"))
        self.assertIsNone(app._access_inventory_item({"ok": True, "items": [item]}, "missing", "inviteId"))
        invite = app._public_invite_with_grant({"scopeType": "project", "scopeId": "project-1"})
        self.assertEqual("scope_and_descendants", invite["grant"]["accessRule"])
        self.assertTrue(invite["grant"]["immutable"])
        self.assertEqual(
            "/api/matm/projects?workspace_id=workspace-1",
            app._protected_query_url("/api/matm/projects", {"workspace_id": "workspace-1", "empty": "", "none": None}),
        )
        self.assertEqual("/api/matm/projects", app._protected_query_url("/api/matm/projects", {}))


if __name__ == "__main__":
    unittest.main()
