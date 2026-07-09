import importlib.util
import unittest
from pathlib import Path


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
