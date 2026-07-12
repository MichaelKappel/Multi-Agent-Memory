import argparse
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review_one_memory.py"
SPEC = importlib.util.spec_from_file_location("review_one_memory", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ReviewOneMemoryTests(unittest.TestCase):
    def test_ingest_report_selects_exactly_one_memory_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report = Path(temp_dir) / "ingest.json"
            report.write_text(json.dumps({"memoryEventId": "mem-one"}), encoding="utf-8")
            args = argparse.Namespace(memory_event_id="", ingest_report=str(report))
            self.assertEqual("mem-one", MODULE.memory_event_id(args))

    def test_mismatched_direct_and_report_event_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report = Path(temp_dir) / "ingest.json"
            report.write_text(json.dumps({"memoryEventId": "mem-report"}), encoding="utf-8")
            args = argparse.Namespace(memory_event_id="mem-direct", ingest_report=str(report))
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                MODULE.memory_event_id(args)

    def test_promote_requires_pending_accepted_review(self):
        plan = MODULE.build_plan(
            {
                "memoryEventId": "mem-one",
                "reviewId": "review-one",
                "status": "pending",
                "firewallDecision": "accepted",
            },
            "promote",
        )
        self.assertEqual("decide", plan["action"])
        self.assertEqual("promoted", plan["expectedStatus"])

        with self.assertRaisesRegex(RuntimeError, "cannot transition"):
            MODULE.build_plan(
                {
                    "memoryEventId": "mem-two",
                    "reviewId": "review-two",
                    "status": "quarantined",
                    "firewallDecision": "quarantine_for_review",
                },
                "promote",
            )

    def test_already_promoted_is_idempotent(self):
        plan = MODULE.build_plan(
            {
                "memoryEventId": "mem-one",
                "reviewId": "review-one",
                "status": "promoted",
                "firewallDecision": "accepted",
            },
            "promote",
        )
        self.assertEqual("already_decided", plan["action"])

    def test_report_hashes_note_and_rejects_raw_tenant_values(self):
        args = argparse.Namespace(apply=True, base_url="https://memoryendpoints.com")
        plan = {
            "reviewId": "review-one",
            "decision": "promote",
            "action": "decide",
            "statusBefore": "pending",
            "expectedStatus": "promoted",
            "firewallDecision": "accepted",
        }
        result = {
            "reviewNoteExposed": False,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        readback = {"memoryEventId": "mem-one", "reviewId": "review-one", "status": "promoted"}
        report = MODULE.build_report(args, "secret-token", "workspace-private", "mem-one", plan, result, readback, "review note")
        self.assertTrue(report["ok"])
        self.assertFalse(report["reviewNoteStored"])
        self.assertNotIn("review note", json.dumps(report))
        self.assertNotIn("secret-token", json.dumps(report))
        self.assertNotIn("workspace-private", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
