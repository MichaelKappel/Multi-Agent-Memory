import io
import json
import re
import unittest
from urllib.parse import urlencode

from app import application
from memoryendpoints.site_data import PROTECTED_ROUTES, ROUTE_TABLE


CANARIES = {
    "company": "anonymous-company-canary-7f3a91",
    "workspace": "anonymous-workspace-canary-7f3a91",
    "project": "anonymous-project-canary-7f3a91",
    "meeting": "anonymous-meeting-canary-7f3a91",
    "memory": "anonymous-memory-canary-7f3a91",
    "agent": "anonymous-agent-canary-7f3a91",
    "source": "anonymous-source-canary-7f3a91",
    "taxonomy": "anonymous-taxonomy-canary-7f3a91",
    "title": "anonymous-title-canary-7f3a91",
    "route": "anonymous-route-canary-7f3a91",
}


QUERY = {
    "company_id": CANARIES["company"],
    "workspace_id": CANARIES["workspace"],
    "project_id": CANARIES["project"],
    "room_id": CANARIES["meeting"],
    "memory_id": CANARIES["memory"],
    "agent_id": CANARIES["agent"],
    "source_id": CANARIES["source"],
    "taxonomy_path": CANARIES["taxonomy"],
    "title": CANARIES["title"],
    "route": CANARIES["route"],
}


BODY = {
    "companyId": CANARIES["company"],
    "workspaceId": CANARIES["workspace"],
    "projectId": CANARIES["project"],
    "roomId": CANARIES["meeting"],
    "memoryId": CANARIES["memory"],
    "agentId": CANARIES["agent"],
    "sourceId": CANARIES["source"],
    "taxonomyPath": CANARIES["taxonomy"],
    "title": CANARIES["title"],
    "route": CANARIES["route"],
}


HEADERS = {
    "HTTP_X_COMPANY_ID": CANARIES["company"],
    "HTTP_X_WORKSPACE_ID": CANARIES["workspace"],
    "HTTP_X_PROJECT_ID": CANARIES["project"],
    "HTTP_X_MEETING_ID": CANARIES["meeting"],
    "HTTP_X_MEMORY_ID": CANARIES["memory"],
    "HTTP_X_AGENT_ID": CANARIES["agent"],
    "HTTP_X_SOURCE_ID": CANARIES["source"],
    "HTTP_X_TAXONOMY_PATH": CANARIES["taxonomy"],
    "HTTP_X_TITLE": CANARIES["title"],
    "HTTP_X_ROUTE": CANARIES["route"],
}


def concrete_path(route):
    """Expand common route-template spellings to one stable anonymous probe."""
    path = re.sub(r"\{[^{}]+\}", CANARIES["route"], route)
    path = re.sub(r"<[^<>]+>", CANARIES["route"], path)
    path = re.sub(r"(?<=/):[A-Za-z_][A-Za-z0-9_]*", CANARIES["route"], path)
    return path


def call_anonymously(route, method):
    raw = json.dumps(BODY).encode("utf-8") if method in ("POST", "PUT", "PATCH") else b""
    captured = {}

    def start_response(status, response_headers):
        captured["status"] = status
        captured["headers"] = response_headers

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": concrete_path(route),
        "QUERY_STRING": urlencode(QUERY),
        "CONTENT_TYPE": "application/json",
        "CONTENT_LENGTH": str(len(raw)),
        "wsgi.input": io.BytesIO(raw),
    }
    environ.update(HEADERS)
    response_body = b"".join(application(environ, start_response)).decode("utf-8")
    return captured["status"], captured["headers"], response_body


class AnonymousProtectedRouteTests(unittest.TestCase):
    def test_every_protected_method_fails_closed_without_leaking_tenant_canaries(self):
        protected_rows = [item for item in ROUTE_TABLE if item["access"] == "protected"]
        protected_routes = [item["route"] for item in protected_rows]

        self.assertEqual(PROTECTED_ROUTES, protected_routes)
        self.assertEqual(len(protected_routes), len(set(protected_routes)), "protected routes must be unique")
        self.assertTrue(protected_rows, "the protected route inventory must not be empty")

        for item in protected_rows:
            route = item["route"]
            methods = item.get("methods") or []
            self.assertTrue(methods, "%s must declare at least one method" % route)
            self.assertEqual(len(methods), len(set(methods)), "%s methods must be unique" % route)
            expanded_path = concrete_path(route)
            self.assertNotRegex(expanded_path, r"\{[^{}]+\}|<[^<>]+>|(?<=/):[A-Za-z_]", "unexpanded route template")

            for method in methods:
                with self.subTest(method=method, route=route, expanded_path=expanded_path):
                    status, response_headers, text = call_anonymously(route, method)

                    human_connector_route = route.startswith("/api/matm/human/connector-pairings/")
                    expected_status = "422 Unprocessable Entity" if human_connector_route else "401 Unauthorized"
                    self.assertEqual(expected_status, status)
                    headers = {name.lower(): value for name, value in response_headers}
                    self.assertTrue(headers.get("content-type", "").startswith("application/json"))
                    self.assertIn("no-store", headers.get("cache-control", ""))

                    payload = json.loads(text)
                    self.assertFalse(payload["ok"])
                    self.assertTrue(payload["safeNoOp"])
                    self.assertTrue(payload["valuesRedacted"])
                    self.assertFalse(payload["rawCredentialExposed"])
                    self.assertFalse(payload["rawPayloadExposed"])
                    expected_code = (
                        "invalid_request"
                        if human_connector_route
                        else "invalid_token"
                        if route == "/api/matm/me" or route.startswith("/api/matm/connector-pairings/")
                        else "auth_required"
                    )
                    self.assertEqual(expected_code, payload["error"]["code"])
                    self.assertTrue(payload["error"]["safeNoOp"])
                    self.assertTrue(payload["error"]["valuesRedacted"])

                    serialized_response = text + "\n" + "\n".join(
                        "%s: %s" % (name, value) for name, value in response_headers
                    )
                    for kind, canary in CANARIES.items():
                        self.assertNotIn(canary, serialized_response, "%s canary leaked" % kind)

    def test_admin_diagnostics_fails_closed_without_echoing_tenant_canaries(self):
        status, response_headers, text = call_anonymously("/api/admin/mysql-diagnostics", "GET")

        self.assertIn(status, ("401 Unauthorized", "404 Not Found"))
        headers = {name.lower(): value for name, value in response_headers}
        self.assertTrue(headers.get("content-type", "").startswith("application/json"))
        self.assertEqual("no-store", headers.get("cache-control"))
        payload = json.loads(text)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["safeNoOp"])
        self.assertTrue(payload["valuesRedacted"])
        self.assertFalse(payload["rawCredentialExposed"])
        self.assertFalse(payload["rawPayloadExposed"])
        serialized_response = text + "\n" + "\n".join(
            "%s: %s" % (name, value) for name, value in response_headers
        )
        for kind, canary in CANARIES.items():
            self.assertNotIn(canary, serialized_response, "%s canary leaked" % kind)


if __name__ == "__main__":
    unittest.main()
