import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing, contextmanager
import hashlib
from html.parser import HTMLParser
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from urllib.parse import urlsplit

from app import application
import memoryendpoints.app as app_module
from memoryendpoints.config import SITE_URL
from memoryendpoints.connector_pairing import normalize_company_agent_name
from memoryendpoints.storage import FileStore, SQLiteStore


ISSUER = "https://memoryendpoints.com"
SITE_ORIGIN = SITE_URL.rstrip("/")
SCHEMA = "memoryendpoints.connector_pairing.v1"
CLIENT_ID = "localendpoint-connect"
REDIRECT_URI = "http://127.0.0.1:53682/memoryendpoints/callback"
JSON_LIMIT = 65536
REQUEST_BODY_LIMIT = 32768
REQUESTED_SCOPES = (
    "connector:self:readback",
    "agent:self:register",
    "memory:public-safe:submit",
    "memory:search:read",
)


@contextmanager
def sqlite_transaction(path):
    """Commit test fixture mutations and always close the probe connection."""
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            yield connection


SCOPE_DIGEST = "sha256-v1:" + hashlib.sha256(
    json.dumps(
        {"schemaVersion": SCHEMA, "scopes": list(REQUESTED_SCOPES)},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
).hexdigest()
GOVERNED_SECRET = re.compile(
    r"me_(?:master|agent|invite|human|accountsession|accountcsrf|masterproof|closure|connector|paircode|pairproof)_v1\."
    r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
)


def _b64url_sha256(value):
    digest = hashlib.sha256(value.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _header(headers, name, default=None):
    expected = name.lower()
    for key, value in headers.items():
        if key.lower() == expected:
            return value
    return default


def call_api(path, method="GET", body=None, token=None, query="", extra_headers=None):
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    captured = {}

    def start_response(status, response_headers):
        captured["status"] = status
        captured["headers"] = dict(response_headers)

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "wsgi.input": io.BytesIO(raw),
        "CONTENT_LENGTH": str(len(raw)),
    }
    if body is not None:
        environ["CONTENT_TYPE"] = "application/json"
    if token:
        environ["HTTP_AUTHORIZATION"] = "Bearer " + token
    for key, value in (extra_headers or {}).items():
        environ[key] = value
    response_body = b"".join(application(environ, start_response))
    payload = json.loads(response_body.decode("utf-8"))
    return (
        int(captured["status"].split(" ", 1)[0]),
        captured["headers"],
        payload,
        response_body,
    )


def call_raw(path, method, raw, token=None, extra_headers=None, content_type="application/json"):
    captured = {}

    def start_response(status, response_headers):
        captured["status"] = status
        captured["headers"] = dict(response_headers)

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "wsgi.input": io.BytesIO(raw),
        "CONTENT_LENGTH": str(len(raw)),
        "CONTENT_TYPE": content_type,
    }
    if token:
        environ["HTTP_AUTHORIZATION"] = "Bearer " + token
    for key, value in (extra_headers or {}).items():
        environ[key] = value
    response_body = b"".join(application(environ, start_response))
    payload = json.loads(response_body.decode("utf-8"))
    return (
        int(captured["status"].split(" ", 1)[0]),
        captured["headers"],
        payload,
        response_body,
    )


def call_with_unreadable_body(path, declared_length, token=None):
    class UnreadableBody:
        def read(self, *_args, **_kwargs):
            raise AssertionError("request body was read before connector authority rejection")

    captured = {}

    def start_response(status, response_headers):
        captured["status"] = status
        captured["headers"] = dict(response_headers)

    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "wsgi.input": UnreadableBody(),
        "CONTENT_LENGTH": str(declared_length),
        "CONTENT_TYPE": "application/json",
    }
    if token:
        environ["HTTP_AUTHORIZATION"] = "Bearer " + token
    response_body = b"".join(application(environ, start_response))
    payload = json.loads(response_body.decode("utf-8"))
    return (
        int(captured["status"].split(" ", 1)[0]),
        captured["headers"],
        payload,
        response_body,
    )


def call_html(path, cookie=""):
    captured = {}

    def start_response(status, response_headers):
        captured["status"] = status
        captured["headers"] = dict(response_headers)

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "wsgi.input": io.BytesIO(b""),
        "CONTENT_LENGTH": "0",
    }
    if cookie:
        environ["HTTP_COOKIE"] = cookie
    raw = b"".join(application(environ, start_response))
    return int(captured["status"].split(" ", 1)[0]), captured["headers"], raw.decode("utf-8")


class _WorkspaceRefParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._inside_workspace_select = False
        self.workspace_refs = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "select" and values.get("name") == "workspaceRef":
            self._inside_workspace_select = True
        elif tag == "option" and self._inside_workspace_select and values.get("value"):
            self.workspace_refs.append(values["value"])

    def handle_endtag(self, tag):
        if tag == "select":
            self._inside_workspace_select = False


class ConnectorPairingApiContract:
    """Black-box WSGI acceptance for memoryendpoints.connector_pairing.v1."""

    backend = None

    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="memoryendpoints-connector-pairing-%s-" % self.backend)
        self.store_path = Path(self.tempdir) / "matm.json"
        self.sqlite_path = Path(self.tempdir) / "matm.sqlite3"
        self._saved_environment = {
            key: os.environ.get(key)
            for key in (
                "MEMORYENDPOINTS_STORE_BACKEND",
                "MEMORYENDPOINTS_STORE_PATH",
                "MEMORYENDPOINTS_SQLITE_PATH",
                "MEMORYENDPOINTS_CREDENTIAL_PEPPER",
                "MEMORYENDPOINTS_CREDENTIAL_CONFIG_PATH",
                "MEMORYENDPOINTS_MYSQL_CONFIG_PATH",
                "MEMORYENDPOINTS_CONNECTOR_PAIRING_RATE_LIMIT",
            )
        }
        os.environ.update(
            {
                "MEMORYENDPOINTS_STORE_BACKEND": self.backend,
                "MEMORYENDPOINTS_STORE_PATH": str(self.store_path),
                "MEMORYENDPOINTS_SQLITE_PATH": str(self.sqlite_path),
                "MEMORYENDPOINTS_CREDENTIAL_PEPPER": secrets.token_urlsafe(48),
                "MEMORYENDPOINTS_CREDENTIAL_CONFIG_PATH": str(Path(self.tempdir) / "missing-pepper.json"),
                "MEMORYENDPOINTS_MYSQL_CONFIG_PATH": str(Path(self.tempdir) / "missing-mysql.json"),
                "MEMORYENDPOINTS_CONNECTOR_PAIRING_RATE_LIMIT": "60",
            }
        )
        self.store = self._new_store()
        setup = self.store.create_free_account(
            "LocalEndpoint Workspace",
            "LocalEndpoint Test Company",
            "LocalEndpoint Pairing",
        )
        (
            self.workspace_id,
            self.master_key_id,
            self.master_token,
            self.account_id,
            self.company_id,
            self.project_id,
            _recovery_secret,
        ) = setup
        self.password = secrets.token_urlsafe(36)
        proof = self.store.create_company_master_proof(self.master_token)
        created = self.store.create_human_account(
            "localendpoint-owner",
            self.password,
            proof["masterProofSecret"],
        )
        self.assertTrue(created["ok"], created)
        session = self.store.login_human_account("localendpoint-owner", self.password)
        memberships = self.store.list_human_company_memberships(session["sessionSecret"])
        selected = self.store.select_human_company_membership(
            session["sessionSecret"], memberships["items"][0]["authorityId"]
        )
        self.assertTrue(selected["ok"], selected)
        self.human_session_secret = selected["sessionSecret"]
        self.human_csrf = selected["csrfToken"]
        self.store.reauthenticate_human_account_session(self.human_session_secret, self.password)
        self._claim_material = {}
        self._workspace_refs = {}

    def tearDown(self):
        for key, value in self._saved_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def _new_store(self):
        if self.backend == "sqlite":
            return SQLiteStore(self.sqlite_path)
        return FileStore(self.store_path)

    def _human_headers(self):
        return {
            "HTTP_COOKIE": "__Host-memoryendpoints-human=" + self.human_session_secret,
            "HTTP_X_CSRF_TOKEN": self.human_csrf,
            "HTTP_ORIGIN": SITE_ORIGIN,
            "HTTP_SEC_FETCH_SITE": "same-origin",
            "HTTP_SEC_FETCH_MODE": "cors",
            "HTTP_SEC_FETCH_DEST": "empty",
        }

    def _idempotency_headers(self, key=None):
        value = key or ("pairing-" + secrets.token_urlsafe(18))
        if key is not None and len(value) < 16:
            value += "-connector-idempotency"
        return {"HTTP_IDEMPOTENCY_KEY": value}

    def _human_mutation_headers(self, key=None):
        headers = self._human_headers()
        headers.update(self._idempotency_headers(key))
        return headers

    def _new_selected_human_session(self):
        store = self._new_store()
        login = store.login_human_account("localendpoint-owner", self.password)
        self.assertTrue(login["ok"], login)
        memberships = store.list_human_company_memberships(login["sessionSecret"])
        self.assertTrue(memberships["ok"], memberships)
        selected = store.select_human_company_membership(
            login["sessionSecret"], memberships["items"][0]["authorityId"]
        )
        self.assertTrue(selected["ok"], selected)
        reauthenticated = store.reauthenticate_human_account_session(
            selected["sessionSecret"], self.password
        )
        self.assertTrue(reauthenticated["ok"], reauthenticated)
        return {
            "sessionSecret": reauthenticated.get("sessionSecret")
            or selected["sessionSecret"],
            "csrfToken": reauthenticated.get("csrfToken") or selected["csrfToken"],
        }

    def _existing_workspace_ref(self, request):
        public_ref = request["publicRequestRef"]
        if public_ref in self._workspace_refs:
            return self._workspace_refs[public_ref]
        status, headers, body = call_html(
            "/connect/authorize/" + public_ref,
            "__Host-memoryendpoints-human=" + self.human_session_secret,
        )
        self.assertEqual(200, status, body)
        self.assertIn("no-store", _header(headers, "Cache-Control", ""))
        self.assertIn(SCOPE_DIGEST, body)
        parser = _WorkspaceRefParser()
        parser.feed(body)
        self.assertEqual(1, len(parser.workspace_refs), parser.workspace_refs)
        workspace_ref = parser.workspace_refs[0]
        self.assertRegex(workspace_ref, r"^workref_[A-Za-z0-9_-]{43}$")
        for forbidden in (
            self._internal_request_id(request),
            self.workspace_id,
            self.company_id,
            self.project_id,
            "localendpoint-agent",
            self._claim_material[public_ref]["pairingRequestProof"],
            self._claim_material[public_ref]["state"],
            *REQUESTED_SCOPES,
        ):
            self.assertNotIn(forbidden, body)
        self._workspace_refs[public_ref] = workspace_ref
        return workspace_ref

    def _internal_request_id(self, request):
        public_ref = request["publicRequestRef"]
        if self.backend == "sqlite":
            with sqlite_transaction(self.sqlite_path) as connection:
                row = connection.execute(
                    "SELECT request_id FROM matm_connector_pairing_requests WHERE public_request_ref = ?",
                    (public_ref,),
                ).fetchone()
            self.assertIsNotNone(row)
            return row[0]
        data = json.loads(self.store_path.read_text(encoding="utf-8"))
        match = next(
            (
                item.get("requestId")
                for item in (data.get("connectorPairingRequests") or {}).values()
                if item.get("publicRequestRef") == public_ref
            ),
            None,
        )
        self.assertIsNotNone(match)
        return match

    def _assert_json(self, status, headers, raw, expected_status=None, no_store=True):
        if expected_status is not None:
            self.assertEqual(expected_status, status)
        self.assertFalse(300 <= status < 400, (status, headers))
        self.assertIsNone(_header(headers, "Location"))
        self.assertTrue(
            (_header(headers, "Content-Type", "").lower()).startswith("application/json"),
            headers,
        )
        self.assertLessEqual(len(raw), JSON_LIMIT)
        content_length = _header(headers, "Content-Length")
        if content_length is not None:
            self.assertEqual(len(raw), int(content_length))
        if no_store:
            cache_control = _header(headers, "Cache-Control", "")
            self.assertIn("no-store", cache_control)
            self.assertIn("private", cache_control)
            self.assertEqual("no-cache", _header(headers, "Pragma"))
            self.assertEqual("no-referrer", _header(headers, "Referrer-Policy"))

    def _assert_error(self, response, expected_status, code, forbidden_values=()):
        status, headers, payload, raw = response
        self._assert_json(status, headers, raw, expected_status)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["safeNoOp"])
        self.assertEqual(code, payload["error"]["code"])
        encoded = json.dumps(payload, sort_keys=True)
        self.assertIsNone(GOVERNED_SECRET.search(encoded), encoded)
        for forbidden in forbidden_values:
            if forbidden:
                self.assertNotIn(str(forbidden), encoded)

    def _assert_redacted_metadata(self, payload):
        encoded = json.dumps(payload, sort_keys=True)
        self.assertIsNone(GOVERNED_SECRET.search(encoded), encoded)
        self.assertNotIn('"privatePayload":', encoded)
        self.assertNotIn("credentialHash", encoded)
        self.assertNotIn("tokenHash", encoded)
        self.assertNotIn("verifierHash", encoded)

    def _schema_applies(self, value, schema, schemas):
        if "$ref" in schema:
            return self._schema_applies(
                value, schemas[schema["$ref"].rsplit("/", 1)[-1]], schemas
            )
        if "allOf" in schema:
            return all(
                self._schema_applies(value, item, schemas)
                for item in schema["allOf"]
            )
        if "const" in schema and value != schema["const"]:
            return False
        if "enum" in schema and value not in schema["enum"]:
            return False
        if isinstance(value, dict):
            required = set(schema.get("required") or ())
            if not required.issubset(value):
                return False
        if "not" in schema and self._schema_applies(value, schema["not"], schemas):
            return False
        return True

    def _assert_strict_openapi_shape(self, value, schema, schemas, path="response"):
        if "$ref" in schema:
            name = schema["$ref"].rsplit("/", 1)[-1]
            self.assertIn(name, schemas, path)
            return self._assert_strict_openapi_shape(
                value, schemas[name], schemas, path
            )
        for index, item in enumerate(schema.get("allOf") or ()):
            self._assert_strict_openapi_shape(
                value, item, schemas, "%s.allOf[%d]" % (path, index)
            )
        if "oneOf" in schema:
            matches = [
                item
                for item in schema["oneOf"]
                if self._schema_applies(value, item, schemas)
            ]
            self.assertEqual(1, len(matches), "%s oneOf matches=%d" % (path, len(matches)))
            self._assert_strict_openapi_shape(value, matches[0], schemas, path)
        if "not" in schema:
            self.assertFalse(
                self._schema_applies(value, schema["not"], schemas),
                "%s matched forbidden schema" % path,
            )
        if "const" in schema:
            self.assertEqual(schema["const"], value, path)
        if "enum" in schema:
            self.assertIn(value, schema["enum"], path)
        if isinstance(value, dict):
            required = set(schema.get("required") or ())
            self.assertTrue(required.issubset(value), "%s missing %r" % (path, sorted(required - set(value))))
            properties = schema.get("properties") or {}
            if schema.get("type") == "object":
                self.assertIs(
                    False,
                    schema.get("additionalProperties"),
                    "%s must close additionalProperties" % path,
                )
            if schema.get("additionalProperties") is False:
                extras = set(value) - set(properties)
                self.assertFalse(extras, "%s extra keys %r" % (path, sorted(extras)))
            for key, item in value.items():
                if key in properties:
                    self._assert_strict_openapi_shape(
                        item, properties[key], schemas, "%s.%s" % (path, key)
                    )
        elif isinstance(value, list):
            prefix = schema.get("prefixItems") or []
            for index, item in enumerate(value):
                item_schema = prefix[index] if index < len(prefix) else schema.get("items")
                if item_schema:
                    self._assert_strict_openapi_shape(
                        item, item_schema, schemas, "%s[%d]" % (path, index)
                    )

    @staticmethod
    def _schema_refs(schema):
        refs = set()
        if isinstance(schema, dict):
            if isinstance(schema.get("$ref"), str):
                refs.add(schema["$ref"].rsplit("/", 1)[-1])
            for value in schema.values():
                refs.update(ConnectorPairingApiContract._schema_refs(value))
        elif isinstance(schema, list):
            for value in schema:
                refs.update(ConnectorPairingApiContract._schema_refs(value))
        return refs

    def _assert_receipt(
        self, payload, action, status=None, replay=None, scope_digest=None
    ):
        receipt = payload.get("receipt") or {}
        self.assertRegex(receipt.get("receiptId") or "", r"^connector-[a-f0-9]{24}$")
        self.assertEqual(action, receipt.get("action"))
        if status is not None:
            self.assertEqual(status, receipt.get("status"))
        if replay is not None:
            self.assertIs(bool(replay), receipt.get("idempotentReplay"))
        if scope_digest is not None:
            self.assertEqual(scope_digest, receipt.get("scopeDigest"))
        self.assertFalse(receipt.get("rawCredentialExposed"))
        self.assertFalse(receipt.get("privatePayloadExposed"))
        self._assert_redacted_metadata(receipt)
        return receipt

    def _assert_scoped_operation_receipt(self, payload):
        receipt = payload["receipt"]
        self.assertRegex(receipt.get("receiptId") or "", r"^connector-[a-f0-9]{24}$")
        self.assertRegex(receipt.get("action") or "", r"^[a-z][a-z0-9_]{2,63}$")
        self.assertEqual(SCOPE_DIGEST, receipt.get("scopeDigest"))
        self.assertFalse(receipt.get("rawCredentialExposed"))
        self.assertFalse(receipt.get("privatePayloadExposed"))
        self._assert_redacted_metadata(receipt)

    def _request_body(
        self,
        agent_id="localendpoint-agent",
        state=None,
        verifier=None,
        requested_scopes=None,
    ):
        verifier = verifier or secrets.token_urlsafe(48)
        state = state or secrets.token_urlsafe(32)
        return {
            "schemaVersion": SCHEMA,
            "clientId": CLIENT_ID,
            "redirectUri": REDIRECT_URI,
            "state": state,
            "codeChallenge": _b64url_sha256(verifier),
            "codeChallengeMethod": "S256",
            "requestedAgentId": agent_id,
            "requestedScopes": list(
                REQUESTED_SCOPES if requested_scopes is None else requested_scopes
            ),
        }, verifier, state

    def _start_request(self, agent_id="localendpoint-agent", state=None, verifier=None, key=None):
        body, verifier, state = self._request_body(agent_id, state, verifier)
        response = call_api(
            "/api/matm/connector-pairings/requests",
            "POST",
            body,
            extra_headers=self._idempotency_headers(key),
        )
        status, headers, payload, raw = response
        self._assert_json(status, headers, raw, 201)
        self.assertEqual(SCHEMA, payload["schemaVersion"])
        request = payload["pairingRequest"]
        self.assertEqual("pending_human_approval", request["status"])
        self.assertEqual(600, request["expiresInSeconds"])
        self.assertEqual("LocalEndpoint Connect", request["clientDisplayName"])
        self.assertEqual("LocalEndpoint Agent", request["agentDisplayName"])
        self.assertNotIn("requestedAgentId", request)
        self.assertNotIn("requestId", request)
        self.assertEqual(list(REQUESTED_SCOPES), request["requestedScopes"])
        self.assertEqual(SCOPE_DIGEST, request["scopeDigest"])
        self.assertRegex(request["scopeDigest"], r"^sha256-v1:[a-f0-9]{64}$")
        pairing_request_proof = payload["pairingRequestProof"]
        self.assertRegex(
            pairing_request_proof,
            r"^me_pairproof_v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$",
        )
        self._assert_secret_not_persisted(pairing_request_proof)
        self._assert_receipt(
            payload,
            "authorize",
            "pending_human_approval",
            False,
            SCOPE_DIGEST,
        )
        approval_url = urlsplit(payload["authorizationUrl"])
        self.assertEqual(ISSUER, "%s://%s" % (approval_url.scheme, approval_url.netloc))
        self.assertTrue(approval_url.path.startswith("/connect/authorize/"), approval_url.path)
        public_request_ref = approval_url.path.rsplit("/", 1)[-1]
        self.assertRegex(public_request_ref, r"^pairref_[A-Za-z0-9_-]{43}$")
        self.assertEqual(public_request_ref, request["publicRequestRef"])
        internal_request_id = self._internal_request_id(request)
        self.assertNotEqual(internal_request_id, public_request_ref)
        self.assertEqual("", approval_url.fragment)
        self.assertEqual("", approval_url.query)
        for forbidden in (
            pairing_request_proof,
            state,
            internal_request_id,
            self.company_id,
            self.workspace_id,
            self.project_id,
            normalize_company_agent_name(agent_id),
            *REQUESTED_SCOPES,
        ):
            self.assertNotIn(forbidden, payload["authorizationUrl"])
        self._claim_material[public_request_ref] = {
            "pairingRequestProof": pairing_request_proof,
            "state": state,
        }
        self._assert_value_not_persisted(state)
        metadata = dict(payload)
        metadata.pop("pairingRequestProof")
        self._assert_redacted_metadata(metadata)
        self._last_pairing_request_result = payload
        return request, verifier, state

    def _approve(
        self,
        request,
        agent_id="localendpoint-agent",
        body=None,
        key=None,
        claim=True,
        claim_key=None,
    ):
        approval_body = body or {
            "schemaVersion": SCHEMA,
            "canonicalAgentApproved": True,
            "approvedScopes": list(REQUESTED_SCOPES),
            "workspaceSelection": {
                "mode": "existing",
                "workspaceRef": self._existing_workspace_ref(request),
            },
        }
        headers = self._human_mutation_headers(key)
        response = call_api(
            "/api/matm/human/connector-pairings/%s/approve"
            % request["publicRequestRef"],
            "POST",
            approval_body,
            extra_headers=headers,
        )
        status, headers, payload, raw = response
        self._assert_json(status, headers, raw, 200)
        self.assertEqual(REDIRECT_URI, payload["wakeUpUrl"])
        wake_up = urlsplit(payload["wakeUpUrl"])
        self.assertEqual("", wake_up.query)
        self.assertEqual("", wake_up.fragment)
        self.assertEqual(list(REQUESTED_SCOPES), payload["approval"]["approvedScopes"])
        self.assertEqual(SCOPE_DIGEST, payload["approval"]["scopeDigest"])
        self._assert_receipt(payload, "authorize", "approved", False, SCOPE_DIGEST)
        encoded = json.dumps(payload, sort_keys=True)
        for forbidden_key in (
            "callbackUrl",
            "authorizationCode",
            "pairingRequestProof",
            '"state"',
            "companyId",
            "workspaceId",
            "projectId",
            "agentId",
            "requestId",
            self._internal_request_id(request),
        ):
            self.assertNotIn(forbidden_key, encoded)
        self._assert_redacted_metadata(payload)
        if not claim:
            return payload, None, None
        claim_payload, code = self._claim_code(
            request, key=claim_key or ("claim-" + (key or secrets.token_urlsafe(18)))
        )
        return payload, code, self._claim_material[request["publicRequestRef"]]["state"]

    def _claim_body(self, request, **overrides):
        material = self._claim_material[request["publicRequestRef"]]
        body = {
            "schemaVersion": SCHEMA,
            "clientId": CLIENT_ID,
            "redirectUri": REDIRECT_URI,
            "pairingRequestProof": material["pairingRequestProof"],
            "state": material["state"],
        }
        body.update(overrides)
        return body

    def _claim_response(self, request, key, body=None):
        return call_api(
            "/api/matm/connector-pairings/authorization-code-claims",
            "POST",
            body or self._claim_body(request),
            extra_headers=self._idempotency_headers(key),
        )

    def _claim_code(self, request, key=None, expected_status=200):
        response = self._claim_response(
            request, key or ("authorization-claim-" + secrets.token_urlsafe(18))
        )
        status, headers, payload, raw = response
        self._assert_json(status, headers, raw, expected_status)
        self.assertEqual("authorization_code_issued", payload["status"])
        self.assertEqual(60, payload["expiresInSeconds"])
        self.assertTrue(payload["stateVerified"])
        self.assertEqual(list(REQUESTED_SCOPES), payload["approvedScopes"])
        self.assertEqual(SCOPE_DIGEST, payload["scopeDigest"])
        code = payload["authorizationCode"]
        self.assertRegex(code, r"^me_paircode_v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
        self._assert_secret_not_persisted(code)
        self._assert_receipt(
            payload,
            "authorization_code_claim",
            "authorization_code_issued",
            bool(payload.get("idempotentReplay")),
            SCOPE_DIGEST,
        )
        public_payload = dict(payload)
        public_payload.pop("authorizationCode")
        self._assert_redacted_metadata(public_payload)
        return payload, code

    def _exchange(self, code, verifier, key=None, expected_status=201):
        response = call_api(
            "/api/matm/connector-pairings/token",
            "POST",
            {
                "schemaVersion": SCHEMA,
                "grantType": "authorization_code",
                "clientId": CLIENT_ID,
                "redirectUri": REDIRECT_URI,
                "code": code,
                "codeVerifier": verifier,
            },
            extra_headers=self._idempotency_headers(key),
        )
        status, headers, payload, raw = response
        self._assert_json(status, headers, raw, expected_status)
        self.assertEqual("pending_activation", payload["pairing"]["status"])
        self.assertEqual(600, payload["pairing"]["activationExpiresInSeconds"])
        self.assertEqual(list(REQUESTED_SCOPES), payload["approvedScopes"])
        self.assertEqual(SCOPE_DIGEST, payload["scopeDigest"])
        self.assertEqual(
            list(REQUESTED_SCOPES), payload["pairing"]["grant"]["approvedScopes"]
        )
        self.assertEqual(
            SCOPE_DIGEST, payload["pairing"]["grant"]["scopeDigest"]
        )
        self.assertEqual(SCOPE_DIGEST, payload["credentialDelivery"]["scopeDigest"])
        secret = payload["connectorCredentialSecret"]
        self.assertRegex(secret, r"^me_connector_v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
        self.assertTrue(payload["credentialDelivery"]["showCredentialOnce"])
        self.assertTrue(payload["credentialDelivery"]["exactRetryUntilActivation"])
        self.assertFalse(payload["credentialDelivery"]["rawCredentialPersisted"])
        self._assert_receipt(
            payload,
            "exchange",
            "pending_activation",
            bool(payload.get("idempotentReplay")),
            SCOPE_DIGEST,
        )
        public_payload = dict(payload)
        public_payload.pop("connectorCredentialSecret")
        self._assert_redacted_metadata(public_payload)
        return payload, secret

    def _activate(self, pairing_id, secret, key=None, expected_status=200):
        response = call_api(
            "/api/matm/connector-pairings/%s/activate" % pairing_id,
            "POST",
            {"schemaVersion": SCHEMA},
            secret,
            extra_headers=self._idempotency_headers(key),
        )
        status, headers, payload, raw = response
        self._assert_json(status, headers, raw, expected_status)
        self.assertEqual("active", payload["pairing"]["status"])
        self.assertEqual(
            list(REQUESTED_SCOPES), payload["pairing"]["grant"]["approvedScopes"]
        )
        self.assertEqual(
            SCOPE_DIGEST, payload["pairing"]["grant"]["scopeDigest"]
        )
        self._assert_receipt(
            payload,
            "activate",
            "active",
            bool(payload.get("idempotentReplay")),
            SCOPE_DIGEST,
        )
        self._assert_redacted_metadata(payload)
        return payload

    def _pair_active(self, agent_id="localendpoint-agent"):
        request, verifier, state = self._start_request(agent_id)
        _approved, code, callback_state = self._approve(request, agent_id)
        self.assertEqual(state, callback_state)
        exchange, secret = self._exchange(code, verifier)
        pairing_id = exchange["pairing"]["pairingId"]
        self._activate(pairing_id, secret)
        return pairing_id, secret, exchange

    def _agent_registration_count(self, agent_id):
        if self.backend == "sqlite":
            with sqlite_transaction(self.sqlite_path) as connection:
                return connection.execute(
                    "SELECT COUNT(*) FROM matm_agents WHERE workspace_id = ? AND agent_id = ?",
                    (self.workspace_id, agent_id),
                ).fetchone()[0]
        data = json.loads(self.store_path.read_text(encoding="utf-8"))
        return int(any(
            item.get("workspaceId") == self.workspace_id and item.get("agentId") == agent_id
            for item in (data.get("agents") or {}).values()
        ))

    def _workspace_count(self, workspace_id):
        if self.backend == "sqlite":
            with sqlite_transaction(self.sqlite_path) as connection:
                return connection.execute(
                    "SELECT COUNT(*) FROM matm_workspaces WHERE workspace_id = ?",
                    (workspace_id,),
                ).fetchone()[0]
        data = json.loads(self.store_path.read_text(encoding="utf-8"))
        return int(workspace_id in (data.get("workspaces") or {}))

    def _pairing_request_count(self):
        if self.backend == "sqlite":
            with sqlite_transaction(self.sqlite_path) as connection:
                return connection.execute(
                    "SELECT COUNT(*) FROM matm_connector_pairing_requests"
                ).fetchone()[0]
        if not self.store_path.exists():
            return 0
        data = json.loads(self.store_path.read_text(encoding="utf-8"))
        return len(data.get("connectorPairingRequests") or {})

    def _assert_value_not_persisted(self, value, include_last_component=False):
        needles = [value.encode("utf-8")]
        if include_last_component:
            needles.append(value.rsplit(".", 1)[-1].encode("ascii"))
        paths = [self.store_path] if self.backend == "file" else list(Path(self.tempdir).glob("matm.sqlite3*"))
        for path in paths:
            if not path.exists():
                continue
            persisted = path.read_bytes()
            for needle in needles:
                self.assertNotIn(needle, persisted, "raw connector credential material was persisted")

    def _assert_secret_not_persisted(self, secret):
        self._assert_value_not_persisted(secret, include_last_component=True)

    def _assert_connector_audit_identifier_free(self, required_actions=()):
        data = self._new_store()._load()
        rows = [
            item
            for item in data.get("auditLog", [])
            if str(item.get("action") or "").startswith("connector_pairing.")
        ]
        actions = {item.get("action") for item in rows}
        self.assertTrue(set(required_actions).issubset(actions), actions)
        self.assertTrue(rows)

        identifier_fields = {
            "accountId",
            "agentId",
            "agentIdentityId",
            "approvedByAuthorityId",
            "approvedByHumanAccountId",
            "authorityId",
            "companyId",
            "connectorCredentialId",
            "credentialId",
            "currentCredentialId",
            "humanAccountId",
            "humanAccountSessionId",
            "masterKeyId",
            "pairingId",
            "predecessorCredentialId",
            "projectId",
            "publicRequestRef",
            "requestId",
            "rotationId",
            "selectedAuthorityId",
            "successorCredentialId",
            "workspaceId",
        }
        private_values = set()

        def collect(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in identifier_fields and isinstance(child, str) and child:
                        private_values.add(child)
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        for key, value in data.items():
            if key != "auditLog":
                collect(value)

        audit_text = json.dumps(rows, ensure_ascii=False, sort_keys=True)
        for private_value in private_values:
            self.assertNotIn(private_value, audit_text)
        for row in rows:
            self.assertIsNone(row.get("workspaceId"), row)
            self.assertRegex(
                row.get("actor") or "",
                r"^connector-[a-z][a-z0-9-]{0,31}-ref-[A-Za-z0-9_-]{24}$",
            )
            self.assertRegex(
                row.get("target") or "",
                r"^connector-[a-z][a-z0-9-]{0,31}-ref-[A-Za-z0-9_-]{24}$",
            )
            details = row.get("details") or {}
            self.assertEqual("hmac-sha256-v1", details.get("correlationScheme"))
            self.assertFalse(details.get("privateIdentifiersLogged"))
            self.assertTrue(identifier_fields.isdisjoint(details), details)

    def _expire_pending_pairing(self, pairing_id):
        expired = "2000-01-01T00:00:00.000000Z"
        if self.backend == "sqlite":
            with sqlite_transaction(self.sqlite_path) as connection:
                tables = [row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )]
                tables.sort(key=lambda name: name != "matm_connector_pairings")
                for table in tables:
                    columns = [row[1] for row in connection.execute("PRAGMA table_info(%s)" % table)]
                    if "pairing_id" not in columns:
                        continue
                    expiry = "activation_expires_at" if "activation_expires_at" in columns else None
                    if not expiry and "expires_at" in columns and "status" in columns:
                        expiry = "expires_at"
                    if expiry:
                        cursor = connection.execute(
                            "UPDATE %s SET %s = ? WHERE pairing_id = ?" % (table, expiry),
                            (expired, pairing_id),
                        )
                        if cursor.rowcount:
                            connection.commit()
                            return
            self.fail("SQLite connector pending-grant expiry field was not found")

        data = json.loads(self.store_path.read_text(encoding="utf-8"))
        changed = False

        def walk(value):
            nonlocal changed
            if isinstance(value, dict):
                if value.get("pairingId") == pairing_id and value.get("status") == "pending_activation":
                    field = "activationExpiresAt" if "activationExpiresAt" in value else "expiresAt"
                    value[field] = expired
                    changed = True
                for item in value.values():
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(data)
        self.assertTrue(changed, "FileStore connector pending-grant expiry field was not found")
        self.store_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def _expire_pairing_request_phase(self, request_id, phase):
        expired = "2000-01-01T00:00:00.000000Z"
        if phase == "request":
            file_fields = ("expiresAt", "requestExpiresAt")
            sql_fields = ("expires_at", "request_expires_at")
            statuses = {"pending_human_approval", "pending"}
        else:
            file_fields = ("authorizationCodeExpiresAt", "codeExpiresAt")
            sql_fields = ("authorization_code_expires_at", "code_expires_at")
            statuses = {"approved", "authorization_code_issued"}
        if self.backend == "sqlite":
            with sqlite_transaction(self.sqlite_path) as connection:
                tables = [row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )]
                for table in tables:
                    columns = [row[1] for row in connection.execute("PRAGMA table_info(%s)" % table)]
                    if "request_id" not in columns:
                        continue
                    expiry = next((field for field in sql_fields if field in columns), None)
                    if not expiry:
                        continue
                    cursor = connection.execute(
                        "UPDATE %s SET %s = ? WHERE request_id = ?" % (table, expiry),
                        (expired, request_id),
                    )
                    if cursor.rowcount:
                        connection.commit()
                        return
            self.fail("SQLite connector %s expiry field was not found" % phase)

        data = json.loads(self.store_path.read_text(encoding="utf-8"))
        changed = False

        def walk(value):
            nonlocal changed
            if isinstance(value, dict):
                if value.get("requestId") == request_id and value.get("status") in statuses:
                    field = next((name for name in file_fields if name in value), None)
                    if field:
                        value[field] = expired
                        changed = True
                for item in value.values():
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(data)
        self.assertTrue(changed, "FileStore connector %s expiry field was not found" % phase)
        self.store_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def test_connector_audit_rows_are_pseudonymous_and_identifier_free(self):
        self._start_request()
        self._assert_connector_audit_identifier_free(
            {"connector_pairing.request"}
        )

    def test_public_discovery_is_same_origin_versioned_bounded_and_secret_free(self):
        status, headers, payload, raw = call_api("/.well-known/memoryendpoints-connector")
        self._assert_json(status, headers, raw, 200, no_store=False)
        self.assertLessEqual(len(raw), 16384)
        self.assertEqual(SCHEMA, payload["schemaVersion"])
        self.assertEqual(ISSUER, payload["issuer"])
        expected = {
            "pairingRequest": "/api/matm/connector-pairings/requests",
            "authorization": "/connect/authorize/{publicRequestRef}",
            "authorizationCodeClaim": "/api/matm/connector-pairings/authorization-code-claims",
            "token": "/api/matm/connector-pairings/token",
            "activation": "/api/matm/connector-pairings/{pairingId}/activate",
            "status": "/api/matm/connector-pairings/{pairingId}",
            "rotation": "/api/matm/connector-pairings/{pairingId}/rotations",
            "rotationActivation": "/api/matm/connector-pairings/{pairingId}/rotations/{rotationId}/activate",
            "credentialList": "/api/matm/connector-pairings/{pairingId}/credentials",
            "revocation": "/api/matm/connector-pairings/{pairingId}/revoke",
            "disconnect": "/api/matm/connector-pairings/{pairingId}/disconnect",
            "cancellation": "/api/matm/connector-pairings/{pairingId}/cancel",
        }
        self.assertEqual(expected, payload["endpoints"])
        for route in payload["endpoints"].values():
            self.assertTrue(route.startswith("/"))
            self.assertNotIn("?", route)
            self.assertNotIn("#", route)
        self.assertEqual(["S256"], payload["security"]["pkceMethods"])
        self.assertTrue(payload["security"]["stateRequired"])
        self.assertEqual(600, payload["security"]["requestTtlSeconds"])
        self.assertEqual(60, payload["security"]["authorizationCodeTtlSeconds"])
        self.assertEqual(600, payload["security"]["pendingGrantTtlSeconds"])
        self.assertFalse(
            payload["security"]["authorizationCallbackParametersAllowed"]
        )
        self.assertEqual(
            "body_only_claim", payload["security"]["authorizationCodeDelivery"]
        )
        self.assertEqual(CLIENT_ID, payload["clients"][0]["clientId"])
        self.assertEqual(
            "localendpoint-agent", payload["clients"][0]["canonicalAgentId"]
        )
        self.assertEqual(list(REQUESTED_SCOPES), payload["clients"][0]["requestedScopes"])
        self.assertEqual(SCOPE_DIGEST, payload["clients"][0]["scopeDigest"])
        self.assertEqual(list(REQUESTED_SCOPES), payload["requestedScopes"])
        self.assertEqual(SCOPE_DIGEST, payload["scopeDigest"])
        root = payload["serviceRoot"]
        self.assertEqual(ISSUER, root["exact"])
        for rule in ("userinfoAllowed", "nonDefaultPortAllowed", "queryAllowed", "fragmentAllowed"):
            self.assertFalse(root[rule])
        self.assertEqual("operating_system_default", payload["transport"]["tlsValidation"])
        self.assertTrue(payload["transport"]["noRedirectsForApiEndpoints"])
        self.assertEqual(32768, payload["transport"]["maximumJsonRequestBytes"])
        self.assertEqual(JSON_LIMIT, payload["transport"]["maximumJsonResponseBytes"])
        self.assertEqual(16384, payload["transport"]["maximumDiscoveryResponseBytes"])
        self.assertFalse(payload["transport"]["credentialsInUrlsAllowed"])
        encoded = raw.decode("utf-8")
        self.assertNotIn(self.company_id, encoded)
        self.assertNotIn(self.workspace_id, encoded)
        self.assertIsNone(GOVERNED_SECRET.search(encoded))

    def test_one_time_secret_response_bound_measures_final_wrapper_payload(self):
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        def oversized_wrapper(data):
            payload = dict(data)
            payload.update(
                {
                    "credentialDeliveredToAuthorizedRecipient": True,
                    "rawCredentialPersisted": False,
                    "showCredentialOnce": True,
                    "wrapperExpansion": "x" * JSON_LIMIT,
                }
            )
            return payload

        with patch.object(
            app_module, "one_time_secret_payload", side_effect=oversized_wrapper
        ):
            raw = b"".join(
                app_module._connector_one_time_secret(
                    start_response,
                    {"ok": True, "oneTimeValue": "must-not-be-reflected"},
                )
            )
        payload = json.loads(raw.decode("utf-8"))
        self._assert_json(
            503,
            captured["headers"],
            raw,
            expected_status=503,
        )
        self.assertEqual("503 Service Unavailable", captured["status"])
        self.assertEqual("connector_service_unavailable", payload["error"]["code"])
        self.assertNotIn("oneTimeValue", payload)
        self.assertNotIn("must-not-be-reflected", raw.decode("utf-8"))

    def test_every_connector_success_response_matches_recursive_strict_openapi_schema(self):
        captures = []

        def capture(label, schema_name, response, expected_status):
            status, headers, payload, raw = response
            self._assert_json(status, headers, raw, expected_status)
            captures.append((label, schema_name, payload))
            return payload

        def switch_company_context(suffix):
            setup = self.store.create_free_account(
                "Strict Workspace " + suffix,
                "Strict Company " + suffix,
                "Strict Project " + suffix,
            )
            (
                self.workspace_id,
                self.master_key_id,
                self.master_token,
                self.account_id,
                self.company_id,
                self.project_id,
                _recovery_secret,
            ) = setup
            self.password = secrets.token_urlsafe(36)
            proof = self.store.create_company_master_proof(self.master_token)
            username = "strict-owner-" + suffix
            created = self.store.create_human_account(
                username, self.password, proof["masterProofSecret"]
            )
            self.assertTrue(created["ok"], created)
            session = self.store.login_human_account(username, self.password)
            memberships = self.store.list_human_company_memberships(
                session["sessionSecret"]
            )
            selected = self.store.select_human_company_membership(
                session["sessionSecret"], memberships["items"][0]["authorityId"]
            )
            reauthenticated = self.store.reauthenticate_human_account_session(
                selected["sessionSecret"], self.password
            )
            self.human_session_secret = reauthenticated.get("sessionSecret") or selected[
                "sessionSecret"
            ]
            self.human_csrf = reauthenticated.get("csrfToken") or selected["csrfToken"]

        request, verifier, _state = self._start_request()
        captures.append(
            (
                "pairing request 201",
                "ConnectorPairingRequestResult",
                self._last_pairing_request_result,
            )
        )
        pending = capture(
            "authorization claim 202",
            "ConnectorAuthorizationCodeClaimPending",
            self._claim_response(request, "strict-contract-pending"),
            202,
        )
        self.assertFalse(pending["idempotencyKeyReserved"])
        approval, _code, _callback_state = self._approve(request, claim=False)
        captures.append(("human approval 200", "ConnectorApprovalResult", approval))
        claim, code = self._claim_code(request, key="strict-contract-claim")
        captures.append(
            ("authorization claim 200", "ConnectorAuthorizationCodeClaimResult", claim)
        )
        exchange, secret = self._exchange(
            code, verifier, key="strict-contract-exchange"
        )
        captures.append(("token exchange 201", "ConnectorTokenExchangeResult", exchange))
        pairing_id = exchange["pairing"]["pairingId"]
        activation = self._activate(
            pairing_id, secret, key="strict-contract-activation"
        )
        captures.append(("pairing activation 200", "ConnectorPairingMutationResult", activation))

        capture(
            "pairing readback 200",
            "ConnectorPairingVerification",
            call_api(
                "/api/matm/connector-pairings/%s" % pairing_id,
                token=secret,
            ),
            200,
        )
        inventory = capture(
            "credential inventory 200",
            "ConnectorCredentialListResult",
            call_api(
                "/api/matm/connector-pairings/%s/credentials" % pairing_id,
                token=secret,
            ),
            200,
        )
        self.assertNotIn("valuesRedacted", inventory["items"][0])
        self.assertNotIn("rawCredentialExposed", inventory["items"][0])
        capture(
            "connector self readback 200",
            "ConnectorSelfReadbackResult",
            call_api("/api/matm/me", token=secret),
            200,
        )
        capture(
            "workspace readback 200",
            "ConnectorWorkspaceReadbackResult",
            call_api("/api/matm/workspace", token=secret),
            200,
        )
        capture(
            "self registration 200",
            "ConnectorAgentRegistrationResult",
            call_api(
                "/api/matm/agents/register",
                "POST",
                {"schemaVersion": SCHEMA},
                secret,
                extra_headers=self._idempotency_headers("strict-contract-register"),
            ),
            200,
        )
        capture(
            "public-safe submit 201",
            "ConnectorPublicSafeMemoryResult",
            call_api(
                "/api/matm/memory-events/submit",
                "POST",
                {
                    "schemaVersion": SCHEMA,
                    "payloadClass": "public_safe",
                    "title": "Strict response contract",
                    "summary": "A synthetic public-safe item used only for response schema verification.",
                    "tags": ["connector-contract"],
                },
                secret,
                extra_headers=self._idempotency_headers("strict-contract-submit"),
            ),
            201,
        )
        capture(
            "memory search 200",
            "ConnectorSearchResult",
            call_api(
                "/api/matm/search",
                "POST",
                {"schemaVersion": SCHEMA, "query": "Strict response", "limit": 10},
                secret,
            ),
            200,
        )

        prepared = capture(
            "rotation prepare 201",
            "ConnectorRotationPrepareResult",
            call_api(
                "/api/matm/connector-pairings/%s/rotations" % pairing_id,
                "POST",
                {"schemaVersion": SCHEMA, "reason": "strict_contract_rotation"},
                secret,
                extra_headers=self._idempotency_headers("strict-contract-rotation"),
            ),
            201,
        )
        successor = prepared["connectorCredentialSecret"]
        rotation_id = prepared["rotation"]["rotationId"]
        capture(
            "rotation activation 200",
            "ConnectorRotationActivationResult",
            call_api(
                "/api/matm/connector-pairings/%s/rotations/%s/activate"
                % (pairing_id, rotation_id),
                "POST",
                {"schemaVersion": SCHEMA},
                successor,
                extra_headers=self._idempotency_headers(
                    "strict-contract-rotation-activate"
                ),
            ),
            200,
        )
        capture(
            "disconnect 200",
            "ConnectorPairingMutationResult",
            call_api(
                "/api/matm/connector-pairings/%s/disconnect" % pairing_id,
                "POST",
                {"schemaVersion": SCHEMA, "reason": "strict_contract_disconnect"},
                successor,
                extra_headers=self._idempotency_headers(
                    "strict-contract-disconnect"
                ),
            ),
            200,
        )

        human_cancel_request, _verifier, _state = self._start_request()
        human_cancel = capture(
            "human cancellation 200",
            "ConnectorPairingRequestMutationResult",
            call_api(
                "/api/matm/human/connector-pairings/%s/cancel"
                % human_cancel_request["publicRequestRef"],
                "POST",
                {"schemaVersion": SCHEMA, "reason": "strict_contract_cancel"},
                extra_headers=self._human_mutation_headers(
                    "strict-contract-human-cancel"
                ),
            ),
            200,
        )
        self.assertNotIn("expiresInSeconds", human_cancel["pairingRequest"])

        switch_company_context("cancel")
        cancel_request, cancel_verifier, _state = self._start_request()
        _approval, cancel_code, _state = self._approve(cancel_request)
        cancel_exchange, cancel_secret = self._exchange(
            cancel_code, cancel_verifier, key="strict-contract-cancel-exchange"
        )
        capture(
            "pending pairing cancellation 200",
            "ConnectorPairingMutationResult",
            call_api(
                "/api/matm/connector-pairings/%s/cancel"
                % cancel_exchange["pairing"]["pairingId"],
                "POST",
                {"schemaVersion": SCHEMA, "reason": "secure_store_failed"},
                cancel_secret,
                extra_headers=self._idempotency_headers(
                    "strict-contract-pending-cancel"
                ),
            ),
            200,
        )

        switch_company_context("revoke")
        revoke_pairing_id, _revoke_secret, _exchange = self._pair_active()
        capture(
            "company-master revocation 200",
            "ConnectorPairingMutationResult",
            call_api(
                "/api/matm/connector-pairings/%s/revoke" % revoke_pairing_id,
                "POST",
                {"schemaVersion": SCHEMA, "reason": "strict_contract_revoke"},
                self.master_token,
                extra_headers=self._idempotency_headers("strict-contract-revoke"),
            ),
            200,
        )

        openapi_response = call_api("/api/matm/openapi.json")
        self.assertEqual(200, openapi_response[0], openapi_response[2])
        specification = openapi_response[2]
        schemas = specification["components"]["schemas"]
        for label, schema_name, payload in captures:
            self.assertIn(schema_name, schemas, label)
            self._assert_strict_openapi_shape(
                payload, schemas[schema_name], schemas, label
            )

        for label, schema_name, payload in captures:
            if schema_name in {
                "ConnectorPairingRequestResult",
                "ConnectorAuthorizationCodeClaimResult",
                "ConnectorTokenExchangeResult",
                "ConnectorRotationPrepareResult",
            }:
                self.assertTrue(payload["credentialDeliveredToAuthorizedRecipient"], label)
                self.assertFalse(payload["rawCredentialPersisted"], label)
                self.assertTrue(payload["showCredentialOnce"], label)
                self.assertNotIn("rawCredentialExposed", payload, label)

        expected_route_refs = {
            ("/api/matm/connector-pairings/requests", "post", "201"): "ConnectorPairingRequestResult",
            ("/api/matm/connector-pairings/authorization-code-claims", "post", "200"): "ConnectorAuthorizationCodeClaimResult",
            ("/api/matm/connector-pairings/authorization-code-claims", "post", "202"): "ConnectorAuthorizationCodeClaimPending",
            ("/api/matm/connector-pairings/token", "post", "201"): "ConnectorTokenExchangeResult",
            ("/api/matm/human/connector-pairings/{publicRequestRef}/approve", "post", "200"): "ConnectorApprovalResult",
            ("/api/matm/human/connector-pairings/{publicRequestRef}/cancel", "post", "200"): "ConnectorPairingRequestMutationResult",
            ("/api/matm/human/connector-pairings/{publicRequestRef}/company-selection", "post", "200"): "ConnectorCompanySelectionResult",
            ("/api/matm/connector-pairings/{pairingId}", "get", "200"): "ConnectorPairingVerification",
            ("/api/matm/connector-pairings/{pairingId}/credentials", "get", "200"): "ConnectorCredentialListResult",
            ("/api/matm/connector-pairings/{pairingId}/activate", "post", "200"): "ConnectorPairingMutationResult",
            ("/api/matm/connector-pairings/{pairingId}/rotations", "post", "201"): "ConnectorRotationPrepareResult",
            ("/api/matm/connector-pairings/{pairingId}/rotations/{rotationId}/activate", "post", "200"): "ConnectorRotationActivationResult",
            ("/api/matm/connector-pairings/{pairingId}/revoke", "post", "200"): "ConnectorPairingMutationResult",
            ("/api/matm/connector-pairings/{pairingId}/disconnect", "post", "200"): "ConnectorPairingMutationResult",
            ("/api/matm/connector-pairings/{pairingId}/cancel", "post", "200"): "ConnectorPairingMutationResult",
            ("/api/matm/me", "get", "200"): "ConnectorSelfReadbackResult",
            ("/api/matm/workspace", "get", "200"): "ConnectorWorkspaceReadbackResult",
            ("/api/matm/agents/register", "post", "200"): "ConnectorAgentRegistrationResult",
            ("/api/matm/memory-events/submit", "post", "201"): "ConnectorPublicSafeMemoryResult",
            ("/api/matm/search", "post", "200"): "ConnectorSearchResult",
        }
        for (path, method, status), expected_schema in expected_route_refs.items():
            response_schema = specification["paths"][path][method]["responses"][status][
                "content"
            ]["application/json"]["schema"]
            self.assertIn(
                expected_schema,
                self._schema_refs(response_schema),
                "%s %s %s" % (method.upper(), path, status),
            )

        self._assert_connector_audit_identifier_free(
            {
                "connector_pairing.request",
                "connector_pairing.approve",
                "connector_pairing.authorization_code_claim",
                "connector_pairing.exchange",
                "connector_pairing.activate",
                "connector_pairing.rotation_prepare",
                "connector_pairing.rotation_activate",
                "connector_pairing.disconnect",
                "connector_pairing.request_cancel",
                "connector_pairing.cancel",
                "connector_pairing.revoke",
            }
        )

    def test_happy_path_is_crash_safe_and_exact_readback_proves_scope(self):
        request, verifier, state = self._start_request()
        self.assertEqual(0, self._agent_registration_count("localendpoint-agent"))
        _approval, code, callback_state = self._approve(request)
        self.assertEqual(state, callback_state)
        self.assertEqual(0, self._agent_registration_count("localendpoint-agent"))

        exchange_key = "lost-response-exchange"
        first, secret = self._exchange(code, verifier, exchange_key)
        retry, retry_secret = self._exchange(code, verifier, exchange_key)
        self.assertEqual(first["pairing"], retry["pairing"])
        self.assertTrue(secrets.compare_digest(secret, retry_secret))
        self.assertEqual(0, self._agent_registration_count("localendpoint-agent"))
        self._assert_secret_not_persisted(secret)

        pairing_id = first["pairing"]["pairingId"]
        activate_key = "lost-response-activation"
        activated = self._activate(pairing_id, secret, activate_key)
        activated_retry = self._activate(pairing_id, secret, activate_key)
        self.assertEqual(activated["pairing"], activated_retry["pairing"])
        self.assertEqual(1, self._agent_registration_count("localendpoint-agent"))

        status, headers, readback, raw = call_api(
            "/api/matm/connector-pairings/%s" % pairing_id,
            token=secret,
        )
        self._assert_json(status, headers, raw, 200)
        pairing = readback["pairing"]
        self.assertEqual("active", pairing["status"])
        self.assertEqual(first["pairing"]["credentialId"], pairing["credentialId"])
        self.assertEqual(self.workspace_id, pairing["workspace"]["workspaceId"])
        self.assertEqual("localendpoint-agent", pairing["agent"]["agentId"])
        grant = pairing["grant"]
        self.assertEqual("connector_agent", grant["credentialType"])
        self.assertEqual("agent", grant["scopeType"])
        self.assertEqual(self.workspace_id, grant["workspaceId"])
        self.assertEqual("localendpoint-agent", grant["agentId"])
        self.assertTrue(grant["active"])
        self.assertFalse(grant["revoked"])
        self.assertEqual(list(REQUESTED_SCOPES), grant["approvedScopes"])
        self.assertEqual(SCOPE_DIGEST, grant["scopeDigest"])
        self.assertEqual(list(REQUESTED_SCOPES), pairing["approvedScopes"])
        self.assertEqual(SCOPE_DIGEST, pairing["scopeDigest"])
        verification = readback["verification"]
        self.assertTrue(verification["canonicalWorkspaceReadable"])
        self.assertTrue(verification["canonicalWorkspaceIdMatches"])
        self.assertTrue(verification["exactAgentReadable"])
        self.assertTrue(verification["exactAgentIdMatches"])
        self.assertTrue(verification["credentialScopedToConnectorAndAgent"])
        self.assertTrue(verification["grantActive"])
        self.assertFalse(verification["grantRevoked"])
        self.assertFalse(verification["rawCredentialExposed"])
        self.assertFalse(verification["privatePayloadExposed"])
        self._assert_receipt(
            readback, "verify", "verified", False, SCOPE_DIGEST
        )
        self._assert_redacted_metadata(readback)

        status, _headers, me, _raw = call_api("/api/matm/me", token=secret)
        self.assertEqual(200, status, me)
        self.assertEqual("connector_agent", me["principal"]["credentialType"])
        self.assertFalse(me["principal"]["ordinaryAgentCredential"])
        self.assertEqual("localendpoint-agent", me["principal"]["agentId"])
        self.assertEqual(self.workspace_id, me["principal"]["resourceContext"]["workspaceId"])
        self.assertEqual(list(REQUESTED_SCOPES), me["principal"]["approvedScopes"])
        self.assertEqual(SCOPE_DIGEST, me["principal"]["scopeDigest"])

        workspace_status = call_api(
            "/api/matm/workspace",
            token=secret,
        )
        self._assert_json(
            workspace_status[0], workspace_status[1], workspace_status[3], 200
        )
        self.assertEqual(self.workspace_id, workspace_status[2]["workspace"]["workspaceId"])
        self.assertEqual(SCOPE_DIGEST, workspace_status[2]["scopeDigest"])
        self.assertTrue(workspace_status[2]["connectorBoundedReadback"])

        inventory = call_api(
            "/api/matm/connector-pairings/%s/credentials" % pairing_id,
            token=secret,
        )
        self._assert_json(inventory[0], inventory[1], inventory[3], 200)
        self.assertEqual(1, inventory[2]["count"])
        self.assertEqual(
            list(REQUESTED_SCOPES), inventory[2]["items"][0]["approvedScopes"]
        )
        self.assertEqual(SCOPE_DIGEST, inventory[2]["items"][0]["scopeDigest"])
        denied_coordination = call_api(
            "/api/matm/current-message",
            token=secret,
            query="workspace_id=%s&agent_id=another-agent" % self.workspace_id,
        )
        self._assert_error(
            denied_coordination, 403, "connector_scope_forbidden", (secret,)
        )

    def test_connector_scopes_allow_only_self_confirmation_public_safe_submit_and_search(self):
        pairing_id, secret, _exchange = self._pair_active()

        registration_body = {"schemaVersion": SCHEMA}
        self._assert_error(
            call_api(
                "/api/matm/agents/register",
                "POST",
                registration_body,
                secret,
            ),
            422,
            "idempotency_key_required",
        )
        registration_headers = self._idempotency_headers("confirm-prebound-agent")
        registered = call_api(
            "/api/matm/agents/register",
            "POST",
            registration_body,
            secret,
            extra_headers=registration_headers,
        )
        self._assert_json(registered[0], registered[1], registered[3], 200)
        self.assertEqual(
            {
                "ok",
                "schemaVersion",
                "registration",
                "alreadyRegistered",
                "idempotentReplay",
                "approvedScopes",
                "scopeDigest",
                "receipt",
                "valuesRedacted",
                "rawCredentialExposed",
                "rawPayloadExposed",
            },
            set(registered[2]),
        )
        self.assertTrue(registered[2]["alreadyRegistered"])
        self.assertTrue(registered[2]["idempotentReplay"])
        self.assertEqual(list(REQUESTED_SCOPES), registered[2]["approvedScopes"])
        self.assertEqual(SCOPE_DIGEST, registered[2]["scopeDigest"])
        self._assert_scoped_operation_receipt(registered[2])
        confirmation = registered[2]["registration"]
        self.assertEqual("already_registered", confirmation["status"])
        self.assertEqual(self.workspace_id, confirmation["workspaceId"])
        self.assertEqual("localendpoint-agent", confirmation["agentId"])
        self.assertFalse(confirmation["created"])
        self.assertEqual(SCOPE_DIGEST, confirmation["scopeDigest"])
        registration_retry = call_api(
            "/api/matm/agents/register",
            "POST",
            registration_body,
            secret,
            extra_headers=registration_headers,
        )
        self.assertEqual(200, registration_retry[0], registration_retry[2])
        self.assertEqual(
            confirmation, registration_retry[2]["registration"]
        )
        self.assertTrue(registration_retry[2]["idempotentReplay"])
        self.assertEqual(
            registered[2]["receipt"]["receiptId"],
            registration_retry[2]["receipt"]["receiptId"],
        )

        submit_body = {
            "schemaVersion": SCHEMA,
            "payloadClass": "public_safe",
            "title": "LocalEndpoint public-safe connection note",
            "summary": "LocalEndpoint confirmed a connector-scoped memory write.",
            "tags": ["localendpoint", "connector"],
        }
        submit_headers = self._idempotency_headers("connector-public-safe-submit")
        self._assert_error(
            call_api(
                "/api/matm/memory-events/submit",
                "POST",
                submit_body,
                secret,
            ),
            422,
            "idempotency_key_required",
        )
        submitted = call_api(
            "/api/matm/memory-events/submit",
            "POST",
            submit_body,
            secret,
            extra_headers=submit_headers,
        )
        self._assert_json(submitted[0], submitted[1], submitted[3], 201)
        self.assertEqual(
            {
                "ok",
                "schemaVersion",
                "memory",
                "actorBinding",
                "idempotentReplay",
                "approvedScopes",
                "scopeDigest",
                "receipt",
                "valuesRedacted",
                "rawCredentialExposed",
                "rawPayloadExposed",
            },
            set(submitted[2]),
        )
        memory = submitted[2]["memory"]
        self.assertEqual("localendpoint-agent", memory["actorAgentId"])
        self.assertEqual(self.workspace_id, memory["workspaceId"])
        self.assertEqual("workspace", memory["scope"])
        self.assertEqual("connector_self", submitted[2]["actorBinding"])
        self.assertEqual(list(REQUESTED_SCOPES), submitted[2]["approvedScopes"])
        self.assertEqual(SCOPE_DIGEST, submitted[2]["scopeDigest"])
        self._assert_scoped_operation_receipt(submitted[2])
        self._assert_redacted_metadata(submitted[2])
        submit_retry = call_api(
            "/api/matm/memory-events/submit",
            "POST",
            submit_body,
            secret,
            extra_headers=submit_headers,
        )
        self.assertEqual(201, submit_retry[0], submit_retry[2])
        self.assertTrue(submit_retry[2]["idempotentReplay"])
        self.assertEqual(memory, submit_retry[2]["memory"])
        self.assertEqual(
            submitted[2]["receipt"]["receiptId"],
            submit_retry[2]["receipt"]["receiptId"],
        )
        changed_submit = dict(
            submit_body,
            summary="A changed body cannot reuse the connector submit key.",
        )
        self._assert_error(
            call_api(
                "/api/matm/memory-events/submit",
                "POST",
                changed_submit,
                secret,
                extra_headers=submit_headers,
            ),
            409,
            "idempotency_conflict",
            (memory["memoryId"],),
        )

        search_path = "/api/matm/search"
        search_body = {
            "schemaVersion": SCHEMA,
            "query": "LocalEndpoint",
            "limit": 10,
        }
        for forbidden in (
            self.workspace_id,
            self.company_id,
            self.project_id,
            "localendpoint-agent",
            *REQUESTED_SCOPES,
        ):
            self.assertNotIn(forbidden, search_path)
        searched = call_api(search_path, "POST", search_body, secret)
        self._assert_json(searched[0], searched[1], searched[3], 200)
        self.assertEqual(
            {
                "ok",
                "schemaVersion",
                "items",
                "count",
                "limit",
                "readOnly",
                "approvedScopes",
                "scopeDigest",
                "receipt",
                "valuesRedacted",
                "rawCredentialExposed",
                "rawPayloadExposed",
            },
            set(searched[2]),
        )
        self.assertEqual(10, searched[2]["limit"])
        self.assertEqual(list(REQUESTED_SCOPES), searched[2]["approvedScopes"])
        self.assertEqual(SCOPE_DIGEST, searched[2]["scopeDigest"])
        self.assertTrue(searched[2]["readOnly"])
        self._assert_scoped_operation_receipt(searched[2])
        self.assertTrue(
            any(item.get("memoryId") == memory["memoryId"] for item in searched[2]["items"])
        )
        invalid_search_bodies = (
            {"schemaVersion": SCHEMA, "query": "LocalEndpoint"},
            {"schemaVersion": SCHEMA, "query": "", "limit": 10},
            {"schemaVersion": SCHEMA, "query": "LocalEndpoint", "limit": 0},
            {"schemaVersion": SCHEMA, "query": "LocalEndpoint", "limit": 51},
            {"schemaVersion": SCHEMA, "query": "LocalEndpoint", "limit": 1.5},
            dict(search_body, workspaceId=self.workspace_id),
        )
        for invalid in invalid_search_bodies:
            with self.subTest(invalidSearch=invalid):
                self._assert_error(
                    call_api(search_path, "POST", invalid, secret),
                    422,
                    "invalid_request",
                )
        self._assert_error(
            call_api(
                search_path,
                "POST",
                search_body,
                secret,
                extra_headers=self._idempotency_headers(
                    "read-only-search-must-not-use-idempotency"
                ),
            ),
            422,
            "idempotency_key_not_allowed",
        )

        status = call_api(
            "/api/matm/connector-pairings/%s" % pairing_id, token=secret
        )
        self.assertEqual(200, status[0], status[2])
        self.assertEqual(SCOPE_DIGEST, status[2]["pairing"]["scopeDigest"])

    def test_connector_public_safe_submit_rejects_private_raw_or_actor_supplied_payloads(self):
        _pairing_id, secret, _exchange = self._pair_active()
        invalid_payloads = (
            {
                "schemaVersion": SCHEMA,
                "payloadClass": "public_safe",
                "title": "Caller-selected actor",
                "summary": "The connector must derive its own actor.",
                "actorAgentId": "another-agent",
            },
            {
                "schemaVersion": SCHEMA,
                "payloadClass": "public_safe",
                "title": "Raw private body",
                "summary": "A public-safe summary cannot carry a raw payload.",
                "privatePayload": {"raw": "must-never-be-stored"},
            },
            {
                "schemaVersion": SCHEMA,
                "payloadClass": "public_safe",
                "title": "Credential-shaped content",
                "summary": "password=synthetic-private-secret-value",
            },
            {
                "schemaVersion": SCHEMA,
                "payloadClass": "public_safe",
                "title": "Scope escalation",
                "summary": "A connector cannot select a broader scope.",
                "scope": "company",
            },
        )
        for index, body in enumerate(invalid_payloads):
            with self.subTest(payload=index):
                response = call_api(
                    "/api/matm/memory-events/submit",
                    "POST",
                    body,
                    secret,
                    extra_headers=self._idempotency_headers(
                        "invalid-connector-public-safe-payload-%02d" % index
                    ),
                )
                self._assert_error(
                    response,
                    422,
                    "connector_public_safe_payload_required",
                    ("must-never-be-stored", "synthetic-private-secret-value"),
                )

    def test_connector_scope_threat_model_denies_every_unlisted_surface_before_validation(self):
        _pairing_id, secret, _exchange = self._pair_active()
        denied_reads = (
            "/api/matm/projects",
            "/api/matm/knowledge-tree",
            "/api/matm/knowledge-documents",
            "/api/matm/external-links",
            "/api/matm/internet-search",
            "/api/matm/memory-events",
            "/api/matm/search",
            "/api/matm/review-queue",
            "/api/matm/meeting-rooms",
            "/api/matm/meeting-messages",
            "/api/matm/routing-decisions",
            "/api/matm/current-message",
            "/api/matm/agent-inbox",
            "/api/matm/receipts",
            "/api/matm/audit-log",
            "/api/matm/uai-memory/packages",
            "/api/matm/uai-memory/startup",
            "/api/matm/uai-memory/file-heads",
            "/api/matm/uai-memory/edit-claims",
            "/api/matm/sync/receipts",
            "/api/matm/sync/changes",
            "/api/matm/sync/heads",
            "/api/matm/sync/retention",
            "/api/matm/access/scope-catalog",
            "/api/matm/access/agent-name-requests",
            "/api/matm/access/invites",
            "/api/matm/access/agent-tokens",
            "/api/matm/access/company-master-credentials",
            "/api/matm/human/company-memberships",
            "/api/matm/human/companies/%s/history" % self.company_id,
            "/api/matm/human/companies/%s/export-plan" % self.company_id,
        )
        for path in denied_reads:
            with self.subTest(method="GET", path=path):
                self._assert_error(
                    call_api(path, token=secret),
                    403,
                    "connector_scope_forbidden",
                    (secret,),
                )

        denied_mutations = (
            "/api/matm/projects",
            "/api/matm/knowledge-documents/upsert",
            "/api/matm/external-links/upsert",
            "/api/matm/review-queue/decide",
            "/api/matm/meeting-rooms",
            "/api/matm/meeting-messages",
            "/api/matm/meeting-messages/promote",
            "/api/matm/meeting-rooms/read",
            "/api/matm/routing-decisions",
            "/api/matm/agent-messages",
            "/api/matm/notifications/ack",
            "/api/matm/uai-memory/packages",
            "/api/matm/uai-memory/records",
            "/api/matm/uai-memory/edit-claims",
            "/api/matm/sync/devices",
            "/api/matm/sync/mutations",
            "/api/matm/access/agent-name-requests",
            "/api/matm/access/invites",
            "/api/matm/access/company-master-credentials",
            "/api/matm/human/companies/%s/exports" % self.company_id,
            "/api/matm/human/companies/%s/history/clear" % self.company_id,
        )
        for index, path in enumerate(denied_mutations):
            with self.subTest(method="POST", path=path):
                self._assert_error(
                    call_raw(
                        path,
                        "POST",
                        b"{not-json",
                        secret,
                        extra_headers=self._idempotency_headers(
                            "connector-denied-mutation-%02d" % index
                        ),
                    ),
                    403,
                    "connector_scope_forbidden",
                    (secret, "not-json"),
                )

        self._assert_error(
            call_api(
                "/api/matm/agents/register",
                "POST",
                {"schemaVersion": SCHEMA, "agentId": "another-agent"},
                secret,
                extra_headers=self._idempotency_headers(
                    "connector-cannot-select-agent"
                ),
            ),
            403,
            "connector_scope_forbidden",
            (secret, "another-agent"),
        )

    def test_approval_wakeup_is_parameter_free_and_claim_retry_rederives_code(self):
        state = secrets.token_urlsafe(40)
        request, _verifier, original_state = self._start_request(state=state)
        approval_key = "lost-response-human-approval"
        approval, _code, _callback_state = self._approve(
            request, key=approval_key, claim=False
        )
        self.assertEqual(REDIRECT_URI, approval["wakeUpUrl"])
        self.assertNotIn("?", approval["wakeUpUrl"])
        self.assertNotIn("#", approval["wakeUpUrl"])
        encoded_approval = json.dumps(approval, sort_keys=True)
        for forbidden in (
            original_state,
            self._claim_material[request["publicRequestRef"]]["pairingRequestProof"],
            self.company_id,
            self.workspace_id,
            self.project_id,
            self._internal_request_id(request),
            "authorizationCode",
            "callbackUrl",
        ):
            self.assertNotIn(forbidden, encoded_approval)
        retry_headers = self._human_headers()
        retry_headers.update(self._idempotency_headers(approval_key))
        retry = call_api(
            "/api/matm/human/connector-pairings/%s/approve"
            % request["publicRequestRef"],
            "POST",
            {
                "schemaVersion": SCHEMA,
                "canonicalAgentApproved": True,
                "approvedScopes": list(REQUESTED_SCOPES),
                "workspaceSelection": {
                    "mode": "existing",
                    "workspaceRef": self._existing_workspace_ref(request),
                },
            },
            extra_headers=retry_headers,
        )
        self.assertEqual(200, retry[0], retry[2])
        self.assertTrue(retry[2]["idempotentReplay"])
        self.assertEqual(approval["wakeUpUrl"], retry[2]["wakeUpUrl"])
        self.assertEqual(approval["receipt"]["receiptId"], retry[2]["receipt"]["receiptId"])
        self.assertTrue(retry[2]["receipt"]["idempotentReplay"])

        claim_key = "lost-response-authorization-claim"
        claimed, code = self._claim_code(request, key=claim_key)
        claimed_retry, retry_code = self._claim_code(request, key=claim_key)
        self.assertTrue(claimed_retry["idempotentReplay"])
        self.assertEqual(claimed["receipt"]["receiptId"], claimed_retry["receipt"]["receiptId"])
        self.assertTrue(secrets.compare_digest(code, retry_code))

    def test_workspace_ref_is_request_and_human_session_bound(self):
        first, _verifier, _state = self._start_request()
        first_ref = self._existing_workspace_ref(first)
        second, _verifier, _state = self._start_request()
        approval_body = {
            "schemaVersion": SCHEMA,
            "canonicalAgentApproved": True,
            "approvedScopes": list(REQUESTED_SCOPES),
            "workspaceSelection": {"mode": "existing", "workspaceRef": first_ref},
        }
        self._assert_error(
            call_api(
                "/api/matm/human/connector-pairings/%s/approve"
                % second["publicRequestRef"],
                "POST",
                approval_body,
                extra_headers=self._human_mutation_headers(
                    "foreign-request-workspace-ref"
                ),
            ),
            401,
            "workspace_ref_invalid",
            (first_ref, self.workspace_id),
        )

        other_session = self._new_selected_human_session()
        other_headers = {
            "HTTP_COOKIE": "__Host-memoryendpoints-human="
            + other_session["sessionSecret"],
            "HTTP_X_CSRF_TOKEN": other_session["csrfToken"],
            "HTTP_ORIGIN": SITE_ORIGIN,
            "HTTP_SEC_FETCH_SITE": "same-origin",
            "HTTP_SEC_FETCH_MODE": "cors",
            "HTTP_SEC_FETCH_DEST": "empty",
        }
        other_headers.update(self._idempotency_headers("foreign-session-workspace-ref"))
        self._assert_error(
            call_api(
                "/api/matm/human/connector-pairings/%s/approve"
                % first["publicRequestRef"],
                "POST",
                approval_body,
                extra_headers=other_headers,
            ),
            401,
            "workspace_ref_invalid",
            (first_ref, self.workspace_id),
        )

        approved, _code, _state = self._approve(
            first,
            body=approval_body,
            key="own-session-workspace-ref",
            claim=False,
        )
        self.assertEqual("approved_awaiting_connector_claim", approved["approval"]["status"])

    def test_pending_claim_does_not_reserve_idempotency_key_and_approval_releases_code(self):
        request, _verifier, state = self._start_request()
        claim_key = "pending-then-approved-authorization-claim"
        pending = self._claim_response(request, claim_key)
        self._assert_json(pending[0], pending[1], pending[3], 202)
        self.assertEqual(SCHEMA, pending[2]["schemaVersion"])
        self.assertEqual("pending_human_approval", pending[2]["status"])
        self.assertEqual(state, self._claim_material[request["publicRequestRef"]]["state"])
        self.assertTrue(pending[2]["stateVerified"])
        self.assertEqual(list(REQUESTED_SCOPES), pending[2]["requestedScopes"])
        self.assertEqual(SCOPE_DIGEST, pending[2]["scopeDigest"])
        self.assertGreaterEqual(pending[2]["retryAfterSeconds"], 1)
        self.assertNotIn("authorizationCode", pending[2])
        self.assertFalse(pending[2]["idempotencyKeyReserved"])
        self._assert_receipt(
            pending[2],
            "authorization_code_claim",
            "pending_human_approval",
            False,
            SCOPE_DIGEST,
        )

        pending_retry = self._claim_response(request, claim_key)
        self.assertEqual(202, pending_retry[0], pending_retry[2])
        self.assertFalse(pending_retry[2]["idempotencyKeyReserved"])
        self._approve(request, claim=False)
        claimed, code = self._claim_code(request, key=claim_key)
        self.assertFalse(claimed["idempotentReplay"])
        self.assertNotEqual("", code)

    def test_claim_binding_is_fail_closed_without_revealing_which_value_failed(self):
        request, _verifier, _state = self._start_request()
        valid = self._claim_body(request)
        wrong_state = secrets.token_urlsafe(32)
        invalid_bindings = (
            (dict(valid, clientId="unknown-client"), "unknown-client"),
            (
                dict(
                    valid,
                    redirectUri="http://127.0.0.1:53683/memoryendpoints/callback",
                ),
                "http://127.0.0.1:53683/memoryendpoints/callback",
            ),
            (dict(valid, state=wrong_state), wrong_state),
            (
                dict(valid, pairingRequestProof="me_pairproof_v1.invalid.invalid"),
                "me_pairproof_v1.invalid.invalid",
            ),
        )
        for index, (invalid, changed_field) in enumerate(invalid_bindings):
            with self.subTest(binding=index):
                response = self._claim_response(
                    request,
                    "invalid-claim-binding-%02d" % index,
                    invalid,
                )
                self._assert_error(
                    response,
                    401,
                    "authorization_claim_invalid",
                    (changed_field,),
                )

    def test_claim_idempotency_conflicts_and_replay_are_stable(self):
        request, _verifier, _state = self._start_request()
        self._approve(request, claim=False)
        claim_key = "authorization-claim-one-use"
        first, code = self._claim_code(request, key=claim_key)

        changed = self._claim_body(request, state=secrets.token_urlsafe(32))
        self._assert_error(
            self._claim_response(request, claim_key, changed),
            409,
            "idempotency_conflict",
            (code, changed["state"]),
        )
        self._assert_error(
            self._claim_response(request, "authorization-claim-second-key"),
            409,
            "idempotency_conflict",
            (code,),
        )

        retry, retry_code = self._claim_code(request, key=claim_key)
        self.assertTrue(retry["idempotentReplay"])
        self.assertEqual(first["receipt"]["receiptId"], retry["receipt"]["receiptId"])
        self.assertTrue(secrets.compare_digest(code, retry_code))

    def test_claim_expiry_cancellation_and_redeemed_states_are_typed_safe_no_ops(self):
        expired_request, _verifier, _state = self._start_request()
        self._expire_pairing_request_phase(
            self._internal_request_id(expired_request), "request"
        )
        self._assert_error(
            self._claim_response(expired_request, "claim-expired-request"),
            410,
            "pairing_request_expired",
        )

        canceled_request, _verifier, _state = self._start_request()
        canceled = call_api(
            "/api/matm/human/connector-pairings/%s/cancel"
            % canceled_request["publicRequestRef"],
            "POST",
            {"schemaVersion": SCHEMA, "reason": "human_canceled_pairing"},
            extra_headers=self._human_mutation_headers("cancel-before-code-claim"),
        )
        self.assertEqual(200, canceled[0], canceled[2])
        self._assert_error(
            self._claim_response(canceled_request, "claim-canceled-request"),
            410,
            "pairing_request_canceled",
        )

        expired_code_request, _verifier, _state = self._start_request()
        self._approve(expired_code_request, claim=False)
        self._expire_pairing_request_phase(
            self._internal_request_id(expired_code_request), "code"
        )
        self._assert_error(
            self._claim_response(expired_code_request, "claim-expired-code"),
            410,
            "authorization_code_expired",
        )

        redeemed_request, verifier, _state = self._start_request()
        self._approve(redeemed_request, claim=False)
        claim_key = "claim-then-redeem-code"
        _claim, code = self._claim_code(redeemed_request, key=claim_key)
        self._exchange(code, verifier, "exchange-claimed-code")
        self._assert_error(
            self._claim_response(redeemed_request, claim_key),
            410,
            "authorization_code_redeemed",
            (code,),
        )

    def test_claim_requires_json_and_idempotency(self):
        request, _verifier, _state = self._start_request()
        claim = self._claim_body(request)
        self._assert_error(
            call_api(
                "/api/matm/connector-pairings/authorization-code-claims",
                "POST",
                claim,
            ),
            422,
            "idempotency_key_required",
        )
        self._assert_error(
            call_api(
                "/api/matm/connector-pairings/authorization-code-claims",
                "POST",
                claim,
                extra_headers={
                    "CONTENT_TYPE": "text/plain",
                    "HTTP_IDEMPOTENCY_KEY": "claim-text-content-type",
                },
            ),
            415,
            "json_content_type_required",
        )

    def test_claim_body_limit_precedes_schema_dispatch(self):
        request, _verifier, _state = self._start_request()
        oversized = dict(
            self._claim_body(request), padding="x" * REQUEST_BODY_LIMIT
        )
        self._assert_error(
            self._claim_response(request, "oversized-claim-request", oversized),
            413,
            "request_body_too_large",
        )

    def test_concurrent_claims_issue_exactly_one_code(self):
        request, _verifier, _state = self._start_request()
        self._approve(request, claim=False)

        def claim(index):
            return self._claim_response(
                request, "concurrent-authorization-claim-%d" % index
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(claim, (1, 2)))
        self.assertEqual([200, 409], sorted(item[0] for item in responses))
        winner = next(item for item in responses if item[0] == 200)
        loser = next(item for item in responses if item[0] == 409)
        self._assert_json(winner[0], winner[1], winner[3], 200)
        self.assertRegex(
            winner[2]["authorizationCode"],
            r"^me_paircode_v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$",
        )
        self._assert_error(
            loser,
            409,
            "idempotency_conflict",
            (winner[2]["authorizationCode"],),
        )
        self.assertNotIn("authorizationCode", loser[2])
        self._assert_secret_not_persisted(winner[2]["authorizationCode"])

    def test_pkce_validation_and_code_replay_rules_are_stable(self):
        request, verifier, _state = self._start_request()
        _approval, code, _callback_state = self._approve(request)
        wrong = self._exchange_response(code, secrets.token_urlsafe(48), "wrong-pkce")
        self._assert_error(wrong, 401, "pkce_verification_failed", (code, verifier))

        first, secret = self._exchange(code, verifier, "first-exchange")
        changed_digest = self._exchange_response(code, secrets.token_urlsafe(48), "first-exchange")
        self._assert_error(changed_digest, 409, "idempotency_conflict", (code, secret))
        replay = self._exchange_response(code, verifier, "different-exchange")
        self._assert_error(replay, 409, "authorization_code_already_exchanged", (code, secret))
        self._activate(first["pairing"]["pairingId"], secret)
        consumed = self._exchange_response(code, verifier, "first-exchange")
        self._assert_error(consumed, 410, "authorization_code_redeemed", (code, secret))

    def _exchange_response(self, code, verifier, key):
        return call_api(
            "/api/matm/connector-pairings/token",
            "POST",
            {
                "schemaVersion": SCHEMA,
                "grantType": "authorization_code",
                "clientId": CLIENT_ID,
                "redirectUri": REDIRECT_URI,
                "code": code,
                "codeVerifier": verifier,
            },
            extra_headers=self._idempotency_headers(key),
        )

    def test_request_validation_json_and_idempotency_are_safe_no_ops(self):
        body, _verifier, _state = self._request_body()
        missing = call_api("/api/matm/connector-pairings/requests", "POST", body)
        self._assert_error(missing, 422, "idempotency_key_required")

        text_plain = call_api(
            "/api/matm/connector-pairings/requests",
            "POST",
            body,
            extra_headers={
                "CONTENT_TYPE": "text/plain",
                "HTTP_IDEMPOTENCY_KEY": "text-plain-idempotency",
            },
        )
        self._assert_error(text_plain, 415, "json_content_type_required")

        for invalid_key in ("x", "x" * 15, "x" * 201, " padded-idempotency-key"):
            with self.subTest(idempotencyKeyLength=len(invalid_key)):
                self._assert_error(
                    call_api(
                        "/api/matm/connector-pairings/requests",
                        "POST",
                        body,
                        extra_headers={"HTTP_IDEMPOTENCY_KEY": invalid_key},
                    ),
                    422,
                    "idempotency_key_invalid",
                )

        for index, (extra_name, extra_value) in enumerate(
            (
                ("workspaceId", "must-not-be-accepted"),
                ("scopeDigest", SCOPE_DIGEST),
            )
        ):
            extra_body = dict(body)
            extra_body[extra_name] = extra_value
            self._assert_error(
                call_api(
                    "/api/matm/connector-pairings/requests",
                    "POST",
                    extra_body,
                    extra_headers=self._idempotency_headers(
                        "strict-extra-property-%02d" % index
                    ),
                ),
                422,
                "invalid_request",
            )

        invalid_cases = (
            ({"state": "short"}, "state_invalid"),
            ({"codeChallengeMethod": "plain"}, "pkce_method_unsupported"),
            ({"codeChallenge": "short"}, "pkce_challenge_invalid"),
            ({"clientId": "unknown-client"}, "connector_client_unsupported"),
            ({"redirectUri": "https://evil.example/callback"}, "redirect_uri_not_allowed"),
            ({"requestedAgentId": "not_human_friendly"}, "connector_agent_identity_invalid"),
            ({"requestedAgentId": "another-valid-agent"}, "connector_agent_identity_invalid"),
        )
        for index, (changes, code) in enumerate(invalid_cases):
            invalid = dict(body)
            invalid.update(changes)
            response = call_api(
                "/api/matm/connector-pairings/requests",
                "POST",
                invalid,
                extra_headers=self._idempotency_headers("invalid-case-%02d-connector" % index),
            )
            self._assert_error(response, 422, code)

        invalid_scope_sets = (
            [],
            list(reversed(REQUESTED_SCOPES)),
            list(REQUESTED_SCOPES[:-1]),
            list(REQUESTED_SCOPES) + [REQUESTED_SCOPES[-1]],
            list(REQUESTED_SCOPES) + ["meeting:rooms:read"],
            [
                "connector:self:readback",
                "agent:self:register",
                "memory:private:submit",
                "memory:search:read",
            ],
        )
        for index, requested_scopes in enumerate(invalid_scope_sets):
            with self.subTest(requestedScopes=requested_scopes):
                before = self._pairing_request_count()
                invalid = dict(body, requestedScopes=requested_scopes)
                response = call_api(
                    "/api/matm/connector-pairings/requests",
                    "POST",
                    invalid,
                    extra_headers=self._idempotency_headers(
                        "invalid-requested-scopes-%02d" % index
                    ),
                )
                self._assert_error(response, 422, "connector_scopes_invalid")
                self.assertEqual(before, self._pairing_request_count())

        key = "request-idempotency"
        request, request_verifier, request_state = self._start_request(key=key)
        retry_body, _ignored_verifier, _ignored_state = self._request_body(
            state=request_state,
            verifier=request_verifier,
        )
        exact_retry = call_api(
            "/api/matm/connector-pairings/requests",
            "POST",
            retry_body,
            extra_headers=self._idempotency_headers(key),
        )
        self.assertEqual(201, exact_retry[0], exact_retry[2])
        self.assertEqual(request, exact_retry[2]["pairingRequest"])
        self.assertTrue(exact_retry[2]["idempotentReplay"])
        self.assertTrue(
            secrets.compare_digest(
                self._claim_material[request["publicRequestRef"]][
                    "pairingRequestProof"
                ],
                exact_retry[2]["pairingRequestProof"],
            )
        )
        self.assertEqual(
            "/connect/authorize/" + request["publicRequestRef"],
            urlsplit(exact_retry[2]["authorizationUrl"]).path,
        )
        changed = dict(body)
        changed["state"] = secrets.token_urlsafe(32)
        conflict = call_api(
            "/api/matm/connector-pairings/requests",
            "POST",
            changed,
            extra_headers=self._idempotency_headers(key),
        )
        self._assert_error(
            conflict,
            409,
            "idempotency_conflict",
            (self._internal_request_id(request),),
        )


    def test_connector_request_body_limit_precedes_schema_dispatch(self):
        body, _verifier, _state = self._request_body()
        oversized = dict(body)
        oversized["padding"] = "x" * REQUEST_BODY_LIMIT
        self._assert_error(
            call_api(
                "/api/matm/connector-pairings/requests",
                "POST",
                oversized,
                extra_headers=self._idempotency_headers("oversized-request-body"),
            ),
            413,
            "request_body_too_large",
        )

    def test_every_connector_mutation_enforces_exact_versioned_body_schema(self):
        request, verifier, _state = self._start_request()
        approval_path = (
            "/api/matm/human/connector-pairings/%s/approve"
            % request["publicRequestRef"]
        )
        workspace_ref = self._existing_workspace_ref(request)
        valid_approval = {
            "schemaVersion": SCHEMA,
            "canonicalAgentApproved": True,
            "approvedScopes": list(REQUESTED_SCOPES),
            "workspaceSelection": {"mode": "existing", "workspaceRef": workspace_ref},
        }
        for invalid in (
            {key: value for key, value in valid_approval.items() if key != "schemaVersion"},
            dict(valid_approval, unexpected=True),
            dict(valid_approval, canonicalAgentApproved=False),
            dict(valid_approval, approvedScopes=list(REQUESTED_SCOPES[:-1])),
            dict(valid_approval, approvedScopes=list(reversed(REQUESTED_SCOPES))),
            dict(valid_approval, scopeDigest=SCOPE_DIGEST),
            dict(valid_approval, workspaceSelection={"mode": "existing", "workspaceRef": workspace_ref, "extra": True}),
            dict(valid_approval, workspaceSelection={"mode": "existing", "workspaceId": self.workspace_id}),
            dict(
                valid_approval,
                workspaceSelection={
                    "mode": "new",
                    "workspaceLabel": "LocalEndpoint Workspace",
                    "projectLabel": "LocalEndpoint Pairing",
                    "workspaceId": self.workspace_id,
                },
            ),
        ):
            self._assert_error(
                call_api(
                    approval_path,
                    "POST",
                    invalid,
                    extra_headers=self._human_mutation_headers(),
                ),
                422,
                "invalid_request" if invalid.get("schemaVersion") else "invalid_request",
            )
        _approval, code, _callback_state = self._approve(request, body=valid_approval)

        valid_claim = self._claim_body(request)
        for invalid in (
            {key: value for key, value in valid_claim.items() if key != "state"},
            dict(valid_claim, unexpected=True),
        ):
            self._assert_error(
                call_api(
                    "/api/matm/connector-pairings/authorization-code-claims",
                    "POST",
                    invalid,
                    extra_headers=self._idempotency_headers(),
                ),
                422,
                "invalid_request",
            )

        exchange_body = {
            "schemaVersion": SCHEMA,
            "grantType": "authorization_code",
            "clientId": CLIENT_ID,
            "redirectUri": REDIRECT_URI,
            "code": code,
            "codeVerifier": verifier,
        }
        self._assert_error(
            call_api(
                "/api/matm/connector-pairings/token",
                "POST",
                dict(exchange_body, unexpected=True),
                extra_headers=self._idempotency_headers(),
            ),
            422,
            "invalid_request",
        )
        exchange, secret = self._exchange(code, verifier)
        pairing_id = exchange["pairing"]["pairingId"]
        activation_path = "/api/matm/connector-pairings/%s/activate" % pairing_id
        for invalid in ({}, {"schemaVersion": SCHEMA, "unexpected": True}):
            self._assert_error(
                call_api(
                    activation_path,
                    "POST",
                    invalid,
                    secret,
                    extra_headers=self._idempotency_headers(),
                ),
                422,
                "invalid_request",
            )
        self._activate(pairing_id, secret)

        invalid_lifecycle_paths = (
            ("/api/matm/connector-pairings/%s/rotations" % pairing_id, secret),
            ("/api/matm/connector-pairings/%s/disconnect" % pairing_id, secret),
            ("/api/matm/connector-pairings/%s/revoke" % pairing_id, self.master_token),
            ("/api/matm/connector-pairings/%s/cancel" % pairing_id, secret),
        )
        for action_path, token in invalid_lifecycle_paths:
            with self.subTest(path=action_path):
                self._assert_error(
                    call_api(
                        action_path,
                        "POST",
                        {"schemaVersion": SCHEMA},
                        token,
                        extra_headers=self._idempotency_headers(),
                    ),
                    422,
                    "invalid_request",
                )
        self.assertEqual(200, call_api(activation_path.rsplit("/", 1)[0], token=secret)[0])

        cancel_request, _cancel_verifier, _cancel_state = self._start_request()
        cancel_path = (
            "/api/matm/human/connector-pairings/%s/cancel"
            % cancel_request["publicRequestRef"]
        )
        self._assert_error(
            call_api(
                cancel_path,
                "POST",
                {"schemaVersion": SCHEMA},
                extra_headers=self._human_mutation_headers(),
            ),
            422,
            "invalid_request",
        )

    def test_only_normalized_exact_canonical_agent_identity_is_accepted(self):
        for index, rejected_agent_id in enumerate(
            (
                "\uff2c\uff4f\uff43\uff41\uff4c\uff25\uff4e\uff44\uff50\uff4f\uff49\uff4e\uff54\uff0d\uff21\uff47\uff45\uff4e\uff54",
                "LocalEndpoint-Agent",
                " localendpoint-agent ",
            )
        ):
            body, _verifier, _state = self._request_body(rejected_agent_id)
            self._assert_error(
                call_api(
                    "/api/matm/connector-pairings/requests",
                    "POST",
                    body,
                    extra_headers=self._idempotency_headers("rejected-agent-identity-%02d" % index),
                ),
                422,
                "connector_agent_identity_invalid",
            )
        request, verifier, state = self._start_request("localendpoint-agent")
        self.assertNotIn("requestedAgentId", request)
        _approved, code, callback_state = self._approve(request, "localendpoint-agent")
        self.assertEqual(state, callback_state)
        exchange, secret = self._exchange(code, verifier)
        self._activate(exchange["pairing"]["pairingId"], secret)

        duplicate, _verifier, _state = self._start_request("localendpoint-agent")
        collision = call_api(
            "/api/matm/human/connector-pairings/%s/approve"
            % duplicate["publicRequestRef"],
            "POST",
            {
                "schemaVersion": SCHEMA,
                "canonicalAgentApproved": True,
                "approvedScopes": list(REQUESTED_SCOPES),
                "workspaceSelection": {
                    "mode": "existing",
                    "workspaceRef": self._existing_workspace_ref(duplicate),
                },
            },
            extra_headers=self._human_mutation_headers(),
        )
        self._assert_error(collision, 409, "agent_name_unavailable")

        other = self.store.create_free_account("Other Workspace", "Other Company", "Other Project")
        other_master = other[2]
        other_company = other[4]
        other_workspace = other[0]
        self.assertNotEqual(self.company_id, other_company)
        # Company-local uniqueness is also enforced by the machine control plane.
        requested = self.store.request_agent_access(other_company, "localendpoint-agent", "workspace", other_workspace)
        self.assertTrue(requested["ok"], requested)
        self.assertTrue(self.store.decide_agent_access_request(other_master, requested["request"]["requestId"], "approved")["ok"])

    def test_secure_store_failure_can_cancel_and_abandoned_grant_expires(self):
        request, verifier, _state = self._start_request()
        _approved, code, _callback_state = self._approve(request)
        exchange, secret = self._exchange(code, verifier)
        pairing_id = exchange["pairing"]["pairingId"]
        self.assertEqual(0, self._agent_registration_count("localendpoint-agent"))

        cancel_key = "secure-store-failed"
        status, headers, canceled, raw = call_api(
            "/api/matm/connector-pairings/%s/cancel" % pairing_id,
            "POST",
            {"schemaVersion": SCHEMA, "reason": "secure_store_failed"},
            secret,
            extra_headers=self._idempotency_headers(cancel_key),
        )
        self._assert_json(status, headers, raw, 200)
        self.assertEqual("canceled", canceled["pairing"]["status"])
        self.assertTrue(canceled["safeNoOpOnRetry"])
        self._assert_receipt(
            canceled, "cancel", "canceled", False, SCOPE_DIGEST
        )
        retry = call_api(
            "/api/matm/connector-pairings/%s/cancel" % pairing_id,
            "POST",
            {"schemaVersion": SCHEMA, "reason": "secure_store_failed"},
            secret,
            extra_headers=self._idempotency_headers(cancel_key),
        )
        self.assertEqual(200, retry[0])
        self._assert_receipt(retry[2], "cancel", "canceled", True, SCOPE_DIGEST)
        self.assertEqual(0, self._agent_registration_count("localendpoint-agent"))
        self._assert_error(
            call_api("/api/matm/connector-pairings/%s" % pairing_id, token=secret),
            410,
            "pairing_canceled",
            (secret,),
        )

        request, verifier, _state = self._start_request()
        _approved, code, _callback_state = self._approve(
            request,
            "localendpoint-agent",
            {
                "schemaVersion": SCHEMA,
                "canonicalAgentApproved": True,
                "approvedScopes": list(REQUESTED_SCOPES),
                "workspaceSelection": {
                    "mode": "new",
                    "workspaceLabel": "Abandoned Pending Workspace",
                    "projectLabel": "Abandoned Pairing",
                },
            },
        )
        exchange, abandoned_secret = self._exchange(code, verifier)
        abandoned_workspace_id = exchange["pairing"]["workspaceId"]
        self.assertEqual(0, self._workspace_count(abandoned_workspace_id))
        abandoned_id = exchange["pairing"]["pairingId"]
        self._expire_pending_pairing(abandoned_id)
        expired = call_api(
            "/api/matm/connector-pairings/%s/activate" % abandoned_id,
            "POST",
            {"schemaVersion": SCHEMA},
            abandoned_secret,
            extra_headers=self._idempotency_headers("expired-activation"),
        )
        self._assert_error(expired, 410, "pending_grant_expired", (abandoned_secret,))
        self.assertEqual(0, self._agent_registration_count("localendpoint-agent"))
        self.assertEqual(0, self._workspace_count(abandoned_workspace_id))

    def test_request_code_and_pending_grant_ttls_are_enforced(self):
        request, _verifier, _state = self._start_request()
        workspace_ref = self._existing_workspace_ref(request)
        self._expire_pairing_request_phase(self._internal_request_id(request), "request")
        expired_request = call_api(
            "/api/matm/human/connector-pairings/%s/approve"
            % request["publicRequestRef"],
            "POST",
            {
                "schemaVersion": SCHEMA,
                "canonicalAgentApproved": True,
                "approvedScopes": list(REQUESTED_SCOPES),
                "workspaceSelection": {"mode": "existing", "workspaceRef": workspace_ref},
            },
            extra_headers=self._human_mutation_headers(),
        )
        self._assert_error(expired_request, 410, "pairing_request_expired")

        request, verifier, _state = self._start_request()
        _approval, code, _callback_state = self._approve(request)
        self._expire_pairing_request_phase(self._internal_request_id(request), "code")
        expired_code = self._exchange_response(code, verifier, "expired-code")
        self._assert_error(expired_code, 410, "authorization_code_expired", (code, verifier))

    def test_rotation_is_two_phase_and_old_credential_survives_until_activation(self):
        pairing_id, old_secret, _exchange = self._pair_active()
        inventory_path = "/api/matm/connector-pairings/%s/credentials" % pairing_id
        initial_inventory = call_api(inventory_path, token=old_secret)
        self._assert_json(initial_inventory[0], initial_inventory[1], initial_inventory[3], 200)
        self.assertEqual(1, initial_inventory[2]["count"])
        self.assertEqual(1, initial_inventory[2]["totalCount"])
        self.assertEqual(100, initial_inventory[2]["limit"])
        self.assertFalse(initial_inventory[2]["hasMore"])
        self.assertEqual(
            initial_inventory[2]["currentCredentialId"],
            initial_inventory[2]["items"][0]["credentialId"],
        )
        self.assertTrue(initial_inventory[2]["items"][0]["isCurrent"])
        self.assertEqual(
            list(REQUESTED_SCOPES),
            initial_inventory[2]["items"][0]["approvedScopes"],
        )
        self.assertEqual(
            SCOPE_DIGEST, initial_inventory[2]["items"][0]["scopeDigest"]
        )
        self._assert_receipt(
            initial_inventory[2],
            "list_credentials",
            "verified",
            False,
            SCOPE_DIGEST,
        )
        master_inventory = call_api(inventory_path, token=self.master_token)
        self.assertEqual(200, master_inventory[0], master_inventory[2])
        self.assertEqual(initial_inventory[2]["items"], master_inventory[2]["items"])
        rotation_key = "rotation-prepare"
        response = call_api(
            "/api/matm/connector-pairings/%s/rotations" % pairing_id,
            "POST",
            {"schemaVersion": SCHEMA, "reason": "scheduled_rotation"},
            old_secret,
            extra_headers=self._idempotency_headers(rotation_key),
        )
        status, headers, prepared, raw = response
        self._assert_json(status, headers, raw, 201)
        rotation = prepared["rotation"]
        self.assertEqual("pending_activation", rotation["status"])
        self.assertEqual(list(REQUESTED_SCOPES), rotation["approvedScopes"])
        self.assertEqual(SCOPE_DIGEST, rotation["scopeDigest"])
        self.assertEqual(SCOPE_DIGEST, prepared["credentialDelivery"]["scopeDigest"])
        self._assert_receipt(
            prepared, "rotate", "pending_activation", False, SCOPE_DIGEST
        )
        successor = prepared["connectorCredentialSecret"]
        self.assertRegex(successor, r"^me_connector_v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
        self._assert_secret_not_persisted(successor)
        prepared_retry = call_api(
            "/api/matm/connector-pairings/%s/rotations" % pairing_id,
            "POST",
            {"schemaVersion": SCHEMA, "reason": "scheduled_rotation"},
            old_secret,
            extra_headers=self._idempotency_headers(rotation_key),
        )
        self.assertEqual(201, prepared_retry[0], prepared_retry[2])
        self.assertEqual(rotation, prepared_retry[2]["rotation"])
        self.assertTrue(secrets.compare_digest(successor, prepared_retry[2]["connectorCredentialSecret"]))

        pending_inventory = call_api(inventory_path, token=old_secret)
        self.assertEqual(200, pending_inventory[0], pending_inventory[2])
        self.assertEqual(2, pending_inventory[2]["totalCount"])
        self.assertEqual(
            {"active", "pending_activation"},
            {item["status"] for item in pending_inventory[2]["items"]},
        )
        for item in pending_inventory[2]["items"]:
            self.assertEqual(list(REQUESTED_SCOPES), item["approvedScopes"])
            self.assertEqual(SCOPE_DIGEST, item["scopeDigest"])
        self.assertNotIn("credentialVerifier", json.dumps(pending_inventory[2]))

        old_readback = call_api("/api/matm/connector-pairings/%s" % pairing_id, token=old_secret)
        self.assertEqual(200, old_readback[0])
        pending_readback = call_api("/api/matm/connector-pairings/%s" % pairing_id, token=successor)
        self._assert_error(pending_readback, 401, "pending_credential_not_active", (successor,))

        activate_key = "rotation-activate"
        status, headers, activated, raw = call_api(
            "/api/matm/connector-pairings/%s/rotations/%s/activate" % (pairing_id, rotation["rotationId"]),
            "POST",
            {"schemaVersion": SCHEMA},
            successor,
            extra_headers=self._idempotency_headers(activate_key),
        )
        self._assert_json(status, headers, raw, 200)
        self.assertEqual("active", activated["rotation"]["status"])
        self.assertEqual(
            list(REQUESTED_SCOPES), activated["rotation"]["approvedScopes"]
        )
        self.assertEqual(SCOPE_DIGEST, activated["rotation"]["scopeDigest"])
        self._assert_receipt(
            activated, "rotate", "rotated", False, SCOPE_DIGEST
        )
        activation_retry = call_api(
            "/api/matm/connector-pairings/%s/rotations/%s/activate" % (pairing_id, rotation["rotationId"]),
            "POST",
            {"schemaVersion": SCHEMA},
            successor,
            extra_headers=self._idempotency_headers(activate_key),
        )
        self.assertEqual(200, activation_retry[0], activation_retry[2])
        self.assertEqual(activated["rotation"], activation_retry[2]["rotation"])
        self.assertEqual(
            activated["receipt"]["receiptId"], activation_retry[2]["receipt"]["receiptId"]
        )
        self.assertTrue(activation_retry[2]["receipt"]["idempotentReplay"])
        self._assert_error(
            call_api("/api/matm/connector-pairings/%s" % pairing_id, token=old_secret),
            401,
            "invalid_token",
            (old_secret,),
        )
        successor_readback = call_api(
            "/api/matm/connector-pairings/%s" % pairing_id, token=successor
        )
        self.assertEqual(200, successor_readback[0], successor_readback[2])
        self.assertEqual(
            "localendpoint-agent",
            successor_readback[2]["pairing"]["agent"]["agentId"],
        )
        self.assertEqual(
            self.workspace_id,
            successor_readback[2]["pairing"]["workspace"]["workspaceId"],
        )
        self.assertEqual(
            SCOPE_DIGEST, successor_readback[2]["pairing"]["scopeDigest"]
        )
        rotated_inventory = call_api(inventory_path, token=successor)
        self.assertEqual(200, rotated_inventory[0], rotated_inventory[2])
        self.assertEqual(2, rotated_inventory[2]["totalCount"])
        statuses = {item["status"] for item in rotated_inventory[2]["items"]}
        self.assertEqual({"active", "superseded"}, statuses)
        for item in rotated_inventory[2]["items"]:
            self.assertEqual(list(REQUESTED_SCOPES), item["approvedScopes"])
            self.assertEqual(SCOPE_DIGEST, item["scopeDigest"])
        current = next(item for item in rotated_inventory[2]["items"] if item["isCurrent"])
        self.assertEqual("active", current["status"])
        self.assertEqual(rotated_inventory[2]["currentCredentialId"], current["credentialId"])

    def test_lifecycle_authority_is_rejected_before_body_or_mutation_dispatch(self):
        pairing_id, secret, _exchange = self._pair_active()
        invalid_secret = secret[:-1] + ("A" if secret[-1] != "A" else "B")
        actions = (
            (
                "/api/matm/connector-pairings/%s/activate" % pairing_id,
                "activate_connector_pairing",
                self.master_token,
                "connector_scope_forbidden",
            ),
            (
                "/api/matm/connector-pairings/%s/rotations" % pairing_id,
                "prepare_connector_rotation",
                self.master_token,
                "connector_scope_forbidden",
            ),
            (
                "/api/matm/connector-pairings/%s/rotations/rotation-untrusted/activate"
                % pairing_id,
                "activate_connector_rotation",
                self.master_token,
                "connector_scope_forbidden",
            ),
            (
                "/api/matm/connector-pairings/%s/disconnect" % pairing_id,
                "disconnect_connector_pairing",
                self.master_token,
                "connector_scope_forbidden",
            ),
            (
                "/api/matm/connector-pairings/%s/cancel" % pairing_id,
                "cancel_connector_pairing",
                self.master_token,
                "connector_scope_forbidden",
            ),
            (
                "/api/matm/connector-pairings/%s/revoke" % pairing_id,
                "revoke_connector_pairing",
                secret,
                "company_master_required",
            ),
        )
        store_type = type(self.store)
        with ExitStack() as stack:
            for _path, mutation_name, _wrong_token, _wrong_code in actions:
                stack.enter_context(
                    patch.object(
                        store_type,
                        mutation_name,
                        side_effect=AssertionError(
                            "%s dispatched before authority rejection" % mutation_name
                        ),
                    )
                )
            for path, _mutation_name, wrong_token, wrong_code in actions:
                with self.subTest(path=path, credential="missing", body="oversized"):
                    self._assert_error(
                        call_with_unreadable_body(path, REQUEST_BODY_LIMIT + 1),
                        401,
                        "invalid_token",
                    )
                with self.subTest(path=path, credential="invalid", body="malformed"):
                    self._assert_error(
                        call_with_unreadable_body(path, 1, invalid_secret),
                        401,
                        "invalid_token",
                        (invalid_secret,),
                    )
                with self.subTest(path=path, credential="wrong_authority", body="oversized"):
                    self._assert_error(
                        call_with_unreadable_body(
                            path, REQUEST_BODY_LIMIT + 1, wrong_token
                        ),
                        403,
                        wrong_code,
                        (wrong_token,),
                    )

    def test_connector_disconnect_is_immediate_idempotent_no_op(self):
        pairing_id, secret, _exchange = self._pair_active()
        status, headers, disconnected, raw = call_api(
            "/api/matm/connector-pairings/%s/disconnect" % pairing_id,
            "POST",
            {"schemaVersion": SCHEMA, "reason": "owner_disconnected_desktop"},
            secret,
            extra_headers=self._idempotency_headers("disconnect"),
        )
        self._assert_json(status, headers, raw, 200)
        self.assertEqual("disconnected", disconnected["pairing"]["status"])
        self.assertTrue(disconnected["safeNoOpOnRetry"])
        disconnect_retry = call_api(
            "/api/matm/connector-pairings/%s/disconnect" % pairing_id,
            "POST",
            {"schemaVersion": SCHEMA, "reason": "owner_disconnected_desktop"},
            secret,
            extra_headers=self._idempotency_headers("disconnect"),
        )
        self.assertEqual(200, disconnect_retry[0], disconnect_retry[2])
        self.assertEqual(
            disconnected["receipt"]["receiptId"],
            disconnect_retry[2]["receipt"]["receiptId"],
        )
        self._assert_receipt(
            disconnect_retry[2],
            "disconnect",
            "disconnected",
            True,
            SCOPE_DIGEST,
        )
        store = self._new_store()
        self.assertIsNone(
            store.authenticate_connector_token(
                secret, pairing_id=pairing_id, allow_pending=True
            )
        )
        lifecycle_principal = store.authenticate_connector_token(
            secret,
            pairing_id=pairing_id,
            allow_pending=True,
            allow_lifecycle_terminal=True,
        )
        self.assertIsNotNone(lifecycle_principal)
        self.assertFalse(lifecycle_principal["active"])
        self.assertEqual("disconnected", lifecycle_principal["pairingStatus"])
        self.assertEqual("disconnected", lifecycle_principal["credentialStatus"])
        self._assert_error(
            call_api("/api/matm/connector-pairings/%s" % pairing_id, token=secret),
            401,
            "invalid_token",
            (secret,),
        )
        self._assert_error(
            call_api("/api/matm/workspace", token=secret),
            401,
            "invalid_token",
            (secret,),
        )
        self._assert_error(
            call_api(
                "/api/matm/agents/register",
                "POST",
                {"schemaVersion": SCHEMA},
                secret,
                extra_headers=self._idempotency_headers("disconnected-register"),
            ),
            401,
            "invalid_token",
            (secret,),
        )

    def test_master_revocation_is_immediate_idempotent_no_op(self):
        pairing_id, secret, _exchange = self._pair_active()
        status, headers, revoked, raw = call_api(
            "/api/matm/connector-pairings/%s/revoke" % pairing_id,
            "POST",
            {"schemaVersion": SCHEMA, "reason": "company_owner_revoked"},
            self.master_token,
            extra_headers=self._idempotency_headers("master-revoke"),
        )
        self._assert_json(status, headers, raw, 200)
        self.assertEqual("revoked", revoked["pairing"]["status"])
        self.assertEqual(self.master_key_id, revoked["receipt"]["actorMasterKeyId"])
        self.assertTrue(revoked["safeNoOpOnRetry"])
        revoke_retry = call_api(
            "/api/matm/connector-pairings/%s/revoke" % pairing_id,
            "POST",
            {"schemaVersion": SCHEMA, "reason": "company_owner_revoked"},
            self.master_token,
            extra_headers=self._idempotency_headers("master-revoke"),
        )
        self.assertEqual(200, revoke_retry[0], revoke_retry[2])
        self.assertEqual(
            revoked["receipt"]["receiptId"],
            revoke_retry[2]["receipt"]["receiptId"],
        )
        self._assert_receipt(
            revoke_retry[2], "revoke", "revoked", True, SCOPE_DIGEST
        )
        self.assertIsNone(
            self._new_store().authenticate_connector_token(
                secret,
                pairing_id=pairing_id,
                allow_pending=True,
                allow_lifecycle_terminal=True,
            )
        )
        self._assert_error(
            call_api("/api/matm/connector-pairings/%s" % pairing_id, token=secret),
            401,
            "invalid_token",
            (secret,),
        )

    def test_auth_concealment_permissions_rate_limit_and_service_errors(self):
        pairing_id, secret, _exchange = self._pair_active()
        unknown = "pairing-" + secrets.token_urlsafe(16)
        self._assert_error(
            call_api("/api/matm/connector-pairings/%s" % unknown, token=secret),
            404,
            "pairing_not_found",
            (pairing_id, secret),
        )
        self._assert_error(
            call_api("/api/matm/connector-pairings/%s" % pairing_id),
            401,
            "invalid_token",
        )
        forbidden = call_api(
            "/api/matm/connector-pairings/%s/revoke" % pairing_id,
            "POST",
            {"schemaVersion": SCHEMA, "reason": "connector_cannot_revoke"},
            secret,
            extra_headers=self._idempotency_headers("forbidden-revoke"),
        )
        self._assert_error(forbidden, 403, "company_master_required", (secret,))

        os.environ["MEMORYENDPOINTS_CONNECTOR_PAIRING_RATE_LIMIT"] = "3"
        first, _verifier, _state = self._request_body()
        second, _verifier, _state = self._request_body()
        third, _verifier, _state = self._request_body()
        self.assertEqual(201, call_api(
            "/api/matm/connector-pairings/requests", "POST", first,
            extra_headers=self._idempotency_headers("rate-1"),
        )[0])
        self.assertEqual(201, call_api(
            "/api/matm/connector-pairings/requests", "POST", second,
            extra_headers=self._idempotency_headers("rate-2"),
        )[0])
        limited = call_api(
            "/api/matm/connector-pairings/requests", "POST", third,
            extra_headers=self._idempotency_headers("rate-3"),
        )
        self._assert_error(limited, 429, "rate_limited")
        self.assertGreaterEqual(int(_header(limited[1], "Retry-After", "0")), 1)

    def test_credential_service_failure_is_redacted_and_retryable(self):
        request, verifier, _state = self._start_request()
        _approval, code, _callback_state = self._approve(request)
        previous = os.environ.pop("MEMORYENDPOINTS_CREDENTIAL_PEPPER")
        try:
            failed = self._exchange_response(code, verifier, "service-error-exchange")
            self._assert_error(
                failed,
                503,
                "credential_system_not_configured",
                (code, verifier, previous),
            )
            self.assertGreaterEqual(int(_header(failed[1], "Retry-After", "0")), 1)
        finally:
            os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = previous
        recovered, secret = self._exchange(code, verifier, "service-error-exchange")
        self.assertEqual("pending_activation", recovered["pairing"]["status"])
        self._assert_secret_not_persisted(secret)

    def test_human_can_create_workspace_during_approval_without_leaking_identifiers_to_wakeup(self):
        request, verifier, state = self._start_request()
        approval, code, callback_state = self._approve(
            request,
            "localendpoint-agent",
            {
                "schemaVersion": SCHEMA,
                "canonicalAgentApproved": True,
                "approvedScopes": list(REQUESTED_SCOPES),
                "workspaceSelection": {
                    "mode": "new",
                    "workspaceLabel": "New LocalEndpoint Workspace",
                    "projectLabel": "LocalEndpoint Pairing",
                },
            },
        )
        self.assertEqual(state, callback_state)
        self.assertEqual(REDIRECT_URI, approval["wakeUpUrl"])
        self.assertNotIn("workspaceId", approval["approval"])
        exchange, secret = self._exchange(code, verifier)
        new_workspace_id = exchange["pairing"]["workspaceId"]
        self.assertNotEqual(self.workspace_id, new_workspace_id)
        self.assertNotIn(new_workspace_id, approval["wakeUpUrl"])
        self.assertEqual(new_workspace_id, exchange["pairing"]["workspaceId"])
        self.assertEqual(0, self._workspace_count(new_workspace_id))
        self._activate(exchange["pairing"]["pairingId"], secret)
        self.assertEqual(1, self._workspace_count(new_workspace_id))

    def test_allowed_connector_operations_use_credential_partitioned_rate_limits(self):
        _pairing_id, secret, _exchange = self._pair_active()
        policies = {
            "selfRegistration": {"limit": 1, "windowSeconds": 600, "partition": "connector_credential"},
            "publicSafeSubmit": {"limit": 1, "windowSeconds": 60, "partition": "connector_credential"},
            "search": {"limit": 1, "windowSeconds": 60, "partition": "connector_credential"},
        }
        with patch.dict(app_module.CONNECTOR_RATE_LIMIT_POLICIES, policies, clear=False):
            registration_body = {"schemaVersion": SCHEMA}
            first_registration = call_api(
                "/api/matm/agents/register",
                "POST",
                registration_body,
                secret,
                extra_headers=self._idempotency_headers("rate-self-register-one"),
            )
            self.assertEqual(200, first_registration[0], first_registration[2])
            registration_limited = call_api(
                "/api/matm/agents/register",
                "POST",
                registration_body,
                secret,
                extra_headers=self._idempotency_headers("rate-self-register-two"),
            )
            self._assert_error(registration_limited, 429, "rate_limited")

            submit_body = {
                "schemaVersion": SCHEMA,
                "payloadClass": "public_safe",
                "title": "Connector operation rate contract",
                "summary": "The first credential-partitioned public-safe write is accepted.",
                "tags": ["connector", "rate-limit"],
            }
            first_submit = call_api(
                "/api/matm/memory-events/submit",
                "POST",
                submit_body,
                secret,
                extra_headers=self._idempotency_headers("rate-submit-one"),
            )
            self.assertEqual(201, first_submit[0], first_submit[2])
            submit_limited = call_api(
                "/api/matm/memory-events/submit",
                "POST",
                submit_body,
                secret,
                extra_headers=self._idempotency_headers("rate-submit-two"),
            )
            self._assert_error(submit_limited, 429, "rate_limited")

            search_body = {"schemaVersion": SCHEMA, "query": "connector", "limit": 10}
            first_search = call_api(
                "/api/matm/search", "POST", search_body, secret
            )
            self.assertEqual(200, first_search[0], first_search[2])
            search_limited = call_api(
                "/api/matm/search", "POST", search_body, secret
            )
            self._assert_error(search_limited, 429, "rate_limited")
            for response in (registration_limited, submit_limited, search_limited):
                self.assertGreaterEqual(int(_header(response[1], "Retry-After", "0")), 1)

    def test_active_connector_operations_reject_oversized_json_before_dispatch(self):
        _pairing_id, secret, _exchange = self._pair_active()
        oversized = b'{"padding":"' + (b"x" * REQUEST_BODY_LIMIT) + b'"}'
        operations = (
            ("/api/matm/agents/register", "confirm_connector_agent_registration"),
            ("/api/matm/memory-events/submit", "submit_memory"),
            ("/api/matm/search", "search_memory"),
        )
        store_type = type(self.store)
        with ExitStack() as stack:
            for _path, operation_name in operations:
                stack.enter_context(
                    patch.object(
                        store_type,
                        operation_name,
                        side_effect=AssertionError(
                            "%s dispatched before bounded JSON rejection"
                            % operation_name
                        ),
                    )
                )
            for path, _operation_name in operations:
                with self.subTest(path=path):
                    self._assert_error(
                        call_raw(
                            path,
                            "POST",
                            oversized,
                            secret,
                            extra_headers=self._idempotency_headers(
                                "oversized-active-connector"
                            ),
                        ),
                        413,
                        "request_body_too_large",
                        (secret,),
                    )


class FileStoreConnectorPairingApiTests(ConnectorPairingApiContract, unittest.TestCase):
    backend = "file"


class SQLiteStoreConnectorPairingApiTests(ConnectorPairingApiContract, unittest.TestCase):
    backend = "sqlite"


if __name__ == "__main__":
    unittest.main()
