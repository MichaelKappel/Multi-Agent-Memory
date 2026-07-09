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
        self.assertFalse(read_order_names & forbidden)
        self.assertIn(".uai/totem.uai", audit_uai_memory.STARTUP_READ_ORDER)
        self.assertNotIn(".uai/short-term-memory.uai", audit_uai_memory.STARTUP_READ_ORDER)

    def test_active_uai_files_are_date_free_and_typed(self):
        items = [audit_uai_memory.audit_file(path) for path in sorted((ROOT / ".uai").glob("*.uai"))]
        self.assertTrue(items)
        self.assertTrue(all(item["dateFree"] for item in items))
        self.assertFalse({Path(item["path"]).name for item in items} & audit_uai_memory.FORBIDDEN_ACTIVE_MEMORY_FILENAMES)


if __name__ == "__main__":
    unittest.main()
