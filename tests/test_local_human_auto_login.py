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
from memoryendpoints import app as app_module
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
    text = response_body.decode("utf-8", errors="replace")
    return captured["status"], captured["headers"], text


class LocalHumanAutoLoginTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = Path(tempfile.mkdtemp(prefix="memoryendpoints-local-human-"))
        self.sqlite_path = self.tempdir / "matm.sqlite3"
        self.local_credential_path = (
            self.tempdir / ".local-secrets" / "memoryendpoints-local-windows-human.json"
        )
        self.saved_environment = {
            key: os.environ.get(key)
            for key in (
                "MEMORYENDPOINTS_STORE_BACKEND",
                "MEMORYENDPOINTS_SQLITE_PATH",
                "MEMORYENDPOINTS_CREDENTIAL_PEPPER",
                "MEMORYENDPOINTS_CREDENTIAL_CONFIG_PATH",
                "MEMORYENDPOINTS_LOCAL_HUMAN_AUTO_LOGIN",
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
                "MEMORYENDPOINTS_LOCAL_HUMAN_AUTO_LOGIN": "1",
                "USERNAME": "Local.User",
                "COMPUTERNAME": "MEMORY-PC",
            }
        )
        self.store = SQLiteStore()
        created = self.store.create_free_account(
            "Local Workspace", "Local Company", "Local Project"
        )
        self.company = {
            "workspaceId": created[0],
            "companyMasterTokenSecret": created[2],
            "companyId": created[4],
        }
        secret_dir = self.tempdir / ".local-secrets"
        secret_dir.mkdir(parents=True, exist_ok=True)
        (secret_dir / "memoryendpoints-company-master.json").write_text(
            json.dumps(
                {
                    "schemaVersion": "memoryendpoints.company_master_credential_file.v1",
                    "companyId": self.company["companyId"],
                    "workspaceId": self.company["workspaceId"],
                    "baseUrl": "http://localhost:8088",
                    "companyMasterTokenSecret": self.company[
                        "companyMasterTokenSecret"
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.patch_root = patch.object(app_module, "ROOT", self.tempdir)
        self.patch_local_path = patch.object(
            app_module, "LOCAL_HUMAN_CREDENTIAL_PATH", self.local_credential_path
        )
        self.patch_root.start()
        self.patch_local_path.start()

    def tearDown(self):
        self.patch_local_path.stop()
        self.patch_root.stop()
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

    def test_loopback_post_creates_and_reuses_one_password_backed_owner(self):
        status, headers, body = call_app(
            "/api/matm/human/local-session",
            "POST",
            {},
            self.local_headers(),
        )
        self.assertEqual("200 OK", status)
        payload = json.loads(body)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["localWindowsAutoLogin"])
        self.assertEqual("local-user", payload["account"]["username"])
        self.assertEqual(self.company["companyId"], payload["selectedCompanyId"])
        self.assertIn("__Host-memoryendpoints-human=", headers["Set-Cookie"])
        self.assertIn("Secure", headers["Set-Cookie"])
        self.assertNotIn(self.company["companyMasterTokenSecret"], body)

        saved = json.loads(self.local_credential_path.read_text(encoding="utf-8"))
        self.assertEqual(
            "memoryendpoints.local_windows_human_credential.v1",
            saved["schemaVersion"],
        )
        self.assertEqual("Local.User", saved["windowsUser"])
        self.assertEqual("MEMORY-PC", saved["machineName"])
        self.assertNotEqual(self.company["companyMasterTokenSecret"], saved["password"])

        second_status, _second_headers, second_body = call_app(
            "/api/matm/human/local-session",
            "POST",
            {},
            self.local_headers(),
        )
        self.assertEqual("200 OK", second_status)
        self.assertTrue(json.loads(second_body)["localWindowsAutoLogin"])
        with self.store._open_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM matm_human_accounts"
            ).fetchone()["count"]
        self.assertEqual(1, count)

    def test_local_page_advertises_bootstrap_but_does_not_create_on_get(self):
        status, _headers, body = call_app(
            "/human", headers=self.local_headers()
        )
        self.assertEqual("200 OK", status)
        self.assertIn("data-human-access-local-auto-login", body)
        self.assertFalse(self.local_credential_path.exists())

        bootstrap = (
            Path(__file__).resolve().parents[1]
            / "static"
            / "js"
            / "human-access-bootstrap.js"
        ).read_text(encoding="utf-8")
        self.assertIn('root.hasAttribute("data-human-access-local-auto-login")', bootstrap)
        self.assertIn("controller.loginLocalComputer()", bootstrap)

    def test_remote_proxy_and_dns_rebinding_requests_cannot_auto_login(self):
        cases = (
            {
                "REMOTE_ADDR": "10.1.10.42",
                "HTTP_HOST": "10.1.10.209:8088",
                "HTTP_ORIGIN": "http://10.1.10.209:8088",
            },
            {
                "REMOTE_ADDR": "127.0.0.1",
                "HTTP_HOST": "attacker.example:8088",
                "HTTP_ORIGIN": "http://attacker.example:8088",
            },
            {
                "REMOTE_ADDR": "127.0.0.1",
                "HTTP_HOST": "localhost:8088",
                "HTTP_ORIGIN": "http://localhost:8088",
                "HTTP_X_FORWARDED_FOR": "10.1.10.42",
            },
        )
        for extra in cases:
            headers = {
                "HTTP_SEC_FETCH_SITE": "same-origin",
                "HTTP_SEC_FETCH_MODE": "cors",
                "HTTP_SEC_FETCH_DEST": "empty",
            }
            headers.update(extra)
            with self.subTest(headers=extra):
                status, response_headers, body = call_app(
                    "/api/matm/human/local-session", "POST", {}, headers
                )
                self.assertEqual("422 Unprocessable Entity", status)
                self.assertEqual(
                    "local_human_auto_login_unavailable",
                    json.loads(body)["error"]["code"],
                )
                self.assertNotIn("Set-Cookie", response_headers)
        self.assertFalse(self.local_credential_path.exists())

    def test_invalid_existing_local_credential_fails_closed_without_overwrite(self):
        self.local_credential_path.write_text(
            '{"schemaVersion":"unexpected","password":"do-not-overwrite"}',
            encoding="utf-8",
        )
        original = self.local_credential_path.read_bytes()
        status, response_headers, body = call_app(
            "/api/matm/human/local-session",
            "POST",
            {},
            self.local_headers(),
        )
        self.assertEqual("422 Unprocessable Entity", status)
        self.assertEqual(
            "local_human_auto_login_unavailable",
            json.loads(body)["error"]["code"],
        )
        self.assertNotIn("Set-Cookie", response_headers)
        self.assertEqual(original, self.local_credential_path.read_bytes())
        with self.store._open_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM matm_human_accounts"
            ).fetchone()["count"]
        self.assertEqual(0, count)

    def test_explicit_disable_flag_removes_bootstrap_and_denies_endpoint(self):
        os.environ["MEMORYENDPOINTS_LOCAL_HUMAN_AUTO_LOGIN"] = "0"
        status, _headers, page = call_app("/human", headers=self.local_headers())
        self.assertEqual("200 OK", status)
        self.assertNotIn("data-human-access-local-auto-login", page)

        api_status, response_headers, body = call_app(
            "/api/matm/human/local-session",
            "POST",
            {},
            self.local_headers(),
        )
        self.assertEqual("422 Unprocessable Entity", api_status)
        self.assertEqual(
            "local_human_auto_login_unavailable",
            json.loads(body)["error"]["code"],
        )
        self.assertNotIn("Set-Cookie", response_headers)
        self.assertFalse(self.local_credential_path.exists())

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
