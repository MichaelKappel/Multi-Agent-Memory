import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing

from memoryendpoints.connector_pairing import (
    CANONICAL_AGENT_ID,
    CLIENT_ID,
    V1_REQUESTED_SCOPES,
    connector_scope_digest,
    generate_state,
)
from memoryendpoints.storage import FileStore, SQLiteStore


REDIRECT_URI = "http://127.0.0.1:53682/memoryendpoints/callback"
EXPIRED = "2000-01-01T00:00:00.000000Z"
FORGED_SCOPES = list(V1_REQUESTED_SCOPES) + ["company:admin"]
FORGED_SCOPE_DIGEST = "sha256-v1:" + ("0" * 64)


def _digest(label):
    return "sha256-v1:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _challenge(verifier):
    raw = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


class ConnectorHardeningContract:
    backend = None

    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="connector-hardening-%s-" % self.backend)
        self.path = Path(self.tempdir) / ("store.json" if self.backend == "file" else "store.sqlite3")
        self.previous_pepper = os.environ.get("MEMORYENDPOINTS_CREDENTIAL_PEPPER")
        os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = secrets.token_urlsafe(48)
        self.store = FileStore(self.path) if self.backend == "file" else SQLiteStore(self.path)
        (
            self.workspace_id,
            _master_key_id,
            self.master_token,
            _account_id,
            self.company_id,
            _project_id,
            _recovery_secret,
        ) = self.store.create_free_account(
            "Hardening Workspace", "Hardening Company", "Hardening Project"
        )
        self.password = secrets.token_urlsafe(36)
        proof = self.store.create_company_master_proof(self.master_token)
        account = self.store.create_human_account(
            "hardening-owner", self.password, proof["masterProofSecret"]
        )
        self.assertTrue(account["ok"], account)
        login = self.store.login_human_account("hardening-owner", self.password)
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

    def _persisted_bytes(self):
        return b"\n".join(
            path.read_bytes()
            for path in self.path.parent.glob(self.path.name + "*")
            if path.is_file()
        )

    def _request(self, label):
        verifier = secrets.token_urlsafe(48)
        state = generate_state()
        payload = {
            "clientId": CLIENT_ID,
            "redirectUri": REDIRECT_URI,
            "state": state,
            "codeChallenge": _challenge(verifier),
            "codeChallengeMethod": "S256",
            "requestedAgentId": CANONICAL_AGENT_ID,
            "requestedScopes": list(V1_REQUESTED_SCOPES),
        }
        result = self.store.create_connector_pairing_request(
            payload,
            "request-%s-idempotency" % label,
            _digest("request-" + label),
        )
        self.assertTrue(result["ok"], result)
        return result, payload, verifier, state

    def _approve(self, request, label):
        catalog = self.store.human_connector_scope_catalog(
            self.session_secret, request["publicRequestRef"]
        )
        self.assertTrue(catalog["ok"], catalog)
        result = self.store.approve_connector_pairing_request(
            self.session_secret,
            request["publicRequestRef"],
            {
                "mode": "existing",
                "workspaceRef": catalog["workspaces"][0]["workspaceRef"],
            },
            list(V1_REQUESTED_SCOPES),
            "approve-%s-idempotency" % label,
            _digest("approve-" + label),
        )
        self.assertTrue(result["ok"], result)
        return result

    def _claim(self, request, payload, state, label, key=None, digest=None):
        return self.store.claim_connector_authorization_code(
            request["pairingRequestProof"],
            state,
            CLIENT_ID,
            payload["redirectUri"],
            key or ("claim-%s-idempotency" % label),
            digest or _digest("claim-" + label),
        )

    def _pending(self, label):
        request, payload, verifier, state = self._request(label)
        self._approve(request, label)
        claim = self._claim(request, payload, state, label)
        self.assertTrue(claim["ok"], claim)
        exchange = self.store.exchange_connector_authorization_code(
            claim["authorizationCode"],
            verifier,
            CLIENT_ID,
            REDIRECT_URI,
            "exchange-%s-idempotency" % label,
            _digest("exchange-" + label),
        )
        self.assertTrue(exchange["ok"], exchange)
        return request, claim, exchange

    def _active(self, label):
        _request, _claim, exchange = self._pending(label)
        pairing_id = exchange["pairing"]["pairingId"]
        token = exchange["connectorCredentialSecret"]
        activation = self.store.activate_connector_pairing(
            pairing_id,
            token,
            "activate-%s-idempotency" % label,
            _digest("activate-" + label),
        )
        self.assertTrue(activation["ok"], activation)
        return pairing_id, token

    def _expire_request(self, request, phase):
        field = "expiresAt" if phase == "request" else "authorizationCodeExpiresAt"
        if self.backend == "file":
            data = json.loads(self.path.read_text(encoding="utf-8"))
            record = next(
                item
                for item in data["connectorPairingRequests"].values()
                if item["publicRequestRef"] == request["publicRequestRef"]
            )
            record[field] = EXPIRED
            self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        else:
            column = "expires_at" if phase == "request" else "authorization_code_expires_at"
            with closing(sqlite3.connect(self.path)) as connection:
                with connection:
                    connection.execute(
                        "UPDATE matm_connector_pairing_requests SET %s = ? WHERE public_request_ref = ?"
                        % column,
                        (EXPIRED, request["publicRequestRef"]),
                    )

    def _expire_pairing(self, pairing_id):
        if self.backend == "file":
            data = json.loads(self.path.read_text(encoding="utf-8"))
            data["connectorPairings"][pairing_id]["activationExpiresAt"] = EXPIRED
            self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        else:
            with closing(sqlite3.connect(self.path)) as connection:
                with connection:
                    connection.execute(
                        "UPDATE matm_connector_pairings SET activation_expires_at = ? WHERE pairing_id = ?",
                        (EXPIRED, pairing_id),
                    )

    def _delete_agent_registration(self, pairing_id):
        if self.backend == "file":
            data = json.loads(self.path.read_text(encoding="utf-8"))
            pairing = data["connectorPairings"][pairing_id]
            data["agents"].pop(
                "%s:%s" % (pairing["workspaceId"], pairing["agentId"]), None
            )
            self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        else:
            with closing(sqlite3.connect(self.path)) as connection:
                with connection:
                    row = connection.execute(
                        "SELECT workspace_id, agent_id FROM matm_connector_pairings WHERE pairing_id = ?",
                        (pairing_id,),
                    ).fetchone()
                    connection.execute(
                        "DELETE FROM matm_agents WHERE workspace_id = ? AND agent_id = ?",
                        row,
                    )

    def _tamper_scope_chain(self, pairing_id, rotation_id=None):
        if self.backend == "file":
            data = json.loads(self.path.read_text(encoding="utf-8"))
            pairing = data["connectorPairings"][pairing_id]
            pairing["approvedScopes"] = list(FORGED_SCOPES)
            pairing["scopeDigest"] = FORGED_SCOPE_DIGEST
            for credential in data["connectorCredentials"].values():
                if credential.get("pairingId") == pairing_id:
                    credential["approvedScopes"] = list(FORGED_SCOPES)
                    credential["scopeDigest"] = FORGED_SCOPE_DIGEST
            if rotation_id:
                rotation = data["connectorRotations"][rotation_id]
                rotation["approvedScopes"] = list(FORGED_SCOPES)
                rotation["scopeDigest"] = FORGED_SCOPE_DIGEST
            self.path.write_text(
                json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
            )
            return
        encoded = json.dumps(FORGED_SCOPES, separators=(",", ":"))
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                connection.execute(
                    "UPDATE matm_connector_pairings SET approved_scopes_json = ?, "
                    "scope_digest = ? WHERE pairing_id = ?",
                    (encoded, FORGED_SCOPE_DIGEST, pairing_id),
                )
                connection.execute(
                    "UPDATE matm_connector_credentials SET approved_scopes_json = ?, "
                    "scope_digest = ? WHERE pairing_id = ?",
                    (encoded, FORGED_SCOPE_DIGEST, pairing_id),
                )
                if rotation_id:
                    connection.execute(
                        "UPDATE matm_connector_rotations SET approved_scopes_json = ?, "
                        "scope_digest = ? WHERE rotation_id = ? AND pairing_id = ?",
                        (encoded, FORGED_SCOPE_DIGEST, rotation_id, pairing_id),
                    )

    def _lifecycle_snapshot(self, pairing_id, rotation_id=None):
        if self.backend == "file":
            data = json.loads(self.path.read_text(encoding="utf-8"))
            pairing = data["connectorPairings"][pairing_id]
            credentials = sorted(
                (item["credentialId"], item["status"])
                for item in data["connectorCredentials"].values()
                if item.get("pairingId") == pairing_id
            )
            rotation = data["connectorRotations"].get(rotation_id) if rotation_id else None
            return (
                pairing["status"],
                pairing["currentCredentialId"],
                tuple(credentials),
                (rotation or {}).get("status"),
            )
        with closing(sqlite3.connect(self.path)) as connection:
            pairing = connection.execute(
                "SELECT status, current_credential_id FROM matm_connector_pairings "
                "WHERE pairing_id = ?",
                (pairing_id,),
            ).fetchone()
            credentials = tuple(
                connection.execute(
                    "SELECT credential_id, status FROM matm_connector_credentials "
                    "WHERE pairing_id = ? ORDER BY credential_id",
                    (pairing_id,),
                ).fetchall()
            )
            rotation = (
                connection.execute(
                    "SELECT status FROM matm_connector_rotations WHERE rotation_id = ?",
                    (rotation_id,),
                ).fetchone()
                if rotation_id
                else None
            )
        return pairing[0], pairing[1], credentials, rotation[0] if rotation else None

    def test_claim_binding_failures_are_indistinguishable_and_secret_free(self):
        request, payload, _verifier, state = self._request("binding")
        invalid = (
            (request["pairingRequestProof"], secrets.token_urlsafe(32), CLIENT_ID, REDIRECT_URI),
            ("me_pairproof_v1.invalid.invalid", state, CLIENT_ID, REDIRECT_URI),
            (request["pairingRequestProof"], state, "wrong-client", REDIRECT_URI),
            (
                request["pairingRequestProof"],
                state,
                CLIENT_ID,
                "http://127.0.0.1:53683/memoryendpoints/callback",
            ),
        )
        for index, (proof, candidate_state, client, redirect) in enumerate(invalid):
            result = self.store.claim_connector_authorization_code(
                proof,
                candidate_state,
                client,
                redirect,
                "invalid-binding-%02d-idempotency" % index,
                _digest("invalid-binding-%02d" % index),
            )
            self.assertFalse(result["ok"], result)
            self.assertEqual("authorization_claim_invalid", result["status"])
            self.assertNotIn("authorizationCode", result)

    def test_claim_expiry_cancel_and_redeemed_are_typed(self):
        expired, payload, _verifier, state = self._request("expired-request")
        self._expire_request(expired, "request")
        result = self._claim(expired, payload, state, "expired-request")
        self.assertEqual("pairing_request_expired", result["status"])

        canceled, payload, _verifier, state = self._request("canceled")
        canceled_result = self.store.cancel_connector_pairing_request(
            self.session_secret,
            canceled["publicRequestRef"],
            "human_cancelled",
            "cancel-request-idempotency",
            _digest("cancel-request"),
        )
        self.assertTrue(canceled_result["ok"], canceled_result)
        result = self._claim(canceled, payload, state, "canceled")
        self.assertEqual("pairing_request_canceled", result["status"])

        request, payload, verifier, state = self._request("redeemed")
        self._approve(request, "redeemed")
        claim_key = "claim-redeemed-idempotency"
        claim_digest = _digest("claim-redeemed")
        claim = self._claim(request, payload, state, "redeemed", claim_key, claim_digest)
        exchange = self.store.exchange_connector_authorization_code(
            claim["authorizationCode"], verifier, CLIENT_ID, REDIRECT_URI,
            "exchange-redeemed-idempotency", _digest("exchange-redeemed")
        )
        self.assertTrue(exchange["ok"], exchange)
        replay = self._claim(request, payload, state, "redeemed", claim_key, claim_digest)
        self.assertFalse(replay["ok"], replay)
        self.assertEqual("authorization_code_redeemed", replay["status"])

    def test_abandoned_pending_grant_expires_and_never_registers_agent(self):
        _request, _claim, exchange = self._pending("abandoned")
        pairing_id = exchange["pairing"]["pairingId"]
        token = exchange["connectorCredentialSecret"]
        self._expire_pairing(pairing_id)
        expired = self.store.expire_connector_pairings()
        self.assertGreaterEqual(expired["expiredPairingCount"], 1)
        self.assertIsNone(self.store.authenticate_connector_token(token, allow_pending=True))
        activation = self.store.activate_connector_pairing(
            pairing_id,
            token,
            "activate-expired-idempotency",
            _digest("activate-expired"),
        )
        self.assertFalse(activation["ok"], activation)

    def test_rotation_preserves_scope_exact_retry_and_revokes_predecessor(self):
        pairing_id, predecessor = self._active("rotation")
        key = "prepare-rotation-idempotency"
        digest = _digest("prepare-rotation")
        first = self.store.prepare_connector_rotation(
            pairing_id, predecessor, "scheduled", key, digest
        )
        retry = self.store.prepare_connector_rotation(
            pairing_id, predecessor, "scheduled", key, digest
        )
        self.assertTrue(first["ok"], first)
        self.assertTrue(retry["ok"], retry)
        self.assertTrue(retry["idempotentReplay"])
        successor = first["connectorCredentialSecret"]
        self.assertTrue(secrets.compare_digest(successor, retry["connectorCredentialSecret"]))
        for result in (first, retry):
            self.assertEqual(list(V1_REQUESTED_SCOPES), result["approvedScopes"])
            self.assertEqual(connector_scope_digest(), result["scopeDigest"])
        self.assertNotIn(successor.encode("ascii"), self._persisted_bytes())
        activated = self.store.activate_connector_rotation(
            pairing_id,
            first["rotation"]["rotationId"],
            successor,
            "activate-rotation-idempotency",
            _digest("activate-rotation"),
        )
        self.assertTrue(activated["ok"], activated)
        self.assertIsNone(self.store.authenticate_connector_token(predecessor))
        self.assertEqual("connector_agent", self.store.authenticate(successor)["credentialType"])

    def test_coherent_pairing_and_credential_scope_tamper_denies_auth_and_activation(self):
        _request, _claim, exchange = self._pending("tamper-pending")
        pairing_id = exchange["pairing"]["pairingId"]
        token = exchange["connectorCredentialSecret"]
        self._tamper_scope_chain(pairing_id)
        before = self._lifecycle_snapshot(pairing_id)

        self.assertIsNone(
            self.store.authenticate_connector_token(token, allow_pending=True)
        )
        result = self.store.activate_connector_pairing(
            pairing_id,
            token,
            "activate-tampered-idempotency",
            _digest("activate-tampered"),
        )
        self.assertFalse(result["ok"], result)
        self.assertEqual("connector_scope_denied", result["status"])
        self.assertEqual(before, self._lifecycle_snapshot(pairing_id))

    def test_coherent_rotation_scope_tamper_is_a_no_op(self):
        pairing_id, predecessor = self._active("tamper-rotation")
        prepared = self.store.prepare_connector_rotation(
            pairing_id,
            predecessor,
            "scheduled",
            "prepare-tampered-rotation-idempotency",
            _digest("prepare-tampered-rotation"),
        )
        self.assertTrue(prepared["ok"], prepared)
        rotation_id = prepared["rotation"]["rotationId"]
        successor = prepared["connectorCredentialSecret"]
        self._tamper_scope_chain(pairing_id, rotation_id)
        before = self._lifecycle_snapshot(pairing_id, rotation_id)

        self.assertIsNone(self.store.authenticate_connector_token(predecessor))
        result = self.store.activate_connector_rotation(
            pairing_id,
            rotation_id,
            successor,
            "activate-tampered-rotation-idempotency",
            _digest("activate-tampered-rotation"),
        )
        self.assertFalse(result["ok"], result)
        self.assertEqual("connector_scope_denied", result["status"])
        self.assertEqual(before, self._lifecycle_snapshot(pairing_id, rotation_id))

    def test_readback_fails_closed_if_authoritative_agent_row_is_missing(self):
        pairing_id, token = self._active("readback-delete")
        self._delete_agent_registration(pairing_id)
        result = self.store.confirm_connector_agent_registration(pairing_id, token)
        self.assertFalse(result["ok"], result)
        self.assertEqual("pairing_verification_failed", result["status"])


class FileConnectorPairingHardeningTests(ConnectorHardeningContract, unittest.TestCase):
    backend = "file"


class SQLiteConnectorPairingHardeningTests(ConnectorHardeningContract, unittest.TestCase):
    backend = "sqlite"


if __name__ == "__main__":
    unittest.main()
