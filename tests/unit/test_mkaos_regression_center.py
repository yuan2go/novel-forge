from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosRegressionCenterTests(MkaosP1TestCase):
    def test_runner_reports_suite_summary_and_diff(self):
        case = mkaos.create_knowledge_regression_case(
            self.storage,
            {"project_id": self.project_id, "title": "leak", "case_type": "source_leakage", "input_payload": {"source_leakage_signal": True}, "expected_blocking": True},
        )
        single = mkaos.run_knowledge_regression_case(self.storage, case["asset"]["id"])
        suite = mkaos.run_knowledge_regression_suite(self.storage, {"project_id": self.project_id, "create_default_fixtures": False})
        self.assertTrue(single["passed"])
        self.assertEqual(suite["summary"]["failed"], 0)
        self.assertFalse(suite["source_isolation"]["raw_text_included"])
