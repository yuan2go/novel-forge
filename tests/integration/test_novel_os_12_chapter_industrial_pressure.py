from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.publishing import create_publish_gate_report, create_release_package
from novel_forge.modules.context_builder import build_flow_context_bundle
from novel_forge.modules.longform_recap import run_longform_recap
from novel_forge.modules.longform_stability import create_arc_plan, create_canon_database, create_longform_artifacts_for_draft
from novel_forge.modules.loop_kernel import run_loop
from novel_forge.modules.mkaos import create_knowledge_card, create_usage_binding, import_source_document
from novel_forge.modules.review_issue import create_review_issue, list_review_issues
from novel_forge.modules.workspace import service as workspace_service
from novel_forge.schemas import DraftChapter
from novel_forge.storage.local import LocalStorage


RAW_SENTINEL = "DO_NOT_LEAK_SOURCE_CHUNK_RAW_TEXT_SENTINEL"


class NovelOS12ChapterIndustrialPressureTests(unittest.TestCase):
    def test_twelve_chapter_slice_triggers_context_mkaos_recap_loop_blocking_gate_and_release_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = workspace_service.init_workspace(storage, "Novel OS 12 Chapter Pressure", "Night Archive", 12)
            workspace_ref = str(workspace.relative_to(storage.root))
            project_id = str(storage.read_asset(workspace).content["project_id"])
            _seed_longform_controls(storage, project_id)
            _seed_mkaos_source_and_knowledge(storage, project_id, workspace_ref)

            draft_paths = []
            for chapter in range(1, 13):
                draft_path = storage.write_asset(
                    "drafts",
                    DraftChapter(
                        title=f"Pressure Chapter {chapter}",
                        content={
                            "chapter": chapter,
                            "text": f"第{chapter}章。阿照继续追查旧城隐税，夜档司账册的竹筹线索推进到第{chapter}个证据点，章尾留下新的行动钩子。",
                            "copyright_boundary": "project-owned deterministic 12 chapter pressure fixture",
                        },
                        metadata={"project_id": project_id, "workspace_path": workspace_ref},
                    ),
                )
                create_longform_artifacts_for_draft(storage, draft_path)
                draft_paths.append(draft_path)

            context = build_flow_context_bundle(
                storage,
                draft_paths[-1],
                flow="prose",
                project_id=project_id,
                workspace_path=workspace_ref,
                chapter_id="12",
                current_goal="generate chapter 12 under Novel OS industrial pressure",
                source_policy={"source_chunk_raw_text_allowed": True, "runtime_assets_in_generation_rag_allowed": True},
            )
            context_payload = json.dumps(context["asset"], ensure_ascii=False)
            self.assertTrue(context["asset"]["content"]["mkaos_pack_id"])
            self.assertFalse(context["asset"]["content"]["source_policy"]["source_chunk_raw_text_allowed"])
            self.assertNotIn(RAW_SENTINEL, context_payload)
            self.assertNotIn('"raw_text"', context_payload)

            latest = storage.read_asset(draft_paths[-1])
            create_review_issue(
                storage,
                {
                    "project_id": project_id,
                    "target_asset_id": latest.id,
                    "target_asset_type": "draft_chapter",
                    "target_asset_path": str(draft_paths[-1].relative_to(storage.root)),
                    "issue_type": "canon_conflict",
                    "severity": "critical",
                    "message": "chapter 12 has a blocking canon conflict for pressure proof",
                },
            )
            blocked_loop = run_loop(
                storage,
                {
                    "loop_type": "chapter_review",
                    "target_path": str(draft_paths[-1].relative_to(storage.root)),
                    "project_id": project_id,
                    "workspace_path": workspace_ref,
                    "budget": {"max_steps": 5, "max_tokens": 2000, "max_cost": 1.0, "max_duration_seconds": 60},
                },
            )
            self.assertEqual(blocked_loop["stop_condition"], "blocking_issue")

            recap = run_longform_recap(
                storage,
                {
                    "project_id": project_id,
                    "workspace_path": workspace_ref,
                    "chapter_count": 12,
                    "bypass_reason": "12 chapter industrial pressure test",
                },
            )
            recap_payload = json.dumps(recap["asset"], ensure_ascii=False)
            self.assertEqual(recap["asset"]["content"]["chapter_range"]["end"], 12)
            self.assertEqual(recap["loop"]["status"], "succeeded")
            self.assertTrue(recap["writeback"]["revision_task_path"])
            self.assertNotIn(RAW_SENTINEL, recap_payload)
            self.assertNotIn('"raw_text"', recap_payload)

            package_gate_path = create_publish_gate_report(
                storage,
                draft_paths[-2],
                workspace_path=workspace_ref,
                human_override=True,
            )
            package_path = create_release_package(
                storage,
                draft_paths[-2],
                workspace_path=workspace_ref,
                publish_gate_path=package_gate_path,
                human_override=True,
            )
            package = storage.read_asset(package_path)
            package_payload = json.dumps(package.to_dict(), ensure_ascii=False)
            self.assertEqual(package.type, "release_package")
            self.assertIn("source_isolation", package.content)
            self.assertNotIn(RAW_SENTINEL, package_payload)
            self.assertNotIn('"raw_text"', package_payload)

            blocked_gate_path = create_publish_gate_report(storage, draft_paths[-1], workspace_path=workspace_ref)
            blocked_gate = storage.read_asset(blocked_gate_path)
            self.assertEqual(blocked_gate.content["decision"], "blocked")
            with self.assertRaisesRegex(ValueError, "release_package blocked by"):
                create_release_package(storage, draft_paths[-1], workspace_path=workspace_ref, publish_gate_path=blocked_gate_path)

            issues = list_review_issues(storage, project_id=project_id, limit=100)
            self.assertTrue(any(issue["content"]["source_system"] == "longform_recap.agent" for issue in issues))
            self.assertGreaterEqual(len(storage.list_json("drafts")), 12)


def _seed_longform_controls(storage: LocalStorage, project_id: str) -> None:
    create_canon_database(
        storage,
        entities=[
            {"entity_id": "azhao", "entity_type": "character", "canonical_name": "阿照", "aliases": [], "forbidden_aliases": ["沈砚"], "role": "protagonist", "status": "active"},
            {"entity_id": "night_archive", "entity_type": "organization", "canonical_name": "夜档司", "aliases": [], "forbidden_aliases": [], "role": "core_org", "status": "active"},
        ],
        project_id=project_id,
    )
    create_arc_plan(
        storage,
        arc_id="arc-hidden-tax",
        title="旧城隐税卷",
        chapter_range="1-20",
        arc_question="谁在复活旧城隐税机制？",
        protagonist_goal="查清隐税机制并保护夜档司账册",
        villain_goal="逼夜档司承接旧债",
        required_payoffs=["解释竹筹来源", "确认旧税契责任人"],
        forbidden_expansion=["不要新开无关宗门线"],
        project_id=project_id,
    )


def _seed_mkaos_source_and_knowledge(storage: LocalStorage, project_id: str, workspace_ref: str) -> None:
    source = import_source_document(
        storage,
        {
            "title": "Pressure source",
            "text": f"{RAW_SENTINEL} 这段来源只能作为证据层切块，不得进入生成上下文。",
            "project_id": project_id,
            "workspace_path": workspace_ref,
            "rights": {"authorization": "test_fixture", "allow_downstream_generation": False},
        },
    )
    chunk_ids = [str(chunk.get("id")) for chunk in source["chunks"] if chunk.get("id")]
    knowledge = create_knowledge_card(
        storage,
        {
            "project_id": project_id,
            "workspace_path": workspace_ref,
            "concept_name": "隐税压力转剧情",
            "discipline": "叙事工程",
            "knowledge_type": "longform_control",
            "core_explanation": "把抽象制度压力转成角色必须立刻行动的证据、阻力和代价。",
            "source_chunk_ids": chunk_ids,
            "confidence": 0.9,
            "quality_score": 0.92,
            "weight": 1.4,
            "risk_level": "low",
        },
    )
    for flow in ["prose", "review", "recap", "publish"]:
        create_usage_binding(
            storage,
            knowledge["asset"]["id"],
            {"flow": flow, "usage_type": "required", "input_role": "pressure_rule", "priority": 10},
        )


if __name__ == "__main__":
    unittest.main()
