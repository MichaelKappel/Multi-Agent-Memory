import hashlib
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from app import application


ORIGIN = "https://memoryendpoints.com"
GOVERNED_SECRET = re.compile(
    r"me_(?:master|agent|invite|human|accountsession|accountcsrf|masterproof|closure)_v1\."
    r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
)
SENSITIVE_KEYS = {
    "agenttokensecret",
    "companymastertokenproof",
    "companymastertokensecret",
    "credentialhash",
    "credentialsecret",
    "credentialverifier",
    "humanownerrecoverysecret",
    "invitesecret",
    "password",
    "passwordhash",
    "recoverysecret",
    "secret",
    "secrethash",
    "sessionhash",
    "successortokenproof",
    "successortokensecret",
    "tokenhash",
    "tokenverifier",
    "verifierhash",
}


def call_api(path, method="GET", body=None, token=None, extra_headers=None, parse_json=True):
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
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
    }
    if body is not None:
        environ["CONTENT_TYPE"] = "application/json"
    if token:
        environ["HTTP_AUTHORIZATION"] = "Bearer " + token
    for key, value in (extra_headers or {}).items():
        environ[key] = value
    response_body = b"".join(application(environ, start_response))
    payload = json.loads(response_body.decode("utf-8")) if parse_json else response_body
    return int(captured["status"].split(" ", 1)[0]), captured["headers"], payload


def _header(headers, name, default=None):
    expected = name.lower()
    for key, value in headers.items():
        if key.lower() == expected:
            return value
    return default


def _normalized_key(value):
    return "".join(character for character in str(value).lower() if character.isalnum())


def _contains_value(value, expected):
    if isinstance(value, dict):
        return expected in value or any(_contains_value(item, expected) for item in value.values())
    if isinstance(value, list):
        return any(_contains_value(item, expected) for item in value)
    return value == expected


class HumanAccountCompanyLifecycleContract:
    backend = None

    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="memoryendpoints-human-account-%s-" % self.backend)
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
            }
        )
        self.username = "memory-owner"
        self.password = secrets.token_urlsafe(36)
        self.primary = self._create_company(
            "Portable Memory Test Company",
            "Portable Memory Workspace",
            "Portable Memory Project",
        )

    def tearDown(self):
        for key, value in self._saved_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def _public_mutation_headers(self):
        return {
            "HTTP_ORIGIN": ORIGIN,
            "HTTP_SEC_FETCH_SITE": "same-origin",
            "HTTP_SEC_FETCH_MODE": "cors",
            "HTTP_SEC_FETCH_DEST": "empty",
        }

    def _create_company(self, company_label, workspace_label, project_label):
        status, headers, payload = call_api(
            "/api/matm/agent-setup/free-account",
            "POST",
            {
                "companyLabel": company_label,
                "label": workspace_label,
                "projectLabel": project_label,
            },
        )
        self.assertEqual(201, status)
        self.assertTrue(payload["ok"])
        self.assertRegex(payload["companyMasterTokenSecret"], r"^me_master_v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
        self.assertRegex(payload["humanOwnerRecoverySecret"], r"^me_human_v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
        self._assert_one_time_headers(headers)
        payload["companyLabel"] = company_label
        return payload

    def _create_master_proof(self, company, session=None):
        headers = self._human_headers(session) if session else self._public_mutation_headers()
        status, response_headers, payload = call_api(
            "/api/matm/human/company-master-proofs",
            "POST",
            {"companyMasterTokenSecret": company["companyMasterTokenSecret"]},
            extra_headers=headers,
        )
        self.assertEqual(201, status)
        proof_secret = payload["companyMasterProofSecret"]
        self.assertIsInstance(proof_secret, str)
        self.assertRegex(proof_secret, r"^me_masterproof_v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
        self.assertEqual(company["companyId"], payload["proof"]["companyId"])
        public_payload = dict(payload)
        public_payload.pop("companyMasterProofSecret")
        self._assert_no_governed_secret(public_payload)
        self._assert_one_time_headers(response_headers)
        return proof_secret

    def _create_account_with_proof(self, company, proof_secret, username=None, password=None):
        username = username or self.username
        password = password or self.password
        status, headers, payload = call_api(
            "/api/matm/human/accounts",
            "POST",
            {
                "username": username,
                "password": password,
                "displayName": "Memory Owner",
                "companyMasterProofSecret": proof_secret,
            },
            extra_headers=self._public_mutation_headers(),
        )
        self.assertEqual(201, status)
        self.assertTrue(payload["ok"])
        self.assertEqual(username, payload["account"]["username"])
        self.assertTrue(payload["account"]["humanAccountId"])
        self.assertEqual(company["companyId"], payload["membership"]["companyId"])
        public_payload = dict(payload)
        public_payload.pop("csrfToken")
        self._assert_no_governed_secret(public_payload)
        return payload["account"], self._session_from_response(headers, payload), payload["membership"]

    def _create_human_account(self, company=None):
        company = company or self.primary
        proof_secret = self._create_master_proof(company)
        return self._create_account_with_proof(company, proof_secret)

    def _login(self):
        status, headers, payload = call_api(
            "/api/matm/human/session",
            "POST",
            {"username": self.username, "password": self.password},
            extra_headers=self._public_mutation_headers(),
        )
        self.assertEqual(201, status)
        self.assertTrue(payload["ok"])
        self.assertEqual(self.username, payload["humanSession"]["username"])
        self.assertIsNone(payload["humanSession"]["selectedCompanyId"])
        return self._session_from_response(headers, payload)

    def _session_from_response(self, headers, payload):
        cookie_header = _header(headers, "Set-Cookie", "")
        cookie = cookie_header.split(";", 1)[0]
        self.assertIn("=", cookie)
        self.assertIn("Secure", cookie_header)
        self.assertIn("HttpOnly", cookie_header)
        self.assertIn("SameSite=Strict", cookie_header)
        self.assertIn("Path=/", cookie_header)
        self.assertNotIn("Domain=", cookie_header)
        csrf_token = payload["csrfToken"]
        self.assertGreaterEqual(len(csrf_token), 32)
        self._assert_one_time_headers(headers)
        return {"cookie": cookie, "csrfToken": csrf_token}

    def _human_headers(self, session, include_csrf=True, origin=ORIGIN, fetch_site="same-origin"):
        headers = {
            "HTTP_COOKIE": session["cookie"],
            "HTTP_ORIGIN": origin,
            "HTTP_SEC_FETCH_SITE": fetch_site,
            "HTTP_SEC_FETCH_MODE": "cors",
            "HTTP_SEC_FETCH_DEST": "empty",
        }
        if include_csrf:
            headers["HTTP_X_CSRF_TOKEN"] = session["csrfToken"]
        return headers

    def _human_call(self, session, path, method="GET", body=None, extra_headers=None, parse_json=True):
        headers = self._human_headers(session)
        headers.update(extra_headers or {})
        return call_api(path, method, body, extra_headers=headers, parse_json=parse_json)

    def _link_company(self, session, company):
        proof_secret = self._create_master_proof(company, session)
        status, _headers, payload = self._human_call(
            session,
            "/api/matm/human/company-memberships/link",
            "POST",
            {"companyMasterProofSecret": proof_secret},
        )
        self.assertEqual(201, status)
        self.assertEqual(company["companyId"], payload["membership"]["companyId"])
        self.assertTrue(payload["proofAccepted"])
        self.assertFalse(payload["rawCredentialPersisted"])
        self._assert_no_governed_secret(payload)
        return payload["membership"], proof_secret

    def _memberships(self, session):
        status, _headers, payload = self._human_call(
            session,
            "/api/matm/human/company-memberships",
        )
        self.assertEqual(200, status)
        self._assert_no_governed_secret(payload)
        return payload

    def _select_company(self, session, authority_id, company_id):
        old_session = dict(session)
        status, headers, payload = self._human_call(
            session,
            "/api/matm/human/session/company",
            "POST",
            {"authorityId": authority_id},
        )
        self.assertEqual(200, status)
        self.assertEqual(company_id, payload["selectedCompanyId"])
        rotated = self._session_from_response(headers, payload)
        self._assert_session_rotated(old_session, rotated)
        self._assert_session_invalid(old_session)
        return rotated

    def _reauth(self, session):
        old_session = dict(session)
        status, headers, payload = self._human_call(
            session,
            "/api/matm/human/session/reauth",
            "POST",
            {"password": self.password},
        )
        self.assertEqual(200, status)
        self.assertTrue(payload["passwordReauthenticatedAt"])
        rotated = self._session_from_response(headers, payload)
        self._assert_session_rotated(old_session, rotated)
        self._assert_session_invalid(old_session)
        return rotated

    def _assert_session_rotated(self, old_session, new_session):
        if secrets.compare_digest(old_session["cookie"], new_session["cookie"]):
            self.fail("the privileged session cookie was not rotated")
        if secrets.compare_digest(old_session["csrfToken"], new_session["csrfToken"]):
            self.fail("the CSRF token was not rotated with the privileged session")

    def _assert_session_invalid(self, session):
        status, _headers, payload = self._human_call(session, "/api/matm/human/session")
        self._assert_error(status, payload, 401, "human_session_required")

    def _account_session(self, company=None):
        company = company or self.primary
        account, session, membership = self._create_human_account(company)
        session = self._select_company(session, membership["authorityId"], company["companyId"])
        return account, session

    def _provision_agent(self, company=None, requested_name="portable-memory-agent"):
        company = company or self.primary
        master_token = company["companyMasterTokenSecret"]
        status, _headers, requested = call_api(
            "/api/matm/access/agent-name-requests",
            "POST",
            {
                "requestedName": requested_name,
                "displayName": "Portable Memory Agent",
                "requestedGrant": {"scopeType": "workspace", "scopeId": company["workspaceId"]},
                "assignmentContext": {
                    "projectId": company["projectId"],
                    "taskId": "portable-memory-verification",
                    "taskLabel": "Portable memory verification",
                },
                "justification": "Verify portable memory and governed token lifecycle behavior.",
            },
            master_token,
        )
        self.assertEqual(201, status)
        request_id = requested["request"]["requestId"]
        status, _headers, _approved = call_api(
            "/api/matm/access/agent-name-requests/%s/decision" % request_id,
            "POST",
            {"decision": "approve", "decisionReason": "Approved for acceptance testing."},
            master_token,
        )
        self.assertEqual(200, status)
        status, _headers, issued = call_api(
            "/api/matm/access/invites",
            "POST",
            {"approvedRequestId": request_id, "expiresInSeconds": 900},
            master_token,
        )
        self.assertEqual(201, status)
        invite_secret = parse_qs(urlsplit(issued["inviteUrl"]).fragment, strict_parsing=True)["invite"][0]
        status, _headers, redeemed = call_api(
            "/api/matm/access/invites/redeem",
            "POST",
            {"inviteSecret": invite_secret},
        )
        self.assertEqual(201, status)
        return {
            "inviteSecret": invite_secret,
            "agentTokenSecret": redeemed["agentTokenSecret"],
            "principal": redeemed["principal"],
        }

    def _agent_inventory(self, session, company=None):
        company = company or self.primary
        status, _headers, payload = self._human_call(
            session,
            "/api/matm/human/companies/%s/agent-tokens" % company["companyId"],
        )
        self.assertEqual(200, status)
        self._assert_no_governed_secret(payload)
        encoded = json.dumps(payload, sort_keys=True)
        self.assertNotIn(company["credentialId"], encoded)
        return payload

    def _prepare_replacement(self, session, agent, idempotency_key):
        credential_id = agent["principal"]["credentialId"]
        path = "/api/matm/human/companies/%s/agent-tokens/%s/replacements" % (
            self.primary["companyId"],
            credential_id,
        )
        status, headers, payload = self._human_call(
            session,
            path,
            "POST",
            {
                "reason": "Routine credential rotation",
                "expiresInSeconds": 300,
            },
            extra_headers={"HTTP_IDEMPOTENCY_KEY": idempotency_key},
        )
        self.assertEqual(201, status)
        self.assertEqual("prepared", payload["replacement"]["status"])
        self.assertEqual(credential_id, payload["replacement"]["predecessorCredentialId"])
        successor_secret = payload["successorTokenSecret"]
        self.assertRegex(successor_secret, r"^me_agent_v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
        public_payload = dict(payload)
        public_payload.pop("successorTokenSecret")
        self._assert_no_governed_secret(public_payload)
        self._assert_one_time_headers(headers)
        return path, payload["replacement"], successor_secret

    def _confirm_replacement(self, session, base_path, replacement_id, successor_proof, idempotency_key):
        return self._human_call(
            session,
            "%s/%s/confirm" % (base_path, replacement_id),
            "POST",
            {"successorTokenProof": successor_proof},
            extra_headers={"HTTP_IDEMPOTENCY_KEY": idempotency_key},
        )

    def _create_intent(self, session, operation):
        status, headers, payload = self._human_call(
            session,
            "/api/matm/human/companies/%s/closure-intents" % self.primary["companyId"],
            "POST",
            {"operation": operation, "acknowledgeExportOpportunity": True},
        )
        self.assertEqual(201, status)
        self.assertEqual(operation, payload["intent"]["operation"])
        secret = payload["closureIntentSecret"]
        self.assertRegex(secret, r"^me_closure_v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
        self._assert_one_time_headers(headers)
        return secret

    def _export_plan(self, session, company=None):
        company = company or self.primary
        status, _headers, payload = self._human_call(
            session,
            "/api/matm/human/companies/%s/export-plan" % company["companyId"],
        )
        self.assertEqual(200, status)
        self.assertEqual(company["companyId"], payload["exportPlan"]["companyId"])
        self.assertTrue(payload["exportPlan"]["exportStronglyRecommended"])
        self.assertTrue(payload["exportPlan"]["completeCompanyExportAvailable"])
        self._assert_no_governed_secret(payload)
        return payload

    def _export_company(self, session, account, company=None):
        company = company or self.primary
        status, headers, raw_export = self._human_call(
            session,
            "/api/matm/human/companies/%s/exports" % company["companyId"],
            "POST",
            {"format": "application/zip"},
            parse_json=False,
        )
        self.assertEqual(201, status)
        self.assertEqual("application/zip", _header(headers, "Content-Type"))
        self.assertEqual(company["companyId"], _header(headers, "X-MemoryEndpoints-Export-Company-Id"))
        self.assertTrue(_header(headers, "X-MemoryEndpoints-Export-Receipt-Id"))
        self.assertEqual("true", _header(headers, "X-MemoryEndpoints-Export-Complete", "").lower())
        expected_digest = "sha256:" + hashlib.sha256(raw_export).hexdigest()
        self.assertEqual(expected_digest, _header(headers, "X-MemoryEndpoints-Export-SHA256"))
        with zipfile.ZipFile(io.BytesIO(raw_export), "r") as archive:
            self.assertEqual({"company.json", "index.json", "manifest.json"}, set(archive.namelist()))
            company_bytes = archive.read("company.json")
            index_bytes = archive.read("index.json")
            company_export = json.loads(company_bytes.decode("utf-8"))
            index = json.loads(index_bytes.decode("utf-8"))
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        self.assertEqual(company["companyId"], company_export["company"]["companyId"])
        self.assertTrue(manifest["completeCompanyExport"])
        self.assertTrue(manifest["includesPortableMemory"])
        self.assertTrue(manifest["includesHumanForensicHistory"])
        self.assertTrue(manifest["valuesRedacted"])
        self.assertFalse(manifest["rawCredentialExposed"])
        self.assertFalse(manifest["credentialVerifiersExposed"])
        self.assertRegex(manifest["exportReceiptDigest"], r"^[a-f0-9]{64}$")
        self.assertEqual("sha256:" + hashlib.sha256(company_bytes).hexdigest(), manifest["checksums"]["company.json"])
        self.assertEqual("sha256:" + hashlib.sha256(index_bytes).hexdigest(), manifest["checksums"]["index.json"])
        self.assertEqual(account["humanAccountId"], manifest["auditActor"]["humanAccountId"])
        self.assertEqual(self.username, manifest["auditActor"]["username"])
        self._assert_no_governed_secret(company_export)
        self._assert_no_governed_secret(index)
        self._assert_no_governed_secret(manifest)
        return _header(headers, "X-MemoryEndpoints-Export-Receipt-Id"), company_export

    def _expire_replacement(self, replacement_id):
        if self.backend == "file":
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
            data["agentTokenReplacements"][replacement_id]["expiresAt"] = "2000-01-01T00:00:00.000000Z"
            self.store_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
            return
        with closing(sqlite3.connect(self.sqlite_path)) as connection:
            connection.execute(
                "UPDATE matm_agent_token_replacements SET expires_at = ? WHERE replacement_id = ?",
                ("2000-01-01T00:00:00.000000Z", replacement_id),
            )
            connection.commit()

    def _expire_master_proof(self, proof_secret):
        proof_id = proof_secret.split(".", 2)[1]
        if self.backend == "file":
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
            data["companyMasterProofs"][proof_id]["expiresAt"] = "2000-01-01T00:00:00.000000Z"
            self.store_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
            return
        with closing(sqlite3.connect(self.sqlite_path)) as connection:
            connection.execute(
                "UPDATE matm_company_master_proofs SET expires_at = ? WHERE master_proof_id = ?",
                ("2000-01-01T00:00:00.000000Z", proof_id),
            )
            connection.commit()

    def _human_account_count(self):
        if self.backend == "file":
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
            return len(data.get("humanAccounts", {}))
        with closing(sqlite3.connect(self.sqlite_path)) as connection:
            return connection.execute("SELECT COUNT(*) FROM matm_human_accounts").fetchone()[0]

    def _replacement_count(self):
        if self.backend == "file":
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
            return len(data.get("agentTokenReplacements", {}))
        with closing(sqlite3.connect(self.sqlite_path)) as connection:
            return connection.execute("SELECT COUNT(*) FROM matm_agent_token_replacements").fetchone()[0]

    def _assert_not_persisted(self, *values):
        persisted = b"\n".join(path.read_bytes() for path in Path(self.tempdir).rglob("*") if path.is_file())
        for value in values:
            encoded = str(value).encode("utf-8")
            secret_component = str(value).rsplit(".", 1)[-1].encode("utf-8")
            if encoded in persisted or secret_component in persisted:
                self.fail("raw password, proof, or governed credential material was persisted")

    def _assert_no_governed_secret(self, payload):
        encoded = json.dumps(payload, sort_keys=True)
        if GOVERNED_SECRET.search(encoded):
            self.fail("a governed credential appeared in a metadata-only response")

        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if _normalized_key(key) in SENSITIVE_KEYS:
                        self.fail("a secret or verifier field appeared in a metadata-only response")
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(payload)

    def _assert_error(self, status, payload, expected_status, code):
        self.assertEqual(expected_status, status)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["safeNoOp"])
        self.assertEqual(code, payload["error"]["code"])
        self._assert_no_governed_secret(payload)

    def _assert_one_time_headers(self, headers):
        self.assertIn("no-store", _header(headers, "Cache-Control", ""))
        self.assertIn("private", _header(headers, "Cache-Control", ""))
        self.assertEqual("no-cache", _header(headers, "Pragma"))
        self.assertEqual("no-referrer", _header(headers, "Referrer-Policy"))

    def test_company_master_proof_is_one_time_and_required_for_first_account_authority(self):
        self.assertEqual(0, self._human_account_count())
        base_body = {"username": self.username, "password": self.password, "displayName": "Memory Owner"}
        status, _headers, missing = call_api(
            "/api/matm/human/accounts",
            "POST",
            base_body,
            extra_headers=self._public_mutation_headers(),
        )
        self._assert_error(status, missing, 422, "company_master_proof_required")
        self.assertEqual(0, self._human_account_count())

        invalid_body = dict(base_body)
        invalid_body["companyMasterProofSecret"] = "me_masterproof_v1.%s.%s" % (
            secrets.token_urlsafe(12),
            secrets.token_urlsafe(32),
        )
        status, _headers, invalid = call_api(
            "/api/matm/human/accounts",
            "POST",
            invalid_body,
            extra_headers=self._public_mutation_headers(),
        )
        self._assert_error(status, invalid, 401, "company_master_proof_invalid")
        self.assertEqual(0, self._human_account_count())

        expired_proof = self._create_master_proof(self.primary)
        self._expire_master_proof(expired_proof)
        expired_body = dict(base_body)
        expired_body["companyMasterProofSecret"] = expired_proof
        status, _headers, expired = call_api(
            "/api/matm/human/accounts",
            "POST",
            expired_body,
            extra_headers=self._public_mutation_headers(),
        )
        self._assert_error(status, expired, 410, "company_master_proof_expired")
        self.assertEqual(0, self._human_account_count())

        proof_secret = self._create_master_proof(self.primary)
        account, _session, membership = self._create_account_with_proof(self.primary, proof_secret)
        self.assertEqual(self.primary["companyId"], membership["companyId"])
        self.assertEqual(1, self._human_account_count())

        status, _headers, reused = call_api(
            "/api/matm/human/accounts",
            "POST",
            {
                "username": "second-memory-owner",
                "password": secrets.token_urlsafe(36),
                "displayName": "Second Memory Owner",
                "companyMasterProofSecret": proof_secret,
            },
            extra_headers=self._public_mutation_headers(),
        )
        self._assert_error(status, reused, 410, "company_master_proof_used")
        self.assertEqual(1, self._human_account_count())
        self.assertTrue(account["humanAccountId"])
        self._assert_not_persisted(
            self.password,
            self.primary["companyMasterTokenSecret"],
            expired_proof,
            proof_secret,
        )

    def test_password_account_links_multiple_companies_and_requires_explicit_selection(self):
        second = self._create_company("Second Portable Company", "Second Workspace", "Second Project")
        account, session, primary_membership = self._create_human_account(self.primary)

        status, _headers, no_selection = self._human_call(
            session,
            "/api/matm/human/companies/%s/export-plan" % self.primary["companyId"],
        )
        self._assert_error(status, no_selection, 409, "selected_company_required")

        session = self._reauth(session)
        second_membership, second_proof = self._link_company(session, second)
        status, _headers, reused_link_proof = self._human_call(
            session,
            "/api/matm/human/company-memberships/link",
            "POST",
            {"companyMasterProofSecret": second_proof},
        )
        self._assert_error(status, reused_link_proof, 410, "company_master_proof_used")
        memberships = self._memberships(session)
        self.assertEqual(
            {self.primary["companyId"], second["companyId"]},
            {item["companyId"] for item in memberships["items"]},
        )

        status, _headers, inspected = self._human_call(session, "/api/matm/human/session")
        self.assertEqual(200, status)
        self.assertIsNone(inspected["humanSession"]["selectedCompanyId"])
        session = self._select_company(session, primary_membership["authorityId"], self.primary["companyId"])
        plan = self._export_plan(session)
        self.assertEqual(account["humanAccountId"], plan["auditActor"]["humanAccountId"])
        self.assertEqual(self.username, plan["auditActor"]["username"])
        status, _headers, history = self._human_call(
            session,
            "/api/matm/human/companies/%s/history" % self.primary["companyId"],
        )
        self.assertEqual(200, status)
        self.assertEqual("human_only", history["visibility"])
        self.assertEqual(account["humanAccountId"], history["auditActor"]["humanAccountId"])
        self._assert_no_governed_secret(history)
        receipt_id, company_export = self._export_company(session, account)
        self.assertTrue(receipt_id)
        self.assertEqual(self.primary["companyId"], company_export["company"]["companyId"])

        status, _headers, wrong_selection = self._human_call(
            session,
            "/api/matm/human/companies/%s/export-plan" % second["companyId"],
        )
        self._assert_error(status, wrong_selection, 404, "human_company_not_found")
        session = self._select_company(session, second_membership["authorityId"], second["companyId"])
        self._export_plan(session, second)

        self._assert_not_persisted(
            self.password,
            self.primary["companyMasterTokenSecret"],
            second["companyMasterTokenSecret"],
            second_proof,
        )

    def test_password_reauth_rotates_session_and_origin_csrf_fetch_metadata_logout_are_enforced(self):
        _account, created_session, primary_membership = self._create_human_account(self.primary)
        status, _headers, signed_out_created = self._human_call(
            created_session,
            "/api/matm/human/session/logout",
            "POST",
            {},
        )
        self.assertEqual(200, status)
        self.assertTrue(signed_out_created["signedOut"])
        status, _headers, wrong_password = call_api(
            "/api/matm/human/session",
            "POST",
            {"username": self.username, "password": secrets.token_urlsafe(24)},
            extra_headers=self._public_mutation_headers(),
        )
        self._assert_error(status, wrong_password, 401, "human_login_failed")
        session = self._login()
        self._assert_session_rotated(created_session, session)

        link_path = "/api/matm/human/company-memberships/link"
        body = {}
        missing_origin_headers = self._human_headers(session)
        missing_origin_headers.pop("HTTP_ORIGIN")
        status, _headers, missing_origin = call_api(link_path, "POST", body, extra_headers=missing_origin_headers)
        self._assert_error(status, missing_origin, 403, "trusted_origin_required")
        status, _headers, cross_site = call_api(
            link_path,
            "POST",
            body,
            extra_headers=self._human_headers(session, fetch_site="cross-site"),
        )
        self._assert_error(status, cross_site, 403, "trusted_origin_required")
        status, _headers, missing_csrf = call_api(
            link_path,
            "POST",
            body,
            extra_headers=self._human_headers(session, include_csrf=False),
        )
        self._assert_error(status, missing_csrf, 403, "csrf_required")

        session = self._select_company(session, primary_membership["authorityId"], self.primary["companyId"])
        status, _headers, rejected_reauth = self._human_call(
            session,
            "/api/matm/human/session/reauth",
            "POST",
            {"password": secrets.token_urlsafe(24)},
        )
        self._assert_error(status, rejected_reauth, 403, "human_reauthentication_failed")
        session = self._reauth(session)

        status, headers, logged_out = self._human_call(
            session,
            "/api/matm/human/session/logout",
            "POST",
            {},
        )
        self.assertEqual(200, status)
        self.assertTrue(logged_out["signedOut"])
        self.assertIn("Max-Age=0", _header(headers, "Set-Cookie", ""))
        self._assert_session_invalid(session)

        status, _headers, recovery_as_login = call_api(
            "/api/matm/human/session",
            "POST",
            {"recoverySecret": self.primary["humanOwnerRecoverySecret"]},
            extra_headers=self._public_mutation_headers(),
        )
        self._assert_error(status, recovery_as_login, 400, "username_password_required")
        self._assert_not_persisted(self.password)

    def test_master_and_agent_bearers_cannot_use_human_management_history_or_export(self):
        agent = self._provision_agent()
        credential_id = agent["principal"]["credentialId"]
        status, _headers, master_me = call_api("/api/matm/me", token=self.primary["companyMasterTokenSecret"])
        self.assertEqual(200, status)
        self.assertEqual("company_master", master_me["principal"]["credentialType"])
        self.assertEqual(self.primary["credentialId"], master_me["principal"]["credentialId"])
        status, _headers, master_inventory = call_api(
            "/api/matm/access/agent-tokens",
            token=self.primary["companyMasterTokenSecret"],
        )
        self.assertEqual(200, status)
        self.assertTrue(any(item["credentialId"] == credential_id for item in master_inventory["items"]))
        self._assert_no_governed_secret(master_inventory)
        calls = (
            ("GET", "/api/matm/human/company-memberships", None),
            ("GET", "/api/matm/human/companies/%s/history" % self.primary["companyId"], None),
            ("GET", "/api/matm/human/companies/%s/export-plan" % self.primary["companyId"], None),
            ("GET", "/api/matm/human/companies/%s/agent-tokens" % self.primary["companyId"], None),
            (
                "POST",
                "/api/matm/human/companies/%s/agent-tokens/%s/replacements"
                % (self.primary["companyId"], credential_id),
                {"reason": "Bearer credentials cannot authorize replacement"},
            ),
        )
        for bearer in (self.primary["companyMasterTokenSecret"], agent["agentTokenSecret"]):
            for method, path, body in calls:
                with self.subTest(method=method, path=path):
                    status, _headers, payload = call_api(path, method, body, token=bearer)
                    self._assert_error(status, payload, 403, "human_owner_required")

    def test_agent_token_replacement_reveals_successor_once_and_confirms_atomically(self):
        account, session = self._account_session(self.primary)
        agent = self._provision_agent()
        predecessor_secret = agent["agentTokenSecret"]
        predecessor_id = agent["principal"]["credentialId"]
        inventory = self._agent_inventory(session)
        self.assertTrue(any(item["credentialId"] == predecessor_id and item["status"] == "active" for item in inventory["items"]))

        session = self._reauth(session)
        base_path, replacement, successor_secret = self._prepare_replacement(
            session,
            agent,
            "prepare-agent-token-replacement",
        )
        replacement_id = replacement["replacementId"]
        successor_id = replacement["successorCredentialId"]
        self.assertEqual(agent["principal"]["agentIdentityId"], replacement["agentIdentityId"])
        self.assertEqual(agent["principal"]["grant"]["grantId"], replacement["immutableGrant"]["grantId"])
        self.assertEqual(agent["principal"]["grant"]["scopeType"], replacement["immutableGrant"]["scopeType"])
        self.assertEqual(agent["principal"]["grant"]["scopeId"], replacement["immutableGrant"]["scopeId"])

        status, _headers, predecessor_me = call_api("/api/matm/me", token=predecessor_secret)
        self.assertEqual(200, status)
        self.assertEqual(predecessor_id, predecessor_me["principal"]["credentialId"])
        status, _headers, inactive_successor = call_api("/api/matm/me", token=successor_secret)
        self._assert_error(status, inactive_successor, 401, "invalid_token")

        status, _headers, prepare_retry = self._human_call(
            session,
            base_path,
            "POST",
            {
                "reason": "Routine credential rotation",
                "expiresInSeconds": 300,
            },
            extra_headers={"HTTP_IDEMPOTENCY_KEY": "prepare-agent-token-replacement"},
        )
        self.assertEqual(200, status)
        self.assertEqual(replacement_id, prepare_retry["replacement"]["replacementId"])
        self.assertTrue(prepare_retry["successorCredentialAlreadyDelivered"])
        self.assertNotIn("successorTokenSecret", prepare_retry)
        self._assert_no_governed_secret(prepare_retry)

        status, _headers, missing_proof = self._confirm_replacement(
            session,
            base_path,
            replacement_id,
            "",
            "confirm-agent-token-replacement-missing-proof",
        )
        self._assert_error(status, missing_proof, 403, "successor_token_proof_required")
        status, _headers, predecessor_still_active = call_api("/api/matm/me", token=predecessor_secret)
        self.assertEqual(200, status)
        self.assertEqual(predecessor_id, predecessor_still_active["principal"]["credentialId"])

        status, _headers, confirmed = self._confirm_replacement(
            session,
            base_path,
            replacement_id,
            successor_secret,
            "confirm-agent-token-replacement",
        )
        self.assertEqual(200, status)
        self.assertEqual("confirmed", confirmed["replacement"]["status"])
        self.assertEqual(predecessor_id, confirmed["replacement"]["revokedCredentialId"])
        self.assertEqual(successor_id, confirmed["replacement"]["activatedCredentialId"])
        self._assert_no_governed_secret(confirmed)

        status, _headers, revoked_predecessor = call_api("/api/matm/me", token=predecessor_secret)
        self._assert_error(status, revoked_predecessor, 401, "invalid_token")
        status, _headers, successor_me = call_api("/api/matm/me", token=successor_secret)
        self.assertEqual(200, status)
        self.assertEqual(successor_id, successor_me["principal"]["credentialId"])
        self.assertEqual(agent["principal"]["agentIdentityId"], successor_me["principal"]["agentIdentityId"])
        self.assertEqual(agent["principal"]["grant"]["grantId"], successor_me["principal"]["grant"]["grantId"])
        self.assertEqual(agent["principal"]["grant"]["scopeType"], successor_me["principal"]["grant"]["scopeType"])
        self.assertEqual(agent["principal"]["grant"]["scopeId"], successor_me["principal"]["grant"]["scopeId"])

        status, _headers, confirm_retry = self._confirm_replacement(
            session,
            base_path,
            replacement_id,
            successor_secret,
            "confirm-agent-token-replacement",
        )
        self.assertEqual(200, status)
        self.assertEqual("confirmed", confirm_retry["replacement"]["status"])
        self.assertNotIn("successorTokenSecret", confirm_retry)
        self._assert_no_governed_secret(confirm_retry)

        inventory = self._agent_inventory(session)
        by_id = {item["credentialId"]: item for item in inventory["items"]}
        self.assertEqual("revoked", by_id[predecessor_id]["status"])
        self.assertEqual("active", by_id[successor_id]["status"])
        self._assert_not_persisted(self.password, predecessor_secret, successor_secret)
        self.assertEqual(account["humanAccountId"], confirmed["auditActor"]["humanAccountId"])

    def test_replacement_cancel_and_expiry_preserve_predecessor(self):
        _account, session = self._account_session(self.primary)
        agent = self._provision_agent(requested_name="replacement-safety-agent")
        predecessor_secret = agent["agentTokenSecret"]

        before_count = self._replacement_count()
        path = "/api/matm/human/companies/%s/agent-tokens/%s/replacements" % (
            self.primary["companyId"],
            agent["principal"]["credentialId"],
        )
        status, _headers, rejected_prepare = self._human_call(
            session,
            path,
            "POST",
            {"reason": "Must require recent password reauthentication"},
        )
        self._assert_error(status, rejected_prepare, 403, "recent_reauthentication_required")
        self.assertEqual(before_count, self._replacement_count())
        session = self._reauth(session)

        base_path, canceled_replacement, canceled_successor = self._prepare_replacement(
            session,
            agent,
            "prepare-canceled-agent-replacement",
        )
        canceled_id = canceled_replacement["replacementId"]
        status, _headers, canceled = self._human_call(
            session,
            "%s/%s/cancel" % (base_path, canceled_id),
            "POST",
            {},
        )
        self.assertEqual(200, status)
        self.assertEqual("canceled", canceled["replacement"]["status"])
        self._assert_no_governed_secret(canceled)
        status, _headers, predecessor_after_cancel = call_api("/api/matm/me", token=predecessor_secret)
        self.assertEqual(200, status)
        self.assertEqual(agent["principal"]["credentialId"], predecessor_after_cancel["principal"]["credentialId"])
        status, _headers, canceled_candidate = call_api("/api/matm/me", token=canceled_successor)
        self._assert_error(status, canceled_candidate, 401, "invalid_token")

        base_path, expiring_replacement, expiring_successor = self._prepare_replacement(
            session,
            agent,
            "prepare-expiring-agent-replacement",
        )
        expiring_id = expiring_replacement["replacementId"]
        self._expire_replacement(expiring_id)
        status, _headers, expired = self._confirm_replacement(
            session,
            base_path,
            expiring_id,
            expiring_successor,
            "confirm-expired-agent-replacement",
        )
        self._assert_error(status, expired, 410, "replacement_expired")
        status, _headers, predecessor_after_expiry = call_api("/api/matm/me", token=predecessor_secret)
        self.assertEqual(200, status)
        self.assertEqual(agent["principal"]["credentialId"], predecessor_after_expiry["principal"]["credentialId"])
        status, _headers, expired_candidate = call_api("/api/matm/me", token=expiring_successor)
        self._assert_error(status, expired_candidate, 401, "invalid_token")
        self._assert_not_persisted(predecessor_secret, canceled_successor, expiring_successor)

    def test_selected_account_lifecycle_export_close_soft_delete_restore_and_permanent_purge(self):
        account, session = self._account_session(self.primary)
        agent = self._provision_agent(requested_name="company-lifecycle-agent")
        receipt_id, _company_export = self._export_company(session, account)

        session = self._reauth(session)
        close_intent = self._create_intent(session, "close")
        status, _headers, closed = self._human_call(
            session,
            "/api/matm/human/companies/%s/close" % self.primary["companyId"],
            "POST",
            {"closureIntentSecret": close_intent, "typedConfirmationPhrase": self.primary["companyLabel"]},
        )
        self.assertEqual(200, status)
        self.assertEqual("closed", closed["status"])
        self.assertEqual(account["humanAccountId"], closed["auditActor"]["humanAccountId"])
        for governed_token in (self.primary["companyMasterTokenSecret"], agent["agentTokenSecret"]):
            status, _headers, rejected = call_api("/api/matm/me", token=governed_token)
            self._assert_error(status, rejected, 401, "invalid_token")

        session = self._reauth(session)
        delete_intent = self._create_intent(session, "delete")
        status, _headers, deleted = self._human_call(
            session,
            "/api/matm/human/companies/%s/delete" % self.primary["companyId"],
            "POST",
            {"closureIntentSecret": delete_intent, "typedConfirmationPhrase": self.primary["companyLabel"]},
        )
        self.assertEqual(200, status)
        self.assertEqual("deleted", deleted["status"])
        self.assertTrue(deleted["restorable"])
        self.assertTrue(deleted["retainedIndefinitely"])
        self.assertTrue(deleted["countsTowardCompanyQuota"])
        self._export_plan(session)

        status, _headers, restored = self._human_call(
            session,
            "/api/matm/human/companies/%s/restore" % self.primary["companyId"],
            "POST",
            {},
        )
        self.assertEqual(200, status)
        self.assertTrue(restored["restored"])
        self.assertEqual("closed", restored["status"])

        session = self._reauth(session)
        delete_again_intent = self._create_intent(session, "delete")
        status, _headers, _deleted_again = self._human_call(
            session,
            "/api/matm/human/companies/%s/delete" % self.primary["companyId"],
            "POST",
            {"closureIntentSecret": delete_again_intent, "typedConfirmationPhrase": self.primary["companyLabel"]},
        )
        self.assertEqual(200, status)

        session = self._reauth(session)
        purge_intent = self._create_intent(session, "permanent_purge")
        status, _headers, purged = self._human_call(
            session,
            "/api/matm/human/companies/%s/permanent-purge" % self.primary["companyId"],
            "POST",
            {
                "closureIntentSecret": purge_intent,
                "typedConfirmationPhrase": "PERMANENTLY PURGE " + self.primary["companyLabel"],
                "exportReceiptId": receipt_id,
            },
        )
        self.assertEqual(200, status)
        self.assertTrue(purged["purged"])
        self.assertEqual(account["humanAccountId"], purged["auditActor"]["humanAccountId"])

        fresh_session = self._login()
        memberships = self._memberships(fresh_session)
        self.assertFalse(any(item["companyId"] == self.primary["companyId"] for item in memberships["items"]))

    def test_recovery_secret_only_opens_restricted_exceptional_closure_session(self):
        status, headers, payload = call_api(
            "/api/matm/human/recovery/closure-session",
            "POST",
            {"recoverySecret": self.primary["humanOwnerRecoverySecret"]},
            extra_headers=self._public_mutation_headers(),
        )
        self.assertEqual(201, status)
        self.assertEqual("recovery_closure", payload["principal"]["authMode"])
        self.assertEqual(self.primary["companyId"], payload["principal"]["selectedCompanyId"])
        self.assertTrue(payload["principal"]["permissions"]["canExportCompany"])
        self.assertTrue(payload["principal"]["permissions"]["canCloseCompany"])
        self.assertFalse(payload["principal"]["permissions"]["canLinkCompanies"])
        self.assertFalse(payload["principal"]["permissions"]["canManageAgentTokens"])
        session = self._session_from_response(headers, payload)

        status, _headers, denied_memberships = self._human_call(
            session,
            "/api/matm/human/company-memberships",
        )
        self._assert_error(status, denied_memberships, 403, "recovery_session_restricted")
        status, _headers, denied_inventory = self._human_call(
            session,
            "/api/matm/human/companies/%s/agent-tokens" % self.primary["companyId"],
        )
        self._assert_error(status, denied_inventory, 403, "recovery_session_restricted")

        self._export_plan(session)
        close_intent = self._create_intent(session, "close")
        status, _headers, closed = self._human_call(
            session,
            "/api/matm/human/companies/%s/close" % self.primary["companyId"],
            "POST",
            {"closureIntentSecret": close_intent, "typedConfirmationPhrase": self.primary["companyLabel"]},
        )
        self.assertEqual(200, status)
        self.assertEqual("closed", closed["status"])
        self.assertEqual("recovery_closure", closed["auditActor"]["authMode"])
        self._assert_not_persisted(self.primary["humanOwnerRecoverySecret"])


class FileStoreHumanAccountCompanyLifecycleTests(HumanAccountCompanyLifecycleContract, unittest.TestCase):
    backend = "file"


class SQLiteHumanAccountCompanyLifecycleTests(HumanAccountCompanyLifecycleContract, unittest.TestCase):
    backend = "sqlite"


if __name__ == "__main__":
    unittest.main()
