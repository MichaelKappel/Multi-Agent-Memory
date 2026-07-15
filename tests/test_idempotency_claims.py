import json
import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from memoryendpoints.storage import (
    FileStore,
    SQLiteStore,
    _idempotency_pending_payload,
)


class IdempotencyClaimOwnershipTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / "var" / "test-store"
        root.mkdir(parents=True, exist_ok=True)
        self.tempdir = root / ("%s-idempotency-claims" % os.getpid())
        shutil.rmtree(str(self.tempdir), ignore_errors=True)
        self.tempdir.mkdir(parents=True)
        self.previous_pepper = os.environ.get("MEMORYENDPOINTS_CREDENTIAL_PEPPER")
        os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = (
            "test-only-idempotency-claim-owner-pepper-" + ("x" * 64)
        )

    def tearDown(self):
        shutil.rmtree(str(self.tempdir), ignore_errors=True)
        if self.previous_pepper is None:
            os.environ.pop("MEMORYENDPOINTS_CREDENTIAL_PEPPER", None)
        else:
            os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = self.previous_pepper

    def _stores(self):
        return (
            ("file", FileStore(self.tempdir / "claims.json")),
            ("sqlite", SQLiteStore(self.tempdir / "claims.sqlite3")),
        )

    def _replace_pending_claim(
        self, backend, store, workspace_id, key, operation, claim_id
    ):
        record_key = "%s:%s:%s" % (workspace_id, operation, key)
        if backend == "file":
            snapshot = store._load()
            record = snapshot["idempotency"][record_key]
            record["response"] = _idempotency_pending_payload(claim_id)
            record["createdAt"] = "2000-01-01T00:00:00Z"
            store._save(snapshot)
            return
        with store._open_connection() as connection:
            with connection:
                connection.execute(
                    "UPDATE matm_idempotency SET response_json = ?, created_at = ? WHERE record_key = ?",
                    (
                        json.dumps(
                            _idempotency_pending_payload(claim_id),
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        "2000-01-01T00:00:00Z",
                        record_key,
                    ),
                )

    def test_stale_or_replaced_claim_cannot_be_stolen_or_overwrite_owner(self):
        for backend, store in self._stores():
            with self.subTest(backend=backend):
                workspace_id = store.create_free_account(
                    "Claim Workspace", "Claim Company", "Claim Project"
                )[0]
                key = "claim-owner-regression-key"
                operation = "claim-owner-regression"
                body = {"effect": "one"}
                original = store.claim_idempotency(
                    workspace_id, key, operation, body
                )
                self.assertTrue(original["_idempotencyClaimed"])
                original_claim_id = original["_claimId"]

                self._replace_pending_claim(
                    backend,
                    store,
                    workspace_id,
                    key,
                    operation,
                    original_claim_id,
                )
                with patch(
                    "memoryendpoints.storage._IDEMPOTENCY_CLAIM_WAIT_SECONDS",
                    0.0,
                ):
                    contender = store.claim_idempotency(
                        workspace_id, key, operation, body
                    )
                self.assertEqual("idempotency_in_progress", contender["status"])
                self.assertNotIn("_idempotencyClaimed", contender)

                successor_claim_id = "idemclaim-successor-owner"
                self._replace_pending_claim(
                    backend,
                    store,
                    workspace_id,
                    key,
                    operation,
                    successor_claim_id,
                )
                self.assertFalse(
                    store.record_idempotency(
                        workspace_id,
                        key,
                        operation,
                        body,
                        {"ok": True, "owner": "stale"},
                        "201 Created",
                        claim_id=original_claim_id,
                    )
                )
                self.assertFalse(
                    store.release_idempotency_claim(
                        workspace_id,
                        key,
                        operation,
                        original_claim_id,
                    )
                )
                self.assertTrue(
                    store.record_idempotency(
                        workspace_id,
                        key,
                        operation,
                        body,
                        {"ok": True, "owner": "successor"},
                        "201 Created",
                        claim_id=successor_claim_id,
                    )
                )
                replay = store.check_idempotency(
                    workspace_id, key, operation, body
                )
                self.assertTrue(replay["idempotentReplay"])
                self.assertEqual("successor", replay["owner"])
                self.assertFalse(
                    store.release_idempotency_claim(
                        workspace_id,
                        key,
                        operation,
                        successor_claim_id,
                    )
                )


if __name__ == "__main__":
    unittest.main()
