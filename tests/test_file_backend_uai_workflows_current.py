"""FileStore exercises for current virtual-UAI collaboration claim parity."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from memoryendpoints.storage import FileStore


class FileBackendUaiWorkflowCurrentTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="matm-file-uai-")
        self.previous_pepper = os.environ.get("MEMORYENDPOINTS_CREDENTIAL_PEPPER")
        os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = "synthetic-file-uai-pepper-" + ("x" * 48)
        self.store = FileStore(Path(self.tempdir.name) / "store.json")
        setup = self.store.create_free_account("File UAI Workspace", "File UAI Company", "File UAI Project")
        self.workspace_id, _master_id, _master, _account, _company, self.project_id, _recovery = setup
        self.agent_id = "file-uai-agent"
        self.store.register_agent(self.workspace_id, self.agent_id, "File UAI Agent")

    def tearDown(self):
        self.tempdir.cleanup()
        if self.previous_pepper is None:
            os.environ.pop("MEMORYENDPOINTS_CREDENTIAL_PEPPER", None)
        else:
            os.environ["MEMORYENDPOINTS_CREDENTIAL_PEPPER"] = self.previous_pepper

    def test_file_backend_edit_claim_is_heartbeat_complete_release_and_filterable(self):
        base_hash = "a" * 64
        claim, error, details = self.store.acquire_uai_edit_claim(
            self.workspace_id, self.project_id, self.agent_id, ".uai/identity.uai", base_hash, "Track a safe identity update", 60
        )
        self.assertIsNone(error, details)
        claim_id = claim["claim"]["claimId"]
        head = self.store.uai_collaboration_heads(self.workspace_id, self.project_id, ".uai/identity.uai")
        self.assertEqual(1, len(head))
        heartbeat, error, _details = self.store.heartbeat_uai_edit_claim(
            self.workspace_id, self.agent_id, claim_id, 120
        )
        self.assertIsNone(error)
        self.assertEqual(120, heartbeat["claim"]["leaseSeconds"])
        conflict, error, _details = self.store.acquire_uai_edit_claim(
            self.workspace_id, self.project_id, self.agent_id, ".uai/identity.uai", base_hash, "Second writer", 60
        )
        self.assertIsNone(conflict)
        self.assertEqual("uai_edit_claim_conflict", error)
        completed, error, _details = self.store.complete_uai_edit_claim(
            self.workspace_id, self.agent_id, claim_id, "b" * 64, "Identity update completed safely"
        )
        self.assertIsNone(error)
        self.assertEqual("completed", completed["claim"]["status"])
        self.assertEqual(1, len(self.store.uai_edit_claims(self.workspace_id, self.project_id, self.agent_id, status="completed")))
        second, error, _details = self.store.acquire_uai_edit_claim(
            self.workspace_id, self.project_id, self.agent_id, ".uai/identity.uai", "b" * 64, "Second safe update", 60
        )
        self.assertIsNone(error)
        released, error, _details = self.store.release_uai_edit_claim(
            self.workspace_id, self.agent_id, second["claim"]["claimId"], "No further change required"
        )
        self.assertIsNone(error)
        self.assertEqual("released", released["claim"]["status"])


if __name__ == "__main__":
    unittest.main()
