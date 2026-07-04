from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.context_builder import build_flow_context_bundle
from novel_forge.modules.mkaos import MkaosPackPolicyError, validate_mkaos_pack_result
from novel_forge.schemas import ChapterPlan
from novel_forge.storage.local import LocalStorage


class MkaosFailClosedPolicyTests(unittest.TestCase):
    def test_mock_build_knowledge_pack_exception_blocks_production(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = _chapter_plan(storage, "mkaos-prod")

            with patch(
                "novel_forge.modules.context_builder.service.build_knowledge_pack",
                side_effect=RuntimeError("mock pack failure"),
            ):
                with self.assertRaisesRegex(ValueError, "MKAOS pack build failed in production"):
                    build_flow_context_bundle(
                        storage,
                        plan_path,
                        flow="prose",
                        project_id="mkaos-prod",
                        chapter_id="1",
                        current_goal="draft production chapter",
                        environment="production",
                        os_envelope=_os_envelope("mkaos-prod", "prose", "knowledge_pack", trace_id="trace-mkaos-prod"),
                    )

    def test_strict_and_operating_system_modes_block_pack_failure(self):
        for environment in ["strict", "operating_system"]:
            with self.subTest(environment=environment):
                with tempfile.TemporaryDirectory() as tmp:
                    storage = LocalStorage(tmp)
                    storage.ensure_layout()
                    plan_path = _chapter_plan(storage, f"mkaos-{environment}")

                    with patch(
                        "novel_forge.modules.context_builder.service.build_knowledge_pack",
                        side_effect=RuntimeError("mock pack failure"),
                    ):
                        with self.assertRaisesRegex(ValueError, "MKAOS pack build failed in production"):
                            build_flow_context_bundle(
                                storage,
                                plan_path,
                                flow="review",
                                project_id=f"mkaos-{environment}",
                                chapter_id="1",
                                current_goal="review strict chapter",
                                environment=environment,
                                os_envelope=_os_envelope(
                                    f"mkaos-{environment}",
                                    "review",
                                    "knowledge_pack",
                                    trace_id=f"trace-{environment}",
                                    environment=environment,
                                ),
                            )

    def test_mock_build_knowledge_pack_exception_records_compat_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = _chapter_plan(storage, "mkaos-compat")

            with patch(
                "novel_forge.modules.context_builder.service.build_knowledge_pack",
                side_effect=RuntimeError("mock pack failure"),
            ):
                result = build_flow_context_bundle(
                    storage,
                    plan_path,
                    flow="outline",
                    project_id="mkaos-compat",
                    chapter_id="1",
                    current_goal="compat outline",
                    environment="compat",
                )

            content = result["asset"]["content"]
            metadata = result["asset"]["metadata"]
            policy = content["mkaos_pack_policy"]
            self.assertFalse(policy["strict"])
            self.assertTrue(policy["compat_warning_allowed"])
            self.assertIn("warning fallback", content["mkaos_pack_warning"])
            self.assertTrue(content["mkaos_runtime_policy_warning_path"])
            self.assertTrue(content["mkaos_pack_trace_span_path"])
            self.assertEqual(metadata["mkaos_pack_policy"], policy)
            self.assertTrue(metadata["mkaos_runtime_policy_warning_path"])
            self.assertTrue(metadata["mkaos_pack_trace_span_path"])

            gate = storage.read_json(storage.root / content["mkaos_runtime_policy_warning_path"])
            self.assertEqual(gate["type"], "gate_result")
            self.assertEqual(gate["content"]["status"], "warning")
            self.assertEqual(gate["content"]["gate_kind"], "runtime_policy")

    def test_prose_empty_pack_blocks_in_production(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = _chapter_plan(storage, "mkaos-empty")

            with self.assertRaisesRegex(MkaosPackPolicyError, "prose MKAOS pack is empty"):
                build_flow_context_bundle(
                    storage,
                    plan_path,
                    flow="prose",
                    project_id="mkaos-empty",
                    chapter_id="1",
                    current_goal="draft with no knowledge",
                    environment="production",
                        os_envelope=_os_envelope("mkaos-empty", "prose", "knowledge_pack", trace_id="trace-empty"),
                    )

    def test_missing_knowledge_pack_id_blocks_in_production(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = _chapter_plan(storage, "mkaos-missing-id")

            def pack_without_id(*_args, **_kwargs):
                return {
                    "path": "data/contexts/pack-without-id.json",
                    "asset": {
                        "id": "",
                        "type": "knowledge_pack",
                        "content": {"pack_items": [{"knowledge_id": "k1"}]},
                        "metadata": {"project_id": "mkaos-missing-id"},
                    },
                    "validation": {"ok": True, "errors": []},
                }

            with patch("novel_forge.modules.context_builder.service.build_knowledge_pack", side_effect=pack_without_id):
                with self.assertRaisesRegex(MkaosPackPolicyError, "knowledge_pack_id is required"):
                    build_flow_context_bundle(
                        storage,
                        plan_path,
                        flow="review",
                        project_id="mkaos-missing-id",
                        chapter_id="1",
                        current_goal="review missing pack id",
                        environment="production",
                        os_envelope=_os_envelope("mkaos-missing-id", "review", "knowledge_pack", trace_id="trace-missing-id"),
                    )

    def test_missing_context_bundle_blocks_in_production_policy_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            pack = {
                "path": "data/contexts/valid-pack.json",
                "asset": {
                    "id": "knowledge_pack_context_required",
                    "type": "knowledge_pack",
                    "content": {
                        "knowledge_pack_id": "knowledge_pack_context_required",
                        "pack_items": [{"knowledge_id": "k1"}],
                    },
                    "metadata": {"project_id": "mkaos-context-required"},
                },
            }

            with self.assertRaisesRegex(MkaosPackPolicyError, "context_bundle is required"):
                validate_mkaos_pack_result(
                    storage,
                    flow="review",
                    mkaos_pack=pack,
                    project_id="mkaos-context-required",
                    environment="production",
                    context_bundle_path="",
                )

    def test_source_isolation_failure_blocks_even_in_compat(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = _chapter_plan(storage, "mkaos-leak")

            def leaking_pack(*_args, **_kwargs):
                return {
                    "path": "data/contexts/leaking-pack.json",
                    "asset": {
                        "id": "knowledge_pack_leak",
                        "type": "knowledge_pack",
                        "title": "Leaking pack",
                        "content": {
                            "knowledge_pack_id": "knowledge_pack_leak",
                            "pack_items": [{"knowledge_id": "k1"}],
                            "raw_text": "source_chunk.raw_text must never enter generation context",
                        },
                        "metadata": {"project_id": "mkaos-leak"},
                    },
                    "validation": {"ok": True, "errors": []},
                }

            with patch("novel_forge.modules.context_builder.service.build_knowledge_pack", side_effect=leaking_pack):
                with self.assertRaisesRegex(ValueError, "source_chunk.raw_text|raw_text"):
                    build_flow_context_bundle(
                        storage,
                        plan_path,
                        flow="prose",
                        project_id="mkaos-leak",
                        chapter_id="1",
                        current_goal="draft leaking chapter",
                        environment="compat",
                    )


def _chapter_plan(storage: LocalStorage, project_id: str) -> Path:
    return storage.write_asset(
        "chapter_plans",
        ChapterPlan(
            title="MKAOS policy chapter plan",
            content={
                "chapter": 1,
                "objective": "prove pack policy",
                "beats": ["open gate", "apply policy", "record proof"],
                "hook": "the policy result is visible",
            },
            metadata={"project_id": project_id},
        ),
    )


def _os_envelope(project_id: str, task_type: str, asset_type: str, *, trace_id: str, environment: str = "production") -> dict[str, object]:
    return {
        "envelope_id": f"env-{trace_id}",
        "project_id": project_id,
        "task_type": task_type,
        "asset_type": asset_type,
        "actor_type": "unit_test",
        "actor_id": "mkaos-policy-test",
        "source": "unit-test",
        "trace_id": trace_id,
        "source_policy": {
            "raw_source_text_allowed": False,
            "generation_rag_allowed": False,
            "source_chunk_raw_text_allowed": False,
        },
        "environment": environment,
    }


if __name__ == "__main__":
    unittest.main()
