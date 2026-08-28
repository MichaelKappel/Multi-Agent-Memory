import argparse
import io
import json
import os
import socket
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import serve_lan


def free_port():
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]
    finally:
        probe.close()


class LanHostOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="multi-agent-memory-lan-host-"
        )
        self.root = Path(self.temporary.name)
        self.docs_root = self.root / "docs"
        self.docs_root.mkdir()
        (self.docs_root / "index.html").write_text(
            "<!doctype html><title>LAN docs</title>", encoding="utf-8"
        )
        self.log_path = self.root / "var" / "lan-host.log"

    def tearDown(self):
        self.temporary.cleanup()

    def arguments(self, *extra):
        return serve_lan.build_parser().parse_args(
            [
                "--root",
                str(self.root),
                "--docs-root",
                str(self.docs_root),
                "--log-path",
                str(self.log_path),
                "--bind-host",
                "127.0.0.1",
                "--advertise-host",
                "127.0.0.1",
                "--api-port",
                str(free_port()),
                "--docs-port",
                str(free_port()),
                "--allowed-network",
                "127.0.0.0/8",
                *extra,
            ]
        )

    def config(self, *extra):
        args = self.arguments(*extra)
        while args.api_port == args.docs_port:
            args.docs_port = free_port()
        return serve_lan.build_config(args)

    def test_non_loopback_runtime_requires_complete_tls_configuration(self):
        args = self.arguments()
        args.bind_host = "0.0.0.0"
        args.advertise_host = "10.1.10.209"
        args.allowed_network = "10.1.10.0/24"
        with self.assertRaisesRegex(
            serve_lan.ConfigurationError, "tls_required_for_non_loopback_runtime"
        ):
            serve_lan.build_config(args)

        cert = self.root / "server.pem"
        key = self.root / "server-key.pem"
        ca = self.root / "ca.pem"
        for path in (cert, key, ca):
            path.write_text("test-only", encoding="utf-8")
        args.tls_cert_file = str(cert)
        args.tls_key_file = str(key)
        args.tls_ca_file = str(ca)
        config = serve_lan.build_config(args)
        self.assertTrue(config.tls_enabled)
        self.assertEqual("https://10.1.10.209:%s" % config.api_port, config.site_url)

    def test_configuration_rejects_unsafe_networks_ports_and_hostnames(self):
        cases = (
            ("bind_host", "localhost", "bind_host_invalid"),
            ("allowed_network", "0.0.0.0/0", "allowed_network_private_required"),
            ("api_port", "0", "api_port_invalid"),
            ("docs_port", "70000", "docs_port_invalid"),
        )
        for field, value, error in cases:
            args = self.arguments()
            setattr(args, field, value)
            with self.subTest(field=field):
                with self.assertRaisesRegex(serve_lan.ConfigurationError, error):
                    serve_lan.build_config(args)

        args = self.arguments()
        args.docs_port = args.api_port
        with self.assertRaisesRegex(
            serve_lan.ConfigurationError, "listener_ports_must_differ"
        ):
            serve_lan.build_config(args)

    def test_peer_allowlist_uses_socket_address_and_fails_closed(self):
        network = serve_lan.ipaddress.ip_network("10.1.10.0/24")
        self.assertTrue(serve_lan.client_is_allowed("127.0.0.1", network))
        self.assertTrue(serve_lan.client_is_allowed("::1", network))
        self.assertTrue(serve_lan.client_is_allowed("10.1.10.42", network))
        self.assertFalse(serve_lan.client_is_allowed("10.1.11.42", network))
        self.assertFalse(serve_lan.client_is_allowed("claimed-host", network))
        self.assertFalse(serve_lan.client_is_allowed("", network))

    def test_second_listener_bind_failure_closes_first_listener(self):
        fake_api = Mock()
        fake_api.base_environ = {}
        with (
            patch.object(serve_lan, "make_server", return_value=fake_api),
            patch.object(
                serve_lan.RestrictedStaticServer,
                "__init__",
                side_effect=OSError("test bind failure"),
            ),
        ):
            with self.assertRaises(OSError):
                serve_lan.create_servers(self.config(), application=lambda *_: ())
        fake_api.server_close.assert_called_once_with()

    def test_wsgi_request_scheme_matches_the_actual_listener_transport(self):
        server = Mock()
        server.base_environ = {}
        http_config = self.config()
        serve_lan.configure_wsgi_transport(server, http_config)
        self.assertEqual("http", server.base_environ["wsgi.url_scheme"])

        tls_config = replace(
            http_config,
            tls_cert_file=self.root / "server.pem",
            tls_key_file=self.root / "server-key.pem",
            tls_ca_file=self.root / "ca.pem",
        )
        serve_lan.configure_wsgi_transport(server, tls_config)
        self.assertEqual("https", server.base_environ["wsgi.url_scheme"])

    @staticmethod
    def wsgi_application(environ, start_response):
        if environ.get("PATH_INFO") == "/api/version":
            body = json.dumps(
                {"ok": True, "storeBackendVerified": True}, separators=(",", ":")
            ).encode("utf-8")
            start_response(
                "200 OK",
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(body))),
                ],
            )
            return [body]
        body = b'{"ok":false}'
        start_response(
            "401 Unauthorized",
            [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body))),
            ],
        )
        return [body]

    def test_supervised_runtime_docs_and_protected_boundary(self):
        config = self.config(
            "--health-interval-seconds",
            "0.05",
            "--probe-timeout-seconds",
            "1",
        )
        supervisor = serve_lan.LanHostSupervisor(config, self.wsgi_application)
        supervisor.start()
        try:
            snapshot = serve_lan.health_snapshot(config)
            self.assertTrue(snapshot["ok"], snapshot)
            connection = serve_lan.http.client.HTTPConnection(
                "127.0.0.1", config.api_port, timeout=1
            )
            try:
                connection.request("GET", "/api/matm/current-message")
                response = connection.getresponse()
                response.read()
            finally:
                connection.close()
            self.assertEqual(401, response.status)

            docs = serve_lan.http.client.HTTPConnection(
                "127.0.0.1", config.docs_port, timeout=1
            )
            try:
                docs.request("GET", "/")
                docs_response = docs.getresponse()
                docs_response.read()
                docs.request("GET", "/missing/")
                missing = docs.getresponse()
                missing.read()
            finally:
                docs.close()
            self.assertEqual(200, docs_response.status)
            self.assertEqual(404, missing.status)
        finally:
            supervisor.stop()
        log = self.log_path.read_text(encoding="utf-8")
        self.assertIn("lan_host_started", log)
        self.assertNotIn("Authorization", log)
        self.assertNotIn("agentTokenSecret", log)

    def test_valid_but_unready_runtime_is_live_without_restart_signal(self):
        def unready(environ, start_response):
            if environ.get("PATH_INFO") == "/api/version":
                body = b'{"ok":true,"storeBackendVerified":false}'
                start_response(
                    "200 OK",
                    [
                        ("Content-Type", "application/json"),
                        ("Content-Length", str(len(body))),
                    ],
                )
                return [body]
            return self.wsgi_application(environ, start_response)

        config = self.config()
        supervisor = serve_lan.LanHostSupervisor(config, unready)
        supervisor.start()
        try:
            runtime = serve_lan.probe_runtime(config)
            self.assertTrue(runtime["live"])
            self.assertFalse(runtime["ready"])
            self.assertEqual("runtime_backend_unready", runtime["code"])
        finally:
            supervisor.stop()

    def test_check_output_is_small_redacted_json(self):
        config = self.config()
        snapshot = {
            "ok": True,
            "runtime": {"live": True, "ready": True, "code": "ready"},
            "documentation": {"live": True, "ready": True, "code": "ready"},
            "tlsRequiredForLan": True,
            "tlsEnabled": False,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        argv = [
            "--root",
            str(config.root),
            "--docs-root",
            str(config.docs_root),
            "--log-path",
            str(config.log_path),
            "--bind-host",
            config.bind_host,
            "--advertise-host",
            config.advertise_host,
            "--api-port",
            str(config.api_port),
            "--docs-port",
            str(config.docs_port),
            "--allowed-network",
            str(config.allowed_network),
            "--check",
        ]
        output = io.StringIO()
        with patch.object(serve_lan, "health_snapshot", return_value=snapshot):
            with redirect_stdout(output):
                status = serve_lan.main(argv)
        rendered = output.getvalue()
        self.assertEqual(0, status)
        self.assertLess(len(rendered), 2048)
        payload = json.loads(rendered)
        self.assertTrue(payload["valuesRedacted"])
        self.assertFalse(payload["rawCredentialExposed"])
        self.assertNotIn(str(self.root), rendered)


if __name__ == "__main__":
    unittest.main()
