from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR = ROOT / "src/novel_forge/modules/production_execution/process_supervisor.py"


class ProcessSupervisorBoundaryTests(unittest.TestCase):
    def test_supervisor_owns_process_group_signals_and_persistent_receipts(self) -> None:
        source = SUPERVISOR.read_text(encoding="utf-8")
        self.assertIn("start_new_session=True", source)
        self.assertIn("os.killpg", source)
        self.assertIn("receipt_path", source)
        self.assertNotIn("TemporaryDirectory", source)

if __name__ == "__main__":
    unittest.main()
