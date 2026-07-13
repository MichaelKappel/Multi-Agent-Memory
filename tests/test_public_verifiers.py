import importlib.util
import json
import unittest
from pathlib import Path

from memoryendpoints.site_data import PUBLIC_ROUTES


ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    path = ROOT / "scripts" / ("%s.py" % name)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify_memoryendpoints = load_script("verify_memoryendpoints")
verify_static_site = load_script("verify_static_site")


class PublicVerifierLeakContractTests(unittest.TestCase):
    def assert_leak_rules(self, module, text, expected_rules):
        rules = set(module.pattern_hits(module.PUBLIC_LEAK_PATTERNS, text))
        self.assertEqual(set(expected_rules), rules)

    def test_memoryendpoints_verifier_flags_local_paths_and_tracebacks(self):
        body = (
            "Traceback (most recent call last):\n"
            "  File \"E:\\MemoryEndpoints.com\\app.py\", line 12, in application\n"
            "store path C:/Users/example/private/store.json\n"
            "file:///E:/MemoryEndpoints.com/private.txt\n"
            "/home/site/private/runtime.json\n"
        )
        self.assert_leak_rules(
            verify_memoryendpoints,
            body,
            {
                "windows_local_path",
                "file_uri",
                "posix_home_path",
                "python_traceback",
                "python_traceback_frame",
            },
        )

    def test_memoryendpoints_verifier_covers_every_public_route(self):
        self.assertEqual(set(PUBLIC_ROUTES), set(verify_memoryendpoints.ROUTES))

    def test_connector_public_routes_use_non_mutating_or_safe_no_op_probes(self):
        probes = verify_memoryendpoints.CONNECTOR_PUBLIC_PROBES
        self.assertEqual(
            {
                "/.well-known/memoryendpoints-connector",
                "/connect/authorize/{publicRequestRef}",
                "/tour/connect/authorize/{demoState}",
                "/api/matm/connector-pairings/requests",
                "/api/matm/connector-pairings/authorization-code-claims",
                "/api/matm/connector-pairings/token",
            },
            set(probes),
        )
        self.assertEqual("GET", probes["/.well-known/memoryendpoints-connector"]["method"])
        self.assertEqual("GET", probes["/connect/authorize/{publicRequestRef}"]["method"])
        self.assertEqual("GET", probes["/tour/connect/authorize/{demoState}"]["method"])
        for route in (
            "/api/matm/connector-pairings/requests",
            "/api/matm/connector-pairings/authorization-code-claims",
            "/api/matm/connector-pairings/token",
        ):
            self.assertEqual("POST", probes[route]["method"])
            self.assertEqual(b"{}", probes[route]["body"])
            self.assertIn(422, probes[route]["expectedStatuses"])

    def test_memoryendpoints_verifier_accepts_only_exact_docs_canonical_redirect(self):
        self.assertTrue(
            verify_memoryendpoints.canonical_redirect_check(
                "/docs",
                301,
                {"Location": "https://memoryendpoints.com/docs/"},
            )
        )
        self.assertFalse(
            verify_memoryendpoints.canonical_redirect_check(
                "/docs",
                301,
                {"Location": "https://memoryendpoints.com/console"},
            )
        )
        self.assertFalse(
            verify_memoryendpoints.canonical_redirect_check(
                "/connect/authorize/{publicRequestRef}",
                301,
                {"Location": "/connect/authorize/pairref_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/"},
            )
        )

    def test_connector_safe_no_op_probe_requires_exact_problem_envelope(self):
        payload = {
            "ok": False,
            "safeNoOp": True,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
            "error": {
                "code": "invalid_request",
                "title": "Connector pairing rejected",
                "detail": "The request body does not match the connector operation schema.",
                "safeNoOp": True,
                "valuesRedacted": True,
            },
        }
        check = verify_memoryendpoints.connector_public_probe_check(
            "/api/matm/connector-pairings/requests",
            422,
            json.dumps(payload),
            {"Content-Type": "application/json; charset=utf-8"},
        )
        self.assertTrue(check["verified"])

        payload["error"]["message"] = "compatibility alias"
        rejected = verify_memoryendpoints.connector_public_probe_check(
            "/api/matm/connector-pairings/requests",
            422,
            json.dumps(payload),
            {"Content-Type": "application/json; charset=utf-8"},
        )
        self.assertFalse(rejected["verified"])

    def test_exact_git_head_requires_explicit_clean_build_metadata(self):
        for build in (
            {"sourceSha": "abc123", "sourceWorktreeDirty": True},
            {"sourceSha": "abc123"},
        ):
            item = {"missing": []}
            verify_memoryendpoints.apply_build_expectations(
                item,
                build,
                "abc123",
                require_clean_build=True,
            )
            self.assertTrue(item["missing"])
            self.assertFalse(item["sourceShaMatchesExpected"])

        clean_item = {"missing": []}
        verify_memoryendpoints.apply_build_expectations(
            clean_item,
            {"sourceSha": "abc123", "sourceWorktreeDirty": False},
            "abc123",
            require_clean_build=True,
        )
        self.assertEqual([], clean_item["missing"])
        self.assertTrue(clean_item["cleanSourceRevision"])
        self.assertTrue(clean_item["sourceShaMatchesExpected"])

    def test_static_site_verifier_flags_local_paths_and_tracebacks(self):
        text = (
            "Traceback (most recent call last):\n"
            "  File \"/tmp/memoryendpoints/app.py\", line 9, in render\n"
            "Local path E:/MemoryEndpoints.com/sites/multiagentmemory.com/index.html\n"
        )
        self.assert_leak_rules(
            verify_static_site,
            text,
            {
                "windows_local_path",
                "private_runtime_path",
                "python_traceback",
                "python_traceback_frame",
            },
        )

    def test_public_urls_and_routes_are_not_flagged_as_local_paths(self):
        public_text = (
            "https://memoryendpoints.com/api/matm/memory-events/submit "
            "https://github.com/MichaelKappel/Multi-Agent-Memory "
            "/api/matm/current-message /.well-known/mcp.json /docs/how-it-works.html"
        )
        self.assertEqual([], verify_memoryendpoints.pattern_hits(verify_memoryendpoints.PUBLIC_LEAK_PATTERNS, public_text))
        self.assertEqual([], verify_static_site.pattern_hits(verify_static_site.PUBLIC_LEAK_PATTERNS, public_text))

    def test_static_site_verifier_scans_error_bodies_for_leaks(self):
        item = {"file": "missing.html", "secretHitCount": 0, "leakHitCount": 0, "leakRules": []}
        verify_static_site.apply_public_text_checks(
            item,
            "Traceback (most recent call last):\n  File \"C:\\Users\\example\\app.py\", line 4, in render\n",
        )
        self.assertGreater(item["leakHitCount"], 0)
        self.assertIn("python_traceback", item["leakRules"])
        self.assertIn("windows_local_path", item["leakRules"])


if __name__ == "__main__":
    unittest.main()
