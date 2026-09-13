"""Additional fail-closed and renderer edge coverage for the shared connector UI."""

import dataclasses
import unittest
from unittest.mock import patch

from memoryendpoints.connector_authorize_ui import (
    ConnectorAuthorizationRenderError,
    ConnectorAuthorizationView,
    DEMO_AUTHORITY,
    PRODUCTION_AUTHORITY,
    CompanyOption,
    demo_authorization_view,
    production_authorization_view,
    render_connector_authorization,
)
from tests.test_connector_authorize_ui import _company, _production_view, _request, _result, _workspace


class ConnectorAuthorizationUiEdgeTests(unittest.TestCase):
    def test_view_and_authentication_shapes_fail_closed(self):
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "view_invalid"):
            render_connector_authorization(object())
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "authentication_state_invalid"):
            render_connector_authorization(
                dataclasses.replace(_production_view(), authenticated="yes")
            )
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "request_invalid"):
            render_connector_authorization(_production_view(request=object()))

    def test_authenticated_collections_and_state_requirements_are_bounded(self):
        companies = tuple(
            CompanyOption("companyref_" + f"{index:043d}", f"Company {index}")
            for index in range(101)
        )
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "company_count_invalid"):
            render_connector_authorization(
                production_authorization_view(
                    authenticated=True,
                    state="company_selection",
                    request=_request(),
                    company_label="Example Company",
                    companies=companies,
                )
            )
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "company_invalid"):
            render_connector_authorization(
                production_authorization_view(
                    authenticated=True,
                    state="company_selection",
                    request=_request(),
                    company_label="Example Company",
                    companies=("not-a-company",),
                )
            )
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "company_required"):
            render_connector_authorization(
                production_authorization_view(
                    authenticated=True,
                    state="company_selection",
                    request=_request(),
                    company_label="Example Company",
                    companies=(),
                )
            )
        workspaces = tuple(_workspace(f"workref_{index:043d}", f"Workspace {index}") for index in range(101))
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "workspace_count_invalid"):
            render_connector_authorization(_production_view(workspaces=workspaces))
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "workspace_invalid"):
            render_connector_authorization(_production_view(workspaces=("not-a-workspace",)))

    def test_request_result_and_label_validation_are_typed(self):
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "result_required"):
            render_connector_authorization(_production_view("approved", result=None))
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "result_state_invalid"):
            render_connector_authorization(_production_view("pending", result=_result()))
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "result_invalid"):
            render_connector_authorization(_production_view("approved", result=object()))
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "agent_display_name_invalid"):
            render_connector_authorization(_production_view("approved", result=_result(agent_display_name="Other Agent")))
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "scope_digest_invalid"):
            render_connector_authorization(_production_view("approved", result=_result(scope_digest="sha256-v1:" + ("0" * 64))))
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "wake_up_url_invalid"):
            render_connector_authorization(_production_view("approved", result=_result(wake_up_url="https://evil.example/callback")))
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "company_label_invalid"):
            render_connector_authorization(_production_view(company_label=""))
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "company_label_invalid"):
            render_connector_authorization(_production_view(company_label="x" * 97))
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "company_label_invalid"):
            render_connector_authorization(_production_view(company_label="bad\nlabel"))

    def test_demo_labels_and_pending_errors_render_without_private_values(self):
        demo = demo_authorization_view("pending")
        with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "demo_object_not_labelled_mock"):
            render_connector_authorization(dataclasses.replace(demo, company_label="Unlabelled Company"))
        no_workspaces = dataclasses.replace(demo, workspaces=())
        body = render_connector_authorization(no_workspaces)
        self.assertIn("No existing workspaces available", body)
        error_body = render_connector_authorization(
            dataclasses.replace(demo, field_error_code="workspace_name_invalid")
        )
        self.assertIn("Use 3 to 80 visible characters for the new workspace name.", error_body)

    def test_result_rejects_a_callback_normalization_mismatch(self):
        from memoryendpoints.connector_authorize_ui import _validate_result

        with patch(
            "memoryendpoints.connector_authorize_ui.build_wake_up_url",
            return_value="https://callback.example/normalized",
        ):
            with self.assertRaisesRegex(ConnectorAuthorizationRenderError, "wake_up_url_invalid"):
                _validate_result(_result())


if __name__ == "__main__":
    unittest.main()
