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
    CANONICAL_AGENT_DISPLAY_NAME,
    CANONICAL_AGENT_ID,
    CLIENT_ID,
    V1_REQUESTED_SCOPES,
    connector_scope_digest,
    generate_state,
)
from memoryendpoints.storage import FileStore, SQLiteStore


REDIRECT_URI = "http://127.0.0.1:53682/memoryendpoints/callback"


def _digest(label):
    return "sha256-v1:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _challenge(verifier):
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


class ConnectorPairingStorageContract:
    backend = None

    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="connector-storage-%s-" % self.backend)
        self.path = Path(self.tempdir) / ("store.json" if self.backend == "file" else "store.sqlite3")
        self.previous_pepper = os.environ.get("MEMORYENDPOINTS_CREDENTIAL_PEPPER")
        os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = secrets.token_urlsafe(48)
        self.store = FileStore(self.path) if self.backend == "file" else SQLiteStore(self.path)
        (
            self.workspace_id,
            _master_key_id,
            master_token,
            _account_id,
            self.company_id,
            self.project_id,
            _recovery_secret,
        ) = self.store.create_free_account(
            "Connector Workspace", "Connector Company", "Connector Project"
        )
        self.password = secrets.token_urlsafe(36)
        proof = self.store.create_company_master_proof(master_token)
        created = self.store.create_human_account(
            "connector-owner", self.password, proof["masterProofSecret"]
        )
        self.assertTrue(created["ok"], created)
        login = self.store.login_human_account("connector-owner", self.password)
        memberships = self.store.list_human_company_memberships(login["sessionSecret"])
        selected = self.store.select_human_company_membership(
            login["sessionSecret"], memberships["items"][0]["authorityId"]
        )
        self.session_secret = selected["sessionSecret"]
        reauthenticated = self.store.reauthenticate_human_account_session(
            self.session_secret, self.password
        )
        self.assertTrue(reauthenticated["ok"], reauthenticated)

    def tearDown(self):
        if self.previous_pepper is None:
            os.environ.pop("MEMORYENDPOINTS_CREDENTIAL_PEPPER", None)
        else:
            os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = self.previous_pepper
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def _persisted_bytes(self):
        chunks = []
        for path in self.path.parent.glob(self.path.name + "*"):
            if path.is_file():
                chunks.append(path.read_bytes())
        return b"\n".join(chunks)

    def _request(self, label="one"):
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
        key = "create-%s-connector-idempotency" % label
        digest = _digest("create-" + label)
        result = self.store.create_connector_pairing_request(payload, key, digest)
        self.assertTrue(result["ok"], result)
        self.assertIn("claimExpiresAt", result["pairingRequest"])
        self.assertIsNone(result["pairingRequest"]["claimExpiresAt"])
        self.assertNotIn("authorizationCodeExpiresAt", result["pairingRequest"])
        return result, payload, verifier, state, key, digest

    def _approve(self, request, label="one"):
        catalog = self.store.human_connector_scope_catalog(
            self.session_secret, request["publicRequestRef"]
        )
        self.assertTrue(catalog["ok"], catalog)
        self.assertNotIn("companyId", catalog["company"])
        self.assertEqual(1, len(catalog["workspaces"]))
        workspace = catalog["workspaces"][0]
        self.assertRegex(workspace["workspaceRef"], r"^workref_[A-Za-z0-9_-]{43}$")
        self.assertNotIn("workspaceId", workspace)
        result = self.store.approve_connector_pairing_request(
            self.session_secret,
            request["publicRequestRef"],
            {"mode": "existing", "workspaceRef": workspace["workspaceRef"]},
            list(V1_REQUESTED_SCOPES),
            "approve-%s-connector-idempotency" % label,
            _digest("approve-" + label),
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(REDIRECT_URI, result["wakeUpUrl"])
        self.assertNotIn("authorizationCode", result)
        self.assertIsNotNone(result["approval"]["claimExpiresAt"])
        self.assertNotIn("authorizationCodeExpiresAt", result["approval"])
        self.assertEqual(list(V1_REQUESTED_SCOPES), result["approvedScopes"])
        self.assertEqual(connector_scope_digest(), result["scopeDigest"])
        return result

    def _registered_display_names(self, pairing_id):
        if self.backend == "file":
            data = json.loads(self.path.read_text(encoding="utf-8"))
            pairing = data["connectorPairings"][pairing_id]
            identity = data["agentIdentities"][pairing["agentIdentityId"]]
            agent = data["agents"][
                "%s:%s" % (pairing["workspaceId"], pairing["agentId"])
            ]
            return identity["agentName"], identity["displayName"], agent["displayName"]
        with closing(sqlite3.connect(self.path)) as connection:
            connection.row_factory = sqlite3.Row
            pairing = connection.execute(
                "SELECT agent_identity_id, workspace_id, agent_id "
                "FROM matm_connector_pairings WHERE pairing_id = ?",
                (pairing_id,),
            ).fetchone()
            identity = connection.execute(
                "SELECT agent_name, display_name FROM matm_agent_identities "
                "WHERE agent_identity_id = ?",
                (pairing["agent_identity_id"],),
            ).fetchone()
            agent = connection.execute(
                "SELECT display_name FROM matm_agents WHERE workspace_id = ? AND agent_id = ?",
                (pairing["workspace_id"], pairing["agent_id"]),
            ).fetchone()
        return identity["agent_name"], identity["display_name"], agent["display_name"]

    def _claim(self, request, payload, state, label="one", key=None, digest=None):
        return self.store.claim_connector_authorization_code(
            request["pairingRequestProof"],
            state,
            CLIENT_ID,
            payload["redirectUri"],
            key or ("claim-%s-connector-idempotency" % label),
            digest or _digest("claim-" + label),
        )

    def _pending_pairing(self, label="one"):
        request, payload, verifier, state, _request_key, _request_digest = self._request(label)
        self._approve(request, label)
        claim = self._claim(request, payload, state, label)
        self.assertTrue(claim["ok"], claim)
        exchange_digest = _digest("exchange-" + label)
        exchange = self.store.exchange_connector_authorization_code(
            claim["authorizationCode"],
            verifier,
            CLIENT_ID,
            REDIRECT_URI,
            "exchange-%s-connector-idempotency" % label,
            exchange_digest,
        )
        self.assertTrue(exchange["ok"], exchange)
        return request, payload, state, claim, exchange

    def test_create_retry_is_deterministic_and_persists_no_raw_desktop_values(self):
        first, payload, _verifier, state, key, digest = self._request("retry")
        retry = self.store.create_connector_pairing_request(payload, key, digest)
        self.assertTrue(retry["ok"], retry)
        self.assertTrue(retry["idempotentReplay"])
        self.assertTrue(
            secrets.compare_digest(
                first["pairingRequestProof"], retry["pairingRequestProof"]
            )
        )
        self.assertEqual(first["publicRequestRef"], retry["publicRequestRef"])
        self.assertEqual(list(V1_REQUESTED_SCOPES), first["requestedScopes"])
        self.assertEqual(connector_scope_digest(), first["scopeDigest"])
        persisted = self._persisted_bytes()
        self.assertNotIn(first["pairingRequestProof"].encode("ascii"), persisted)
        self.assertNotIn(state.encode("ascii"), persisted)

    def test_public_ref_is_non_authorizing_and_authorization_context_is_tenant_neutral(self):
        request, payload, _verifier, state, _key, _digest_value = self._request("public")
        context = self.store.connector_pairing_authorization_context(
            self.session_secret, request["publicRequestRef"]
        )
        self.assertTrue(context["ok"], context)
        self.assertNotIn("wakeUpUrl", context["authorizationContext"])
        self.assertNotIn("workspaceLabel", context["authorizationContext"])
        encoded = json.dumps(context, sort_keys=True)
        for forbidden in (
            self.company_id,
            self.workspace_id,
            self.project_id,
            CANONICAL_AGENT_ID,
            request["pairingRequestProof"],
            state,
            payload["redirectUri"],
        ):
            self.assertNotIn(forbidden, encoded)
        self.assertFalse(
            self.store.get_connector_pairing_request(
                pairing_request_proof=request["publicRequestRef"]
            )["ok"]
        )
        with self.assertRaises(TypeError):
            self.store.connector_pairing_authorization_context(
                request["publicRequestRef"]
            )

    def test_approved_authorization_refresh_is_safe_and_company_bound(self):
        request, payload, _verifier, state, _key, _digest_value = self._request(
            "approved-refresh"
        )
        self._approve(request, "approved-refresh")
        refreshed = self.store.connector_pairing_authorization_context(
            self.session_secret, request["publicRequestRef"]
        )
        self.assertTrue(refreshed["ok"], refreshed)
        context = refreshed["authorizationContext"]
        self.assertEqual("approved", context["status"])
        self.assertEqual(REDIRECT_URI, context["wakeUpUrl"])
        self.assertEqual("Connector Workspace", context["workspaceLabel"])
        encoded = json.dumps(refreshed, sort_keys=True)
        for forbidden in (
            "redirectUri",
            "callbackUrl",
            "workspaceId",
            "companyId",
            "requestId",
            "agentId",
            self.workspace_id,
            self.company_id,
            self.project_id,
            request["pairingRequestProof"],
            state,
        ):
            self.assertNotIn(forbidden, encoded)
        self.assertNotIn("?", context["wakeUpUrl"])
        self.assertNotIn("#", context["wakeUpUrl"])

        claimed = self._claim(
            request, payload, state, "approved-refresh"
        )
        self.assertTrue(claimed["ok"], claimed)
        issued_refresh = self.store.connector_pairing_authorization_context(
            self.session_secret, request["publicRequestRef"]
        )
        self.assertTrue(issued_refresh["ok"], issued_refresh)
        self.assertEqual(
            "authorization_code_issued",
            issued_refresh["authorizationContext"]["status"],
        )
        self.assertNotIn("wakeUpUrl", issued_refresh["authorizationContext"])
        self.assertNotIn("workspaceLabel", issued_refresh["authorizationContext"])

        (
            _other_workspace,
            _other_master_key,
            other_master,
            _other_account,
            _other_company,
            _other_project,
            _other_recovery,
        ) = self.store.create_free_account(
            "Other Workspace", "Other Company", "Other Project"
        )
        other_password = secrets.token_urlsafe(36)
        proof = self.store.create_company_master_proof(other_master)
        created = self.store.create_human_account(
            "other-connector-owner", other_password, proof["masterProofSecret"]
        )
        self.assertTrue(created["ok"], created)
        login = self.store.login_human_account(
            "other-connector-owner", other_password
        )
        memberships = self.store.list_human_company_memberships(
            login["sessionSecret"]
        )
        selected = self.store.select_human_company_membership(
            login["sessionSecret"], memberships["items"][0]["authorityId"]
        )
        mismatch = self.store.connector_pairing_authorization_context(
            selected["sessionSecret"], request["publicRequestRef"]
        )
        self.assertFalse(mismatch["ok"], mismatch)
        self.assertEqual("pairing_request_not_found", mismatch["status"])
        mismatch_encoded = json.dumps(mismatch, sort_keys=True)
        for forbidden in (
            self.company_id,
            self.workspace_id,
            request["publicRequestRef"],
            REDIRECT_URI,
            "Connector Workspace",
        ):
            self.assertNotIn(forbidden, mismatch_encoded)

    def test_company_and_workspace_selectors_are_opaque_session_request_bound(self):
        request, _payload, _verifier, _state, _key, _digest_value = self._request(
            "selectors"
        )
        companies = self.store.human_connector_company_catalog(
            self.session_secret, request["publicRequestRef"]
        )
        self.assertTrue(companies["ok"], companies)
        self.assertEqual(1, len(companies["companies"]))
        company = companies["companies"][0]
        self.assertRegex(company["companyRef"], r"^companyref_[A-Za-z0-9_-]{43}$")
        self.assertNotIn("companyId", company)
        self.assertNotIn("authorityId", company)
        selected = self.store.select_human_connector_company_membership(
            self.session_secret,
            request["publicRequestRef"],
            company["companyRef"],
        )
        self.assertTrue(selected["ok"], selected)
        self.assertNotIn("companyId", selected)
        self.assertNotIn("authorityId", selected)
        self.session_secret = selected["sessionSecret"]

        scopes = self.store.human_connector_scope_catalog(
            self.session_secret, request["publicRequestRef"]
        )
        self.assertTrue(scopes["ok"], scopes)
        workspace_ref = scopes["workspaces"][0]["workspaceRef"]
        tampered = workspace_ref[:-1] + ("A" if workspace_ref[-1] != "A" else "B")
        rejected = self.store.approve_connector_pairing_request(
            self.session_secret,
            request["publicRequestRef"],
            {"mode": "existing", "workspaceRef": tampered},
            list(V1_REQUESTED_SCOPES),
            "tampered-workspace-ref-idempotency",
            _digest("tampered-workspace-ref"),
        )
        self.assertFalse(rejected["ok"], rejected)
        self.assertEqual("workspace_ref_invalid", rejected["status"])

    def test_claim_pending_does_not_bind_idempotency_then_exact_retry_rederives(self):
        request, payload, _verifier, state, _key, _digest_value = self._request("claim")
        claim_key = "claim-pending-then-issued-idempotency"
        claim_digest = _digest("claim-pending-then-issued")
        pending = self._claim(
            request, payload, state, "claim", claim_key, claim_digest
        )
        self.assertTrue(pending["ok"], pending)
        self.assertEqual("pending_human_approval", pending["status"])
        self.assertTrue(pending["pending"])
        self.assertFalse(pending["idempotencyBound"])

        self._approve(request, "claim")
        first = self._claim(request, payload, state, "claim", claim_key, claim_digest)
        retry = self._claim(request, payload, state, "claim", claim_key, claim_digest)
        self.assertTrue(first["ok"], first)
        self.assertTrue(retry["ok"], retry)
        self.assertTrue(retry["idempotentReplay"])
        self.assertTrue(
            secrets.compare_digest(first["authorizationCode"], retry["authorizationCode"])
        )
        conflict = self._claim(
            request,
            payload,
            state,
            "claim",
            "claim-different-key-idempotency",
            _digest("claim-different"),
        )
        self.assertFalse(conflict["ok"], conflict)
        self.assertEqual("idempotency_conflict", conflict["status"])
        self.assertNotIn(first["authorizationCode"].encode("ascii"), self._persisted_bytes())

    def test_activation_and_exact_readbacks_keep_connector_identity_and_scope(self):
        _request, _payload, _state, _claim, exchange = self._pending_pairing("active")
        pairing_id = exchange["pairing"]["pairingId"]
        token = exchange["connectorCredentialSecret"]
        activated = self.store.activate_connector_pairing(
            pairing_id,
            token,
            "activate-connector-idempotency",
            _digest("activate"),
        )
        self.assertTrue(activated["ok"], activated)
        self.assertEqual(list(V1_REQUESTED_SCOPES), activated["approvedScopes"])
        self.assertEqual(connector_scope_digest(), activated["scopeDigest"])

        direct_principal = self.store.authenticate_connector_token(token)
        principal = self.store.authenticate(token)
        for candidate in (direct_principal, principal):
            self.assertEqual("connector_agent", candidate["credentialType"])
            self.assertEqual(CANONICAL_AGENT_DISPLAY_NAME, candidate["agentName"])
            self.assertEqual(list(V1_REQUESTED_SCOPES), candidate["approvedScopes"])
            self.assertNotIn("connectorScopes", candidate)
            self.assertEqual(connector_scope_digest(), candidate["scopeDigest"])

        workspace = self.store.connector_workspace_readback(pairing_id, token)
        agent = self.store.confirm_connector_agent_registration(pairing_id, token)
        status = self.store.connector_pairing_status(pairing_id, token)
        for result in (workspace, agent, status):
            self.assertTrue(result["ok"], result)
            self.assertEqual(list(V1_REQUESTED_SCOPES), result["approvedScopes"])
            self.assertEqual(connector_scope_digest(), result["scopeDigest"])
        self.assertEqual(self.workspace_id, workspace["workspace"]["workspaceId"])
        self.assertEqual(CANONICAL_AGENT_ID, agent["agent"]["agentId"])
        self.assertEqual(
            (CANONICAL_AGENT_DISPLAY_NAME,) * 3,
            self._registered_display_names(pairing_id),
        )
        self.assertTrue(status["verification"]["verified"])
        self.assertNotIn(token.encode("ascii"), self._persisted_bytes())

    def test_start_rejects_identity_and_scope_variants_with_stable_codes(self):
        request, payload, _verifier, _state, _key, _digest_value = self._request("valid")
        self.assertTrue(request["ok"])
        invalid_agent = dict(payload, requestedAgentId="another-agent")
        invalid = self.store.create_connector_pairing_request(
            invalid_agent,
            "invalid-agent-connector-idempotency",
            _digest("invalid-agent"),
        )
        self.assertEqual("connector_agent_identity_invalid", invalid["status"])
        invalid_scope = dict(payload, requestedScopes=list(reversed(V1_REQUESTED_SCOPES)))
        invalid = self.store.create_connector_pairing_request(
            invalid_scope,
            "invalid-scopes-connector-idempotency",
            _digest("invalid-scopes"),
        )
        self.assertEqual("connector_scopes_invalid", invalid["status"])


class FileConnectorPairingStorageTests(ConnectorPairingStorageContract, unittest.TestCase):
    backend = "file"


class SQLiteConnectorPairingStorageTests(ConnectorPairingStorageContract, unittest.TestCase):
    backend = "sqlite"


if __name__ == "__main__":
    unittest.main()
