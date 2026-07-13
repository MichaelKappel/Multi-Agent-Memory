import io
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

from app import application


ROOT = Path(__file__).resolve().parents[1]
HUMAN_ACCESS_JS = ROOT / "static" / "js" / "human-access.js"
PROTECTED_SHELL_ROUTES = ("/console", "/knowledge", "/human", "/agents")

TENANT_CANARIES = (
    "preauth-company-canary-4d8e1f",
    "preauth-workspace-canary-4d8e1f",
    "preauth-project-canary-4d8e1f",
    "preauth-agent-canary-4d8e1f",
)

# These are server-rendered operational surfaces and defaults, not neutral
# authentication controls. Hidden markup still leaks and therefore fails.
FORBIDDEN_MARKERS = (
    "data-matm-console",
    "data-console-workspace",
    "data-console-principal",
    "data-console-command",
    "data-console-human-access",
    "data-console-agent-token-list",
    "data-console-agent-invite-list",
    "data-console-memory",
    "data-console-sync",
    "data-console-review",
    "data-console-meeting",
    "data-console-message",
    "data-console-inbox",
    "data-console-receipts",
    "data-console-audit",
    "data-knowledge-private",
    "data-knowledge-search",
    "data-knowledge-tree",
    "data-knowledge-article",
    "data-knowledge-results",
    'name="credential"',
    'name="workspaceId"',
    'name="workspaceKey"',
    "Workspace Overview",
    "Workspace locked",
    "Review Queue",
    "Public-safe operator review from the human console.",
    "Meeting note: please use this room",
    "Hello MemoryEndpoints agents:",
    "memoryendpoints://console/",
    "Approved and pending name requests will appear here.",
    "Redacted agent credential metadata will appear here.",
    "Search results will appear here.",
    "Select a page.",
)


def call_get(path, cookie=""):
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = {name.lower(): value for name, value in headers}

    path_info, _, query = path.partition("?")
    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path_info,
        "QUERY_STRING": query,
        "CONTENT_LENGTH": "0",
        "wsgi.input": io.BytesIO(b""),
    }
    if cookie:
        environ["HTTP_COOKIE"] = cookie
    body = b"".join(application(environ, start_response)).decode("utf-8", errors="replace")
    return captured["status"], captured["headers"], body


class _PreauthMarkupAudit(HTMLParser):
    """Find interactive markup rendered inside <main> but outside the auth shell."""

    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.shell_count = 0
        self.interactive_outside_shell = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        parent_main = self.stack[-1][0] if self.stack else False
        parent_shell = self.stack[-1][1] if self.stack else False
        inside_main = parent_main or tag == "main"
        inside_shell = parent_shell or "data-human-preauth-shell" in attributes
        if "data-human-preauth-shell" in attributes:
            self.shell_count += 1
        if inside_main and not inside_shell and tag in ("form", "button", "input", "select", "textarea"):
            self.interactive_outside_shell.append((tag, attributes.get("name") or attributes.get("type") or ""))
        if tag not in self.VOID_TAGS:
            self.stack.append((inside_main, inside_shell, tag))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if not self.stack:
            return
        # Test pages are expected to be valid HTML. Recover conservatively from
        # a mismatch so a malformed page cannot accidentally pass the audit.
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][2] == tag:
                del self.stack[index:]
                return


class PreauthenticationShellContractTests(unittest.TestCase):
    def test_signed_out_protected_pages_render_only_one_private_neutral_shell(self):
        query = (
            "company_id=%s&workspace_id=%s&project_id=%s&agent_id=%s"
            % TENANT_CANARIES
        )
        for route in PROTECTED_SHELL_ROUTES:
            with self.subTest(route=route):
                status, headers, body = call_get(route + "?" + query)
                self.assertEqual("200 OK", status)
                self.assertTrue(headers.get("content-type", "").startswith("text/html"))
                cache_control = headers.get("cache-control", "").lower()
                self.assertIn("no-store", cache_control)
                self.assertIn("private", cache_control)
                self.assertEqual("no-cache", headers.get("pragma", "").lower())

                audit = _PreauthMarkupAudit()
                audit.feed(body)
                self.assertEqual(1, audit.shell_count, "%s must render one data-human-preauth-shell" % route)
                self.assertEqual(
                    [],
                    audit.interactive_outside_shell,
                    "%s rendered non-authentication controls outside its pre-auth shell" % route,
                )

                for marker in FORBIDDEN_MARKERS + TENANT_CANARIES:
                    self.assertNotIn(marker.lower(), body.lower(), "%s exposed forbidden marker %r" % (route, marker))

    def test_signed_out_shell_has_only_bounded_account_and_master_proof_inputs(self):
        allowed_names = {
            "username",
            "password",
            "passwordConfirmation",
            "displayName",
            "companyMasterTokenSecret",
            "companyMasterProofSecret",
        }
        for route in PROTECTED_SHELL_ROUTES:
            with self.subTest(route=route):
                status, _headers, body = call_get(route)
                self.assertEqual("200 OK", status)
                field_names = set(
                    re.findall(r'<(?:input|select|textarea)\b[^>]*\bname=["\']([^"\']+)', body, re.IGNORECASE)
                )
                unexpected = field_names - allowed_names
                self.assertEqual(set(), unexpected, "%s rendered non-preauth inputs %r" % (route, sorted(unexpected)))
                self.assertNotRegex(body, r'(?i)<input\b[^>]*\bname=["\'](?:bearer|credential|workspaceKey|agentToken)["\']')

    def test_public_tours_remain_explicit_mock_surfaces_and_public_pages_remain_public(self):
        for route in ("/tour", "/tour/knowledge"):
            with self.subTest(route=route):
                status, headers, body = call_get(route)
                self.assertEqual("200 OK", status)
                self.assertIn("Mock data", body)
                self.assertIn("mock-transport.js", body)
                self.assertNotIn("no-store", headers.get("cache-control", "").lower())

        for route in ("/", "/docs", "/docs/"):
            with self.subTest(route=route):
                status, headers, body = call_get(route)
                self.assertEqual("200 OK", status)
                self.assertIn("MemoryEndpoints", body)
                self.assertNotIn("data-human-preauth-shell", body)
                self.assertNotIn("no-store", headers.get("cache-control", "").lower())

    def test_human_access_bfcache_contract_scrubs_and_revalidates(self):
        self.assertTrue(HUMAN_ACCESS_JS.is_file(), "human-access.js must own protected human session state")
        source = HUMAN_ACCESS_JS.read_text(encoding="utf-8")
        self.assertRegex(source, r'addEventListener\(["\']pagehide["\']')
        self.assertRegex(source, r'addEventListener\(["\']pageshow["\']')
        self.assertIn("event.persisted", source)
        self.assertRegex(source, r"(?i)function\s+scrubProtectedState\s*\(")
        self.assertRegex(source, r"(?i)function\s+revalidateHumanSession\s*\(")
        self.assertIn("/api/matm/human/session", source)
        self.assertRegex(source, r'cache\s*:\s*["\']no-store["\']')
        self.assertRegex(source, r'credentials\s*:\s*["\']same-origin["\']')
        for protected_state in (
            "selectedCompanyId",
            "workspaceId",
            "projectId",
            "agentId",
            "memberships",
            "roster",
            "inventory",
            "results",
        ):
            self.assertIn(protected_state, source, "%s must be explicitly included in protected-state scrubbing" % protected_state)
        self.assertRegex(source, r"(?:replaceChildren\s*\(\s*\)|textContent\s*=\s*[\"\']\s*[\"\'])")


if __name__ == "__main__":
    unittest.main()
