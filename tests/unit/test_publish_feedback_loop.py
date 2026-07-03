from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.audit import create_publish_gate_report, create_release_package
from novel_forge.modules.feedback import process_publish_feedback_loop
from novel_forge.modules.mkaos import create_knowledge_card, record_usage_event
from novel_forge.schemas import DraftChapter, ProjectWorkspaceState, ReaderFeedback
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


if __name__ == "__main__":
    unittest.main()
