import json
import tempfile
import unittest
from pathlib import Path

from scripts import migrate_long_term_memory_to_memoryendpoints as migration


class LongTermMemoryMigrationTests(unittest.TestCase):
    def test_load_memory_items_extracts_public_safe_records(self):
        with tempfile.TemporaryDirectory() as tempdir:
            docs = Path(tempdir)
            (docs / "system-targets.md").write_text(
                "# System Targets\n\nKeep hosted workspace memory searchable.\n\n- Verify redaction.\n",
                encoding="utf-8",
            )

            items = migration.load_memory_items(docs)

        self.assertEqual(1, len(items))
        item = items[0]
        self.assertEqual("System Targets", item["title"])
        self.assertIn("Keep hosted workspace memory searchable.", item["summary"])
        self.assertEqual("procedure", item["memoryType"])
        self.assertIn("long-term-memory-migration", item["tags"])
        self.assertTrue(item["contentHash"].startswith("sha256:"))
        self.assertTrue(item["idempotencyKey"].startswith("ltm-migration-"))

    def test_dry_run_report_does_not_store_credentials_or_raw_workspace(self):
        items = [
            {
                "sourcePath": "docs/long-term-memory/example.md",
                "title": "Example",
                "contentHash": "sha256:abc",
                "idempotencyKey": "ltm-migration-example",
                "memoryType": "note",
                "summary": "A public-safe summary.",
                "tags": ["long-term-memory-migration"],
            }
        ]

        report = migration.build_dry_run_report("https://memoryendpoints.com", "docs/long-term-memory", items)
        text = json.dumps(report)

        self.assertTrue(report["ok"])
        self.assertTrue(report["valuesRedacted"])
        self.assertFalse(report["rawCredentialValuesStored"])
        self.assertIn("idempotencyKeyHash", report["items"][0])
        self.assertNotIn("ltm-migration-example", text)
        self.assertNotIn("apiKeySecret", text)


if __name__ == "__main__":
    unittest.main()
