from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.content_intelligence_governance import content_intelligence_preflight_gate
from novel_forge.modules.genre_os.service import build_genre_strategy_pack
from novel_forge.modules.model_operation_governance import enforce_model_operation_preflight
from novel_forge.modules.style_os.service import build_style_profile, extract_style_fingerprint, ingest_style_sample
from novel_forge.modules.topics import service as topics_service
from novel_forge.schemas import MaterialCard
from novel_forge.storage.local import LocalStorage


class CountingTopicModel:
    name = "fixture-topic-model"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, prompt: str, context: dict | None = None) -> dict:
        self.calls += 1
        return {
            "provider": "fixture-provider",
            "model": self.name,
            "text": "A governed topic seed with enough detail for validation.",
            "copyright_boundary": "fixture output uses abstract material patterns only",
        }


class ModelOperationGovernanceTests(unittest.TestCase):
    def test_topic_production_missing_provider_gate_blocks_before_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            material_path = _material(storage, project_id="topic-prod")
            model = CountingTopicModel()

            with self.assertRaisesRegex(RuntimeError, "provider_runtime_gate"):
                topics_service.develop_topic(
                    storage,
                    str(material_path),
                    model=model,
                    environment="production",
                    os_envelope=_envelope("topic-prod", "develop-topic", "topic_seed"),
                    source_policy={"source_isolation_required": True, "raw_source_text_allowed": False},
                )

            self.assertEqual(model.calls, 0)
            reports = _production_governance_reports(storage)
            self.assertTrue(reports)
            self.assertEqual(reports[-1]["content"]["status"], "blocked")
            self.assertEqual(reports[-1]["content"]["blocking_issues"][0]["dimension"], "provider_runtime_gate")

    def test_topic_production_provider_gate_records_passed_governance_on_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            material_path = _material(storage, project_id="topic-prod")
            model = CountingTopicModel()

            topic_path = topics_service.develop_topic(
                storage,
                str(material_path),
                model=model,
                environment="production",
                os_envelope=_envelope("topic-prod", "develop-topic", "topic_seed"),
                source_policy={"source_isolation_required": True, "raw_source_text_allowed": False},
                provider_runtime_gate={
                    "status": "passed",
                    "provider": "fixture-provider",
                    "model": "fixture-topic-model",
                    "path": "runs/provider-runtime-gate.json",
                },
            )

            self.assertEqual(model.calls, 1)
            topic = storage.read_json(topic_path)
            governance = topic["content"]["production_governance"]
            self.assertEqual(governance["status"], "passed")
            self.assertTrue(governance["path"])
            report = storage.read_json(storage.root / governance["path"])
            self.assertEqual(report["type"], "production_governance_report")
            self.assertEqual(report["content"]["operation"], "develop-topic")
            self.assertEqual(report["content"]["gate_statuses"]["provider_runtime_gate"]["status"], "passed")

    def test_content_intelligence_preflight_blocks_production_model_operation_without_genre_style_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            material_path = _material(storage, project_id="ci-prod")
            material = storage.read_json(material_path)

            content_gate = content_intelligence_preflight_gate(
                storage,
                target_asset_id=str(material["id"]),
                target_asset_path=material_path,
                project_id="ci-prod",
                required=True,
            )

            self.assertEqual(content_gate["status"], "blocked")
            self.assertEqual(
                {issue["dimension"] for issue in content_gate["blocking_issues"]},
                {"content_intelligence.genre_strategy", "content_intelligence.style_policy"},
            )
            with self.assertRaisesRegex(RuntimeError, "content_intelligence"):
                enforce_model_operation_preflight(
                    storage,
                    operation="draft-chapter",
                    environment="production",
                    target_asset_id=str(material["id"]),
                    target_asset_path=material_path,
                    project_id="ci-prod",
                    asset_type="draft_chapter",
                    task_type="draft_chapter",
                    os_envelope=_envelope("ci-prod", "draft-chapter", "draft_chapter"),
                    source_policy={"source_isolation_required": True, "raw_source_text_allowed": False},
                    provider_runtime_gate={
                        "status": "passed",
                        "provider": "fixture-provider",
                        "model": "fixture-draft-model",
                        "path": "runs/provider-runtime-gate.json",
                    },
                    extra_gate_statuses={"content_intelligence": content_gate},
                    extra_required_gates=["content_intelligence"],
                )

    def test_content_intelligence_preflight_passes_production_model_operation_with_genre_style_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            material_path = _material(storage, project_id="ci-prod")
            material = storage.read_json(material_path)
            _genre_and_style_evidence(storage, project_id="ci-prod")

            content_gate = content_intelligence_preflight_gate(
                storage,
                target_asset_id=str(material["id"]),
                target_asset_path=material_path,
                project_id="ci-prod",
                required=True,
            )

            self.assertEqual(content_gate["status"], "passed")
            governance = enforce_model_operation_preflight(
                storage,
                operation="draft-chapter",
                environment="production",
                target_asset_id=str(material["id"]),
                target_asset_path=material_path,
                project_id="ci-prod",
                asset_type="draft_chapter",
                task_type="draft_chapter",
                os_envelope=_envelope("ci-prod", "draft-chapter", "draft_chapter"),
                source_policy={"source_isolation_required": True, "raw_source_text_allowed": False},
                provider_runtime_gate={
                    "status": "passed",
                    "provider": "fixture-provider",
                    "model": "fixture-draft-model",
                    "path": "runs/provider-runtime-gate.json",
                },
                extra_gate_statuses={"content_intelligence": content_gate},
                extra_required_gates=["content_intelligence"],
            )

            self.assertEqual(governance["status"], "passed")
            self.assertIn("content_intelligence", governance["required_gates"])
            report = storage.read_json(storage.root / governance["path"])
            self.assertEqual(report["content"]["gate_statuses"]["content_intelligence"]["status"], "passed")


def _material(storage: LocalStorage, *, project_id: str) -> Path:
    return storage.write_asset(
        "materials",
        MaterialCard(
            title="Governed material",
            tags=["material", "suspense"],
            content={
                "usable_patterns": ["public signal hook", "ethical choice pressure"],
                "do_not_copy": ["source phrasing", "source plot sequence"],
            },
            metadata={"project_id": project_id},
        ),
    )


def _envelope(project_id: str, task_type: str, asset_type: str) -> dict:
    return {
        "envelope_id": f"env-{project_id}-{task_type}",
        "project_id": project_id,
        "task_type": task_type,
        "asset_type": asset_type,
        "actor_type": "unit_test",
        "actor_id": "test",
        "source": "unit-test",
        "trace_id": f"trace-{project_id}-{task_type}",
        "environment": "production",
        "source_policy": {"source_isolation_required": True, "raw_source_text_allowed": False},
    }


def _production_governance_reports(storage: LocalStorage) -> list[dict]:
    return [
        storage.read_json(path)
        for path in storage.list_json("runs")
        if storage.read_json(path).get("type") == "production_governance_report"
    ]


def _genre_and_style_evidence(storage: LocalStorage, *, project_id: str) -> None:
    build_genre_strategy_pack(
        storage,
        genre="mystery",
        subgenre="police_procedural",
        project_id=project_id,
        platform_id="local",
    )
    sample = ingest_style_sample(
        storage,
        sample_text="雨夜里，值班灯忽然闪了一下。她停住脚步，看见证物袋上多出一枚陌生指纹。",
        project_id=project_id,
        rights={"license": "project-owned-or-authorized", "allowed_usage": "style_parameter_extraction"},
    )
    fingerprint = extract_style_fingerprint(storage, sample_path=sample["path"])
    build_style_profile(storage, fingerprint_path=fingerprint["path"], style_name="CI fixture style")


if __name__ == "__main__":
    unittest.main()
