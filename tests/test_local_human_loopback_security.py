import io
import json
import os
import secrets
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import application
from memoryendpoints.storage import SQLiteStore


def call_app(path, method="GET", body=None, headers=None):
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    captured = {}

    def start_response(status, response_headers):
        captured["status"] = status
        captured["headers"] = dict(response_headers)

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "CONTENT_LENGTH": str(len(raw)),
        "wsgi.input": io.BytesIO(raw),
        "wsgi.url_scheme": "http",
        "SERVER_PORT": "8088",
    }
    if body is not None:
        environ["CONTENT_TYPE"] = "application/json"
    environ.update(headers or {})
    response_body = b"".join(application(environ, start_response))
    return (
        captured["status"],
        captured["headers"],
        response_body.decode("utf-8", errors="replace"),
    )


class LocalHumanLoopbackSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = Path(tempfile.mkdtemp(prefix="memoryendpoints-local-human-"))
        self.sqlite_path = self.tempdir / "matm.sqlite3"
        self.saved_environment = {
            key: os.environ.get(key)
            for key in (
                "MEMORYENDPOINTS_STORE_BACKEND",
                "MEMORYENDPOINTS_SQLITE_PATH",
                "MEMORYENDPOINTS_CREDENTIAL_PEPPER",
                "MEMORYENDPOINTS_CREDENTIAL_CONFIG_PATH",
                "USERNAME",
                "COMPUTERNAME",
            )
        }
        os.environ.update(
            {
                "MEMORYENDPOINTS_STORE_BACKEND": "sqlite",
                "MEMORYENDPOINTS_SQLITE_PATH": str(self.sqlite_path),
                "MEMORYENDPOINTS_CREDENTIAL_PEPPER": secrets.token_urlsafe(48),
                "MEMORYENDPOINTS_CREDENTIAL_CONFIG_PATH": str(
                    self.tempdir / "missing-pepper.json"
                ),
                "USERNAME": "Local.User",
                "COMPUTERNAME": "MEMORY-PC",
            }
        )
        self.store = SQLiteStore()

    def tearDown(self):
        for key, value in self.saved_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tempdir, ignore_errors=True)

    @staticmethod
    def local_headers():
        return {
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_HOST": "localhost:8088",
            "HTTP_ORIGIN": "http://localhost:8088",
            "HTTP_SEC_FETCH_SITE": "same-origin",
            "HTTP_SEC_FETCH_MODE": "cors",
            "HTTP_SEC_FETCH_DEST": "empty",
        }

    def test_loopback_and_spoofed_windows_identity_cannot_mint_owner_session(self):
        cases = (
            {},
            {"REMOTE_USER": "Local.User"},
            {"HTTP_X_WINDOWS_USER": "Local.User"},
            {
                "REMOTE_USER": "Local.User",
                "HTTP_X_FORWARDED_USER": "Local.User",
            },
        )
        for extra in cases:
            headers = self.local_headers()
            headers.update(extra)
            with self.subTest(extra=extra):
                status, response_headers, body = call_app(
                    "/api/matm/human/local-session", "POST", {}, headers
                )
                self.assertEqual("404 Not Found", status)
                self.assertEqual("not_found", json.loads(body)["error"]["code"])
                self.assertNotIn("Set-Cookie", response_headers)

        with self.store._open_connection() as connection:
            account_count = connection.execute(
                "SELECT COUNT(*) AS count FROM matm_human_accounts"
            ).fetchone()["count"]
            session_count = connection.execute(
                "SELECT COUNT(*) AS count FROM matm_human_account_sessions"
            ).fetchone()["count"]
        self.assertEqual(0, account_count)
        self.assertEqual(0, session_count)
        self.assertFalse(
            (self.tempdir / ".local-secrets" / "memoryendpoints-local-windows-human.json").exists()
        )

    def test_local_page_prefills_username_without_attempting_auto_login(self):
        status, _headers, body = call_app("/human", headers=self.local_headers())
        self.assertEqual("200 OK", status)
        self.assertIn('value="local-user"', body)
        self.assertNotIn("data-human-access-local-auto-login", body)

        static_root = Path(__file__).resolve().parents[1] / "static" / "js"
        bootstrap = (static_root / "human-access-bootstrap.js").read_text(
            encoding="utf-8"
        )
        controller = (static_root / "human-access.js").read_text(encoding="utf-8")
        self.assertNotIn("loginLocalComputer", bootstrap)
        self.assertNotIn("loginLocalComputer", controller)
        self.assertNotIn("/api/matm/human/local-session", controller)

    def test_same_machine_lan_url_redirects_to_loopback_for_secure_cookie(self):
        headers = {
            "REMOTE_ADDR": "10.1.10.209",
            "HTTP_HOST": "10.1.10.209:8088",
        }
        with patch(
            "memoryendpoints.app._request_is_from_local_machine", return_value=True
        ):
            status, response_headers, body = call_app("/human", headers=headers)
        self.assertEqual("302 Found", status)
        self.assertEqual(
            "http://localhost:8088/human", response_headers["Location"]
        )
        self.assertEqual("", body)


if __name__ == "__main__":
    unittest.main()
