from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosProviderSemanticGovernanceTests(MkaosP1TestCase):
    def test_provider_e2e_probe_requires_explicit_opt_in(self):
        report = mkaos.run_mkaos_provider_e2e_probe(
            self.storage,
            {
                "project_id": self.project_id,
                "probe_type": "both",
                "provider_mode": "mock",
                "persist": False,
            },
        )["data"]

        self.assertEqual(report["status"], "opt_in_required")
        self.assertFalse(report["passed"])
        self.assertFalse(report["source_isolation"]["raw_text_included"])

    def test_provider_e2e_probe_accepts_mock_opt_in_without_network(self):
        seeded = self.seed_knowledge_system()
        history_id = seeded["history"]["asset"]["id"]
        report = mkaos.run_mkaos_provider_e2e_probe(
            self.storage,
            {
                "project_id": self.project_id,
                "probe_type": "both",
                "provider_mode": "mock",
                "provider_opt_in": True,
                "model_judge_payload": {"knowledge_items": [{"knowledge_id": history_id, "concept_name": "行动化制度冲突"}]},
                "model_judge_result": {"conflicts": []},
                "mock_provider_candidates": [
                    {
                        "candidate_id": "candidate-provider-ok",
                        "concept_name": "行动化制度冲突",
                        "core_explanation": "把制度压力转为角色选择、场景阻碍和利益代价。",
                        "target_flows": ["prose"],
                        "target_disciplines": ["历史制度"],
                        "confidence": 0.86,
                    }
                ],
                "persist": True,
            },
        )["data"]

        self.assertEqual(report["status"], "completed")
        self.assertTrue(report["passed"])
        self.assertEqual(report["model_judge_probe"]["status"], "completed")
        self.assertTrue(report["extraction_provider_probe"]["passed"])

    def test_semantic_conflict_review_marks_model_review_need_for_mixed_rhythm(self):
        items = [
            {"knowledge_id": "k-fast", "concept_name": "番茄快节奏强反转", "core_explanation": "强情绪、强爽点、快速打脸。"},
            {"knowledge_id": "k-literary", "concept_name": "出版文学质感", "core_explanation": "慢热、结构完整、语言稳定。"},
        ]
        report = mkaos.run_semantic_conflict_review(
            self.storage,
            {"project_id": self.project_id, "flow": "prose", "knowledge_items": items, "persist": False},
        )["data"]

        self.assertTrue(report["conflicts"])
        self.assertTrue(report["requires_model_review"])
        self.assertEqual(report["reasoning_mode"], "graph_plus_deterministic_semantic_first_slice")

    def test_human_approval_flow_can_apply_low_effect_quarantine(self):
        seeded = self.seed_knowledge_system()
        risky_id = seeded["risky"]["asset"]["id"]
        for index in range(3):
            mkaos.record_usage_event(
                self.storage,
                {
                    "project_id": self.project_id,
                    "knowledge_id": risky_id,
                    "knowledge_pack_id": "pack-risk",
                    "flow": "prose",
                    "agent_name": "DraftAgent",
                    "used_as": "constraint",
                    "effect_score": 0.01,
                    "target_artifact_id": f"bad-{index}",
                },
            )

        evolution = mkaos.run_knowledge_evolution_cycle(
            self.storage,
            {
                "project_id": self.project_id,
                "flow": "prose",
                "evolution_mode": "human_approval",
                "create_approval_requests": True,
            },
        )["data"]
        approvals = evolution["approval_workflow"]["approvals"]
        self.assertTrue(approvals)
        quarantine = next(item for item in approvals if item["action_type"] == "quarantine_knowledge")

        resolved = mkaos.resolve_governance_approval(
            self.storage,
            quarantine["approval_id"],
            {"status": "approved", "apply": True, "actor": "unit-test"},
        )

        self.assertEqual(resolved["asset"]["content"]["status"], "applied")
        updated = next(row for row in mkaos.list_knowledge_cards(self.storage, project_id=self.project_id, include_deprecated=True) if row["id"] == risky_id)
        self.assertEqual(updated["content"]["status"], "quarantined")
