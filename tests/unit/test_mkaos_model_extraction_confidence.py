from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_model_extraction import score_extraction_candidate


class MkaosModelExtractionConfidenceTests(unittest.TestCase):
    def test_confidence_scores_safe_mechanism_candidate(self):
        candidate = {
            "abstraction_level": "mechanism",
            "creative_principle": "把制度压力转成角色选择和代价",
            "evidence_refs": ["span-1"],
            "applicable_flows": ["outline", "prose", "review"],
            "risk_level": "low",
            "quality_dimensions": {"abstraction_score": 0.8, "creative_usability_score": 0.82},
        }

        score = score_extraction_candidate(candidate, {"valid": True, "errors": []}, {"forbidden_field_count": 0}, deterministic_candidates=[candidate])

        self.assertGreaterEqual(score["confidence"], 0.7)
        self.assertIn(score["approval_recommendation"], {"approve", "review"})
        self.assertGreaterEqual(score["quality_dimensions"]["originality_safety_score"], 0.7)

    def test_forbidden_fields_lower_originality_safety(self):
        candidate = {"risk_level": "high", "applicable_flows": [], "evidence_refs": []}

        score = score_extraction_candidate(candidate, {"valid": False, "errors": ["bad"]}, {"forbidden_field_count": 2}, deterministic_candidates=[])

        self.assertLess(score["confidence"], 0.65)
        self.assertEqual(score["approval_recommendation"], "reject")


if __name__ == "__main__":
    unittest.main()
