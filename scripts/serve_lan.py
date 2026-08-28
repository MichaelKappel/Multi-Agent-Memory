"""Run the MATM runtime and public documentation as a supervised LAN service.

The protected runtime requires TLS whenever it binds beyond loopback. Public
documentation remains a separate HTTP listener and never receives credentials.
"""

from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import os
import signal
import socket
import ssl
import sys
import threading
import time
from dataclasses import dataclass
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Callable
from urllib.parse import urlsplit
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOCS_ROOT = ROOT / "sites" / "multiagentmemory.com"
DEFAULT_LOG_PATH = ROOT / "var" / "lan-host" / "lan-host.log"
MAX_PROBE_BYTES = 64 * 1024
MAX_LOG_BYTES = 1024 * 1024


class ConfigurationError(ValueError):
    """Raised when the LAN host configuration is unsafe or incomplete."""


@dataclass(frozen=True)
class LanHostConfig:
    root: Path
    docs_root: Path
    log_path: Path
    bind_host: str
    advertise_host: str
    api_port: int
    docs_port: int
    allowed_network: ipaddress.IPv4Network
    tls_cert_file: Path | None
    tls_key_file: Path | None
    tls_ca_file: Path | None
    health_interval_seconds: float
    health_failure_threshold: int
    probe_timeout_seconds: float

    @property
    def tls_enabled(self) -> bool:
        return bool(self.tls_cert_file and self.tls_key_file)

    @property
    def api_scheme(self) -> str:
        return "https" if self.tls_enabled else "http"

    @property
    def site_url(self) -> str:
        return f"{self.api_scheme}://{self.advertise_host}:{self.api_port}"

    @property
    def docs_url(self) -> str:
        return f"http://{self.advertise_host}:{self.docs_port}"


def discover_lan_ipv4() -> str:
    """Discover the preferred outbound IPv4 address without sending payloads."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        return str(probe.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def _port(value: object, name: str) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{name}_invalid") from exc
    if not 1 <= parsed <= 65535:
        raise ConfigurationError(f"{name}_invalid")
    return parsed


def _ipv4(value: object, name: str) -> ipaddress.IPv4Address:
    try:
        parsed = ipaddress.ip_address(str(value or "").strip())
    except ValueError as exc:
        raise ConfigurationError(f"{name}_invalid") from exc
    if not isinstance(parsed, ipaddress.IPv4Address):
        raise ConfigurationError(f"{name}_ipv4_required")
    return parsed


def _private_network(value: object) -> ipaddress.IPv4Network:
    try:
        parsed = ipaddress.ip_network(str(value or "").strip(), strict=False)
    except ValueError as exc:
        raise ConfigurationError("allowed_network_invalid") from exc
    if not isinstance(parsed, ipaddress.IPv4Network):
        raise ConfigurationError("allowed_network_ipv4_required")
    if not (
        parsed.network_address.is_loopback
        or (
            parsed.network_address.is_private
            and parsed.broadcast_address.is_private
            and parsed.prefixlen >= 8
        )
    ):
        raise ConfigurationError("allowed_network_private_required")
    return parsed


def _optional_file(value: object, name: str) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text).expanduser().resolve()
    if not path.is_file():
        raise ConfigurationError(f"{name}_not_found")
    return path


def build_config(args: argparse.Namespace) -> LanHostConfig:
    root = Path(args.root).expanduser().resolve()
    docs_root = Path(args.docs_root).expanduser().resolve()
    log_path = Path(args.log_path).expanduser().resolve()
    bind = _ipv4(args.bind_host, "bind_host")
    if not (bind.is_unspecified or bind.is_loopback or bind.is_private):
        raise ConfigurationError("bind_host_private_required")
    advertise = _ipv4(args.advertise_host or discover_lan_ipv4(), "advertise_host")
    if not (advertise.is_loopback or advertise.is_private):
        raise ConfigurationError("advertise_host_private_required")
    api_port = _port(args.api_port, "api_port")
    docs_port = _port(args.docs_port, "docs_port")
    if api_port == docs_port:
        raise ConfigurationError("listener_ports_must_differ")
    allowed_network = _private_network(
        args.allowed_network or f"{advertise}/24"
    )
    cert_file = _optional_file(args.tls_cert_file, "tls_cert_file")
    key_file = _optional_file(args.tls_key_file, "tls_key_file")
    ca_file = _optional_file(args.tls_ca_file, "tls_ca_file")
    if bool(cert_file) != bool(key_file):
        raise ConfigurationError("tls_cert_and_key_required_together")
    if not bind.is_loopback and not (cert_file and key_file):
        raise ConfigurationError("tls_required_for_non_loopback_runtime")
    if cert_file and not ca_file:
        raise ConfigurationError("tls_ca_required_for_health_verification")
    if not docs_root.is_dir():
        raise ConfigurationError("documentation_root_not_found")
    if args.health_interval_seconds <= 0 or args.probe_timeout_seconds <= 0:
        raise ConfigurationError("health_timing_invalid")
    if not 1 <= args.health_failure_threshold <= 20:
        raise ConfigurationError("health_failure_threshold_invalid")
    return LanHostConfig(
        root=root,
        docs_root=docs_root,
        log_path=log_path,
        bind_host=str(bind),
        advertise_host=str(advertise),
        api_port=api_port,
        docs_port=docs_port,
        allowed_network=allowed_network,
        tls_cert_file=cert_file,
        tls_key_file=key_file,
        tls_ca_file=ca_file,
        health_interval_seconds=float(args.health_interval_seconds),
        health_failure_threshold=int(args.health_failure_threshold),
        probe_timeout_seconds=float(args.probe_timeout_seconds),
    )


def client_is_allowed(address: object, allowed_network: ipaddress.IPv4Network) -> bool:
    try:
        parsed = ipaddress.ip_address(str(address or "").strip())
    except ValueError:
        return False
    return bool(parsed.is_loopback or parsed in allowed_network)


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True
    allowed_network: ipaddress.IPv4Network

    def verify_request(self, request: object, client_address: tuple[str, int]) -> bool:
        return client_is_allowed(client_address[0], self.allowed_network)


class QuietWSGIRequestHandler(WSGIRequestHandler):
    def log_message(self, _format: str, *args: object) -> None:
        return


class ContainedStaticHandler(SimpleHTTPRequestHandler):
    server_version = "MultiAgentMemoryDocs/1"

    def log_message(self, _format: str, *args: object) -> None:
        return

    def list_directory(self, _path: str):
        self.send_error(404, "Not found")
        return None

    def translate_path(self, path: str) -> str:
        translated = Path(super().translate_path(path))
        root = Path(self.directory).resolve()
        try:
            resolved = translated.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            return str(root / ".blocked-path")
        return str(resolved)


class RestrictedStaticServer(ThreadingHTTPServer):
    daemon_threads = True
    allowed_network: ipaddress.IPv4Network

    def verify_request(self, request: object, client_address: tuple[str, int]) -> bool:
        return client_is_allowed(client_address[0], self.allowed_network)


def configure_application_environment(config: LanHostConfig) -> None:
    os.environ.setdefault("MEMORYENDPOINTS_SITE_NAME", "Multi-Agent Memory Intranet")
    os.environ.setdefault("MEMORYENDPOINTS_SITE_URL", config.site_url)
    os.environ.setdefault("MEMORYENDPOINTS_COMPANION_DOCS_URL", config.docs_url)
    if str(config.root) not in sys.path:
        sys.path.insert(0, str(config.root))


def create_servers(config: LanHostConfig, application: Callable | None = None):
    configure_application_environment(config)
    if application is None:
        from app import application as loaded_application

        application = loaded_application
    api_server = None
    docs_server = None
    try:
        api_server = make_server(
            config.bind_host,
            config.api_port,
            application,
            server_class=ThreadingWSGIServer,
            handler_class=QuietWSGIRequestHandler,
        )
        api_server.allowed_network = config.allowed_network
        if config.tls_enabled:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(
                certfile=str(config.tls_cert_file), keyfile=str(config.tls_key_file)
            )
            api_server.socket = context.wrap_socket(api_server.socket, server_side=True)
        docs_handler = partial(ContainedStaticHandler, directory=str(config.docs_root))
        docs_server = RestrictedStaticServer(
            (config.bind_host, config.docs_port), docs_handler
        )
        docs_server.allowed_network = config.allowed_network
        return api_server, docs_server
    except Exception:
        if docs_server is not None:
            docs_server.server_close()
        if api_server is not None:
            api_server.server_close()
        raise


def _read_response(connection: http.client.HTTPConnection, path: str):
    connection.request("GET", path, headers={"Accept": "application/json, text/html"})
    response = connection.getresponse()
    content_type = str(response.getheader("Content-Type") or "").lower()
    content_length = response.getheader("Content-Length")
    if content_length:
        try:
            if int(content_length) > MAX_PROBE_BYTES:
                return response.status, content_type, b"", "probe_response_too_large"
        except ValueError:
            return response.status, content_type, b"", "probe_content_length_invalid"
    body = response.read(MAX_PROBE_BYTES + 1)
    if len(body) > MAX_PROBE_BYTES:
        return response.status, content_type, b"", "probe_response_too_large"
    if 300 <= response.status < 400:
        return response.status, content_type, body, "probe_redirect_rejected"
    return response.status, content_type, body, ""


def probe_runtime(config: LanHostConfig) -> dict:
    connection: http.client.HTTPConnection | None = None
    try:
        if config.tls_enabled:
            context = ssl.create_default_context(cafile=str(config.tls_ca_file))
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            connection = http.client.HTTPSConnection(
                "127.0.0.1",
                config.api_port,
                timeout=config.probe_timeout_seconds,
                context=context,
            )
        else:
            connection = http.client.HTTPConnection(
                "127.0.0.1", config.api_port, timeout=config.probe_timeout_seconds
            )
        status, content_type, body, error = _read_response(connection, "/api/version")
        if error:
            return {"live": False, "ready": False, "code": error}
        if status != 200 or not content_type.startswith("application/json"):
            return {"live": False, "ready": False, "code": "runtime_probe_invalid"}
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return {"live": False, "ready": False, "code": "runtime_probe_malformed"}
        if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
            return {"live": False, "ready": False, "code": "runtime_probe_schema_invalid"}
        ready = bool(payload.get("ok") and payload.get("storeBackendVerified"))
        return {
            "live": True,
            "ready": ready,
            "code": "ready" if ready else "runtime_backend_unready",
        }
    except (OSError, ssl.SSLError, TimeoutError, http.client.HTTPException):
        return {"live": False, "ready": False, "code": "runtime_probe_unavailable"}
    finally:
        if connection is not None:
            connection.close()


def probe_docs(config: LanHostConfig) -> dict:
    connection = http.client.HTTPConnection(
        "127.0.0.1", config.docs_port, timeout=config.probe_timeout_seconds
    )
    try:
        status, content_type, _body, error = _read_response(connection, "/")
        if error:
            return {"live": False, "ready": False, "code": error}
        ready = status == 200 and content_type.startswith("text/html")
        return {
            "live": ready,
            "ready": ready,
            "code": "ready" if ready else "docs_probe_invalid",
        }
    except (OSError, TimeoutError, http.client.HTTPException):
        return {"live": False, "ready": False, "code": "docs_probe_unavailable"}
    finally:
        connection.close()


def health_snapshot(config: LanHostConfig) -> dict:
    runtime = probe_runtime(config)
    docs = probe_docs(config)
    return {
        "ok": bool(runtime["ready"] and docs["ready"]),
        "runtime": runtime,
        "documentation": docs,
        "tlsRequiredForLan": True,
        "tlsEnabled": config.tls_enabled,
        "valuesRedacted": True,
        "rawCredentialExposed": False,
        "rawPayloadExposed": False,
    }


class SafeLogger:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def write(self, code: str) -> None:
        safe_code = "".join(
            character for character in str(code) if character.isalnum() or character in "_.-"
        )[:120]
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.is_file() and self.path.stat().st_size >= MAX_LOG_BYTES:
                rotated = self.path.with_suffix(self.path.suffix + ".1")
                if rotated.exists():
                    rotated.unlink()
                self.path.replace(rotated)
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(f"{timestamp} {safe_code or 'event'}\n")


class LanHostSupervisor:
    def __init__(self, config: LanHostConfig, application: Callable | None = None):
        self.config = config
        self.application = application
        self.logger = SafeLogger(config.log_path)
        self.stop_event = threading.Event()
        self.failures: list[str] = []
        self.api_server = None
        self.docs_server = None
        self.threads: list[threading.Thread] = []

    def _serve(self, name: str, server) -> None:
        try:
            server.serve_forever(poll_interval=0.25)
        except Exception:
            self.failures.append(f"{name}_thread_failed")
            self.stop_event.set()

    def start(self) -> None:
        self.api_server, self.docs_server = create_servers(
            self.config, self.application
        )
        self.threads = [
            threading.Thread(
                target=self._serve,
                args=("runtime", self.api_server),
                name="multi-agent-memory-runtime",
                daemon=True,
            ),
            threading.Thread(
                target=self._serve,
                args=("documentation", self.docs_server),
                name="multi-agent-memory-docs",
                daemon=True,
            ),
        ]
        for thread in self.threads:
            thread.start()
        self.logger.write("lan_host_started")

    def stop(self) -> None:
        self.stop_event.set()
        for server in (self.api_server, self.docs_server):
            if server is not None:
                try:
                    server.shutdown()
                except Exception:
                    pass
        for server in (self.api_server, self.docs_server):
            if server is not None:
                try:
                    server.server_close()
                except Exception:
                    pass
        for thread in self.threads:
            thread.join(timeout=2)

    def run(self) -> int:
        self.start()
        consecutive_liveness_failures = 0
        try:
            while not self.stop_event.wait(self.config.health_interval_seconds):
                if self.failures or any(not thread.is_alive() for thread in self.threads):
                    self.logger.write(self.failures[0] if self.failures else "server_thread_stopped")
                    return 1
                snapshot = health_snapshot(self.config)
                live = bool(
                    snapshot["runtime"]["live"]
                    and snapshot["documentation"]["live"]
                )
                if live:
                    consecutive_liveness_failures = 0
                else:
                    consecutive_liveness_failures += 1
                    self.logger.write("health_liveness_failed")
                    if consecutive_liveness_failures >= self.config.health_failure_threshold:
                        return 1
            return 0
        finally:
            self.stop()
            self.logger.write("lan_host_stopped")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--docs-root", default=str(DEFAULT_DOCS_ROOT))
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH))
    parser.add_argument(
        "--bind-host", default=os.environ.get("MULTI_AGENT_MEMORY_BIND", "0.0.0.0")
    )
    parser.add_argument(
        "--advertise-host",
        default=os.environ.get("MULTI_AGENT_MEMORY_ADVERTISE_HOST", ""),
    )
    parser.add_argument(
        "--api-port", default=os.environ.get("MULTI_AGENT_MEMORY_API_PORT", "8088")
    )
    parser.add_argument(
        "--docs-port", default=os.environ.get("MULTI_AGENT_MEMORY_DOCS_PORT", "8090")
    )
    parser.add_argument(
        "--allowed-network",
        default=os.environ.get("MULTI_AGENT_MEMORY_ALLOWED_NETWORK", ""),
    )
    parser.add_argument(
        "--tls-cert-file",
        default=os.environ.get("MULTI_AGENT_MEMORY_TLS_CERT_FILE", ""),
    )
    parser.add_argument(
        "--tls-key-file",
        default=os.environ.get("MULTI_AGENT_MEMORY_TLS_KEY_FILE", ""),
    )
    parser.add_argument(
        "--tls-ca-file",
        default=os.environ.get("MULTI_AGENT_MEMORY_TLS_CA_FILE", ""),
    )
    parser.add_argument("--health-interval-seconds", type=float, default=15.0)
    parser.add_argument("--health-failure-threshold", type=int, default=3)
    parser.add_argument("--probe-timeout-seconds", type=float, default=3.0)
    parser.add_argument("--check", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        config = build_config(build_parser().parse_args(argv))
    except ConfigurationError as exc:
        payload = {
            "ok": False,
            "code": str(exc),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        print(json.dumps(payload, sort_keys=True))
        return 2
    if argv is not None and "--check" in argv or (argv is None and "--check" in sys.argv[1:]):
        snapshot = health_snapshot(config)
        print(json.dumps(snapshot, sort_keys=True))
        return 0 if snapshot["ok"] else 1
    supervisor = LanHostSupervisor(config)

    def request_stop(_signum, _frame):
        supervisor.stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(signum, request_stop)
        except (OSError, ValueError):
            pass
    try:
        return supervisor.run()
    except Exception:
        supervisor.logger.write("lan_host_start_failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
