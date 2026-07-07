from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_model_extraction import FORBIDDEN_FIELDS, REQUIRED_CANDIDATE_FIELDS
from novel_forge.modules.mkaos_model_extraction.candidate_validator import validate_candidate_payload
from novel_forge.modules.mkaos_model_extraction.provider_runner import _safe_provider_input
from novel_forge.modules.mkaos_model_extraction.service import _provider_candidates


class MkaosModelExtractionSchemaTests(unittest.TestCase):
    def test_candidate_schema_requires_creative_contract_fields(self):
        candidate = {
            "concept_name": "压力转行动",
            "source_type": "professional_book",
            "discipline": "narrative",
            "knowledge_type": "mechanism",
            "abstraction_level": "mechanism",
            "core_explanation": "把专业机制抽象为人物选择压力。",
            "creative_principle": "知识必须推动角色行动。",
            "narrative_function": "推动主线",
            "conflict_function": "制造利益冲突",
            "character_function": "显露欲望和代价",
            "worldbuilding_function": "形成规则约束",
            "prose_function": "转成场景动作",
            "review_function": "检查是否百科化",
            "positive_usage": ["转成选择"],
            "negative_usage": ["不要解释概念"],
            "anti_patterns": ["百科化"],
            "applicable_flows": ["outline", "prose", "review"],
            "originality_boundary": "abstract only",
            "evidence_refs": ["chunk-1"],
            "confidence": 0.8,
            "risk_level": "low",
            "quality_dimensions": {"creative_usability_score": 0.8},
        }

        result = validate_candidate_payload(candidate)

        self.assertTrue(result["valid"])
        self.assertTrue(set(REQUIRED_CANDIDATE_FIELDS).issubset(candidate.keys()))
        self.assertIn("raw_text", FORBIDDEN_FIELDS)

    def test_missing_applicable_flow_is_invalid(self):
        candidate = {field: "x" for field in REQUIRED_CANDIDATE_FIELDS}
        candidate.update({"positive_usage": [], "negative_usage": [], "anti_patterns": [], "applicable_flows": [], "quality_dimensions": {}, "risk_level": "low"})

        result = validate_candidate_payload(candidate)

        self.assertFalse(result["valid"])
        self.assertTrue(any(error["field"] == "applicable_flows" for error in result["errors"]))

    def test_provider_analyze_patterns_become_reviewable_candidates(self):
        output = {
            "summary": "文本呈现秩序压力和选择代价。",
            "word_count": 12,
            "patterns": ["把礼法压力转成角色必须付出资源代价的选择机制。"],
        }

        candidates = _provider_candidates(output)

        self.assertEqual(len(candidates), 1)
        self.assertIn("选择机制", candidates[0]["creative_principle"])
        self.assertEqual(candidates[0]["metadata"]["provider_output_shape"], "analyze.summary_patterns")

    def test_provider_evidence_text_uses_bounded_excerpt_not_title_when_allowed(self):
        payload = {
            "allow_evidence_text": True,
            "input_summary": "章节标题",
            "text": "原文章节片段" * 1000,
        }

        text = _safe_provider_input(payload)

        self.assertTrue(text.startswith("原文章节片段"))
        self.assertLessEqual(len(text), 4000)


if __name__ == "__main__":
    unittest.main()
