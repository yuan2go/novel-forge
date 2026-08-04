from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos import (
    convert_assets,
    convert_rules,
    create_knowledge_card,
    create_usage_binding,
    import_source_document,
    query_knowledge,
)
from novel_forge.storage.local import LocalStorage
from tests.unit.legacy_compatibility import legacy_settings
from novel_forge.modules.source_intake import create_source_policy, create_source_risk_report


class MkaosOsEnvelopeTests(unittest.TestCase):
    def test_production_mkaos_mutation_requires_os_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            with self.assertRaisesRegex(ValueError, "OS envelope required"):
                import_source_document(storage, {"title": "prod source", "text": "production source", "project_id": "p-env", "environment": "production"})

    def test_production_os_envelope_is_attached_and_traced(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            envelope = _envelope("p-env", "source_import", "source_document", trace_id="trace-mkaos-envelope")
            source = import_source_document(
                storage,
                {
                    "title": "enveloped source",
                    "text": "source evidence for abstract conversion",
                    "project_id": "p-env",
                    "environment": "production",
                    "os_envelope": envelope,
                },
            )
            metadata = source["asset"]["metadata"]
            self.assertEqual(metadata["os_envelope"]["trace_id"], "trace-mkaos-envelope")
            self.assertEqual(metadata["os_envelope"]["status"], "enforced")
            self.assertEqual(source["chunks"][0]["asset"]["metadata"]["os_envelope_id"], metadata["os_envelope_id"])

            traces = _assets_by_type(storage, "trace_span")
            self.assertTrue(any(row["content"]["span_type"] == "os_envelope" and row["content"]["trace_id"] == "trace-mkaos-envelope" for row in traces))

    def test_sample_bypass_is_explicit_and_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            source = import_source_document(
                storage,
                {
                    "title": "sample source",
                    "text": "sample fixture source",
                    "project_id": "p-sample",
                    "environment": "sample",
                    "bypass_reason": "unit fixture",
                },
            )
            envelope = source["asset"]["metadata"]["os_envelope"]
            self.assertEqual(envelope["status"], "bypassed")
            self.assertEqual(envelope["bypass_reason"], "unit fixture")

    def test_query_and_convert_services_return_standard_envelope_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            source = import_source_document(storage, {"title": "制度来源", "text": "制度压力造成行动成本。", "project_id": "p-query"})
            _govern_source(storage, project_id="p-query", source_ref="制度来源")
            knowledge = create_knowledge_card(
                storage,
                {
                    "concept_name": "制度压力",
                    "core_explanation": "制度约束改变行动成本。",
                    "source_chunk_ids": [source["chunks"][0]["id"]],
                    "project_id": "p-query",
                    "quality_score": 0.8,
                    "weight": 1.2,
                },
            )
            create_usage_binding(storage, knowledge["asset"]["id"], {"flow": "prose", "input_role": "optional", "usage_type": "optional", "priority": 5})

            response = query_knowledge(
                storage,
                {
                    "project_id": "p-query",
                    "flow": "prose",
                    "query": "制度压力",
                    "environment": "production",
                    "os_envelope": _envelope("p-query", "prose", "knowledge_query", trace_id="trace-query"),
                },
            )
            self.assertTrue(response["success"])
            self.assertEqual(response["trace_id"], "trace-query")
            self.assertEqual(response["data"]["items"][0]["concept_name"], "制度压力")
            self.assertGreater(response["data"]["items"][0]["selection_score"], 0)

            converted_rules = convert_rules(
                storage,
                {
                    "project_id": "p-query",
                    "knowledge_id": knowledge["asset"]["id"],
                    "environment": "production",
                    "os_envelope": _envelope("p-query", "review", "rule_card", trace_id="trace-convert-rules"),
                    "create_template": True,
                },
            )
            self.assertTrue(converted_rules["success"])
            self.assertEqual(converted_rules["trace_id"], "trace-convert-rules")
            self.assertEqual(converted_rules["data"]["rule"]["asset"]["type"], "rule_card")
            self.assertEqual(converted_rules["data"]["template"]["asset"]["type"], "template_card")

            conversion_source = import_source_document(storage, {"title": "新的抽象来源", "text": "新的抽象来源材料。", "project_id": "p-query"})
            _govern_source(storage, project_id="p-query", source_ref="新的抽象来源")
            converted_assets = convert_assets(
                storage,
                {
                    "project_id": "p-query",
                    "source_id": conversion_source["asset"]["id"],
                    "concept_name": "新机制",
                    "core_explanation": "抽象机制只保留行动约束。",
                    "environment": "production",
                    "os_envelope": _envelope("p-query", "knowledge_create", "knowledge_card", trace_id="trace-convert-assets"),
                },
            )
            self.assertTrue(converted_assets["success"])
            self.assertEqual(converted_assets["trace_id"], "trace-convert-assets")
            self.assertEqual(converted_assets["data"]["knowledge"][0]["asset"]["type"], "knowledge_card")

    def test_mkaos_query_api_uses_standard_envelope(self):
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")

        from novel_forge.api.app import create_app
        from novel_forge.infrastructure.settings import IndustrialSettings

        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(create_app(legacy_settings(root=Path(tmp).resolve())))
            missing = client.post(
                "/product/mkaos/sources",
                json={"title": "prod", "text": "prod", "project_id": "p-api", "environment": "production"},
            )
            self.assertEqual(missing.status_code, 400)
            self.assertIn("OS envelope required", missing.text)

            source = client.post(
                "/product/mkaos/sources",
                json={
                    "title": "api source",
                    "text": "制度压力造成行动成本。",
                    "project_id": "p-api",
                    "environment": "production",
                    "os_envelope": _envelope("p-api", "source_import", "source_document", trace_id="trace-api-source"),
                },
            )
            self.assertEqual(source.status_code, 200, source.text)
            governed_storage = LocalStorage(tmp)
            governed_storage.ensure_layout()
            _govern_source(governed_storage, project_id="p-api", source_ref="api source")
            knowledge = client.post(
                "/product/mkaos/convert/assets",
                json={
                    "project_id": "p-api",
                    "source_id": source.json()["asset"]["id"],
                    "concept_name": "API制度压力",
                    "core_explanation": "抽象制度压力影响行动成本。",
                    "environment": "production",
                    "os_envelope": _envelope("p-api", "knowledge_create", "knowledge_card", trace_id="trace-api-convert"),
                },
            )
            self.assertEqual(knowledge.status_code, 200, knowledge.text)
            query = client.post(
                "/product/mkaos/query/knowledge",
                json={
                    "project_id": "p-api",
                    "query": "制度压力",
                    "environment": "production",
                    "os_envelope": _envelope("p-api", "query", "knowledge_query", trace_id="trace-api-query"),
                },
            )
            self.assertEqual(query.status_code, 200, query.text)
            self.assertTrue(query.json()["success"])
            self.assertEqual(query.json()["trace_id"], "trace-api-query")


def _envelope(project_id: str, task_type: str, asset_type: str, *, trace_id: str) -> dict[str, object]:
    return {
        "project_id": project_id,
        "task_type": task_type,
        "asset_type": asset_type,
        "actor_type": "unit_test",
        "actor_id": "test-runner",
        "source": "mkaos",
        "version": "0.1.0",
        "trace_id": trace_id,
        "source_policy": {"raw_source_text_allowed": False, "generation_rag_allowed": False},
        "environment": "production",
    }


def _govern_source(storage: LocalStorage, *, project_id: str, source_ref: str) -> None:
    policy = create_source_policy(storage, {"project_id": project_id, "source_ref": source_ref, "risk_tier": "R0"})
    create_source_risk_report(
        storage,
        {"project_id": project_id, "source_ref": source_ref, "source_policy_path": policy["path"], "risk_tier": "R0"},
    )


def _assets_by_type(storage: LocalStorage, asset_type: str) -> list[dict[str, object]]:
    rows = []
    for path in storage.list_json("runs"):
        data = storage.read_json(path)
        if isinstance(data, dict) and data.get("type") == asset_type:
            rows.append(data)
    return rows


if __name__ == "__main__":
    unittest.main()
