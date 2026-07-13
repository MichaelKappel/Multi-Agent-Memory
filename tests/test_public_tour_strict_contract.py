import io
import json
import subprocess
import unittest
from pathlib import Path

from app import application


ROOT = Path(__file__).resolve().parents[1]
MOCK_TRANSPORT = ROOT / "static" / "js" / "mock-transport.js"
STRICT_MOCK_CONTRACT = ROOT / "tests" / "strict_mock_transport_contract.js"
SHARED_SITE_JS = ROOT / "static" / "js" / "site.js"
SHARED_KNOWLEDGE_JS = ROOT / "static" / "js" / "knowledge.js"


def call_get(path):
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "CONTENT_LENGTH": "0",
        "wsgi.input": io.BytesIO(b""),
    }
    body = b"".join(application(environ, start_response)).decode("utf-8", errors="replace")
    return captured["status"], captured["headers"], body


class PublicTourStrictContractTests(unittest.TestCase):
    def test_signed_out_auth_shells_expose_no_operational_or_mock_objects(self):
        forbidden_console_values = (
            "MemoryEndpoints-Backend-Agent",
            "human-verifier-agent",
            "codex-agent",
            "swarm-observer-agent",
            "docs/long-term-memory/",
            "goal-human-verification",
            "Human verification goal meeting",
        )
        for route in ("/console", "/knowledge"):
            status, _headers, body = call_get(route)
            self.assertEqual("200 OK", status)
            self.assertNotIn("mock-transport.js", body)
            self.assertNotIn("Mock data", body)
            for value in forbidden_console_values:
                with self.subTest(route=route, operational_value=value):
                    self.assertFalse(value in body, msg="%s exposed operational value %s" % (route, value))

        mock_object_markers = (
            "mock-session-local",
            "mock-workspace-",
            "mock-company-",
            "mock-account-",
            "mock-project-",
            "mock-knowledge-",
            "mock-room-",
            "mock-notification-",
            "mock-receipt-",
            "mock-routing-",
        )
        for path in (SHARED_SITE_JS, SHARED_KNOWLEDGE_JS):
            source = path.read_text(encoding="utf-8")
            for marker in mock_object_markers:
                with self.subTest(asset=path.name, mock_object=marker):
                    self.assertFalse(
                        marker in source,
                        msg="mock object %s escaped the dedicated transport in %s" % (marker, path.name),
                    )

    def test_strict_mock_transport_contract(self):
        completed = subprocess.run(
            ["node", str(STRICT_MOCK_CONTRACT), str(MOCK_TRANSPORT)],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(0, completed.returncode, msg=json.dumps(payload, indent=2, sort_keys=True))
        self.assertTrue(payload["ok"])
        self.assertEqual(0, payload["failureCount"])
        self.assertEqual(0, payload["networkCalls"])


if __name__ == "__main__":
    unittest.main()
