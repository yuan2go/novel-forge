from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosExtractionAgentTests(MkaosP1TestCase):
    def test_candidate_generation_and_approval(self):
        seeded = self.seed_knowledge_system()
        result = mkaos.extract_knowledge_candidates(self.storage, {"project_id": self.project_id, "source_chunk_ids": [seeded["chunk_id"]], "extraction_goal": "制度冲突"})
        candidate = result["candidates"][0]["asset"]
        self.assertEqual(candidate["content"]["status"], "needs_review")
        self.assertFalse(candidate["content"]["abstraction_check"]["raw_expression_included"])
        approved = mkaos.approve_knowledge_candidate(self.storage, candidate["id"], {"project_id": self.project_id})
        self.assertEqual(approved["knowledge"]["asset"]["type"], "knowledge_card")
        self.assertNotIn("历史制度会改变资源分配", str(approved))

    def test_model_assisted_extraction_requires_opt_in(self):
        seeded = self.seed_knowledge_system()
        result = mkaos.extract_knowledge_candidates(
            self.storage,
            {
                "project_id": self.project_id,
                "source_chunk_ids": [seeded["chunk_id"]],
                "provider_mode": "model_assisted",
                "mock_provider_candidates": [{"concept_name": "Provider 候选", "core_explanation": "可迁移抽象"}],
            },
        )
        self.assertEqual(result["provider"]["status"], "opt_in_required")
        self.assertEqual(result["candidates"][0]["asset"]["content"]["provider_mode"], "local_deterministic")

    def test_opted_in_provider_candidate_is_sanitized_when_source_like(self):
        seeded = self.seed_knowledge_system()
        result = mkaos.extract_knowledge_candidates(
            self.storage,
            {
                "project_id": self.project_id,
                "source_chunk_ids": [seeded["chunk_id"]],
                "provider_mode": "model_assisted",
                "provider_opt_in": True,
                "mock_provider_candidates": [
                    {
                        "concept_name": "Provider 原文风险候选",
                        "core_explanation": "历史制度会改变资源分配。叙事爽点需要选择代价。",
                        "confidence": 0.9,
                    }
                ],
            },
        )
        candidate = result["candidates"][0]["asset"]["content"]
        self.assertEqual(result["provider"]["status"], "mock_provider_ready")
        self.assertFalse(candidate["abstraction_check"]["passed"])
        self.assertNotIn("历史制度会改变资源分配", candidate["core_explanation"])
