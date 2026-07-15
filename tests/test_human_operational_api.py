import io
import json
import os
from pathlib import Path
import secrets
import shutil
import tempfile
import unittest
from unittest import mock
from concurrent.futures import ThreadPoolExecutor

from memoryendpoints import app
from memoryendpoints.config import SITE_URL
from memoryendpoints.human_operational import route_human_operational
from memoryendpoints.storage import FileStore, SQLiteStore


ORIGIN = SITE_URL.rstrip("/")
AUDIT_ACTOR_FIELDS = {
    "humanAccountId",
    "humanAccountSessionId",
    "username",
    "authorityId",
    "companyId",
    "workspaceId",
    "projectId",
    "authMode",
}


class UnreadableBody:
    def __init__(self):
        self.read_count = 0

    def read(self, _size=-1):
        self.read_count += 1
        raise AssertionError("request body must not be read")


class ExplodingStore:
    def __init__(self):
        self.touched = False

    def __getattr__(self, _name):
        self.touched = True
        raise AssertionError("storage must not be touched")


class HumanOperationalContract:
    backend = None
    store_class = None

    def setUp(self):
        self.tempdir = tempfile.mkdtemp(
            prefix="memoryendpoints-human-operational-%s-" % self.backend
        )
        self._saved_environment = {
            "MEMORYENDPOINTS_CREDENTIAL_PEPPER": os.environ.get(
                "MEMORYENDPOINTS_CREDENTIAL_PEPPER"
            )
        }
        os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = secrets.token_urlsafe(
            48
        )
        suffix = "json" if self.backend == "file" else "sqlite3"
        self.path = Path(self.tempdir) / ("store." + suffix)
        self.store = self.store_class(self.path)
        self.primary = self._create_company(
            "Human Operational Workspace",
            "Human Operational Company",
            "Human Operational Project",
        )
        self.secondary = self._create_company(
            "Other Workspace", "Other Company", "Other Project"
        )
        proof = self.store.create_company_master_proof(self.primary["master"])
        created = self.store.create_human_account_with_session(
            "operational-owner",
            "a unique human operational passphrase 123",
            proof["masterProofSecret"],
            "Operational Owner",
        )
        self.assertTrue(created["ok"])
        self.account = created["account"]
        self.membership = created["membership"]
        selected = self.store.select_human_company_membership(
            created["sessionSecret"], self.membership["authorityId"]
        )
        self.assertTrue(selected["ok"])
        self.session = {
            "secret": selected["sessionSecret"],
            "csrf": selected["csrfToken"],
        }

    def tearDown(self):
        previous = self._saved_environment["MEMORYENDPOINTS_CREDENTIAL_PEPPER"]
        if previous is None:
            os.environ.pop("MEMORYENDPOINTS_CREDENTIAL_PEPPER", None)
        else:
            os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = previous
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def _create_company(self, workspace_label, company_label, project_label):
        values = self.store.create_free_account(
            workspace_label, company_label, project_label
        )
        return {
            "workspaceId": values[0],
            "masterKeyId": values[1],
            "master": values[2],
            "accountId": values[3],
            "companyId": values[4],
            "projectId": values[5],
        }

    def _call(
        self,
        path,
        method="GET",
        body=None,
        session=None,
        context_version=None,
        extra_headers=None,
        input_stream=None,
        store=None,
        query_string="",
    ):
        session = self.session if session is None else session
        raw = json.dumps(body).encode("utf-8") if body is not None else b""
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "QUERY_STRING": query_string,
            "CONTENT_TYPE": "application/json" if body is not None else "",
            "CONTENT_LENGTH": str(len(raw)),
            "wsgi.input": input_stream or io.BytesIO(raw),
            "HTTP_SEC_FETCH_SITE": "same-origin",
            "HTTP_SEC_FETCH_MODE": "cors",
            "HTTP_SEC_FETCH_DEST": "empty",
            "HTTP_ORIGIN": ORIGIN,
        }
        if session:
            environ["HTTP_COOKIE"] = (
                "__Host-memoryendpoints-human=" + session.get("secret", "")
            )
            if session.get("csrf"):
                environ["HTTP_X_CSRF_TOKEN"] = session["csrf"]
        if context_version:
            environ["HTTP_X_MEMORYENDPOINTS_CONTEXT_VERSION"] = context_version
        environ.update(extra_headers or {})
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = list(headers)

        chunks = route_human_operational(
            environ, start_response, path, store or self.store, SITE_URL
        )
        raw_response = b"".join(chunks)
        payload = json.loads(raw_response.decode("utf-8"))
        return int(captured["status"].split(" ", 1)[0]), captured["headers"], payload

    def _error_code(self, payload):
        return (payload.get("error") or {}).get("code")

    def _header(self, headers, name):
        wanted = name.lower()
        return next(
            (value for key, value in headers if key.lower() == wanted), None
        )

    def _catalog(self, session=None):
        status, headers, payload = self._call(
            "/api/matm/human/operational/context-catalog", session=session
        )
        self.assertEqual(200, status, payload)
        self.assertIn("private", self._header(headers, "Cache-Control"))
        self.assertFalse(payload["csrfTokenRotated"])
        self.assertEqual(payload["contextVersion"], payload["resourceContext"]["contextVersion"])
        return payload

    def _select_resource(self):
        catalog = self._catalog()
        status, headers, payload = self._call(
            "/api/matm/human/session/resource-context",
            "POST",
            {
                "authorityId": self.membership["authorityId"],
                "workspaceId": self.primary["workspaceId"],
                "projectId": self.primary["projectId"],
                "contextVersion": catalog["contextVersion"],
            },
        )
        self.assertEqual(200, status, payload)
        cookie = self._header(headers, "Set-Cookie")
        self.assertTrue(cookie)
        self.session = {
            "secret": cookie.split(";", 1)[0].split("=", 1)[1],
            "csrf": payload["csrfToken"],
        }
        self.assertTrue(payload["csrfTokenRotated"])
        self.assertTrue(payload["sessionRotated"])
        self.assertNotEqual(catalog["contextVersion"], payload["contextVersion"])
        self.assertEqual(AUDIT_ACTOR_FIELDS, set(payload["auditActor"]))
        return catalog, payload

    def _memory_count(self):
        if self.backend == "file":
            return len(self.store._load()["memoryEvents"])
        with self.store._open_connection() as connection:
            return connection.execute(
                "SELECT COUNT(*) AS count FROM matm_memory_records"
            ).fetchone()["count"]

    def _set_role(self, role):
        if self.backend == "file":
            data = self.store._load()
            data["humanCompanyAuthorities"][self.membership["authorityId"]][
                "role"
            ] = role
            self.store._save(data)
            return
        with self.store._open_connection() as connection:
            with connection:
                connection.execute(
                    "UPDATE matm_human_company_authorities SET role = ? WHERE authority_id = ?",
                    (role, self.membership["authorityId"]),
                )

    def test_authorization_is_rejected_before_body_or_storage(self):
        unreadable = UnreadableBody()
        exploding = ExplodingStore()
        status, _headers, payload = self._call(
            "/api/matm/human/operational/memory-events/submit",
            "POST",
            session={},
            extra_headers={
                "HTTP_AUTHORIZATION": "Bearer machine-token",
                "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": "8192",
            },
            input_stream=unreadable,
            store=exploding,
        )
        self.assertEqual(403, status)
        self.assertEqual("human_authorization_forbidden", self._error_code(payload))
        self.assertEqual(0, unreadable.read_count)
        self.assertFalse(exploding.touched)

    def test_csrf_and_same_origin_boundary_fail_closed(self):
        missing = dict(self.session, csrf="")
        status, _headers, payload = self._call(
            "/api/matm/human/operational/context-catalog", session=missing
        )
        self.assertEqual(403, status)
        self.assertEqual("human_csrf_required", self._error_code(payload))

        wrong = dict(self.session, csrf="not-the-session-csrf")
        status, _headers, payload = self._call(
            "/api/matm/human/operational/context-catalog", session=wrong
        )
        self.assertEqual(403, status)
        self.assertEqual("human_csrf_invalid", self._error_code(payload))

        status, _headers, payload = self._call(
            "/api/matm/human/operational/context-catalog",
            extra_headers={"HTTP_SEC_FETCH_SITE": "cross-site"},
        )
        self.assertEqual(403, status)
        self.assertEqual("human_trusted_origin_required", self._error_code(payload))

    def test_context_selection_is_explicit_rotating_and_company_scoped(self):
        catalog = self._catalog()
        self.assertIsNone(catalog["resourceContext"]["workspaceId"])
        self.assertIsNone(catalog["resourceContext"]["projectId"])
        old_session = dict(self.session)
        status, headers, payload = self._call(
            "/api/matm/human/session/resource-context",
            "POST",
            {
                "authorityId": self.membership["authorityId"],
                "workspaceId": self.secondary["workspaceId"],
                "projectId": self.secondary["projectId"],
                "contextVersion": catalog["contextVersion"],
            },
        )
        self.assertEqual(403, status)
        self.assertEqual(
            "human_resource_context_cross_company", self._error_code(payload)
        )
        self.assertIsNone(self._header(headers, "Set-Cookie"))
        self.assertIsNotNone(
            self.store.authenticate_human_account_session(old_session["secret"])
        )

        _catalog, selected = self._select_resource()
        self.assertEqual(self.primary["workspaceId"], selected["resourceContext"]["workspaceId"])
        self.assertEqual(self.primary["projectId"], selected["resourceContext"]["projectId"])
        self.assertIsNone(
            self.store.authenticate_human_account_session(old_session["secret"])
        )

    def test_stale_context_is_rejected_before_operational_work(self):
        catalog, selected = self._select_resource()
        original = self.store.search_memory

        def forbidden_work(*_args, **_kwargs):
            raise AssertionError("stale context reached protected search work")

        self.store.search_memory = forbidden_work
        try:
            status, _headers, payload = self._call(
                "/api/matm/human/operational/search",
                context_version=catalog["contextVersion"],
            )
        finally:
            self.store.search_memory = original
        self.assertEqual(409, status)
        self.assertEqual("human_resource_context_stale", self._error_code(payload))

        status, _headers, payload = self._call(
            "/api/matm/human/operational/search",
            context_version=selected["contextVersion"],
        )
        self.assertEqual(200, status, payload)
        self.assertEqual(selected["contextVersion"], payload["contextVersion"])

    def test_company_and_csrf_transitions_preserve_the_frozen_context_rules(self):
        _catalog, selected = self._select_resource()
        rotated_csrf = self.store.rotate_human_account_session_csrf(
            self.session["secret"]
        )
        self.assertTrue(rotated_csrf["ok"])
        self.session["csrf"] = rotated_csrf["csrfToken"]
        after_csrf = self._catalog()
        self.assertEqual(selected["contextVersion"], after_csrf["contextVersion"])

        switched = self.store.select_human_company_membership(
            self.session["secret"], self.membership["authorityId"]
        )
        self.assertTrue(switched["ok"])
        self.session = {
            "secret": switched["sessionSecret"],
            "csrf": switched["csrfToken"],
        }
        after_company = self._catalog()
        self.assertIsNone(after_company["resourceContext"]["workspaceId"])
        self.assertIsNone(after_company["resourceContext"]["projectId"])
        self.assertNotEqual(selected["contextVersion"], after_company["contextVersion"])

    def test_permission_map_is_server_enforced_and_denied_lanes_stay_hidden(self):
        _catalog, selected = self._select_resource()
        self._set_role("credential_admin")
        status, _headers, payload = self._call(
            "/api/matm/human/operational/memory-events/submit",
            "POST",
            {
                "title": "Denied write",
                "summary": "This write must remain a safe no-op.",
            },
            context_version=selected["contextVersion"],
            extra_headers={"HTTP_IDEMPOTENCY_KEY": "denied-memory-0001"},
        )
        self.assertEqual(403, status)
        self.assertEqual("human_operation_not_permitted", self._error_code(payload))
        self.assertEqual(0, self._memory_count())

        status, _headers, payload = self._call(
            "/api/matm/human/operational/collaboration", context_version=selected["contextVersion"]
        )
        self.assertEqual(403, status)
        self.assertEqual("human_operation_not_permitted", self._error_code(payload))

    def test_memory_submit_is_atomic_idempotent_and_genuinely_human_attributed(self):
        _catalog, selected = self._select_resource()
        body = {
            "title": "Human operational decision",
            "summary": "Use server-derived human attribution for this public-safe memory.",
            "tags": ["human-operational"],
            "memoryType": "decision",
            "scope": "project",
            "scopeId": self.primary["projectId"],
        }
        headers = {"HTTP_IDEMPOTENCY_KEY": "human-memory-lost-response-0001"}
        first_status, _first_headers, first = self._call(
            "/api/matm/human/operational/memory-events/submit",
            "POST",
            body,
            context_version=selected["contextVersion"],
            extra_headers=headers,
        )
        second_status, _second_headers, second = self._call(
            "/api/matm/human/operational/memory-events/submit",
            "POST",
            body,
            context_version=selected["contextVersion"],
            extra_headers=headers,
        )
        self.assertEqual(201, first_status, first)
        self.assertEqual(201, second_status, second)
        self.assertFalse(first["idempotentReplay"])
        self.assertTrue(second["idempotentReplay"])
        self.assertEqual(first["event"]["eventId"], second["event"]["eventId"])
        self.assertEqual(1, self._memory_count())
        self.assertFalse(first["csrfTokenRotated"])
        self.assertNotIn("csrfToken", first)
        self.assertNotIn("actorAgentId", first["event"])
        self.assertEqual(AUDIT_ACTOR_FIELDS, set(first["auditActor"]))
        self.assertEqual(first["auditActor"], first["event"]["auditActor"])
        self.assertEqual(self.account["humanAccountId"], first["auditActor"]["humanAccountId"])
        self.assertEqual(self.primary["projectId"], first["auditActor"]["projectId"])

        items = self.store.search_memory(
            self.primary["workspaceId"],
            "server-derived",
            {"scope": "project", "scopeId": self.primary["projectId"]},
        )
        self.assertEqual(1, len(items))
        self.assertNotIn("actorAgentId", items[0])
        self.assertEqual(first["auditActor"], items[0]["auditActor"])

        if self.backend == "file":
            data = self.store._load()
            audit = next(
                item
                for item in data["auditLog"]
                if item.get("action") == "human.memory.submit"
            )
            self.assertEqual(first["auditActor"], audit["details"]["auditActor"])
        else:
            with self.store._open_connection() as connection:
                row = connection.execute(
                    "SELECT * FROM matm_memory_records WHERE memory_id = ?",
                    (first["event"]["eventId"],),
                ).fetchone()
                self.assertIsNone(row["actor_agent_id"])
                self.assertEqual("human_account", row["auth_mode"])
                self.assertEqual(
                    first["auditActor"]["humanAccountSessionId"],
                    row["human_account_session_id"],
                )
                audit = connection.execute(
                    "SELECT details_json FROM matm_audit_log WHERE action = 'human.memory.submit'"
                ).fetchone()
                self.assertEqual(
                    first["auditActor"],
                    json.loads(audit["details_json"])["auditActor"],
                )

    def test_agent_memory_contract_remains_agent_shaped(self):
        event = self.store.submit_memory(
            self.primary["workspaceId"],
            "bearer-agent-regression",
            "project",
            "Agent memory",
            "The existing bearer-only agent memory path remains unchanged.",
            ["bearer-regression"],
            "api",
            scope_id=self.primary["projectId"],
        )
        self.assertEqual("bearer-agent-regression", event["actorAgentId"])
        self.assertNotIn("auditActor", event)
        found = self.store.search_memory(
            self.primary["workspaceId"],
            "bearer-only",
            {"scope": "project", "scopeId": self.primary["projectId"]},
        )
        self.assertEqual("bearer-agent-regression", found[0]["actorAgentId"])
        self.assertNotIn("auditActor", found[0])

    def test_user_supplied_agent_attribution_is_rejected_without_persistence(self):
        _catalog, selected = self._select_resource()
        status, _headers, payload = self._call(
            "/api/matm/human/operational/memory-events/submit",
            "POST",
            {
                "title": "Spoof attempt",
                "summary": "This must not synthesize an agent actor.",
                "actorAgentId": "spoofed-agent",
            },
            context_version=selected["contextVersion"],
            extra_headers={"HTTP_IDEMPOTENCY_KEY": "spoofed-memory-0001"},
        )
        self.assertEqual(422, status)
        self.assertEqual("human_memory_payload_invalid", self._error_code(payload))
        self.assertEqual(0, self._memory_count())

    def test_concurrent_idempotent_submit_serializes_to_one_human_memory(self):
        _catalog, selected = self._select_resource()
        payload = {
            "title": "Concurrent human memory",
            "summary": "Concurrent retries serialize to one human-attributed record.",
            "tags": ["concurrency"],
            "memoryType": "evidence",
            "subject": "Concurrent human memory",
        }

        def submit():
            return self.store.submit_human_operational_memory(
                self.session["secret"],
                self.session["csrf"],
                selected["contextVersion"],
                "human-memory-concurrent-0001",
                payload,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _index: submit(), range(2)))
        self.assertTrue(all(item.get("ok") for item in results), results)
        self.assertEqual(
            [False, True], sorted(item["idempotentReplay"] for item in results)
        )
        self.assertEqual(
            1, len({item["event"]["eventId"] for item in results})
        )
        self.assertEqual(1, self._memory_count())

    def test_all_read_operations_are_context_bound_and_internet_search_is_stored_only(self):
        document, error = self.store.upsert_knowledge_document(
            self.primary["workspaceId"],
            "seed-agent",
            {
                "scope": "project",
                "scopeId": self.primary["projectId"],
                "projectId": self.primary["projectId"],
                "title": "Human operational guide",
                "content": "Context-bound human operational knowledge.",
                "category": "operations",
                "source": "memoryendpoints://human-operational-guide",
            },
        )
        self.assertIsNone(error)
        _link, link_error = self.store.upsert_external_link(
            self.primary["workspaceId"],
            "seed-agent",
            {
                "url": "https://example.com/human-operational-guide",
                "siteName": "Example Documentation",
                "pageTitle": "Human Operational Guide",
                "description": "Stored reviewed reference for human operations.",
                "reviewStatus": "reviewed",
                "knowledgeDocumentId": document["searchDocumentId"],
                "relationshipType": "reference",
            },
        )
        self.assertIsNone(link_error)
        self.store.submit_memory(
            self.primary["workspaceId"],
            "seed-agent",
            "project",
            "Context-bound search",
            "Search result visible only in the selected project context.",
            ["context-bound"],
            "api",
            scope_id=self.primary["projectId"],
        )
        _catalog, selected = self._select_resource()
        version = selected["contextVersion"]
        routes = (
            ("/api/matm/human/operational/workspace", ""),
            ("/api/matm/human/operational/search", "q=context-bound"),
            ("/api/matm/human/operational/knowledge-tree", "q=operational"),
            ("/api/matm/human/operational/knowledge-documents", "q=operational"),
            ("/api/matm/human/operational/external-links", "q=operational"),
            ("/api/matm/human/operational/internet-search", "q=operational"),
        )
        for route, query_string in routes:
            with self.subTest(route=route):
                status, _headers, payload = self._call(
                    route,
                    context_version=version,
                    query_string=query_string,
                )
                self.assertEqual(200, status, payload)
                self.assertEqual(version, payload["contextVersion"])
                self.assertEqual(
                    selected["resourceContext"], payload["resourceContext"]
                )
                self.assertEqual(AUDIT_ACTOR_FIELDS, set(payload["auditActor"]))
                self.assertFalse(payload["csrfTokenRotated"])
        status, _headers, internet = self._call(
            "/api/matm/human/operational/internet-search",
            context_version=version,
            query_string="q=operational",
        )
        self.assertEqual(200, status)
        self.assertTrue(internet["curatedOnly"])
        self.assertFalse(internet["liveNetworkRequestMade"])


class HumanOperationalAppDispatchTests(unittest.TestCase):
    def test_app_rejects_authorization_without_constructing_store_or_reading_body(self):
        unreadable = UnreadableBody()
        environ = {
            "PATH_INFO": "/api/matm/human/operational/memory-events/submit",
            "REQUEST_METHOD": "POST",
            "QUERY_STRING": "",
            "CONTENT_TYPE": "application/json",
            "CONTENT_LENGTH": "8192",
            "wsgi.input": unreadable,
            "HTTP_AUTHORIZATION": "Bearer machine-token",
        }
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = headers

        with mock.patch.object(
            app, "_store", side_effect=AssertionError("store constructed")
        ):
            payload = json.loads(
                b"".join(app.application(environ, start_response)).decode("utf-8")
            )
        self.assertEqual("403 Forbidden", captured["status"])
        self.assertEqual(
            "human_authorization_forbidden", payload["error"]["code"]
        )
        self.assertEqual(0, unreadable.read_count)


class FileStoreHumanOperationalTests(HumanOperationalContract, unittest.TestCase):
    backend = "file"
    store_class = FileStore


class SQLiteStoreHumanOperationalTests(HumanOperationalContract, unittest.TestCase):
    backend = "sqlite"
    store_class = SQLiteStore


if __name__ == "__main__":
    unittest.main()
