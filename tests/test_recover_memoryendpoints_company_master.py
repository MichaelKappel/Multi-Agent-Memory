import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from scripts import recover_memoryendpoints_company_master as recovery


BASE_URL = "https://memoryendpoints.example"
COMPANY_ID = "company-test-boundary"
WORKSPACE_ID = "workspace-test-boundary"


def _master_token(identifier_character, secret_character):
    return (
        "me_master_v1.masterkey-"
        + (identifier_character * 20)
        + "."
        + (secret_character * 43)
    )


def _agent_token(identifier_character, secret_character):
    return (
        "me_agent_v1.agenttoken-"
        + (identifier_character * 20)
        + "."
        + (secret_character * 43)
    )


def _document(token, base_url=BASE_URL):
    return {
        "schemaVersion": recovery.CREDENTIAL_FILE_SCHEMA,
        "baseUrl": base_url,
        "companyId": COMPANY_ID,
        "workspaceId": WORKSPACE_ID,
        "companyMasterTokenSecret": token,
    }


def _write_document(path, token, base_url=BASE_URL):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_document(token, base_url), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _principal_payload(
    credential_type="company_master", company_id=COMPANY_ID, scope_type=None
):
    principal = {
        "credentialType": credential_type,
        "companyId": company_id,
        "resourceContext": {"workspaceId": None},
    }
    if scope_type:
        principal["grant"] = {
            "scopeType": scope_type,
            "scopeId": company_id if scope_type == "company" else WORKSPACE_ID,
        }
    return {
        "ok": True,
        "principal": principal,
    }


class _Response:
    def __init__(self, status, payload):
        self.status = status
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _request_headers(request):
    return {key.lower(): value for key, value in request.header_items()}


class RecoverMemoryEndpointsCompanyMasterTests(unittest.TestCase):
    def test_existing_final_is_validated_and_short_circuits_without_source(self):
        final_token = _master_token("a", "b")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / recovery.PROJECT_SECRET_PATH
            _write_document(target, final_token)
            calls = []

            def open_url(request, timeout):
                calls.append((request, timeout))
                self.assertEqual(BASE_URL + recovery.ME_ROUTE, request.full_url)
                self.assertEqual("Bearer " + final_token, _request_headers(request)["authorization"])
                return _Response(200, _principal_payload())

            result = recovery.recover_company_master(
                project_root=root,
                environ={},
                open_url=open_url,
            )

            self.assertEqual("already_valid", result["status"])
            self.assertEqual(1, len(calls))
            self.assertEqual(final_token, json.loads(target.read_text(encoding="utf-8"))["companyMasterTokenSecret"])
            encoded_result = json.dumps(result)
            self.assertNotIn(final_token, encoded_result)
            self.assertNotIn(COMPANY_ID, encoded_result)
            self.assertNotIn(WORKSPACE_ID, encoded_result)

    def test_valid_pending_is_promoted_without_any_source_credential(self):
        candidate = _master_token("c", "d")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / recovery.PROJECT_SECRET_PATH
            pending = target.parent / recovery.PENDING_SECRET_NAME
            _write_document(pending, candidate)

            def open_url(request, timeout):
                self.assertEqual(30, timeout)
                self.assertEqual(BASE_URL + recovery.ME_ROUTE, request.full_url)
                self.assertEqual("Bearer " + candidate, _request_headers(request)["authorization"])
                return _Response(200, _principal_payload())

            result = recovery.recover_company_master(
                project_root=root,
                environ={},
                open_url=open_url,
            )

            self.assertEqual("pending_promoted", result["status"])
            self.assertTrue(target.is_file())
            self.assertFalse(pending.exists())
            self.assertEqual(candidate, json.loads(target.read_text(encoding="utf-8"))["companyMasterTokenSecret"])

    def test_explicit_source_writes_pending_before_exact_post_and_promotes_after_readback(self):
        source_token = _master_token("e", "f")
        candidate = _master_token("1", "2")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "governed-source.json"
            _write_document(source_path, source_token)
            target = root / "project" / recovery.PROJECT_SECRET_PATH
            pending = target.parent / recovery.PENDING_SECRET_NAME
            calls = []

            def open_url(request, timeout):
                headers = _request_headers(request)
                calls.append((request.full_url, request.get_method(), headers, request.data))
                bearer = headers["authorization"]
                if request.full_url.endswith(recovery.ME_ROUTE) and bearer == "Bearer " + source_token:
                    return _Response(200, _principal_payload())
                if request.full_url.endswith(recovery.DELEGATION_ROUTE):
                    self.assertTrue(pending.is_file(), "candidate must be durable before POST")
                    if os.name != "nt":
                        self.assertEqual(0, stat.S_IMODE(pending.stat().st_mode) & 0o077)
                    stored = json.loads(pending.read_text(encoding="utf-8"))
                    self.assertEqual(candidate, stored["companyMasterTokenSecret"])
                    return _Response(201, {"ok": True, "valuesRedacted": True})
                if request.full_url.endswith(recovery.ME_ROUTE) and bearer == "Bearer " + candidate:
                    return _Response(200, _principal_payload())
                self.fail("unexpected request")

            with patch.object(recovery.secrets, "token_hex", return_value="1" * 20), patch.object(
                recovery.secrets, "token_urlsafe", return_value="2" * 43
            ):
                result = recovery.recover_company_master(
                    project_root=root / "project",
                    source_credential_file=source_path,
                    environ={recovery.SOURCE_TOKEN_ENVIRONMENT: _agent_token("9", "8")},
                    open_url=open_url,
                )

            self.assertEqual("recovered", result["status"])
            self.assertEqual(3, len(calls))
            post_url, post_method, post_headers, post_data = calls[1]
            self.assertEqual(BASE_URL + recovery.DELEGATION_ROUTE, post_url)
            self.assertEqual("POST", post_method)
            self.assertEqual("Bearer " + source_token, post_headers["authorization"])
            self.assertNotIn("masterkey-" + ("1" * 20), post_headers["idempotency-key"])
            self.assertEqual(
                {
                    "schemaVersion": "memoryendpoints.company_master_delegation.v1",
                    "workspaceId": WORKSPACE_ID,
                    "candidateTokenSecret": candidate,
                    "label": "Human recovery master",
                    "principalName": "human-recovery",
                },
                json.loads(post_data.decode("utf-8")),
            )
            final_document = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(_document(candidate), final_document)
            self.assertFalse(pending.exists())
            if os.name != "nt":
                self.assertEqual(0, stat.S_IMODE(target.stat().st_mode) & 0o077)
            self.assertNotIn(source_token, json.dumps(result))
            self.assertNotIn(candidate, json.dumps(result))

    def test_unknown_post_outcome_retains_and_reuses_exact_pending_candidate(self):
        source_token = _master_token("3", "4")
        candidate = _master_token("5", "6")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "source.json"
            _write_document(source_path, source_token)
            target = root / "project" / recovery.PROJECT_SECRET_PATH
            pending = target.parent / recovery.PENDING_SECRET_NAME
            first_posts = []

            def first_open_url(request, timeout):
                headers = _request_headers(request)
                if request.full_url.endswith(recovery.ME_ROUTE) and headers["authorization"] == "Bearer " + source_token:
                    return _Response(200, _principal_payload())
                if request.full_url.endswith(recovery.DELEGATION_ROUTE):
                    first_posts.append((headers["idempotency-key"], bytes(request.data)))
                    raise URLError("response lost")
                if request.full_url.endswith(recovery.ME_ROUTE) and headers["authorization"] == "Bearer " + candidate:
                    return _Response(401, {"ok": False})
                self.fail("unexpected first request")

            with patch.object(recovery.secrets, "token_hex", return_value="5" * 20), patch.object(
                recovery.secrets, "token_urlsafe", return_value="6" * 43
            ):
                with self.assertRaisesRegex(recovery.RecoveryError, "pending credential was retained"):
                    recovery.recover_company_master(
                        project_root=root / "project",
                        source_credential_file=source_path,
                        open_url=first_open_url,
                    )

            self.assertTrue(pending.is_file())
            self.assertFalse(target.exists())
            self.assertEqual(candidate, json.loads(pending.read_text(encoding="utf-8"))["companyMasterTokenSecret"])
            second_posts = []
            candidate_checks = 0

            def second_open_url(request, timeout):
                nonlocal candidate_checks
                headers = _request_headers(request)
                bearer = headers["authorization"]
                if request.full_url.endswith(recovery.ME_ROUTE) and bearer == "Bearer " + candidate:
                    candidate_checks += 1
                    return _Response(
                        401 if candidate_checks == 1 else 200,
                        {"ok": False} if candidate_checks == 1 else _principal_payload(),
                    )
                if request.full_url.endswith(recovery.ME_ROUTE) and bearer == "Bearer " + source_token:
                    return _Response(200, _principal_payload())
                if request.full_url.endswith(recovery.DELEGATION_ROUTE):
                    second_posts.append((headers["idempotency-key"], bytes(request.data)))
                    return _Response(200, {"ok": True})
                self.fail("unexpected second request")

            with patch.object(recovery, "_generate_candidate", side_effect=AssertionError("must reuse pending")):
                result = recovery.recover_company_master(
                    project_root=root / "project",
                    source_credential_file=source_path,
                    open_url=second_open_url,
                )

            self.assertEqual("recovered", result["status"])
            self.assertEqual(first_posts, second_posts)
            self.assertTrue(target.is_file())
            self.assertFalse(pending.exists())

    def test_environment_source_is_supported_with_an_explicit_workspace_boundary(self):
        source_token = _master_token("7", "8")
        candidate = _master_token("9", "a")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def open_url(request, timeout):
                headers = _request_headers(request)
                bearer = headers["authorization"]
                if request.full_url.endswith(recovery.ME_ROUTE) and bearer == "Bearer " + source_token:
                    return _Response(200, _principal_payload())
                if request.full_url.endswith(recovery.DELEGATION_ROUTE):
                    self.assertEqual(WORKSPACE_ID, json.loads(request.data.decode("utf-8"))["workspaceId"])
                    return _Response(201, {"ok": True})
                if request.full_url.endswith(recovery.ME_ROUTE) and bearer == "Bearer " + candidate:
                    return _Response(200, _principal_payload())
                self.fail("unexpected request")

            with patch.object(recovery.secrets, "token_hex", return_value="9" * 20), patch.object(
                recovery.secrets, "token_urlsafe", return_value="a" * 43
            ):
                result = recovery.recover_company_master(
                    project_root=root,
                    base_url=BASE_URL,
                    workspace_id=WORKSPACE_ID,
                    environ={recovery.SOURCE_TOKEN_ENVIRONMENT: source_token},
                    open_url=open_url,
                )

            self.assertEqual("recovered", result["status"])

    def test_company_scoped_agent_can_recover_the_standard_master_file(self):
        source_token = _agent_token("b", "c")
        candidate = _master_token("d", "e")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def open_url(request, timeout):
                headers = _request_headers(request)
                bearer = headers["authorization"]
                if request.full_url.endswith(recovery.ME_ROUTE) and bearer == "Bearer " + source_token:
                    return _Response(
                        200, _principal_payload("agent_token", scope_type="company")
                    )
                if request.full_url.endswith(recovery.DELEGATION_ROUTE):
                    body = json.loads(request.data.decode("utf-8"))
                    self.assertEqual(recovery.TOP_LEVEL_AGENT_SCHEMA, body["schemaVersion"])
                    self.assertEqual("Bearer " + source_token, bearer)
                    return _Response(201, {"ok": True})
                if request.full_url.endswith(recovery.ME_ROUTE) and bearer == "Bearer " + candidate:
                    return _Response(200, _principal_payload())
                self.fail("unexpected request")

            with patch.object(recovery.secrets, "token_hex", return_value="d" * 20), patch.object(
                recovery.secrets, "token_urlsafe", return_value="e" * 43
            ):
                result = recovery.recover_company_master(
                    project_root=root,
                    base_url=BASE_URL,
                    workspace_id=WORKSPACE_ID,
                    environ={recovery.AGENT_TOKEN_ENVIRONMENT: source_token},
                    open_url=open_url,
                )

            self.assertEqual("recovered", result["status"])
            document = json.loads(
                (root / recovery.PROJECT_SECRET_PATH).read_text(encoding="utf-8")
            )
            self.assertEqual(candidate, document["companyMasterTokenSecret"])

    def test_non_company_master_source_is_rejected_before_pending_or_post(self):
        source_token = _agent_token("b", "c")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calls = []

            def open_url(request, timeout):
                calls.append(request.full_url)
                return _Response(200, _principal_payload("agent_token"))

            with self.assertRaisesRegex(recovery.RecoveryError, "company-scoped top-level agent"):
                recovery.recover_company_master(
                    project_root=root,
                    base_url=BASE_URL,
                    workspace_id=WORKSPACE_ID,
                    environ={recovery.SOURCE_TOKEN_ENVIRONMENT: source_token},
                    open_url=open_url,
                )

            self.assertEqual([BASE_URL + recovery.ME_ROUTE], calls)
            self.assertFalse((root / recovery.PROJECT_SECRET_PATH).exists())
            self.assertFalse((root / recovery.PROJECT_SECRET_PATH.parent / recovery.PENDING_SECRET_NAME).exists())

    def test_remote_http_and_mismatched_explicit_origin_fail_before_network_use(self):
        source_token = _master_token("d", "e")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "source.json"
            _write_document(source_path, source_token, "http://example.com")
            calls = []

            with self.assertRaisesRegex(recovery.RecoveryError, "must use HTTPS"):
                recovery.recover_company_master(
                    project_root=root / "project",
                    source_credential_file=source_path,
                    open_url=lambda request, timeout: calls.append(request),
                )
            self.assertEqual([], calls)

            _write_document(source_path, source_token, BASE_URL)
            with self.assertRaisesRegex(recovery.RecoveryError, "does not match"):
                recovery.recover_company_master(
                    project_root=root / "project",
                    source_credential_file=source_path,
                    base_url="https://other.example",
                    open_url=lambda request, timeout: calls.append(request),
                )
            self.assertEqual([], calls)
            self.assertEqual("http://127.0.0.1:8123", recovery._validate_base_url("http://127.0.0.1:8123"))


if __name__ == "__main__":
    unittest.main()
