from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.audit import create_publish_gate_report, create_release_package
from novel_forge.modules.feedback import create_reader_simulation_report, process_publish_feedback_loop, process_real_feedback_backflow
from novel_forge.modules.mkaos import create_knowledge_card, create_usage_binding, record_usage_event
from novel_forge.schemas import DraftChapter, ProjectWorkspaceState, ReaderFeedback, SourceChunk
from novel_forge.storage.local import LocalStorage


class PublishFeedbackLoopTests(unittest.TestCase):
    def test_publish_gate_writes_envelope_context_mkaos_and_source_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = _workspace(storage, "publish-loop-p")
            draft_path = _draft(storage, workspace, project_id="publish-loop-p")

            gate_path = create_publish_gate_report(
                storage,
                draft_path,
                workspace_path=str(workspace.relative_to(storage.root)),
                human_override=True,
            )
            gate = storage.read_asset(gate_path)
            content = gate.content

            self.assertTrue(content["context_bundle_path"])
            self.assertTrue(content["os_envelope_id"])
            self.assertIn("mkaos_risk", content)
            self.assertFalse(content["source_isolation"]["source_chunk_raw_text_allowed"])
            self.assertFalse(content["source_isolation"]["raw_source_text_allowed"])
            context_bundle = storage.read_json(storage.root / content["context_bundle_path"])
            self.assertNotIn('"raw_text"', str(context_bundle))
            self.assertIn("os_envelope", gate.metadata)

    def test_publish_gate_production_requires_envelope_before_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = _workspace(storage, "publish-prod-p")
            draft_path = _draft(storage, workspace, project_id="publish-prod-p")
            before_contexts = len(storage.list_json("contexts"))

            with self.assertRaisesRegex(ValueError, "OS envelope required"):
                create_publish_gate_report(
                    storage,
                    draft_path,
                    workspace_path=str(workspace.relative_to(storage.root)),
                    environment="production",
                )

            self.assertEqual(len(storage.list_json("contexts")), before_contexts)

    def test_publish_gate_uses_production_environment_from_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = _workspace(storage, "publish-env-envelope-p")
            draft_path = _draft(storage, workspace, project_id="publish-env-envelope-p")
            _publish_knowledge(storage, "publish-env-envelope-p")

            gate_path = create_publish_gate_report(
                storage,
                draft_path,
                workspace_path=str(workspace.relative_to(storage.root)),
                envelope=_production_envelope("publish-env-envelope-p", "publish_gate_report", trace_id="trace-publish-env-envelope"),
            )
            gate = storage.read_asset(gate_path)

            self.assertEqual(gate.metadata["os_envelope"]["environment"], "production")
            self.assertEqual(gate.metadata["source_policy"]["empty_pack_policy"], "block")
            self.assertFalse(gate.metadata["source_policy"]["compat_warning_allowed"])

    def test_production_release_package_blocks_non_ready_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = _workspace(storage, "release-prod-block-p")
            draft_path = _draft(storage, workspace, project_id="release-prod-block-p")
            gate_path = create_publish_gate_report(storage, draft_path, workspace_path=str(workspace.relative_to(storage.root)))
            gate = storage.read_asset(gate_path)

            self.assertNotEqual(gate.content["decision"], "ready")
            with self.assertRaisesRegex(ValueError, "publish gate decision"):
                create_release_package(
                    storage,
                    draft_path,
                    workspace_path=str(workspace.relative_to(storage.root)),
                    publish_gate_path=gate_path,
                    envelope=_production_envelope("release-prod-block-p", "release_package", trace_id="trace-release-prod-block"),
                )

    def test_release_package_blocks_mkaos_risk_and_excludes_raw_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = _workspace(storage, "publish-risk-p")
            draft_path = _draft(storage, workspace, project_id="publish-risk-p")
            create_knowledge_card(
                storage,
                {
                    "concept_name": "Risky canon note",
                    "core_explanation": "must be reviewed before publish",
                    "project_id": "publish-risk-p",
                    "risk_level": "critical",
                },
            )

            gate_path = create_publish_gate_report(storage, draft_path, workspace_path=str(workspace.relative_to(storage.root)))
            gate = storage.read_asset(gate_path)

            self.assertEqual(gate.content["decision"], "blocked")
            self.assertTrue(gate.content["mkaos_risk"]["blocking"])
            with self.assertRaisesRegex(ValueError, "MKAOS high/critical risk"):
                create_release_package(storage, draft_path, workspace_path=str(workspace.relative_to(storage.root)), publish_gate_path=gate_path)

    def test_publish_feedback_loop_writes_back_to_mkaos_weight(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = _workspace(storage, "feedback-loop-p")
            knowledge = create_knowledge_card(
                storage,
                {
                    "concept_name": "Hook pressure",
                    "core_explanation": "feedback should affect future hook pressure",
                    "project_id": "feedback-loop-p",
                    "weight": 1.0,
                },
            )
            record_usage_event(
                storage,
                {
                    "knowledge_id": knowledge["asset"]["id"],
                    "knowledge_pack_id": "feedback-loop-pack",
                    "project_id": "feedback-loop-p",
                    "flow": "review",
                    "agent_name": "ReviewAgent",
                    "used_as": "feedback_baseline",
                },
            )
            feedback_path = storage.write_asset(
                "feedback",
                ReaderFeedback(
                    title="Reader feedback",
                    content={"rows": [{"chapter": "1", "rating": "2", "comment": "weak hook, boring and I may drop"}]},
                    metadata={"project_id": "feedback-loop-p", "workspace_path": str(workspace.relative_to(storage.root))},
                ),
            )

            result = process_publish_feedback_loop(
                storage,
                feedback_paths=[str(feedback_path.relative_to(storage.root))],
                project_id="feedback-loop-p",
                workspace_path=str(workspace.relative_to(storage.root)),
                require_human_gate=True,
            )
            updated = storage.read_json(storage.root / knowledge["path"])

            self.assertEqual(result["status"], "waiting_human")
            self.assertTrue(result["sentiment_report_path"])
            self.assertTrue(result["backflow_plan_path"])
            self.assertEqual(result["mkaos_weight_update_count"], 1)
            self.assertLess(updated["content"]["weight"], 1.0)

    def test_reader_simulation_scores_personas_and_rejects_source_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = _workspace(storage, "reader-sim-p")
            draft_path = _draft(storage, workspace, project_id="reader-sim-p")

            result = create_reader_simulation_report(
                storage,
                draft_path=str(draft_path.relative_to(storage.root)),
                project_id="reader-sim-p",
                workspace_path=str(workspace.relative_to(storage.root)),
                platform="fanqie",
            )
            asset = result["asset"]

            self.assertEqual(asset["type"], "reader_simulation_report")
            self.assertEqual(len(asset["content"]["personas"]), 6)
            self.assertIn("predicted_score", asset["content"]["aggregate"])
            self.assertFalse(asset["content"]["source_policy"]["source_chunk_raw_text_allowed"])

            source_chunk_path = storage.write_asset(
                "raw",
                SourceChunk(
                    title="source chunk",
                    content={
                        "source_document_id": "source1",
                        "chunk_index": 0,
                        "clean_text": "cleaned reference",
                        "raw_text": "forbidden raw source text",
                        "content_hash": "hash1",
                    },
                    metadata={"project_id": "reader-sim-p"},
                ),
            )
            with self.assertRaisesRegex(ValueError, "must not use source_document or source_chunk"):
                create_reader_simulation_report(storage, draft_path=str(source_chunk_path.relative_to(storage.root)), project_id="reader-sim-p")

    def test_real_feedback_backflow_writes_learning_assets_and_mkaos_weight(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = _workspace(storage, "real-feedback-p")
            knowledge = create_knowledge_card(
                storage,
                {
                    "concept_name": "Retention hook",
                    "core_explanation": "real feedback should adjust hook strength",
                    "project_id": "real-feedback-p",
                    "weight": 1.0,
                },
            )
            record_usage_event(
                storage,
                {
                    "knowledge_id": knowledge["asset"]["id"],
                    "knowledge_pack_id": "real-feedback-pack",
                    "project_id": "real-feedback-p",
                    "flow": "publish",
                    "agent_name": "PublishingAgent",
                    "used_as": "release_strategy",
                },
            )

            result = process_real_feedback_backflow(
                storage,
                metrics={
                    "completion_rate": 0.42,
                    "follow_read_rate": 0.31,
                    "comments": ["节奏太拖", "看不懂设定", "想看更强反转"],
                    "favorites": 8,
                    "bookshelf_adds": 11,
                    "reward_count": 1,
                    "chapter_drop_points": [{"chapter": 3, "drop_rate": 0.36, "reason": "铺垫过长"}],
                    "negative_keywords": ["拖", "看不懂"],
                    "character_mentions": {"主角": 5},
                },
                project_id="real-feedback-p",
                workspace_path=str(workspace.relative_to(storage.root)),
                platform="qidian",
            )
            updated = storage.read_json(storage.root / knowledge["path"])
            learning_types = {storage.read_json(storage.root / path)["type"] for path in result["learning_asset_paths"]}
            platform_backflow = storage.read_json(storage.root / result["platform_backflow_path"])
            report = storage.read_json(storage.root / result["path"])

            self.assertEqual(result["mkaos_weight_update_count"], 1)
            self.assertLess(updated["content"]["weight"], 1.0)
            self.assertEqual(platform_backflow["type"], "platform_feedback_backflow")
            self.assertIn("review_rule_pack", learning_types)
            self.assertIn("topic_seed", learning_types)
            self.assertIn("writing_template", learning_types)
            self.assertEqual(report["type"], "reader_feedback_backflow_report")
            self.assertEqual(report["content"]["target_updates"]["platform_strategy"]["status"], "updated")


def _workspace(storage: LocalStorage, project_id: str) -> Path:
    return storage.write_asset(
        "workspaces",
        ProjectWorkspaceState(
            title=f"Workspace {project_id}",
            content={
                "project_id": project_id,
                "memory": {},
                "chapter_states": [],
                "continuity_threads": {},
                "open_issues": [],
                "project_config": {"target_platform": "local_serial", "publish_min_hook_score": 0.7},
            },
        ),
    )


def _draft(storage: LocalStorage, workspace_path: Path, *, project_id: str) -> Path:
    return storage.write_asset(
        "drafts",
        DraftChapter(
            title="Chapter 1",
            content={
                "chapter": 1,
                "text": "原创章节文本，主角在门口看见新税帖，决定连夜去县衙查账，结尾留下明确行动钩子。",
                "copyright_boundary": "project-owned unit fixture",
            },
            metadata={"project_id": project_id, "workspace_path": str(workspace_path.relative_to(storage.root))},
            references=[str(workspace_path.relative_to(storage.root))],
        ),
    )


def _publish_knowledge(storage: LocalStorage, project_id: str) -> None:
    card = create_knowledge_card(
        storage,
        {
            "concept_name": "Publish governance",
            "core_explanation": "production publish must carry a MKAOS pack",
            "project_id": project_id,
            "weight": 1.0,
        },
    )
    create_usage_binding(storage, card["asset"]["id"], {"flow": "publish", "usage_type": "required", "input_role": "publish_gate", "priority": 10})


def _production_envelope(project_id: str, asset_type: str, *, trace_id: str) -> dict:
    return {
        "project_id": project_id,
        "task_type": "publish",
        "asset_type": asset_type,
        "actor_type": "unit_test",
        "source": "tests.unit.test_publish_feedback_loop",
        "trace_id": trace_id,
        "source_policy": {"raw_source_text_allowed": False, "generation_rag_allowed": True},
        "environment": "production",
    }


if __name__ == "__main__":
    unittest.main()
