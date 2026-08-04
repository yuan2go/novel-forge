from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos import (
    build_knowledge_graph,
    build_knowledge_pack,
    create_knowledge_card,
    create_rule_card,
    create_template_card,
    create_usage_binding,
    import_source_document,
    learn_from_knowledge_effects,
    query_knowledge_graph,
    query_knowledge_graph_paths,
    record_review_feedback,
    record_usage_event,
)
from novel_forge.storage.local import LocalStorage
from tests.unit.legacy_compatibility import legacy_settings


RAW_SENTINEL = "RAW_SENTINEL_DO_NOT_LEAK"


class MkaosKnowledgeGraphLearningTests(unittest.TestCase):
    def test_multidisciplinary_graph_unifies_cards_rules_templates_feedback_without_raw_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            seed = _seed_graph_fixture(storage)

            graph = build_knowledge_graph(storage, {"project_id": "kg-learn-p", "flow": "prose", "persist": True})
            payload = json.dumps(graph, ensure_ascii=False)
            self.assertTrue(graph["success"])
            self.assertTrue(graph["data"]["path"])
            self.assertNotIn('"raw_text"', payload)
            self.assertNotIn("clean_text", payload)
            self.assertNotIn(RAW_SENTINEL, payload)
            self.assertIn("knowledge_card", graph["data"]["summary"]["coverage"])
            self.assertIn("rule_card", graph["data"]["summary"]["coverage"])
            self.assertIn("template_card", graph["data"]["summary"]["coverage"])
            self.assertIn("bound_to_flow", graph["data"]["summary"]["edge_relation_counts"])
            self.assertIn("effect_observed", graph["data"]["summary"]["edge_relation_counts"])

            query = query_knowledge_graph(storage, {"project_id": "kg-learn-p", "flow": "prose", "query": "土地兼并"})
            self.assertTrue(query["success"])
            self.assertTrue(any(node["label"] == "土地兼并行动成本" for node in query["data"]["nodes"]))
            self.assertEqual(query["data"]["source_isolation"]["raw_source_text_included"], False)

            path = query_knowledge_graph_paths(storage, {"project_id": "kg-learn-p", "flow": "prose", "source": seed["positive"]["asset"]["id"], "target": "prose", "max_depth": 2})
            self.assertTrue(path["success"])
            self.assertGreaterEqual(path["data"]["path_count"], 1)
            self.assertIn("bound_to_flow", path["data"]["paths"][0]["relation_path"])

    def test_effect_learning_writes_auditable_snapshot_and_changes_pack_selection_weight(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            seed = _seed_graph_fixture(storage)

            before = build_knowledge_pack(storage, {"project_id": "kg-learn-p", "flow": "prose", "knowledge_budget": {"max_core_knowledge": 2}})
            before_weights = {item["knowledge_id"]: item["weight"] for item in before["asset"]["content"]["pack_items"]}

            learning = learn_from_knowledge_effects(
                storage,
                {
                    "project_id": "kg-learn-p",
                    "flow": "prose",
                    "apply_updates": True,
                    "learning_rate": 0.3,
                    "persist": True,
                },
            )
            self.assertTrue(learning["success"])
            self.assertTrue(learning["data"]["path"])
            self.assertGreaterEqual(len(learning["data"]["recommendations"]), 1)
            self.assertGreaterEqual(len(learning["data"]["applied_updates"]), 1)
            self.assertEqual(learning["data"]["source_isolation"]["raw_source_text_included"], False)
            self.assertNotIn('"raw_text"', json.dumps(learning, ensure_ascii=False))
            self.assertNotIn(RAW_SENTINEL, json.dumps(learning, ensure_ascii=False))

            after = build_knowledge_pack(storage, {"project_id": "kg-learn-p", "flow": "prose", "knowledge_budget": {"max_core_knowledge": 2}})
            after_items = after["asset"]["content"]["pack_items"]
            after_weights = {item["knowledge_id"]: item["weight"] for item in after_items}
            positive_id = seed["positive"]["asset"]["id"]
            negative_id = seed["negative"]["asset"]["id"]
            self.assertGreater(after_weights[positive_id], before_weights[positive_id])
            self.assertLess(after_weights[negative_id], before_weights[negative_id])
            self.assertEqual(after_items[0]["knowledge_id"], positive_id)

    def test_knowledge_graph_and_learning_api_smoke(self):
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")

        from novel_forge.api.app import create_app
        from novel_forge.infrastructure.settings import IndustrialSettings

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            client = TestClient(create_app(legacy_settings(root=root)))
            source = client.post(
                "/product/mkaos/sources",
                json={"project_id": "kg-api-p", "title": "水利制度", "text": "水利争端会改变乡绅和佃户的成本。"},
            )
            self.assertEqual(source.status_code, 200, source.text)
            knowledge = client.post(
                "/product/mkaos/knowledge",
                json={
                    "project_id": "kg-api-p",
                    "concept_name": "水利争端",
                    "discipline": "制度经济",
                    "core_explanation": "水利规则把资源分配压力推到行动选择上。",
                    "source_chunk_ids": [source.json()["chunks"][0]["id"]],
                },
            )
            self.assertEqual(knowledge.status_code, 200, knowledge.text)
            binding = client.post(
                f"/product/mkaos/knowledge/{knowledge.json()['asset']['id']}/usage-bindings",
                json={"flow": "prose", "usage_type": "optional", "input_role": "optional"},
            )
            self.assertEqual(binding.status_code, 200, binding.text)
            graph = client.post("/product/mkaos/knowledge-graph/build", json={"project_id": "kg-api-p", "flow": "prose"})
            self.assertEqual(graph.status_code, 200, graph.text)
            self.assertTrue(graph.json()["success"])
            learning = client.post("/product/mkaos/learning/effects", json={"project_id": "kg-api-p", "flow": "prose", "persist": False})
            self.assertEqual(learning.status_code, 200, learning.text)
            self.assertTrue(learning.json()["success"])


def _seed_graph_fixture(storage: LocalStorage) -> dict:
    source = import_source_document(
        storage,
        {
            "project_id": "kg-learn-p",
            "title": "土地兼并来源",
            "text": f"土地兼并造成佃户行动成本变化。{RAW_SENTINEL}",
        },
    )
    chunk_id = source["chunks"][0]["id"]
    positive = create_knowledge_card(
        storage,
        {
            "project_id": "kg-learn-p",
            "concept_name": "土地兼并行动成本",
            "discipline": "历史制度",
            "knowledge_type": "conflict_mechanism",
            "core_explanation": "豪强获利、小农受损，主角必须选择是否公开田契。",
            "source_chunk_ids": [chunk_id],
            "quality_score": 0.7,
            "weight": 1.0,
        },
    )
    negative = create_knowledge_card(
        storage,
        {
            "project_id": "kg-learn-p",
            "concept_name": "制度百科解释",
            "discipline": "历史制度",
            "knowledge_type": "explanation",
            "core_explanation": "只解释制度定义，暂未转为行动。",
            "source_chunk_ids": [chunk_id],
            "quality_score": 0.7,
            "weight": 1.0,
        },
    )
    rule = create_rule_card(
        storage,
        {
            "project_id": "kg-learn-p",
            "rule_name": "制度知识必须转行动",
            "rule_type": "knowledge_effectiveness",
            "trigger_condition": "制度知识进入正文",
            "check_items": ["必须改变角色选择成本"],
            "severity": "high",
            "blocking": False,
            "applicable_flows": ["prose"],
        },
    )
    template = create_template_card(
        storage,
        {
            "project_id": "kg-learn-p",
            "template_name": "制度冲突场景模板",
            "template_type": "knowledge_application",
            "structure": ["pressure", "choice", "cost", "payoff"],
            "applicable_flows": ["prose"],
        },
    )
    for card in [positive, negative]:
        create_usage_binding(
            storage,
            card["asset"]["id"],
            {
                "flow": "prose",
                "usage_type": "optional",
                "input_role": "optional",
                "priority": 20,
                "review_rule_id": rule["asset"]["id"],
                "template_id": template["asset"]["id"],
            },
        )
    record_usage_event(
        storage,
        {
            "project_id": "kg-learn-p",
            "knowledge_id": positive["asset"]["id"],
            "flow": "prose",
            "knowledge_pack_id": "pack-positive",
            "agent_name": "ProseAgent",
            "used_as": "scene_constraint",
            "effect_score": 0.9,
            "review_result": {"passed": True},
            "reader_feedback": {"rating": 5, "sentiment": "positive"},
        },
    )
    record_usage_event(
        storage,
        {
            "project_id": "kg-learn-p",
            "knowledge_id": negative["asset"]["id"],
            "flow": "prose",
            "knowledge_pack_id": "pack-negative",
            "agent_name": "ProseAgent",
            "used_as": "exposition",
            "effect_score": 0.1,
            "review_result": {"anti_encyclopedia_hit": True},
            "reader_feedback": {"rating": 2, "sentiment": "negative"},
        },
    )
    record_review_feedback(storage, {"project_id": "kg-learn-p", "knowledge_id": positive["asset"]["id"], "flow": "prose", "delta": 0.12, "reason": "effective_scene"})
    record_review_feedback(storage, {"project_id": "kg-learn-p", "knowledge_id": negative["asset"]["id"], "flow": "prose", "delta": -0.18, "reason": "encyclopedia_exposition"})
    return {"source": source, "positive": positive, "negative": negative, "rule": rule, "template": template}


if __name__ == "__main__":
    unittest.main()
