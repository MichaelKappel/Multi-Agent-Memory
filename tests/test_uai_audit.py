import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "scripts" / "audit_uai_memory.py"


spec = importlib.util.spec_from_file_location("audit_uai_memory", AUDIT_PATH)
audit_uai_memory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_uai_memory)


class UaiAuditContractTests(unittest.TestCase):
    def test_startup_order_has_no_catch_all_active_memory_file(self):
        forbidden = audit_uai_memory.FORBIDDEN_ACTIVE_MEMORY_FILENAMES
        read_order_names = {Path(item).name for item in audit_uai_memory.STARTUP_READ_ORDER}
        self.assertEqual({name.lower() for name in forbidden}, forbidden)
        self.assertFalse(read_order_names & forbidden)
        self.assertEqual(".uai/memory-maintenance.uai", audit_uai_memory.STARTUP_READ_ORDER[0])
        self.assertIn(".uai/totem.uai", audit_uai_memory.STARTUP_READ_ORDER)
        self.assertIn(".uai/taboo.uai", audit_uai_memory.STARTUP_READ_ORDER)
        self.assertIn(".uai/talisman.uai", audit_uai_memory.STARTUP_READ_ORDER)
        self.assertNotIn(".uai/short-term-memory.uai", audit_uai_memory.STARTUP_READ_ORDER)
        self.assertNotIn(".uai/current-state.uai", audit_uai_memory.STARTUP_READ_ORDER)
        self.assertNotIn(".uai/short-term-memory.uai", audit_uai_memory.manifest_read_order())
        self.assertNotIn(".uai/current-state.uai", audit_uai_memory.manifest_read_order())

    def test_active_uai_files_are_date_free_and_typed(self):
        items = [audit_uai_memory.audit_file(path) for path in sorted((ROOT / ".uai").rglob("*.uai"))]
        self.assertTrue(items)
        self.assertTrue(all(item["dateFree"] for item in items))
        active_names = {Path(item["path"]).name.lower() for item in items}
        self.assertFalse(active_names & audit_uai_memory.FORBIDDEN_ACTIVE_MEMORY_FILENAMES)

    def test_active_handoff_buckets_have_no_guidance_or_payload_files(self):
        items = audit_uai_memory.audit_handoff_buckets()
        self.assertTrue(items)
        self.assertTrue(all(item["ok"] for item in items), items)


if __name__ == "__main__":
    unittest.main()
