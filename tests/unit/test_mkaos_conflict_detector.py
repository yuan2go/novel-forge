from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosConflictDetectorTests(MkaosP1TestCase):
    def test_source_policy_and_relation_conflicts(self):
        seeded = self.seed_knowledge_system()
        mkaos.create_knowledge_relation(
            self.storage,
            {
                "project_id": self.project_id,
                "source_knowledge_id": seeded["history"]["asset"]["id"],
                "target_knowledge_id": seeded["mystery"]["asset"]["id"],
                "relation_type": "contradicts",
            },
        )
        items = [
            {"knowledge_id": seeded["history"]["asset"]["id"], "status": "verified", "risk_level": "low"},
            {"knowledge_id": seeded["mystery"]["asset"]["id"], "status": "verified", "risk_level": "low"},
            {"knowledge_id": seeded["risky"]["asset"]["id"], "status": "verified", "risk_level": "high", "quality_dimensions": {"copyright_risk_score": 0.9}},
        ]
        result = mkaos.detect_knowledge_conflicts(
            self.storage,
            {"project_id": self.project_id, "knowledge_items": items, "source_policy": {"exclude_high_risk": True}},
        )
        types = {item["conflict_type"] for item in result["conflicts"]}
        self.assertIn("knowledge_vs_knowledge", types)
        self.assertIn("knowledge_vs_source_policy", types)
        self.assertGreater(result["blocking_count"], 0)

    def test_non_blocking_platform_warning_can_continue(self):
        result = mkaos.detect_knowledge_conflicts(
            self.storage,
            {"platform": "publishing", "knowledge_items": [{"knowledge_id": "k", "concept_name": "飞卢强爽点模板", "risk_level": "low"}]},
        )
        self.assertEqual(result["blocking_count"], 0)
        self.assertEqual(result["conflicts"][0]["conflict_type"], "knowledge_vs_platform")

    def test_graph_reasoning_detects_forbids_and_missing_requires(self):
        seeded = self.seed_knowledge_system()
        history_id = seeded["history"]["asset"]["id"]
        mystery_id = seeded["mystery"]["asset"]["id"]
        support = mkaos.create_knowledge_card(
            self.storage,
            {
                "project_id": self.project_id,
                "concept_name": "线索位置支持知识",
                "discipline": "逻辑学",
                "core_explanation": "证据链需要提前布置可复盘的线索位置。",
            },
        )
        support_id = support["asset"]["id"]
        mkaos.create_knowledge_relation(
            self.storage,
            {
                "project_id": self.project_id,
                "source_knowledge_id": history_id,
                "target_knowledge_id": mystery_id,
                "relation_type": "forbids",
                "confidence": 0.9,
            },
        )
        mkaos.create_knowledge_relation(
            self.storage,
            {
                "project_id": self.project_id,
                "source_knowledge_id": mystery_id,
                "target_knowledge_id": support_id,
                "relation_type": "requires",
                "confidence": 0.8,
            },
        )
        result = mkaos.detect_knowledge_conflicts(
            self.storage,
            {
                "project_id": self.project_id,
                "environment": "production",
                "knowledge_items": [
                    {"knowledge_id": history_id, "status": "verified", "risk_level": "low"},
                    {"knowledge_id": mystery_id, "status": "verified", "risk_level": "low"},
                ],
            },
        )
        explanations = " ".join(item["explanation"] for item in result["conflicts"])
        self.assertIn("forbids", explanations)
        self.assertIn("requires missing", explanations)
        self.assertGreaterEqual(result["blocking_count"], 2)
        self.assertEqual(result["reasoning_mode"], "deterministic_graph_first_slice")

    def test_model_judge_is_opt_in_and_consumes_mock_result(self):
        blocked = mkaos.detect_knowledge_conflicts(self.storage, {"enable_model_judge": True, "knowledge_items": []})
        self.assertEqual(blocked["model_judge"]["status"], "opt_in_required")
        judged = mkaos.detect_knowledge_conflicts(
            self.storage,
            {
                "enable_model_judge": True,
                "model_judge_opt_in": True,
                "model_judge_result": {
                    "provider": "mock",
                    "conflicts": [
                        {
                            "conflict_type": "knowledge_vs_task_goal",
                            "severity": "high",
                            "blocking": True,
                            "involved_knowledge_ids": ["k1"],
                            "explanation": "深层语义目标冲突",
                            "recommendation": "人工裁定",
                            "confidence": 0.77,
                        }
                    ],
                },
            },
        )
        self.assertEqual(judged["model_judge"]["status"], "completed")
        self.assertTrue(any(item.get("judge_source") == "model_judge" for item in judged["conflicts"]))

    def test_transitive_graph_inference_and_semantic_rules(self):
        seeded = self.seed_knowledge_system()
        history_id = seeded["history"]["asset"]["id"]
        mystery_id = seeded["mystery"]["asset"]["id"]
        rhythm = mkaos.create_knowledge_card(
            self.storage,
            {
                "project_id": self.project_id,
                "concept_name": "快节奏强爽点",
                "discipline": "平台策略",
                "core_explanation": "快节奏、强情绪、反转密度和强爽点适合低门槛平台。",
            },
        )
        literary = mkaos.create_knowledge_card(
            self.storage,
            {
                "project_id": self.project_id,
                "concept_name": "出版向文学质感",
                "discipline": "出版策略",
                "core_explanation": "文学质感、慢热推进、结构完整和语言稳定适合出版向。",
            },
        )
        support = mkaos.create_knowledge_card(
            self.storage,
            {
                "project_id": self.project_id,
                "concept_name": "制度推理支撑",
                "discipline": "历史制度",
                "core_explanation": "制度冲突支撑证据链推理。",
            },
        )
        mkaos.create_knowledge_relation(
            self.storage,
            {"project_id": self.project_id, "source_knowledge_id": history_id, "target_knowledge_id": support["asset"]["id"], "relation_type": "supports"},
        )
        mkaos.create_knowledge_relation(
            self.storage,
            {"project_id": self.project_id, "source_knowledge_id": support["asset"]["id"], "target_knowledge_id": mystery_id, "relation_type": "forbids"},
        )
        result = mkaos.detect_knowledge_conflicts(
            self.storage,
            {
                "project_id": self.project_id,
                "environment": "production",
                "knowledge_items": [
                    {"knowledge_id": history_id, "concept_name": "制度冲突", "core_explanation": "制度冲突支撑推理", "status": "verified"},
                    {"knowledge_id": mystery_id, "concept_name": "证据链", "core_explanation": "公平线索可复盘", "status": "verified"},
                    {"knowledge_id": rhythm["asset"]["id"], "concept_name": "快节奏强爽点", "core_explanation": "快节奏 强情绪 反转密度 强爽点", "status": "verified"},
                    {"knowledge_id": literary["asset"]["id"], "concept_name": "出版向文学质感", "core_explanation": "文学质感 慢热 结构完整 语言稳定 出版向", "status": "verified"},
                ],
            },
        )
        self.assertTrue(any(item.get("graph_evidence", {}).get("inference") == "transitive_support_to_blocking_relation" for item in result["conflicts"]))
        self.assertTrue(any(item["explanation"].startswith("Fast-payoff") for item in result["conflicts"]))
