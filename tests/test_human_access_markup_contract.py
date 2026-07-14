import io
import unittest

from app import application
from memoryendpoints.human_access_ui import render_human_access_main


def call_get(path):
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = {name.lower(): value for name, value in headers}

    body = b"".join(
        application(
            {
                "REQUEST_METHOD": "GET",
                "PATH_INFO": path,
                "QUERY_STRING": "",
                "CONTENT_LENGTH": "0",
                "wsgi.input": io.BytesIO(b""),
            },
            start_response,
        )
    ).decode("utf-8")
    return captured["status"], captured["headers"], body


class HumanAccessMarkupContractTests(unittest.TestCase):
    def test_full_renderer_has_every_controller_selector_once(self):
        markup = render_human_access_main(authenticated=True)
        selectors = (
            "data-human-access-status",
            "data-human-access-locked",
            "data-human-access-account-step",
            "data-human-access-protected",
            "data-human-access-demo-label",
            "data-human-access-master-proof-form",
            "data-human-access-account-form",
            "data-human-access-login-form",
            "data-human-access-logout",
            "data-human-access-membership-form",
            "data-human-access-membership-list",
            "data-human-access-link-company",
            "data-human-access-link-dialog",
            "data-human-access-link-proof-form",
            "data-human-access-link-cancel",
            "data-human-access-roster-list",
            "data-human-access-roster-empty",
            "data-human-access-roster-refresh",
            "data-human-access-agent-master-setting-form",
            "data-human-access-agent-master-setting-status",
            "data-human-access-reauth-dialog",
            "data-human-access-reauth-form",
            "data-human-access-reauth-cancel",
            "data-human-access-replacement-dialog",
            "data-human-access-replacement-summary",
            "data-human-access-replacement-status",
            "data-human-access-successor-token",
            "data-human-access-successor-show",
            "data-human-access-successor-copy",
            "data-human-access-successor-saved",
            "data-human-access-successor-clear",
            "data-human-access-possession-form",
            "data-human-access-possession-token",
            "data-human-access-replacement-retry",
            "data-human-access-replacement-cancel",
        )
        for selector in selectors:
            with self.subTest(selector=selector):
                self.assertEqual(1, markup.count(selector))
        self.assertNotIn("predecessorToken", markup)
        self.assertNotIn("oldToken", markup)
        self.assertIn("Existing raw credentials can never be viewed", markup)

    def test_signed_out_renderer_is_bounded_but_uses_same_root(self):
        markup = render_human_access_main(authenticated=False)
        self.assertIn("data-human-access", markup)
        self.assertIn("data-human-preauth-shell", markup)
        self.assertIn("data-human-access-preauth-only", markup)
        self.assertNotIn("data-human-access-protected", markup)
        self.assertNotIn("successorTokenProof", markup)

    def test_company_master_help_names_issuer_default_path_and_safe_fallback(self):
        signed_out = render_human_access_main(authenticated=False)
        authenticated = render_human_access_main(authenticated=True)

        self.assertIn('href="/agent-setup"', signed_out)
        self.assertIn("Where do I get the company master credential?", signed_out)
        self.assertIn(
            "&lt;project-root&gt;/.local-secrets/memoryendpoints-company-master.json",
            signed_out,
        )
        self.assertIn("ask your top-level AI agent to check that exact project-relative file", signed_out)
        self.assertIn("displaying this path does not create the file", signed_out)
        self.assertIn("scripts/recover_memoryendpoints_company_master.py", signed_out)
        self.assertIn("without exposing it in chat", signed_out)
        self.assertIn("Lower-scoped agents must ask", signed_out)
        self.assertLess(
            signed_out.index("human-access-credential-guide"),
            signed_out.index("data-human-access-master-proof-form"),
        )
        self.assertEqual(2, authenticated.count("human-access-credential-guide"))

    def test_demo_route_uses_real_renderer_and_mock_transport_injection(self):
        status, headers, body = call_get("/tour/human")
        self.assertEqual("200 OK", status)
        self.assertTrue(headers["content-type"].startswith("text/html"))
        self.assertIn("no-store", headers.get("cache-control", "").lower())
        self.assertEqual("no-referrer", headers["referrer-policy"])
        self.assertEqual("DENY", headers["x-frame-options"])
        self.assertEqual("nosniff", headers["x-content-type-options"])
        self.assertEqual("max-age=31536000", headers["strict-transport-security"])
        self.assertIn("script-src-attr 'none'", headers["content-security-policy"])
        self.assertIn("nonce-", headers["content-security-policy"])
        self.assertIn("data-human-access-demo", body)
        self.assertIn("data-human-access-demo-warning", body)
        self.assertIn("Never enter a real username", body)
        self.assertIn("session-only mock data", body)
        self.assertNotIn('onsubmit="return false"', body)
        self.assertIn("/static/js/human-access.js", body)
        self.assertIn("/static/js/human-access-bootstrap.js", body)
        self.assertIn("/static/css/human-access.css", body)

    def test_demo_warning_is_visible_before_secret_shaped_fields_and_production_omits_it(self):
        demo = render_human_access_main(authenticated=False, demo=True)
        production = render_human_access_main(authenticated=False, demo=False)

        warning_position = demo.index("data-human-access-demo-warning")
        password_position = demo.index('name="password"')
        self.assertLess(warning_position, password_position)
        warning_end = demo.index("</aside>", warning_position)
        self.assertNotIn("hidden", demo[warning_position:warning_end])
        self.assertNotIn("data-human-access-demo-warning", production)


if __name__ == "__main__":
    unittest.main()
