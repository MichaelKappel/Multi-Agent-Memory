"""SQLite parity for the current UAI collaboration claim lifecycle."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from memoryendpoints.storage import SQLiteStore


class SqliteUaiWorkflowCurrentTests(unittest.TestCase):
    def test_sqlite_edit_claim_heartbeat_completion_release_and_conflict(self):
        previous = os.environ.get("MEMORYENDPOINTS_CREDENTIAL_PEPPER")
        os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = "synthetic-sqlite-uai-pepper-" + ("x" * 48)
        self.addCleanup(
            lambda: os.environ.__setitem__("MEMORYENDPOINTS_CREDENTIAL_PEPPER", previous)
            if previous is not None
            else os.environ.pop("MEMORYENDPOINTS_CREDENTIAL_PEPPER", None)
        )
        with tempfile.TemporaryDirectory(prefix="matm-sqlite-uai-") as tmp:
            store = SQLiteStore(Path(tmp) / "store.sqlite3")
            workspace_id, _master_id, _master, _account, _company, project_id, _recovery = store.create_free_account(
                "SQLite UAI Workspace", "SQLite UAI Company", "SQLite UAI Project"
            )
            agent_id = "sqlite-uai-agent"
            store.register_agent(workspace_id, agent_id, "SQLite UAI Agent")
            claim, error, details = store.acquire_uai_edit_claim(
                workspace_id, project_id, agent_id, ".uai/identity.uai", "a" * 64, "Track a safe update", 60
            )
            self.assertIsNone(error, details)
            claim_id = claim["claim"]["claimId"]
            heartbeat, error, _details = store.heartbeat_uai_edit_claim(workspace_id, agent_id, claim_id, 120)
            self.assertIsNone(error)
            self.assertEqual(120, heartbeat["claim"]["leaseSeconds"])
            conflict, error, _details = store.acquire_uai_edit_claim(
                workspace_id, project_id, agent_id, ".uai/identity.uai", "a" * 64, "Second writer", 60
            )
            self.assertIsNone(conflict)
            self.assertEqual("uai_edit_claim_conflict", error)
            completed, error, _details = store.complete_uai_edit_claim(
                workspace_id, agent_id, claim_id, "b" * 64, "Safe update completed"
            )
            self.assertIsNone(error)
            self.assertEqual("completed", completed["claim"]["status"])
            second, error, _details = store.acquire_uai_edit_claim(
                workspace_id, project_id, agent_id, ".uai/identity.uai", "b" * 64, "Second safe update", 60
            )
            self.assertIsNone(error)
            released, error, _details = store.release_uai_edit_claim(
                workspace_id, agent_id, second["claim"]["claimId"], "No further change required"
            )
            self.assertIsNone(error)
            self.assertEqual("released", released["claim"]["status"])


if __name__ == "__main__":
    unittest.main()
