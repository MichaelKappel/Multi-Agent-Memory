"""Cross-process atomicity contracts for SQLite connector pairing."""

import base64
from contextlib import closing
import hashlib
import multiprocessing
import os
from pathlib import Path
import queue
import secrets
import shutil
import sqlite3
import tempfile
import unittest

from memoryendpoints.connector_pairing import (
    CANONICAL_AGENT_ID,
    CLIENT_ID,
    V1_REQUESTED_SCOPES,
    generate_state,
)
from memoryendpoints.storage import SQLiteStore


REDIRECT_URI = "http://127.0.0.1:53682/memoryendpoints/callback"
PROCESS_TIMEOUT_SECONDS = 60


def _digest(label):
    return "sha256-v1:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _challenge(verifier):
    raw = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _fingerprint(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None


def _project_result(label, method, result):
    resource = (
        result.get("pairingRequest")
        or result.get("approval")
        or result.get("pairing")
        or result.get("rotation")
        or {}
    )
    secret = (
        result.get("pairingRequestProof")
        or result.get("authorizationCode")
        or result.get("connectorCredentialSecret")
    )
    return {
        "kind": "result",
        "label": label,
        "method": method,
        "ok": bool(result.get("ok")),
        "status": result.get("status") if not result.get("ok") else resource.get("status") or result.get("status"),
        "idempotentReplay": bool(result.get("idempotentReplay")),
        "publicRequestRef": result.get("publicRequestRef") or resource.get("publicRequestRef"),
        "pairingId": resource.get("pairingId"),
        "rotationId": resource.get("rotationId"),
        "credentialId": resource.get("credentialId"),
        "secretFingerprint": _fingerprint(secret),
    }


def _worker(database_path, pepper, start_event, ready_queue, result_queue, spec):
    label = spec["label"]
    method = spec["method"]
    try:
        os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = pepper
        store = SQLiteStore(Path(database_path))
        ready_queue.put(label)
        if not start_event.wait(PROCESS_TIMEOUT_SECONDS):
            raise RuntimeError("worker_start_timeout")
        function = {
            "create": store.create_connector_pairing_request,
            "approve": store.approve_connector_pairing_request,
            "cancel_request": store.cancel_connector_pairing_request,
            "claim": store.claim_connector_authorization_code,
            "exchange": store.exchange_connector_authorization_code,
            "prepare_rotation": store.prepare_connector_rotation,
            "activate_pairing": store.activate_connector_pairing,
            "cancel_pairing": store.cancel_connector_pairing,
        }[method]
        result = function(*spec["args"])
        result_queue.put(_project_result(label, method, result))
    except BaseException as exc:  # pragma: no cover - reported to parent assertion
        result_queue.put(
            {
                "kind": "exception",
                "label": label,
                "method": method,
                "errorType": exc.__class__.__name__,
                "error": str(exc)[:200],
            }
        )


class SQLiteConnectorPairingConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="connector-concurrency-")
        self.database_path = Path(self.tempdir) / "store.sqlite3"
        self.previous_pepper = os.environ.get("MEMORYENDPOINTS_CREDENTIAL_PEPPER")
        self.pepper = secrets.token_urlsafe(48)
        os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = self.pepper
        self.store = SQLiteStore(self.database_path)
        (
            self.workspace_id,
            _master_key_id,
            master_token,
            _account_id,
            _company_id,
            _project_id,
            _recovery_secret,
        ) = self.store.create_free_account(
            "Concurrency Workspace", "Concurrency Company", "Concurrency Project"
        )
        self.password = secrets.token_urlsafe(36)
        proof = self.store.create_company_master_proof(master_token)
        created = self.store.create_human_account(
            "concurrency-owner", self.password, proof["masterProofSecret"]
        )
        self.assertTrue(created["ok"], created)
        login = self.store.login_human_account("concurrency-owner", self.password)
        memberships = self.store.list_human_company_memberships(login["sessionSecret"])
        selected = self.store.select_human_company_membership(
            login["sessionSecret"], memberships["items"][0]["authorityId"]
        )
        self.session_secret = selected["sessionSecret"]
        self.assertTrue(
            self.store.reauthenticate_human_account_session(
                self.session_secret, self.password
            )["ok"]
        )

    def tearDown(self):
        if self.previous_pepper is None:
            os.environ.pop("MEMORYENDPOINTS_CREDENTIAL_PEPPER", None)
        else:
            os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = self.previous_pepper
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def _payload(self):
        verifier = secrets.token_urlsafe(48)
        state = generate_state()
        return {
            "clientId": CLIENT_ID,
            "redirectUri": REDIRECT_URI,
            "state": state,
            "codeChallenge": _challenge(verifier),
            "codeChallengeMethod": "S256",
            "requestedAgentId": CANONICAL_AGENT_ID,
            "requestedScopes": list(V1_REQUESTED_SCOPES),
        }, verifier, state

    def _request(self, label):
        payload, verifier, state = self._payload()
        result = self.store.create_connector_pairing_request(
            payload,
            "request-%s-concurrency" % label,
            _digest("request-" + label),
        )
        self.assertTrue(result["ok"], result)
        return result, payload, verifier, state

    def _approve(self, request, label):
        catalog = self.store.human_connector_scope_catalog(
            self.session_secret, request["publicRequestRef"]
        )
        result = self.store.approve_connector_pairing_request(
            self.session_secret,
            request["publicRequestRef"],
            {
                "mode": "existing",
                "workspaceRef": catalog["workspaces"][0]["workspaceRef"],
            },
            list(V1_REQUESTED_SCOPES),
            "approve-%s-concurrency" % label,
            _digest("approve-" + label),
        )
        self.assertTrue(result["ok"], result)
        return result

    def _claim(self, request, payload, state, label):
        result = self.store.claim_connector_authorization_code(
            request["pairingRequestProof"],
            state,
            CLIENT_ID,
            payload["redirectUri"],
            "claim-%s-concurrency" % label,
            _digest("claim-" + label),
        )
        self.assertTrue(result["ok"], result)
        return result

    def _pending(self, label):
        request, payload, verifier, state = self._request(label)
        self._approve(request, label)
        claim = self._claim(request, payload, state, label)
        exchange = self.store.exchange_connector_authorization_code(
            claim["authorizationCode"],
            verifier,
            CLIENT_ID,
            REDIRECT_URI,
            "exchange-%s-concurrency" % label,
            _digest("exchange-" + label),
        )
        self.assertTrue(exchange["ok"], exchange)
        return request, payload, verifier, state, claim, exchange

    def _active(self, label):
        _request, _payload, _verifier, _state, _claim, exchange = self._pending(label)
        pairing_id = exchange["pairing"]["pairingId"]
        token = exchange["connectorCredentialSecret"]
        activated = self.store.activate_connector_pairing(
            pairing_id,
            token,
            "activate-%s-concurrency" % label,
            _digest("activate-" + label),
        )
        self.assertTrue(activated["ok"], activated)
        return pairing_id, token

    def _run(self, specs):
        context = multiprocessing.get_context("spawn")
        start_event = context.Event()
        ready_queue = context.Queue()
        result_queue = context.Queue()
        processes = [
            context.Process(
                target=_worker,
                args=(
                    str(self.database_path),
                    self.pepper,
                    start_event,
                    ready_queue,
                    result_queue,
                    spec,
                ),
            )
            for spec in specs
        ]
        try:
            for process in processes:
                process.start()
            for _ in processes:
                ready_queue.get(timeout=PROCESS_TIMEOUT_SECONDS)
            start_event.set()
            results = [
                result_queue.get(timeout=PROCESS_TIMEOUT_SECONDS) for _ in processes
            ]
            for process in processes:
                process.join(PROCESS_TIMEOUT_SECONDS)
                self.assertFalse(process.is_alive(), "connector worker did not exit")
                self.assertEqual(0, process.exitcode)
        finally:
            start_event.set()
            for process in processes:
                if process.is_alive():
                    process.terminate()
                process.join(5)
            for resource in (ready_queue, result_queue):
                resource.close()
                resource.join_thread()
        exceptions = [item for item in results if item.get("kind") == "exception"]
        self.assertEqual([], exceptions, results)
        return sorted(results, key=lambda item: item["label"])

    def test_concurrent_exact_create_has_one_request_and_deterministic_retry(self):
        payload, _verifier, _state = self._payload()
        args = (payload, "same-create-concurrency-key", _digest("same-create"))
        results = self._run(
            [
                {"label": "one", "method": "create", "args": args},
                {"label": "two", "method": "create", "args": args},
            ]
        )
        self.assertTrue(all(item["ok"] for item in results), results)
        self.assertEqual([False, True], sorted(item["idempotentReplay"] for item in results))
        self.assertEqual(1, len({item["publicRequestRef"] for item in results}))
        self.assertEqual(1, len({item["secretFingerprint"] for item in results}))
        with closing(sqlite3.connect(self.database_path)) as connection:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM matm_connector_pairing_requests").fetchone()[0])

    def test_concurrent_claim_different_keys_issues_one_code(self):
        request, payload, _verifier, state = self._request("claim-race")
        self._approve(request, "claim-race")
        base = (
            request["pairingRequestProof"], state, CLIENT_ID, payload["redirectUri"]
        )
        results = self._run(
            [
                {"label": "one", "method": "claim", "args": base + ("claim-race-one-key", _digest("claim-race-one"))},
                {"label": "two", "method": "claim", "args": base + ("claim-race-two-key", _digest("claim-race-two"))},
            ]
        )
        winners = [item for item in results if item["ok"]]
        losers = [item for item in results if not item["ok"]]
        self.assertEqual(1, len(winners), results)
        self.assertEqual(1, len(losers), results)
        self.assertEqual("idempotency_conflict", losers[0]["status"])
        self.assertIsNotNone(winners[0]["secretFingerprint"])

    def test_concurrent_exact_exchange_creates_one_pairing_and_credential(self):
        request, payload, verifier, state = self._request("exchange-race")
        self._approve(request, "exchange-race")
        claim = self._claim(request, payload, state, "exchange-race")
        args = (
            claim["authorizationCode"], verifier, CLIENT_ID, REDIRECT_URI,
            "same-exchange-concurrency-key", _digest("same-exchange"),
        )
        results = self._run(
            [
                {"label": "one", "method": "exchange", "args": args},
                {"label": "two", "method": "exchange", "args": args},
            ]
        )
        self.assertTrue(all(item["ok"] for item in results), results)
        self.assertEqual([False, True], sorted(item["idempotentReplay"] for item in results))
        self.assertEqual(1, len({item["pairingId"] for item in results}))
        self.assertEqual(1, len({item["secretFingerprint"] for item in results}))
        with closing(sqlite3.connect(self.database_path)) as connection:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM matm_connector_pairings").fetchone()[0])
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM matm_connector_credentials").fetchone()[0])

    def test_concurrent_approve_vs_cancel_has_one_terminal_winner(self):
        request, _payload, _verifier, _state = self._request("terminal-race")
        catalog = self.store.human_connector_scope_catalog(
            self.session_secret, request["publicRequestRef"]
        )
        approve_args = (
            self.session_secret,
            request["publicRequestRef"],
            {"mode": "existing", "workspaceRef": catalog["workspaces"][0]["workspaceRef"]},
            list(V1_REQUESTED_SCOPES),
            "approve-terminal-race-key",
            _digest("approve-terminal-race"),
        )
        cancel_args = (
            self.session_secret,
            request["publicRequestRef"],
            "race_cancel",
            "cancel-terminal-race-key",
            _digest("cancel-terminal-race"),
        )
        results = self._run(
            [
                {"label": "approve", "method": "approve", "args": approve_args},
                {"label": "cancel", "method": "cancel_request", "args": cancel_args},
            ]
        )
        self.assertEqual(1, sum(1 for item in results if item["ok"]), results)
        loser = next(item for item in results if not item["ok"])
        self.assertEqual("pairing_request_unavailable", loser["status"])
        with closing(sqlite3.connect(self.database_path)) as connection:
            status = connection.execute(
                "SELECT status FROM matm_connector_pairing_requests WHERE public_request_ref = ?",
                (request["publicRequestRef"],),
            ).fetchone()[0]
        self.assertIn(status, ("approved", "canceled"))

    def test_concurrent_rotation_prepare_creates_one_successor(self):
        pairing_id, token = self._active("rotation-race")
        base = (pairing_id, token, "scheduled")
        results = self._run(
            [
                {"label": "one", "method": "prepare_rotation", "args": base + ("rotation-race-one-key", _digest("rotation-race-one"))},
                {"label": "two", "method": "prepare_rotation", "args": base + ("rotation-race-two-key", _digest("rotation-race-two"))},
            ]
        )
        self.assertEqual(1, sum(1 for item in results if item["ok"]), results)
        loser = next(item for item in results if not item["ok"])
        self.assertEqual("rotation_pending", loser["status"])
        with closing(sqlite3.connect(self.database_path)) as connection:
            self.assertEqual(
                1,
                connection.execute(
                    "SELECT COUNT(*) FROM matm_connector_rotations WHERE pairing_id = ? AND status = 'pending_activation'",
                    (pairing_id,),
                ).fetchone()[0],
            )

    def test_concurrent_activation_vs_cancel_has_one_terminal_winner(self):
        _request, _payload, _verifier, _state, _claim, exchange = self._pending("grant-race")
        pairing_id = exchange["pairing"]["pairingId"]
        token = exchange["connectorCredentialSecret"]
        results = self._run(
            [
                {
                    "label": "activate",
                    "method": "activate_pairing",
                    "args": (pairing_id, token, "activate-grant-race-key", _digest("activate-grant-race")),
                },
                {
                    "label": "cancel",
                    "method": "cancel_pairing",
                    "args": (pairing_id, token, "secure_store_failed", "cancel-grant-race-key", _digest("cancel-grant-race")),
                },
            ]
        )
        self.assertEqual(1, sum(1 for item in results if item["ok"]), results)
        with closing(sqlite3.connect(self.database_path)) as connection:
            status = connection.execute(
                "SELECT status FROM matm_connector_pairings WHERE pairing_id = ?",
                (pairing_id,),
            ).fetchone()[0]
        self.assertIn(status, ("active", "canceled"))


if __name__ == "__main__":
    multiprocessing.freeze_support()
    unittest.main()
