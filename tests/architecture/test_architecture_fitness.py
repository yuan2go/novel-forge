from pathlib import Path
import unittest

from novel_forge.tools.architecture_fitness import build_report


ROOT = Path(__file__).resolve().parents[2]


class ArchitectureFitnessTests(unittest.TestCase):
    def test_current_production_boundary_passes_fitness_rules(self) -> None:
        report = build_report(ROOT)
        self.assertEqual(report["status"], "PASS", report)
        self.assertGreater(report["checked_domain_files"], 0)
        self.assertGreater(report["classified_production_entries"], 0)


if __name__ == "__main__":
    unittest.main()
