import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
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
enterprise_readiness_audit = load_script("enterprise_readiness_audit")


def create_sentinel_database(path, user_version, label):
    connection = sqlite3.connect(str(path))
    try:
        connection.execute("CREATE TABLE sentinel (label TEXT NOT NULL)")
        connection.execute("INSERT INTO sentinel (label) VALUES (?)", (label,))
        connection.execute("PRAGMA user_version = %d" % int(user_version))
        connection.commit()
    finally:
        connection.close()


def database_snapshot(path):
    stat = path.stat()
    connection = sqlite3.connect("file:%s?mode=ro" % path.as_posix(), uri=True)
    try:
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    finally:
        connection.close()
    return {
        "bytes": path.read_bytes(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "mtimeNs": stat.st_mtime_ns,
        "userVersion": user_version,
    }


def verifier_environment(directory, matm_path, oauth_path):
    environment = os.environ.copy()
    environment.update(
        {
            "MEMORYENDPOINTS_STORE_BACKEND": "sqlite",
            "MEMORYENDPOINTS_DATA_DIR": str(directory),
            "MEMORYENDPOINTS_SQLITE_PATH": str(matm_path),
            "MEMORYENDPOINTS_STORE_PATH": str(directory / "sentinel.json"),
            "MEMORYENDPOINTS_MCP_OAUTH_PATH": str(oauth_path),
            "MEMORYENDPOINTS_CREDENTIAL_CONFIG_PATH": str(
                directory / "sentinel-credential-config.json"
            ),
            "MEMORYENDPOINTS_MCP_HOST_CONFIG_PATH": str(
                directory / "sentinel-mcp-host-config.json"
            ),
        }
    )
    environment.pop("MEMORYENDPOINTS_CREDENTIAL_PEPPER", None)
    environment.pop("MEMORYENDPOINTS_MYSQL_URL", None)
    environment.pop("DATABASE_URL", None)
    return environment


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

    def test_memoryendpoints_verifier_uses_the_configured_public_site_identity(self):
        self.assertEqual("Private MATM Intranet", verify_memoryendpoints.expected_site_identity(wsgi=True))
        self.assertEqual("MemoryEndpoints", verify_memoryendpoints.expected_site_identity(wsgi=False))
        self.assertEqual(
            "Custom Public Name",
            verify_memoryendpoints.expected_site_identity(
                wsgi=False,
                explicit=" Custom Public Name ",
            ),
        )
        with self.assertRaises(ValueError):
            verify_memoryendpoints.expected_site_identity(wsgi=False, explicit="  ")
        self.assertEqual(
            [],
            verify_memoryendpoints.configured_site_identity_missing(
                "/",
                "Welcome to Private MATM Intranet",
                site_name="Private MATM Intranet",
            ),
        )
        self.assertEqual(
            ["configured site identity"],
            verify_memoryendpoints.configured_site_identity_missing(
                "/",
                "MemoryEndpoints",
                site_name="Private MATM Intranet",
            ),
        )
        self.assertEqual(
            [],
            verify_memoryendpoints.configured_site_identity_missing(
                "/robots.txt",
                "User-agent: *",
                site_name="Private MATM Intranet",
            ),
        )
        self.assertEqual(
            {
                "/api/matm/openapi.json",
                "/api/matm/sync/capabilities",
                "/api/matm/uai-memory/contract",
                "/mcp/resources",
                "/mcp/setup/status",
                "/.well-known/oauth-protected-resource",
                "/.well-known/oauth-protected-resource/mcp",
                "/.well-known/oauth-authorization-server",
                "/oauth/register",
                "/oauth/session",
                "/oauth/token",
                "/oauth/revoke",
                "/robots.txt",
            },
            verify_memoryendpoints.SITE_IDENTITY_OPTIONAL_ROUTES,
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


class WsgiVerifierIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="public-verifier-test-")
        self.directory = Path(self.tempdir.name)
        self.matm_path = self.directory / "live-matm.sqlite3"
        self.oauth_path = self.directory / "live-oauth.sqlite3"
        create_sentinel_database(self.matm_path, 5, "matm-sentinel")
        create_sentinel_database(self.oauth_path, 7, "oauth-sentinel")
        (self.directory / "sentinel.json").write_text(
            '{"sentinel":true}\n', encoding="utf-8"
        )
        (self.directory / "sentinel-credential-config.json").write_text(
            '{"sentinel":true}\n', encoding="utf-8"
        )
        (self.directory / "sentinel-mcp-host-config.json").write_text(
            '{"sentinel":true}\n', encoding="utf-8"
        )
        self.before_names = sorted(path.name for path in self.directory.iterdir())
        self.before_matm = database_snapshot(self.matm_path)
        self.before_oauth = database_snapshot(self.oauth_path)

    def tearDown(self):
        self.tempdir.cleanup()

    def run_python(self, arguments, timeout=180):
        return subprocess.run(
            [sys.executable] + list(arguments),
            cwd=str(ROOT),
            env=verifier_environment(
                self.directory, self.matm_path, self.oauth_path
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            timeout=timeout,
        )

    def assert_sentinels_unchanged(self):
        self.assertEqual(self.before_matm, database_snapshot(self.matm_path))
        self.assertEqual(self.before_oauth, database_snapshot(self.oauth_path))
        self.assertEqual(
            self.before_names,
            sorted(path.name for path in self.directory.iterdir()),
        )
        for database in (self.matm_path, self.oauth_path):
            for suffix in ("-wal", "-shm", "-journal", ".tmp", ".lock"):
                self.assertFalse(Path(str(database) + suffix).exists())

    def test_wsgi_subprocess_never_touches_configured_live_stores(self):
        completed = self.run_python(
            [str(ROOT / "scripts" / "verify_memoryendpoints.py"), "--wsgi"]
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual("wsgi", report["mode"])
        self.assertNotIn("memoryendpoints-verifier-", completed.stdout)
        self.assertNotIn(str(self.directory), completed.stdout)
        self.assert_sentinels_unchanged()

    def test_forced_wsgi_failure_restores_environment_and_removes_temp_tree(self):
        code = r'''
import importlib.util
import io
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

path = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("isolated_verifier", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
baseline = {key: os.environ.get(key) for key in module.WSGI_ISOLATION_ENVIRONMENT}
original = module.fetch_wsgi
observed = []

def fail_after_store_probe(route, method="GET", body=None):
    result = original(route, method, body)
    observed.append(os.environ["MEMORYENDPOINTS_DATA_DIR"])
    if route == "/api/version":
        raise RuntimeError("forced_wsgi_probe_failure")
    return result

module.fetch_wsgi = fail_after_store_probe
output = io.StringIO()
with redirect_stdout(output):
    result = module.main(["--wsgi"])
report = json.loads(output.getvalue())
restored = baseline == {
    key: os.environ.get(key) for key in module.WSGI_ISOLATION_ENVIRONMENT
}
removed = bool(observed) and not Path(observed[-1]).exists()
print(json.dumps({
    "result": result,
    "error": report.get("error", {}).get("code"),
    "restored": restored,
    "removed": removed,
}))
'''
        completed = self.run_python(
            ["-c", code, str(ROOT / "scripts" / "verify_memoryendpoints.py")]
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(
            {
                "result": 2,
                "error": "wsgi_verifier_failed",
                "restored": True,
                "removed": True,
            },
            json.loads(completed.stdout),
        )
        self.assertEqual("", completed.stderr)
        self.assert_sentinels_unchanged()

    def test_http_mode_does_not_change_environment_or_stores(self):
        code = r'''
import importlib.util
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("http_verifier", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
baseline = {key: os.environ.get(key) for key in module.WSGI_ISOLATION_ENVIRONMENT}

def stop_http_probe(*_args, **_kwargs):
    raise RuntimeError("forced_http_probe_stop")

module.fetch = stop_http_probe
try:
    module.main(["--base-url", "http://127.0.0.1:1"])
    raised = False
except RuntimeError as exc:
    raised = str(exc) == "forced_http_probe_stop"
restored = baseline == {
    key: os.environ.get(key) for key in module.WSGI_ISOLATION_ENVIRONMENT
}
print(json.dumps({"raised": raised, "unchanged": restored}))
'''
        completed = self.run_python(
            ["-c", code, str(ROOT / "scripts" / "verify_memoryendpoints.py")]
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(
            {"raised": True, "unchanged": True}, json.loads(completed.stdout)
        )
        self.assert_sentinels_unchanged()

    def test_cli_parses_before_runtime_import_and_preimport_fails_closed(self):
        code = r'''
import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("ordered_verifier", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
forbidden = set(module.WSGI_FORBIDDEN_PREIMPORTS)
clean_load = not forbidden.intersection(sys.modules)
with contextlib.redirect_stderr(io.StringIO()):
    try:
        module.main(["--not-a-real-option"])
    except SystemExit as exc:
        parsed_first = exc.code == 2 and not forbidden.intersection(sys.modules)
    else:
        parsed_first = False
import memoryendpoints.config
captured = io.StringIO()
with contextlib.redirect_stdout(captured):
    result = module.main(["--wsgi"])
report = json.loads(captured.getvalue())
print(json.dumps({
    "cleanLoad": clean_load,
    "parsedFirst": parsed_first,
    "preimportCode": result,
    "preimportError": report.get("error", {}).get("code"),
}))
'''
        completed = self.run_python(
            ["-c", code, str(ROOT / "scripts" / "verify_memoryendpoints.py")]
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(
            {
                "cleanLoad": True,
                "parsedFirst": True,
                "preimportCode": 2,
                "preimportError": "wsgi_verifier_isolation_unavailable",
            },
            json.loads(completed.stdout),
        )
        self.assert_sentinels_unchanged()

    def test_isolation_environment_is_exact_and_has_no_secret_setting(self):
        self.assertEqual(
            {
                "MEMORYENDPOINTS_STORE_BACKEND",
                "MEMORYENDPOINTS_DATA_DIR",
                "MEMORYENDPOINTS_SQLITE_PATH",
                "MEMORYENDPOINTS_STORE_PATH",
                "MEMORYENDPOINTS_MCP_OAUTH_PATH",
                "MEMORYENDPOINTS_CREDENTIAL_CONFIG_PATH",
                "MEMORYENDPOINTS_MCP_HOST_CONFIG_PATH",
            },
            set(verify_memoryendpoints.WSGI_ISOLATION_ENVIRONMENT),
        )
        self.assertNotIn(
            "MEMORYENDPOINTS_CREDENTIAL_PEPPER",
            verify_memoryendpoints.WSGI_ISOLATION_ENVIRONMENT,
        )


class EnterpriseReadinessIsolationTests(unittest.TestCase):
    def test_unit_discovery_cannot_touch_parent_store_or_inherit_credentials(self):
        with tempfile.TemporaryDirectory(prefix="readiness-isolation-test-") as temporary:
            root = Path(temporary)
            parent_root = root / "parent-live-var"
            isolated_root = root / "isolated"
            probe_root = root / "probe-tests"
            parent_root.mkdir()
            isolated_root.mkdir()
            probe_root.mkdir()
            parent_sqlite = parent_root / "matm_store.sqlite3"
            parent_oauth = parent_root / "mcp_oauth.sqlite3"
            create_sentinel_database(parent_sqlite, 97, "parent-matm")
            create_sentinel_database(parent_oauth, 98, "parent-oauth")
            before_sqlite = database_snapshot(parent_sqlite)
            before_oauth = database_snapshot(parent_oauth)
            (probe_root / "test_default_store_probe.py").write_text(
                "import unittest\n"
                "from memoryendpoints.storage import SQLiteStore\n\n"
                "class DefaultStoreProbe(unittest.TestCase):\n"
                "    def test_default_store_is_isolated(self):\n"
                "        self.assertTrue(SQLiteStore().healthcheck())\n",
                encoding="utf-8",
            )
            parent_environment = os.environ.copy()
            parent_environment.update(
                {
                    "MEMORYENDPOINTS_STORE_BACKEND": "sqlite",
                    "MEMORYENDPOINTS_DATA_DIR": str(parent_root),
                    "MEMORYENDPOINTS_SQLITE_PATH": str(parent_sqlite),
                    "MEMORYENDPOINTS_STORE_PATH": str(parent_root / "matm_store.json"),
                    "MEMORYENDPOINTS_MCP_OAUTH_PATH": str(parent_oauth),
                    "MEMORYENDPOINTS_AGENT_TOKEN": "must-not-reach-child",
                    "MEMORYENDPOINTS_COMPANY_MASTER_TOKEN": "must-not-reach-child",
                    "MEMORYENDPOINTS_CREDENTIAL_PEPPER": "must-not-reach-child",
                    "MEMORYENDPOINTS_INVITE_SECRET": "must-not-reach-child",
                    "MEMORYENDPOINTS_MYSQL_PASSWORD": "must-not-reach-child",
                    "DATABASE_URL": "mysql://must-not-reach-child",
                }
            )
            baseline_environment = dict(parent_environment)
            child_environment = enterprise_readiness_audit.isolated_readiness_environment(
                isolated_root,
                base_environment=parent_environment,
            )
            for name in (
                "MEMORYENDPOINTS_AGENT_TOKEN",
                "MEMORYENDPOINTS_COMPANY_MASTER_TOKEN",
                "MEMORYENDPOINTS_CREDENTIAL_PEPPER",
                "MEMORYENDPOINTS_INVITE_SECRET",
                "MEMORYENDPOINTS_MYSQL_PASSWORD",
                "DATABASE_URL",
            ):
                self.assertNotIn(name, child_environment)
            completed = enterprise_readiness_audit.run_check(
                "isolated_discovery_probe",
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    str(probe_root),
                ],
                environment=child_environment,
            )
            self.assertTrue(completed["ok"], completed)
            self.assertEqual(baseline_environment, parent_environment)
            self.assertEqual(before_sqlite, database_snapshot(parent_sqlite))
            self.assertEqual(before_oauth, database_snapshot(parent_oauth))
            isolated_sqlite = isolated_root / "data" / "readiness.sqlite3"
            self.assertTrue(isolated_sqlite.exists())
            self.assertNotEqual(parent_sqlite.resolve(), isolated_sqlite.resolve())


if __name__ == "__main__":
    unittest.main()
