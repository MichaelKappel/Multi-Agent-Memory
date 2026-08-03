import json
import os
import shutil
import struct
import subprocess
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = ROOT / "sites" / "multiagentmemory.com"
BROWSER_SCRIPT = ROOT / "tests" / "multiagentmemory_release_history_browser.cjs"


class QuietStaticHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SITE_ROOT), **kwargs)

    def log_message(self, format, *args):
        return


def first_existing(paths):
    for path in paths:
        if path and Path(path).exists():
            return Path(path)
    return None


def playwright_module():
    return first_existing(
        (
            os.environ.get("PLAYWRIGHT_MODULE_PATH"),
            ROOT / "node_modules" / "playwright",
            Path.home() / "node_modules" / "playwright",
        )
    )


def browser_executable():
    program_files = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
    program_files_x86 = Path(
        os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")
    )
    local_app_data = Path(
        os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
    )
    return first_existing(
        (
            os.environ.get("PLAYWRIGHT_BROWSER_EXECUTABLE"),
            program_files / "Google" / "Chrome" / "Application" / "chrome.exe",
            program_files_x86 / "Google" / "Chrome" / "Application" / "chrome.exe",
            program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            program_files_x86 / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            local_app_data / "Google" / "Chrome" / "Application" / "chrome.exe",
            local_app_data / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        )
    )


def png_dimensions(path):
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError("browser screenshot is not a valid PNG")
    return struct.unpack(">II", header[16:24])


class MultiAgentMemoryReleaseHistoryBrowserTests(unittest.TestCase):
    def test_release_history_browser_matrix(self):
        node = shutil.which("node")
        playwright = playwright_module()
        browser = browser_executable()
        if not node or not playwright or not browser:
            self.skipTest(
                "Node, Playwright, and Chrome or Edge are required for browser qualification"
            )

        server = ThreadingHTTPServer(("127.0.0.1", 0), QuietStaticHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(
                prefix="multiagentmemory-release-browser-"
            ) as output:
                base_url = "http://127.0.0.1:%d" % server.server_address[1]
                completed = subprocess.run(
                    (
                        node,
                        str(BROWSER_SCRIPT),
                        base_url,
                        output,
                        str(playwright),
                        str(browser),
                    ),
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                )
                self.assertEqual(
                    0, completed.returncode, msg=completed.stderr or completed.stdout
                )
                result = json.loads(completed.stdout)
                self.assertTrue(result["ok"])
                self.assertEqual(5, result["scenarioCount"])
                self.assertEqual(
                    {
                        "desktop-1440",
                        "mobile-390",
                        "physical-320-text-200",
                        "forced-colors-1440",
                        "no-js-mobile-390",
                    },
                    {item["name"] for item in result["scenarios"]},
                )
                for item in result["scenarios"]:
                    screenshot = Path(item["screenshot"])
                    self.assertTrue(screenshot.is_file(), msg=screenshot)
                    self.assertGreater(
                        screenshot.stat().st_size, 10_000, msg=screenshot
                    )
                    width, height = png_dimensions(screenshot)
                    self.assertEqual(item["viewport"]["width"], width, msg=screenshot)
                    self.assertGreater(
                        height, item["viewport"]["height"], msg=screenshot
                    )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
