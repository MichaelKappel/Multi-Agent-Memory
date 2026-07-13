import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile

from memoryendpoints.company_export import CompanyExportError, assemble_company_export


class CompanyExportAssemblyTests(unittest.TestCase):
    def _snapshot(self):
        return {
            "company": {"companyId": "company-acme", "label": "Acme Memory"},
            "workspaces": [
                {"workspaceId": "workspace-one", "label": "Research"},
                {"workspaceId": "workspace-two", "label": "Operations"},
            ],
            "projects": [{"projectId": "project-one", "workspaceId": "workspace-one"}],
            "meetingRooms": [{"roomId": "room-one", "summary": "Portable decisions"}],
            "memories": [{"memoryId": "memory-one", "summary": "Stable client context"}],
        }

    def _read_archive(self, result):
        with zipfile.ZipFile(io.BytesIO(result["body"]), "r") as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    def test_output_is_deterministic_and_assembled_without_temp_files(self):
        snapshot = self._snapshot()
        generated_at = "2026-07-12T21:00:00Z"
        with tempfile.TemporaryDirectory() as temp_dir:
            before = set(os.listdir(temp_dir))
            old_temp = tempfile.tempdir
            tempfile.tempdir = temp_dir
            try:
                first = assemble_company_export(snapshot, generated_at=generated_at)
                second = assemble_company_export(snapshot, generated_at=generated_at)
            finally:
                tempfile.tempdir = old_temp
            self.assertEqual(before, set(os.listdir(temp_dir)))

        self.assertEqual(first["body"], second["body"])
        self.assertEqual(first["digest"], hashlib.sha256(first["body"]).hexdigest())
        self.assertEqual("application/zip", first["contentType"])
        self.assertIn(first["filename"], first["contentDisposition"])

    def test_archive_is_valid_complete_and_manifest_hashes_match(self):
        result = assemble_company_export(self._snapshot(), generated_at="2026-07-12T21:00:00Z")
        files = self._read_archive(result)
        self.assertEqual({"company.json", "index.json", "manifest.json"}, set(files))

        company = json.loads(files["company.json"])
        manifest = json.loads(files["manifest.json"])
        index = json.loads(files["index.json"])
        for collection in ("company", "workspaces", "projects", "meetingRooms", "memories"):
            self.assertEqual(self._snapshot()[collection], company[collection])
        self.assertEqual(2, result["recordCounts"]["workspaces"])
        self.assertEqual(1, result["recordCounts"]["memories"])
        self.assertEqual(result["recordCounts"], manifest["recordCounts"])
        self.assertEqual(result["totalRecords"], index["totalRecords"])
        self.assertEqual("company-acme", manifest["companyId"])
        self.assertEqual("Acme Memory", manifest["companyLabel"])
        self.assertEqual("2026-07-12T21:00:00Z", manifest["generatedAt"])
        for entry in manifest["files"]:
            self.assertEqual(hashlib.sha256(files[entry["path"]]).hexdigest(), entry["sha256"])
            self.assertEqual(len(files[entry["path"]]), entry["byteLength"])
        self.assertEqual(hashlib.sha256(files["manifest.json"]).hexdigest(), result["manifestSha256"])
        self.assertEqual(result["fileDigests"]["manifest.json"], result["manifestSha256"])

    def test_credentials_and_hostile_sensitive_keys_are_excluded_recursively(self):
        sentinel = "THIS-RAW-VALUE-MUST-NOT-SURVIVE"
        governed = "me_agent_v1.agent-record." + ("s" * 43)
        snapshot = self._snapshot()
        snapshot.update(
            {
                "companyMasterKeys": [{"tokenHash": sentinel}],
                "Agent_Tokens": [{"agentTokenSecret": sentinel}],
                "agent-invites": [{"invite_secret": sentinel}],
                "businessData": {
                    "PaSs-WoRd": sentinel,
                    "TO_KEN": sentinel,
                    "Credential.Verifier": sentinel,
                    "PePpEr": sentinel,
                    "S-e-S-s-I-o-N": sentinel,
                    "c.S.r.F": sentinel,
                    "nested": {
                        "secret_HASH": sentinel,
                        "safeAgentTokenId": "public-record-id",
                        "note": "never copy " + governed,
                    },
                },
            }
        )
        result = assemble_company_export(snapshot, generated_at="2026-07-12T21:00:00Z")
        files = self._read_archive(result)
        company = json.loads(files["company.json"])
        archive_text = b"\n".join(files.values()).decode("utf-8")

        self.assertNotIn(sentinel, archive_text)
        self.assertNotIn(governed, archive_text)
        self.assertNotIn("companyMasterKeys", company)
        self.assertNotIn("Agent_Tokens", company)
        self.assertIn("agent-invites", company)
        self.assertEqual([{}], company["agent-invites"])
        self.assertEqual("public-record-id", company["businessData"]["nested"]["safeAgentTokenId"])
        for key in ("PaSs-WoRd", "TO_KEN", "Credential.Verifier", "PePpEr", "S-e-S-s-I-o-N", "c.S.r.F"):
            self.assertNotIn(key, company["businessData"])
        self.assertNotIn("secret_HASH", company["businessData"]["nested"])
        self.assertIn("[REDACTED_SECRET]", company["businessData"]["nested"]["note"])

    def test_identity_can_be_supplied_explicitly_and_invalid_json_values_fail_closed(self):
        result = assemble_company_export(
            {"workspaces": []},
            generated_at="2026-07-12T21:00:00Z",
            company_id="company-one",
            company_label="Company One",
        )
        self.assertEqual("company-one", result["companyId"])
        with self.assertRaises(CompanyExportError):
            assemble_company_export(
                {"companyId": "company-one", "companyLabel": "Company One", "bad": float("nan")},
                generated_at="2026-07-12T21:00:00Z",
            )
        with self.assertRaises(CompanyExportError):
            assemble_company_export(
                {"companyId": "company-one", "companyLabel": "Company One", "bad": object()},
                generated_at="2026-07-12T21:00:00Z",
            )
        with self.assertRaises(CompanyExportError):
            assemble_company_export(
                {"companyId": "company-one", "companyLabel": "Company One", 42: "bad-key"},
                generated_at="2026-07-12T21:00:00Z",
            )


if __name__ == "__main__":
    unittest.main()
