import base64
import datetime
import hashlib
import io
import json
import multiprocessing
import os
import queue
import tempfile
import threading
import time
import unicodedata
import unittest
from pathlib import Path
from unittest.mock import patch

from app import application
from memoryendpoints.config import (
    bootstrap_account_runtime_config,
    free_account_runtime_config,
)
from memoryendpoints.storage import (
    BootstrapAccountError,
    FileStore,
    SQLiteStore,
    _bootstrap_file_process_lock,
    bootstrap_capability_digest,
    bootstrap_idempotency_digest,
    bootstrap_request_digest,
)
from tests.governed_test_support import DeterministicCredentialPepperMixin


ROUTE = "/api/matm/agent-setup/bootstrap-account"
BOOTSTRAP_ENV = (
    "MEMORYENDPOINTS_FREE_ACCOUNT_ENABLED",
    "MEMORYENDPOINTS_BOOTSTRAP_ACCOUNT_ENABLED",
    "MEMORYENDPOINTS_BOOTSTRAP_ACCOUNT_CAPABILITY_DIGEST_SHA256",
    "MEMORYENDPOINTS_BOOTSTRAP_ACCOUNT_ISSUED_AT",
    "MEMORYENDPOINTS_BOOTSTRAP_ACCOUNT_EXPIRES_AT",
)
EXPECTED_RESPONSE_KEYS = {
    "schemaVersion",
    "ok",
    "accountId",
    "companyId",
    "workspaceId",
    "projectId",
    "companyMasterCredentialId",
    "humanOwnerCredentialId",
    "candidateCredentialsAccepted",
    "credentialValuesReturned",
    "idempotencySupported",
    "valuesRedacted",
    "rawCredentialExposed",
    "rawPayloadExposed",
    "idempotencyKeyExposed",
}


def canonical_secret(label):
    raw = hashlib.sha256(label.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def request_body(label="one"):
    return {
        "schemaVersion": "memoryendpoints.bootstrap_account_request.v1",
        "companyLabel": "Bootstrap Company " + label,
        "workspaceLabel": "Bootstrap Workspace " + label,
        "projectLabel": "Bootstrap Project " + label,
        "candidateCompanyMasterTokenSecret": (
            "me_master_v1.masterkey-%s.%s"
            % (hashlib.sha256((label + "-master-id").encode()).hexdigest()[:20], canonical_secret(label + "-master"))
        ),
        "candidateHumanOwnerRecoverySecret": (
            "me_human_v1.humancred-%s.%s"
            % (hashlib.sha256((label + "-human-id").encode()).hexdigest()[:20], canonical_secret(label + "-human"))
        ),
    }


def call_app(
    body=None,
    *,
    raw=None,
    method="POST",
    query="",
    authorization=None,
    idempotency_key=None,
    host="bootstrap.test",
    scheme="https",
    origin=None,
    content_type="application/json",
    content_length=None,
    stream=None,
    remote_addr="127.0.0.1",
    transfer_encoding=None,
):
    encoded = raw if raw is not None else (
        json.dumps(body).encode("utf-8") if body is not None else b""
    )
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = list(headers)

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": ROUTE,
        "QUERY_STRING": query,
        "wsgi.url_scheme": scheme,
        "HTTP_HOST": host,
        "REMOTE_ADDR": remote_addr,
        "CONTENT_TYPE": content_type,
        "CONTENT_LENGTH": str(len(encoded) if content_length is None else content_length),
        "wsgi.input": stream if stream is not None else io.BytesIO(encoded),
    }
    if authorization is not None:
        environ["HTTP_AUTHORIZATION"] = authorization
    if idempotency_key is not None:
        environ["HTTP_IDEMPOTENCY_KEY"] = idempotency_key
    if origin is not None:
        environ["HTTP_ORIGIN"] = origin
    if transfer_encoding is not None:
        environ["HTTP_TRANSFER_ENCODING"] = transfer_encoding
    response = b"".join(application(environ, start_response))
    return captured["status"], captured["headers"], response


def file_bootstrap_worker(
    path,
    body,
    capability,
    idempotency,
    expires_at,
    gate,
    output,
):
    try:
        gate.wait(30)
        result = FileStore(Path(path)).create_bootstrap_account(
            body,
            bootstrap_capability_digest(capability),
            bootstrap_idempotency_digest(idempotency),
            bootstrap_request_digest(body),
            expires_at,
        )
        output.put({"kind": "ok", "result": result})
    except BaseException as exc:
        output.put(
            {
                "kind": "error",
                "errorType": exc.__class__.__name__,
                "errorCode": getattr(exc, "code", None),
            }
        )


def file_bootstrap_route_worker(
    path,
    body,
    capability,
    idempotency,
    issued_at,
    expires_at,
    remote_addr,
    gate,
    output,
):
    try:
        os.environ.update(
            {
                "MEMORYENDPOINTS_STORE_BACKEND": "file",
                "MEMORYENDPOINTS_STORE_PATH": path,
                "MEMORYENDPOINTS_SITE_URL": "https://bootstrap.test",
                "MEMORYENDPOINTS_FREE_ACCOUNT_ENABLED": "false",
                "MEMORYENDPOINTS_BOOTSTRAP_ACCOUNT_ENABLED": "true",
                "MEMORYENDPOINTS_BOOTSTRAP_ACCOUNT_CAPABILITY_DIGEST_SHA256": bootstrap_capability_digest(
                    capability
                ),
                "MEMORYENDPOINTS_BOOTSTRAP_ACCOUNT_ISSUED_AT": issued_at,
                "MEMORYENDPOINTS_BOOTSTRAP_ACCOUNT_EXPIRES_AT": expires_at,
            }
        )
        gate.wait(30)
        status, headers, response = call_app(
            body,
            authorization="Bootstrap " + capability,
            idempotency_key=idempotency,
            remote_addr=remote_addr,
        )
        output.put(
            {
                "kind": "ok",
                "status": status,
                "headers": dict(headers),
                "body": json.loads(response),
            }
        )
    except BaseException as exc:
        output.put(
            {
                "kind": "error",
                "errorType": exc.__class__.__name__,
                "errorCode": getattr(exc, "code", None),
            }
        )


def file_bootstrap_rate_worker(
    path,
    source_partition,
    capability_partition,
    source_limit,
    project_limit,
    maximum_live_source_partitions,
    gate,
    output,
):
    try:
        gate.wait(30)
        result = FileStore(Path(path)).consume_commons_layered_rate_limit(
            "bootstrapSourceRequest",
            source_partition,
            source_limit,
            600,
            "bootstrapCapabilityRequest",
            capability_partition,
            project_limit,
            600,
            maximum_live_source_partitions,
        )
        output.put({"kind": "ok", "result": result})
    except BaseException as exc:
        output.put(
            {
                "kind": "error",
                "errorType": exc.__class__.__name__,
                "errorCode": getattr(exc, "code", None),
            }
        )


def file_bootstrap_lock_crash_worker(path, ready):
    with _bootstrap_file_process_lock(Path(path)):
        ready.set()
        os._exit(23)


class BootstrapConfigTests(unittest.TestCase):
    def setUp(self):
        self.saved = {key: os.environ.get(key) for key in BOOTSTRAP_ENV}
        for key in BOOTSTRAP_ENV:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_bootstrap_tuple_is_all_or_none_short_lived_and_fail_closed(self):
        self.assertFalse(bootstrap_account_runtime_config()["available"])
        os.environ["MEMORYENDPOINTS_BOOTSTRAP_ACCOUNT_ENABLED"] = "true"
        config = bootstrap_account_runtime_config()
        self.assertFalse(config["available"])
        self.assertIn("bootstrap_account_config_incomplete", config["blockers"])

        now = datetime.datetime(2026, 9, 4, 12, 0, tzinfo=datetime.timezone.utc)
        capability = canonical_secret("config-capability")
        os.environ.update(
            {
                "MEMORYENDPOINTS_BOOTSTRAP_ACCOUNT_CAPABILITY_DIGEST_SHA256": bootstrap_capability_digest(capability),
                "MEMORYENDPOINTS_BOOTSTRAP_ACCOUNT_ISSUED_AT": "2026-09-04T11:59:59Z",
                "MEMORYENDPOINTS_BOOTSTRAP_ACCOUNT_EXPIRES_AT": "2026-09-04T12:09:59Z",
            }
        )
        self.assertTrue(bootstrap_account_runtime_config(now)["available"])
        os.environ["MEMORYENDPOINTS_BOOTSTRAP_ACCOUNT_ISSUED_AT"] = (
            "2026-09-04T11:59:59.000000Z"
        )
        self.assertFalse(bootstrap_account_runtime_config(now)["available"])
        os.environ["MEMORYENDPOINTS_BOOTSTRAP_ACCOUNT_ISSUED_AT"] = (
            "2026-09-04T11:59:59Z"
        )
        os.environ["MEMORYENDPOINTS_BOOTSTRAP_ACCOUNT_EXPIRES_AT"] = "2026-09-04T12:10:00Z"
        self.assertFalse(bootstrap_account_runtime_config(now)["available"])
        os.environ["MEMORYENDPOINTS_BOOTSTRAP_ACCOUNT_ENABLED"] = "ture"
        self.assertFalse(bootstrap_account_runtime_config(now)["available"])

    def test_free_account_defaults_on_and_invalid_values_fail_closed(self):
        self.assertTrue(free_account_runtime_config()["enabled"])
        os.environ["MEMORYENDPOINTS_FREE_ACCOUNT_ENABLED"] = "false"
        self.assertFalse(free_account_runtime_config()["enabled"])
        os.environ["MEMORYENDPOINTS_FREE_ACCOUNT_ENABLED"] = "flase"
        config = free_account_runtime_config()
        self.assertFalse(config["enabled"])
        self.assertFalse(config["valid"])


class BootstrapAccountContract(DeterministicCredentialPepperMixin):
    backend = None

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="bootstrap-account-")
        self.saved = {
            key: os.environ.get(key)
            for key in BOOTSTRAP_ENV
            + (
                "MEMORYENDPOINTS_STORE_BACKEND",
                "MEMORYENDPOINTS_STORE_PATH",
                "MEMORYENDPOINTS_SQLITE_PATH",
                "MEMORYENDPOINTS_SITE_URL",
            )
        }
        os.environ.update(
            {
                "MEMORYENDPOINTS_STORE_BACKEND": self.backend,
                "MEMORYENDPOINTS_STORE_PATH": str(Path(self.tempdir.name) / "store.json"),
                "MEMORYENDPOINTS_SQLITE_PATH": str(Path(self.tempdir.name) / "store.sqlite3"),
                "MEMORYENDPOINTS_SITE_URL": "https://bootstrap.test",
                "MEMORYENDPOINTS_FREE_ACCOUNT_ENABLED": "false",
            }
        )
        self.capability = canonical_secret("capability-" + self.backend)
        self.idempotency_key = canonical_secret("idempotency-" + self.backend)
        self.configure_capability(self.capability)

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tempdir.cleanup()

    def configure_capability(self, capability, issued_delta=-5, expires_delta=300):
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        os.environ.update(
            {
                "MEMORYENDPOINTS_BOOTSTRAP_ACCOUNT_ENABLED": "true",
                "MEMORYENDPOINTS_BOOTSTRAP_ACCOUNT_CAPABILITY_DIGEST_SHA256": bootstrap_capability_digest(capability),
                "MEMORYENDPOINTS_BOOTSTRAP_ACCOUNT_ISSUED_AT": (now + datetime.timedelta(seconds=issued_delta)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "MEMORYENDPOINTS_BOOTSTRAP_ACCOUNT_EXPIRES_AT": (now + datetime.timedelta(seconds=expires_delta)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )

    def authorized_call(self, body=None, **kwargs):
        return call_app(
            body if body is not None else request_body(self.backend),
            authorization="Bootstrap " + self.capability,
            idempotency_key=self.idempotency_key,
            **kwargs,
        )

    def store(self):
        if self.backend == "file":
            return FileStore(Path(self.tempdir.name) / "store.json")
        return SQLiteStore(Path(self.tempdir.name) / "store.sqlite3")

    def assert_no_cors(self, headers):
        self.assertFalse(
            any(name.lower().startswith("access-control-") for name, _ in headers)
        )

    def test_success_exact_replay_custody_readback_and_secret_free_storage(self):
        body = request_body(self.backend)
        raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        first_status, first_headers, first_raw = self.authorized_call(raw=raw)
        reordered = {key: body[key] for key in reversed(tuple(body))}
        second_status, second_headers, second_raw = self.authorized_call(
            raw=json.dumps(reordered, indent=1, ensure_ascii=False).encode("utf-8")
        )
        self.assertEqual("201 Created", first_status)
        self.assertEqual(first_status, second_status)
        self.assertEqual(first_raw, second_raw)
        self.assert_no_cors(first_headers)
        self.assert_no_cors(second_headers)
        response = json.loads(first_raw)
        self.assertEqual(EXPECTED_RESPONSE_KEYS, set(response))
        self.assertEqual("memoryendpoints.bootstrap_account.v1", response["schemaVersion"])
        self.assertTrue(response["candidateCredentialsAccepted"])
        self.assertFalse(response["credentialValuesReturned"])
        self.assertTrue(response["idempotencySupported"])
        self.assertTrue(response["valuesRedacted"])
        self.assertFalse(response["rawCredentialExposed"])
        self.assertFalse(response["rawPayloadExposed"])
        self.assertFalse(response["idempotencyKeyExposed"])

        store = self.store()
        data = store._load()
        self.assertEqual(1, len(data["accounts"]))
        self.assertEqual(1, len(data["companies"]))
        self.assertEqual(1, len(data["workspaces"]))
        self.assertEqual(1, len(data["projects"]))
        self.assertEqual(1, len(data["bootstrapAccountSetups"]))
        audits = [
            item
            for item in data["auditLog"]
            if item.get("action") == "workspace.create_bootstrap_account"
        ]
        self.assertEqual(1, len(audits))
        setup = next(iter(data["bootstrapAccountSetups"].values()))
        self.assertEqual("complete", setup["status"])
        self.assertEqual(bootstrap_capability_digest(self.capability), setup["capabilityDigestSha256"])
        self.assertEqual(bootstrap_idempotency_digest(self.idempotency_key), setup["idempotencyDigestSha256"])
        self.assertEqual(bootstrap_request_digest(body), setup["requestDigestSha256"])
        self.assertNotIn("companyLabel", setup)
        self.assertNotIn("candidateCompanyMasterTokenSecret", setup)
        self.assertTrue(
            store.authenticate_company_master(
                body["candidateCompanyMasterTokenSecret"], response["companyId"]
            )
        )
        self.assertTrue(
            store.authenticate_human_owner(
                body["candidateHumanOwnerRecoverySecret"], response["companyId"]
            )
        )
        persisted = Path(
            os.environ[
                "MEMORYENDPOINTS_STORE_PATH"
                if self.backend == "file"
                else "MEMORYENDPOINTS_SQLITE_PATH"
            ]
        ).read_bytes()
        for secret in (
            self.capability,
            self.idempotency_key,
            body["candidateCompanyMasterTokenSecret"],
            body["candidateHumanOwnerRecoverySecret"],
        ):
            self.assertNotIn(secret.encode("utf-8"), persisted)

    def test_hidden_boundary_precedes_body_and_store_and_never_emits_cors(self):
        class ExplodingStream:
            def read(self, _length):
                raise AssertionError("hidden request body was read")

        cases = (
            {"authorization": "Bootstrap " + canonical_secret("wrong")},
            {"method": "OPTIONS"},
            {"method": "GET"},
            {"query": "x=1"},
            {"scheme": "http"},
            {"host": "other.test"},
            {"origin": "https://other.test"},
        )
        expected_body = None
        for overrides in cases:
            with self.subTest(overrides=overrides), patch(
                "memoryendpoints.app._store",
                side_effect=AssertionError("hidden request touched storage"),
            ):
                status, headers, response = call_app(
                    method=overrides.get("method", "POST"),
                    query=overrides.get("query", ""),
                    authorization=overrides.get(
                        "authorization", "Bootstrap " + self.capability
                    ),
                    idempotency_key=self.idempotency_key,
                    host=overrides.get("host", "bootstrap.test"),
                    scheme=overrides.get("scheme", "https"),
                    origin=overrides.get("origin"),
                    content_length=100,
                    stream=ExplodingStream(),
                )
            self.assertEqual("404 Not Found", status)
            self.assert_no_cors(headers)
            if expected_body is None:
                expected_body = response
            self.assertEqual(expected_body, response)

        for key in BOOTSTRAP_ENV[1:]:
            os.environ.pop(key, None)
        with patch(
            "memoryendpoints.app._store",
            side_effect=AssertionError("disabled request touched storage"),
        ):
            status, headers, response = call_app(
                content_length=100, stream=ExplodingStream()
            )
        self.assertEqual("404 Not Found", status)
        self.assertEqual(expected_body, response)
        self.assert_no_cors(headers)

    def test_strict_request_validation_happens_before_storage(self):
        valid = request_body(self.backend)
        invalid_bodies = []
        extra = dict(valid, extra=True)
        invalid_bodies.append(extra)
        missing = dict(valid)
        missing.pop("projectLabel")
        invalid_bodies.append(missing)
        wrong_schema = dict(valid, schemaVersion="memoryendpoints.bootstrap_account.v1")
        invalid_bodies.append(wrong_schema)
        invalid_bodies.append(dict(valid, companyLabel=" leading"))
        invalid_bodies.append(dict(valid, companyLabel="two  spaces"))
        invalid_bodies.append(dict(valid, companyLabel="line\nbreak"))
        invalid_bodies.append(dict(valid, companyLabel="token: abcdefghijklmnop"))
        invalid_bodies.append(dict(valid, companyLabel=unicodedata.normalize("NFD", "Café")))
        invalid_bodies.append(dict(valid, workspaceLabel=7))
        invalid_bodies.append(dict(valid, candidateHumanOwnerRecoverySecret="invalid"))
        same_secret = canonical_secret("same-secret")
        invalid_bodies.append(
            dict(
                valid,
                candidateCompanyMasterTokenSecret="me_master_v1.masterkey-%s.%s" % ("a" * 20, same_secret),
                candidateHumanOwnerRecoverySecret="me_human_v1.humancred-%s.%s" % ("b" * 20, same_secret),
            )
        )
        with patch(
            "memoryendpoints.app._store",
            side_effect=AssertionError("invalid request touched storage"),
        ):
            for body in invalid_bodies:
                with self.subTest(body=body):
                    status, headers, response = self.authorized_call(body)
                    self.assertEqual("400 Bad Request", status)
                    self.assertEqual(
                        "bootstrap_account_request_invalid",
                        json.loads(response)["error"]["code"],
                    )
                    self.assert_no_cors(headers)

            duplicate = (
                '{"schemaVersion":"memoryendpoints.bootstrap_account_request.v1",'
                '"schemaVersion":"memoryendpoints.bootstrap_account_request.v1"}'
            ).encode("utf-8")
            status, _, _ = self.authorized_call(raw=duplicate)
            self.assertEqual("400 Bad Request", status)
            status, _, _ = self.authorized_call(
                raw=b"{}", content_type="text/plain"
            )
            self.assertEqual("400 Bad Request", status)
            status, _, _ = self.authorized_call(
                raw=b"{}", content_length="not-a-number"
            )
            self.assertEqual("400 Bad Request", status)
            status, _, _ = self.authorized_call(
                raw=b"{}", content_length="0002"
            )
            self.assertEqual("400 Bad Request", status)
            status, _, _ = self.authorized_call(
                raw=b"{}", transfer_encoding="chunked"
            )
            self.assertEqual("400 Bad Request", status)
            class FailingStream:
                def read(self, _length):
                    raise OSError("synthetic bounded read failure")

            status, _, _ = self.authorized_call(
                content_length=2, stream=FailingStream()
            )
            self.assertEqual("400 Bad Request", status)

    def test_size_limit_does_not_read_or_touch_storage(self):
        class ExplodingStream:
            def read(self, _length):
                raise AssertionError("oversized request body was read")

        with patch(
            "memoryendpoints.app._store",
            side_effect=AssertionError("oversized request touched storage"),
        ):
            status, headers, response = self.authorized_call(
                content_length=4097, stream=ExplodingStream()
            )
        self.assertEqual("413 Content Too Large", status)
        self.assertEqual(
            "bootstrap_account_request_too_large",
            json.loads(response)["error"]["code"],
        )
        self.assert_no_cors(headers)

    def test_expiry_is_rechecked_inside_the_atomic_store_claim(self):
        body = request_body(self.backend)
        expired = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(seconds=1)
        ).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
        admitted = {
            "available": True,
            "capabilityDigestSha256": bootstrap_capability_digest(
                self.capability
            ),
            "expiresAt": expired,
        }
        with patch(
            "memoryendpoints.app.bootstrap_account_runtime_config",
            return_value=admitted,
        ):
            status, _, response = self.authorized_call(body)
        self.assertEqual("503 Service Unavailable", status)
        self.assertEqual(
            "bootstrap_account_unavailable",
            json.loads(response)["error"]["code"],
        )
        data = self.store()._load()
        self.assertEqual({}, data["bootstrapAccountSetups"])
        self.assertEqual({}, data["accounts"])

    def test_conflicts_are_typed_and_have_no_second_effect(self):
        body = request_body(self.backend)
        first = self.authorized_call(body)
        self.assertEqual("201 Created", first[0])
        different_body = dict(body, projectLabel="Different Project")
        status, _, response = self.authorized_call(different_body)
        self.assertEqual("409 Conflict", status)
        self.assertEqual("bootstrap_account_conflict", json.loads(response)["error"]["code"])
        self.idempotency_key = canonical_secret("different-idem-" + self.backend)
        status, _, _ = self.authorized_call(body)
        self.assertEqual("409 Conflict", status)
        data = self.store()._load()
        self.assertEqual(1, len(data["accounts"]))
        self.assertEqual(
            1,
            len(
                [
                    item
                    for item in data["auditLog"]
                    if item.get("action") == "workspace.create_bootstrap_account"
                ]
            ),
        )

        second_capability = canonical_secret("second-capability-" + self.backend)
        self.configure_capability(second_capability)
        self.capability = second_capability
        self.idempotency_key = canonical_secret("second-idem-" + self.backend)
        status, _, _ = self.authorized_call(body)
        self.assertEqual("409 Conflict", status)
        self.assertEqual(1, len(self.store()._load()["accounts"]))

    def test_concurrent_exact_call_commits_one_graph_and_one_audit(self):
        body = request_body(self.backend)
        barrier = threading.Barrier(3)
        results = []
        errors = []

        def worker():
            try:
                barrier.wait(timeout=5)
                results.append(self.authorized_call(body))
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=20)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual([], errors)
        self.assertEqual(["201 Created", "201 Created"], sorted(item[0] for item in results))
        self.assertEqual(results[0][2], results[1][2])
        data = self.store()._load()
        self.assertEqual(1, len(data["accounts"]))
        self.assertEqual(1, len(data["bootstrapAccountSetups"]))
        self.assertEqual(
            1,
            len(
                [
                    item
                    for item in data["auditLog"]
                    if item.get("action") == "workspace.create_bootstrap_account"
                ]
            ),
        )

    def test_rate_limit_is_source_first_and_emits_retry_after(self):
        body = request_body(self.backend)
        responses = [self.authorized_call(body) for _ in range(11)]
        self.assertTrue(all(item[0] == "201 Created" for item in responses[:10]))
        status, headers, response = responses[-1]
        self.assertEqual("429 Too Many Requests", status)
        self.assertIn("Retry-After", dict(headers))
        self.assertEqual(
            "bootstrap_account_rate_limited", json.loads(response)["error"]["code"]
        )

    def test_free_account_is_hidden_when_explicitly_disabled(self):
        class ExplodingStream:
            def read(self, _length):
                raise AssertionError("disabled free-account request body was read")

        with patch(
            "memoryendpoints.app._store",
            side_effect=AssertionError("disabled free-account touched storage"),
        ):
            captured = {}

            def start_response(status, headers):
                captured["status"] = status
                captured["headers"] = headers

            environ = {
                "REQUEST_METHOD": "POST",
                "PATH_INFO": "/api/matm/agent-setup/free-account",
                "QUERY_STRING": "",
                "CONTENT_LENGTH": "100",
                "wsgi.input": ExplodingStream(),
            }
            response = b"".join(application(environ, start_response))
        self.assertEqual("404 Not Found", captured["status"])
        self.assertEqual("not_found", json.loads(response)["error"]["code"])


class BootstrapFileAccountTests(BootstrapAccountContract, unittest.TestCase):
    backend = "file"

    def _run_spawned_workers(
        self, processes, output, expected_count, timeout_seconds
    ):
        deadline = time.monotonic() + timeout_seconds
        results = []
        started = []
        try:
            for process in processes:
                process.start()
                started.append(process)
            for _index in range(expected_count):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    results.append(output.get(timeout=remaining))
                except queue.Empty:
                    break
            for process in processes:
                process.join(max(0, deadline - time.monotonic()))
            expected = {
                "resultCount": expected_count,
                "processes": [
                    {"alive": False, "exitCode": 0} for _process in processes
                ],
            }
            actual = {
                "resultCount": len(results),
                "processes": [
                    {"alive": process.is_alive(), "exitCode": process.exitcode}
                    for process in processes
                ],
            }
            self.assertEqual(expected, actual)
            return results
        finally:
            live = [process for process in started if process.is_alive()]
            for process in live:
                process.terminate()
            cleanup_deadline = time.monotonic() + 5
            for process in live:
                process.join(max(0, cleanup_deadline - time.monotonic()))
            live = [process for process in processes if process.is_alive()]
            for process in live:
                process.kill()
            cleanup_deadline = time.monotonic() + 5
            for process in live:
                process.join(max(0, cleanup_deadline - time.monotonic()))
            output.close()
            output.join_thread()

    def _spawn_file_calls(self, calls):
        context = multiprocessing.get_context("spawn")
        gate = context.Barrier(len(calls))
        output = context.Queue()
        path = str(Path(self.tempdir.name) / "multiprocess.json")
        expires_at = os.environ[
            "MEMORYENDPOINTS_BOOTSTRAP_ACCOUNT_EXPIRES_AT"
        ]
        processes = [
            context.Process(
                target=file_bootstrap_worker,
                args=(
                    path,
                    body,
                    self.capability,
                    idempotency,
                    expires_at,
                    gate,
                    output,
                ),
            )
            for body, idempotency in calls
        ]
        return path, self._run_spawned_workers(
            processes, output, len(processes), 30
        )

    def test_spawned_exact_replay_is_one_persisted_graph(self):
        body = request_body("file-process-exact")
        path, results = self._spawn_file_calls(
            [(body, self.idempotency_key), (body, self.idempotency_key)]
        )
        self.assertEqual(["ok", "ok"], sorted(item["kind"] for item in results), results)
        self.assertEqual(results[0]["result"], results[1]["result"])
        data = FileStore(Path(path))._load()
        self.assertEqual(1, len(data["accounts"]))
        self.assertEqual(1, len(data["bootstrapAccountSetups"]))
        self.assertEqual(
            1,
            len(
                [
                    item
                    for item in data["auditLog"]
                    if item.get("action") == "workspace.create_bootstrap_account"
                ]
            ),
        )

    def test_spawned_conflicting_calls_have_one_success_and_one_typed_conflict(self):
        first = request_body("file-process-first")
        second = request_body("file-process-second")
        path, results = self._spawn_file_calls(
            [
                (first, canonical_secret("file-process-idem-first")),
                (second, canonical_secret("file-process-idem-second")),
            ]
        )
        self.assertEqual(["error", "ok"], sorted(item["kind"] for item in results), results)
        failed = next(item for item in results if item["kind"] == "error")
        self.assertEqual("bootstrap_account_conflict", failed["errorCode"])
        data = FileStore(Path(path))._load()
        self.assertEqual(1, len(data["accounts"]))
        self.assertEqual(1, len(data["bootstrapAccountSetups"]))
        self.assertEqual(
            1,
            len(
                [
                    item
                    for item in data["auditLog"]
                    if item.get("action") == "workspace.create_bootstrap_account"
                ]
            ),
        )

    def test_spawned_route_rate_limit_has_exact_persisted_counts(self):
        context = multiprocessing.get_context("spawn")
        call_count = 12
        gate = context.Barrier(call_count)
        output = context.Queue()
        path = str(Path(self.tempdir.name) / "multiprocess-rate-route.json")
        body = request_body("file-process-route-rate")
        issued_at = os.environ[
            "MEMORYENDPOINTS_BOOTSTRAP_ACCOUNT_ISSUED_AT"
        ]
        expires_at = os.environ[
            "MEMORYENDPOINTS_BOOTSTRAP_ACCOUNT_EXPIRES_AT"
        ]
        processes = [
            context.Process(
                target=file_bootstrap_route_worker,
                args=(
                    path,
                    body,
                    self.capability,
                    self.idempotency_key,
                    issued_at,
                    expires_at,
                    "198.51.100.44",
                    gate,
                    output,
                ),
            )
            for _index in range(call_count)
        ]
        results = self._run_spawned_workers(
            processes, output, call_count, 45
        )
        self.assertTrue(all(item["kind"] == "ok" for item in results), results)
        statuses = [item["status"] for item in results]
        self.assertEqual(10, statuses.count("201 Created"), statuses)
        self.assertEqual(2, statuses.count("429 Too Many Requests"), statuses)
        self.assertTrue(
            all(
                item["body"].get("error", {}).get("code")
                == "bootstrap_account_rate_limited"
                and "Retry-After" in item["headers"]
                for item in results
                if item["status"] == "429 Too Many Requests"
            )
        )
        persisted = json.loads(Path(path).read_text(encoding="utf-8"))
        records = list(persisted["connectorRateLimits"].values())
        source = [
            item for item in records if item.get("bucket") == "bootstrapSourceRequest"
        ]
        capability = [
            item
            for item in records
            if item.get("bucket") == "bootstrapCapabilityRequest"
        ]
        self.assertEqual([10], [item["requestCount"] for item in source])
        self.assertEqual([10], [item["requestCount"] for item in capability])
        self.assertEqual(1, len(persisted["accounts"]))

    def test_spawned_distinct_sources_enforce_capacity_and_preserve_json(self):
        context = multiprocessing.get_context("spawn")
        call_count = 5
        gate = context.Barrier(call_count)
        output = context.Queue()
        path = str(Path(self.tempdir.name) / "multiprocess-rate-capacity.json")
        processes = [
            context.Process(
                target=file_bootstrap_rate_worker,
                args=(
                    path,
                    "source-%d" % index,
                    "one-capability",
                    10,
                    10,
                    3,
                    gate,
                    output,
                ),
            )
            for index in range(call_count)
        ]
        results = self._run_spawned_workers(
            processes, output, call_count, 30
        )
        self.assertTrue(all(item["kind"] == "ok" for item in results), results)
        admitted = [item for item in results if item["result"]["allowed"]]
        denied = [item for item in results if not item["result"]["allowed"]]
        self.assertEqual(3, len(admitted), results)
        self.assertEqual(2, len(denied), results)
        self.assertEqual(
            {"source_partition_capacity"},
            {item["result"]["deniedLayer"] for item in denied},
        )
        persisted = json.loads(Path(path).read_text(encoding="utf-8"))
        records = list(persisted["connectorRateLimits"].values())
        source = [
            item for item in records if item.get("bucket") == "bootstrapSourceRequest"
        ]
        capability = [
            item
            for item in records
            if item.get("bucket") == "bootstrapCapabilityRequest"
        ]
        self.assertEqual(3, len(source))
        self.assertEqual([3], [item["requestCount"] for item in capability])

    def test_abrupt_worker_exit_releases_file_rate_lock(self):
        context = multiprocessing.get_context("spawn")
        ready = context.Event()
        path = str(Path(self.tempdir.name) / "multiprocess-lock-crash.json")
        process = context.Process(
            target=file_bootstrap_lock_crash_worker,
            args=(path, ready),
        )
        process.start()
        self.assertTrue(ready.wait(10))
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join(5)
        self.assertFalse(process.is_alive())
        self.assertEqual(23, process.exitcode)
        result = FileStore(Path(path)).consume_commons_layered_rate_limit(
            "bootstrapSourceRequest",
            "source-after-crash",
            1,
            600,
            "bootstrapCapabilityRequest",
            "capability-after-crash",
            1,
            600,
            2,
        )
        self.assertTrue(result["allowed"])
        json.loads(Path(path).read_text(encoding="utf-8"))

    def test_injected_file_save_failure_leaves_no_domain_state(self):
        body = request_body("file-crash")
        store = FileStore(Path(self.tempdir.name) / "crash.json")
        with patch.object(
            store, "_save", side_effect=RuntimeError("synthetic failure")
        ):
            with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                store.create_bootstrap_account(
                    body,
                    bootstrap_capability_digest(self.capability),
                    bootstrap_idempotency_digest(self.idempotency_key),
                    bootstrap_request_digest(body),
                    os.environ[
                        "MEMORYENDPOINTS_BOOTSTRAP_ACCOUNT_EXPIRES_AT"
                    ],
                )
        data = FileStore(Path(self.tempdir.name) / "crash.json")._load()
        self.assertEqual({}, data["bootstrapAccountSetups"])
        self.assertEqual({}, data["accounts"])
        self.assertEqual([], data["auditLog"])


class BootstrapSQLiteAccountTests(BootstrapAccountContract, unittest.TestCase):
    backend = "sqlite"

    def test_injected_transaction_failure_rolls_back_every_domain_row(self):
        body = request_body("sqlite-crash")
        store = SQLiteStore(Path(self.tempdir.name) / "crash.sqlite3")
        capability_digest = bootstrap_capability_digest(self.capability)
        idempotency_digest = bootstrap_idempotency_digest(self.idempotency_key)

        with patch.object(
            store,
            "_ensure_default_meeting_rooms_sql",
            side_effect=RuntimeError("synthetic failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                store.create_bootstrap_account(
                    body,
                    capability_digest,
                    idempotency_digest,
                    bootstrap_request_digest(body),
                    os.environ["MEMORYENDPOINTS_BOOTSTRAP_ACCOUNT_EXPIRES_AT"],
                )
        with store._open_connection() as connection:
            for table in (
                "matm_bootstrap_account_setups",
                "matm_accounts",
                "matm_companies",
                "matm_workspaces",
                "matm_projects",
                "matm_company_master_keys",
                "matm_human_owner_credentials",
                "matm_audit_log",
            ):
                count = connection.execute(
                    "SELECT COUNT(*) AS item_count FROM %s" % table
                ).fetchone()["item_count"]
                self.assertEqual(0, count, table)


if __name__ == "__main__":
    unittest.main()
