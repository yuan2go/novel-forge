from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos import (
    adapt_pack_for_flow,
    apply_weight_update,
    build_knowledge_pack,
    create_knowledge_card,
    create_rule_card,
    create_template_card,
    create_usage_binding,
    import_source_document,
    list_source_chunks,
    list_usage_events,
    rebuild_source_chunks,
    record_review_feedback,
    record_usage_event,
    run_minimal_acceptance_fixture,
    update_knowledge_card,
    update_usage_binding,
    validate_artifact,
    validate_canon_conflict,
)
from novel_forge.storage.local import LocalStorage
from tests.unit.legacy_compatibility import legacy_settings


class MkaosTests(unittest.TestCase):
    def test_mkaos_api_smoke_builds_pack(self):
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")

        from novel_forge.api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(create_app(legacy_settings(root=Path(tmp).resolve())))
            source = client.post(
                "/product/mkaos/sources",
                json={"title": "土地兼并", "text": "王朝末期，土地兼并严重，小农破产。"},
            )
            self.assertEqual(source.status_code, 200, source.text)
            chunk_ids = [row["id"] for row in source.json()["chunks"]]
            knowledge = client.post(
                "/product/mkaos/knowledge",
                json={"concept_name": "土地兼并", "core_explanation": "豪强获利，小农受损。", "source_chunk_ids": chunk_ids},
            )
            self.assertEqual(knowledge.status_code, 200, knowledge.text)
            binding = client.post(
                f"/product/mkaos/knowledge/{knowledge.json()['asset']['id']}/usage-bindings",
                json={"flow": "outline", "usage_type": "required", "input_role": "required", "constraint_text": "地方土地案作为第一卷主线冲突"},
            )
            self.assertEqual(binding.status_code, 200, binding.text)
            pack = client.post("/product/mkaos/packs/build", json={"flow": "outline", "current_goal": "API smoke"})
            self.assertEqual(pack.status_code, 200, pack.text)
            preview = client.get(f"/product/mkaos/packs/{pack.json()['asset']['id']}/prompt-preview")
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertIn("MKAOS Knowledge Pack", preview.json()["preview"])

    def test_source_import_cleaning_and_chunk_dedupe(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            source = import_source_document(
                storage,
                {
                    "title": "制度笔记",
                    "text": "页眉\n页眉\n页眉\n\n土地兼并严重。\n\n土地兼并严重。\n\n小农破产，流民增加。",
                    "project_id": "p0",
                },
            )

            chunks = list_source_chunks(storage, source["asset"]["id"])
            self.assertEqual(source["asset"]["type"], "source_document")
            self.assertEqual(len(chunks), 1)
            self.assertIn("小农破产", chunks[0]["content"]["clean_text"])
            self.assertNotIn("页眉", chunks[0]["content"]["clean_text"])

            rebuilt = rebuild_source_chunks(storage, source["asset"]["id"])
            self.assertEqual(rebuilt["chunk_count"], 1)
            self.assertEqual(len(list_source_chunks(storage, source["asset"]["id"])), 1)

    def test_knowledge_bindings_and_pack_builder_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            source = import_source_document(storage, {"title": "土地兼并", "text": "王朝末期，土地兼并严重，小农破产。", "project_id": "p0"})
            chunk_ids = [row["id"] for row in source["chunks"]]
            knowledge = create_knowledge_card(
                storage,
                {
                    "concept_name": "土地兼并",
                    "discipline": "历史制度",
                    "knowledge_type": "conflict_mechanism",
                    "core_explanation": "豪强获利，小农受损，中央税源减少。",
                    "source_chunk_ids": chunk_ids,
                    "project_id": "p0",
                    "applicable_genres": ["历史"],
                    "applicable_platforms": ["local"],
                },
            )
            rule = create_rule_card(
                storage,
                {
                    "rule_name": "制度有效性检查",
                    "rule_type": "institutional_effectiveness",
                    "trigger_condition": "制度知识进入故事",
                    "check_items": ["推动利益冲突"],
                    "severity": "high",
                    "blocking": False,
                    "applicable_flows": ["review"],
                    "project_id": "p0",
                },
            )
            template = create_template_card(storage, {"template_name": "地方土地案主线模板", "project_id": "p0"})
            kid = knowledge["asset"]["id"]
            create_usage_binding(storage, kid, {"flow": "outline", "usage_type": "required", "input_role": "required", "template_id": template["asset"]["id"], "constraint_text": "地方土地案作为第一卷主线冲突", "priority": 1})
            create_usage_binding(storage, kid, {"flow": "chapter_outline", "usage_type": "required", "input_role": "required", "constraint_text": "每章必须有行动闭环", "priority": 1})
            prose = create_usage_binding(storage, kid, {"flow": "prose", "usage_type": "optional", "input_role": "optional", "constraint_text": "禁止大段解释土地制度", "priority": 1})
            create_usage_binding(storage, kid, {"flow": "review", "usage_type": "review_rule", "input_role": "review_rule", "review_rule_id": rule["asset"]["id"], "priority": 1})

            outline_pack = build_knowledge_pack(storage, {"flow": "outline", "project_id": "p0", "genre": "历史", "platform": "local"})
            prose_pack = build_knowledge_pack(storage, {"flow": "prose", "project_id": "p0", "genre": "历史", "platform": "local"})
            review_pack = build_knowledge_pack(storage, {"flow": "review", "project_id": "p0", "genre": "历史", "platform": "local"})
            self.assertTrue(outline_pack["asset"]["content"]["required_knowledge"])
            self.assertTrue(prose_pack["asset"]["content"]["optional_knowledge"])
            self.assertTrue(review_pack["asset"]["content"]["review_rules"])
            self.assertFalse(_contains_key(prose_pack["asset"]["content"], "raw_text"))

            update_usage_binding(storage, prose["asset"]["id"], {"enabled": False})
            disabled_pack = build_knowledge_pack(storage, {"flow": "prose", "project_id": "p0", "genre": "历史", "platform": "local"})
            self.assertFalse(disabled_pack["asset"]["content"]["optional_knowledge"])

            update_knowledge_card(storage, kid, {"status": "deprecated"})
            deprecated_pack = build_knowledge_pack(storage, {"flow": "outline", "project_id": "p0", "genre": "历史", "platform": "local"})
            self.assertFalse(deprecated_pack["asset"]["content"]["required_knowledge"])

    def test_flow_adapters_validate_and_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            fixture = run_minimal_acceptance_fixture(storage)
            packs = fixture["packs"]

            outline_adapter = adapt_pack_for_flow(storage, packs["outline"]["asset"]["id"])
            chapter_adapter = adapt_pack_for_flow(storage, packs["chapter_outline"]["asset"]["id"])
            prose_adapter = adapt_pack_for_flow(storage, packs["prose"]["asset"]["id"])
            review_adapter = adapt_pack_for_flow(storage, packs["review"]["asset"]["id"])
            self.assertTrue(outline_adapter["review_rule_refs"])
            self.assertIn("action_loop", chapter_adapter)
            self.assertFalse(prose_adapter["raw_source_text_included"])
            self.assertIn("issue_contract", review_adapter)

            bad = validate_artifact(
                storage,
                {
                    "artifact_text": "土地兼并是一种制度现象，本质上会导致小农破产。因此税源减少，所谓地方秩序也会变化。\n\n制度的概念是土地集中，专业上它意味着资源配置变化，因此需要解释清楚。",
                    "checks": ["anti_encyclopedia"],
                },
            )
            good = validate_artifact(storage, {"artifact_text": "田契被雨水泡皱，佃户跪在县衙门口，粮仓的锁却换了新铜。", "checks": ["anti_encyclopedia"]})
            self.assertFalse(bad["passed"])
            self.assertTrue(good["passed"])

            conflict = validate_canon_conflict(
                storage,
                {
                    "artifact_text": "阿照死了。",
                    "canon": {"entities": [{"canonical_name": "阿照", "status": "alive"}]},
                },
            )
            self.assertFalse(conflict["passed"])
            self.assertEqual(conflict["issues"][0]["severity"], "critical")

            kid = fixture["knowledge_card"]["asset"]["id"]
            usage = record_usage_event(storage, {"knowledge_id": kid, "knowledge_pack_id": packs["prose"]["asset"]["id"], "project_id": "mkaos-p0-fixture", "flow": "prose", "agent_name": "ProseAgent", "used_as": "scene_constraint"})
            self.assertEqual(usage["event_count"], 1)
            self.assertTrue(list_usage_events(storage, project_id="mkaos-p0-fixture", flow="prose"))
            score = record_review_feedback(storage, {"knowledge_id": kid, "flow": "review", "review_passed": True, "human_confirmed_effective": True})
            self.assertGreater(score["asset"]["content"]["delta"], 0)
            updated = apply_weight_update(storage, {"knowledge_id": kid, "flow": "review", "conflict_effective": True})
            self.assertGreater(updated["knowledge"]["asset"]["content"]["weight"], 1.0)

    def test_minimal_acceptance_fixture_proves_closed_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            result = run_minimal_acceptance_fixture(storage)
            self.assertEqual(
                result["acceptance"],
                {
                    "knowledge_enters_outline": True,
                    "knowledge_enters_chapter_outline": True,
                    "knowledge_enters_prose": True,
                    "knowledge_enters_review": True,
                    "prose_source_isolation": True,
                },
            )


def _contains_key(value, key):
    if isinstance(value, dict):
        return any(str(item_key) == key or _contains_key(item_value, key) for item_key, item_value in value.items())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


if __name__ == "__main__":
    unittest.main()
