from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.context_builder import create_context_build_plan, create_context_bundle
from novel_forge.modules.workspace.service import init_workspace
from novel_forge.schemas import DraftChapter, KnowledgeCard, MaterialCard, Outline, ReviewReport, SourceDocument
from novel_forge.storage.local import LocalStorage


class ContextBuilderStageProfileTests(unittest.TestCase):
    def test_direct_context_profile_aliases_resolve_to_stage_contracts(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace_ref, project_id = _workspace(storage, "Alias Context Project")
            outline_path = _outline(storage, project_id, workspace_ref)

            plan = create_context_build_plan(storage, outline_path, query="chapter plan alias", context_profile="chapter_plan")
            content = plan["asset"]["content"]

            self.assertEqual(content["context_profile_policy"]["profile"], "chapter_outline")
            self.assertEqual(content["context_profile_policy"]["stage"], "chapter_plan")
            self.assertIn("stage_profile_enforced", content["selection_policy"])

    def test_topic_profile_rejects_draft_and_source_assets_even_when_manually_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace_ref, project_id = _workspace(storage, "Topic Context Project")
            outline_path = _outline(storage, project_id, workspace_ref)
            knowledge_path = storage.write_asset_auto(
                KnowledgeCard(
                    title="Abstract premise lever",
                    content={"principle": "topic seeds should express pressure, promise, and fresh angle"},
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                )
            )
            material_path = storage.write_asset_auto(
                MaterialCard(
                    title="Reusable market material",
                    content={"pattern": "authority pressure forces an early irreversible choice"},
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                )
            )
            draft_path = storage.write_asset_auto(
                DraftChapter(
                    title="Existing draft should not shape topic seed",
                    content={"chapter": 1, "text": "原创测试草稿，不应进入 topic 阶段上下文。"},
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                )
            )
            source_path = storage.write_asset_auto(
                SourceDocument(
                    title="External source",
                    content={"raw_text": "RAW_SOURCE_SENTINEL"},
                    metadata={"project_id": project_id, "workspace_path": workspace_ref, "rights_status": "unknown"},
                )
            )

            plan = create_context_build_plan(storage, outline_path, query="topic pressure promise", context_profile="topic")
            _replace_candidates(storage, plan["path"], [knowledge_path, material_path, draft_path, source_path])

            bundle = create_context_bundle(
                storage,
                plan["path"],
                selected_asset_paths=[_rel(storage, knowledge_path), _rel(storage, material_path), _rel(storage, draft_path), _rel(storage, source_path)],
                priority_asset_paths=[_rel(storage, draft_path), _rel(storage, source_path)],
                final_confirmed=True,
            )
            content = bundle["asset"]["content"]
            selected_types = {item["type"] for item in content["selected_assets"]}
            selected_paths = {item["path"] for item in content["selected_assets"]}
            rejected_by_path = {item["path"]: item for item in content["policy_rejections"]}

            self.assertEqual(content["stage_context_contract"]["profile"], "topic")
            self.assertEqual(content["stage_context_contract"]["stage"], "topic")
            self.assertFalse(content["source_isolation"]["raw_source_text_allowed"])
            self.assertIn("knowledge_card", selected_types)
            self.assertIn("material_card", selected_types)
            self.assertNotIn(_rel(storage, draft_path), selected_paths)
            self.assertNotIn(_rel(storage, source_path), selected_paths)
            self.assertIn(_rel(storage, draft_path), rejected_by_path)
            self.assertIn("stage_profile_rejected", rejected_by_path[_rel(storage, draft_path)]["signals"])
            self.assertIn(_rel(storage, source_path), rejected_by_path)
            self.assertIn("blocked_asset_type", rejected_by_path[_rel(storage, source_path)]["signals"])
            self.assertEqual(content["approval_requests"][0]["scope"], "context")
            self.assertTrue(content["approval_requests"][0]["approval_request_path"])
            self.assertTrue(content["approval_requests"][0]["blocking"])
            self.assertIn(_rel(storage, source_path), content["approval_requests"][0]["rejected_paths"])
            self.assertNotIn("RAW_SOURCE_SENTINEL", content["actual_context"])

    def test_revision_profile_allows_review_and_draft_lineage_but_still_rejects_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace_ref, project_id = _workspace(storage, "Revision Context Project")
            outline_path = _outline(storage, project_id, workspace_ref)
            draft_path = storage.write_asset_auto(
                DraftChapter(
                    title="Chapter draft",
                    content={"chapter": 1, "text": "原创测试草稿，需要根据审稿问题修订。"},
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                )
            )
            review_path = storage.write_asset_auto(
                ReviewReport(
                    title="Chapter review",
                    content={"issues": [{"type": "opening", "severity": "medium", "fix": "increase pressure"}]},
                    issues=[{"type": "opening", "severity": "medium", "fix": "increase pressure"}],
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                )
            )
            source_path = storage.write_asset_auto(
                SourceDocument(
                    title="External source",
                    content={"raw_text": "REVISION_RAW_SOURCE_SENTINEL"},
                    metadata={"project_id": project_id, "workspace_path": workspace_ref, "rights_status": "unknown"},
                )
            )

            plan = create_context_build_plan(storage, outline_path, query="revision review issue draft", context_profile="revision")
            _replace_candidates(storage, plan["path"], [draft_path, review_path, source_path])

            bundle = create_context_bundle(
                storage,
                plan["path"],
                selected_asset_paths=[_rel(storage, draft_path), _rel(storage, review_path), _rel(storage, source_path)],
                final_confirmed=True,
            )
            content = bundle["asset"]["content"]
            selected_types = {item["type"] for item in content["selected_assets"]}
            rejected_by_path = {item["path"]: item for item in content["policy_rejections"]}

            self.assertEqual(content["stage_context_contract"]["profile"], "revision")
            self.assertEqual(content["stage_context_contract"]["stage"], "revision")
            self.assertIn("draft_chapter", selected_types)
            self.assertIn("review_report", selected_types)
            self.assertIn(_rel(storage, source_path), rejected_by_path)
            self.assertIn("blocked_asset_type", rejected_by_path[_rel(storage, source_path)]["signals"])
            self.assertTrue(content["approval_requests"][0]["approval_request_path"])
            self.assertNotIn("REVISION_RAW_SOURCE_SENTINEL", content["actual_context"])

    def test_production_context_rejects_source_eligibility_failed_materials(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace_ref, project_id = _workspace(storage, "Eligibility Context Project")
            outline_path = _outline(storage, project_id, workspace_ref)
            passed_path = storage.write_asset_auto(
                MaterialCard(
                    title="Governed material",
                    content={
                        "usable_patterns": ["approved abstract mechanism"],
                        "source_chunk_ids": ["chunk-ok"],
                        "source_eligibility": {
                            "status": "passed",
                            "generation_context_allowed": True,
                            "evidence_only": False,
                            "source_policy_refs": ["policy-ok"],
                            "source_risk_report_refs": ["risk-ok"],
                        },
                    },
                    metadata={"project_id": project_id, "workspace_path": workspace_ref, "use_in_generation_rag": True},
                )
            )
            blocked_path = storage.write_asset_auto(
                MaterialCard(
                    title="Ungoverned material",
                    content={
                        "usable_patterns": ["unreviewed abstract mechanism"],
                        "source_chunk_ids": ["chunk-blocked"],
                        "source_eligibility": {"status": "needs_review", "generation_context_allowed": False, "evidence_only": True},
                    },
                    metadata={"project_id": project_id, "workspace_path": workspace_ref, "use_in_generation_rag": True},
                )
            )

            plan = create_context_build_plan(storage, outline_path, query="outline material", context_profile="outline", environment="production")
            _replace_candidates(storage, plan["path"], [passed_path, blocked_path])
            bundle = create_context_bundle(
                storage,
                plan["path"],
                selected_asset_paths=[_rel(storage, passed_path), _rel(storage, blocked_path)],
                final_confirmed=True,
            )
            content = bundle["asset"]["content"]
            selected_paths = {item["path"] for item in content["selected_assets"]}
            rejected_by_path = {item["path"]: item for item in content["policy_rejections"]}

            self.assertIn(_rel(storage, passed_path), selected_paths)
            self.assertNotIn(_rel(storage, blocked_path), selected_paths)
            selected = next(item for item in content["selected_assets"] if item["path"] == _rel(storage, passed_path))
            self.assertEqual(selected["source_eligibility"]["status"], "passed")
            self.assertEqual(content["compressed_context"]["material_cards"][0]["source_eligibility"]["status"], "passed")
            self.assertIn(_rel(storage, blocked_path), rejected_by_path)
            self.assertIn("source_eligibility_rejected", rejected_by_path[_rel(storage, blocked_path)]["signals"])

    def test_context_bundle_records_knowledge_and_material_usage_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace_ref, project_id = _workspace(storage, "Usage Feedback Context Project")
            outline_path = _outline(storage, project_id, workspace_ref)
            knowledge_path = storage.write_asset_auto(
                KnowledgeCard(
                    title="Approved abstract principle",
                    content={"principles": ["pressure must force a visible irreversible choice"]},
                    metadata={"project_id": project_id, "workspace_path": workspace_ref, "use_in_generation_rag": True},
                )
            )
            material_path = storage.write_asset_auto(
                MaterialCard(
                    title="Approved governed material",
                    content={
                        "usable_patterns": ["authority pressure creates a public cost"],
                        "do_not_copy": ["names", "sentences"],
                        "source_eligibility": {
                            "status": "passed",
                            "generation_context_allowed": True,
                            "evidence_only": False,
                            "source_policy_refs": ["policy-ok"],
                            "source_risk_report_refs": ["risk-ok"],
                        },
                    },
                    metadata={"project_id": project_id, "workspace_path": workspace_ref, "use_in_generation_rag": True},
                )
            )

            plan = create_context_build_plan(storage, outline_path, query="outline pressure", context_profile="outline", environment="production")
            _replace_candidates(storage, plan["path"], [knowledge_path, material_path])
            bundle = create_context_bundle(
                storage,
                plan["path"],
                selected_asset_paths=[_rel(storage, knowledge_path), _rel(storage, material_path)],
                final_confirmed=True,
            )
            events = bundle["asset"]["content"]["usage_feedback_events"]
            event_types = {item["type"] for item in events}
            event_paths = [item["path"] for item in events]

            self.assertEqual(bundle["asset"]["content"]["usage_feedback_event_count"], 2)
            self.assertIn("knowledge_usage_event", event_types)
            self.assertIn("material_usage_event", event_types)
            for event_path in event_paths:
                self.assertTrue(event_path)
                event = storage.read_json(storage.root / event_path)
                self.assertEqual(event["metadata"]["project_id"], project_id)
                self.assertEqual(event["content"]["target_artifact_id"], bundle["asset"]["content"]["target_asset_id"])
                self.assertEqual(event["content"]["used_as"], "context_bundle_selected_asset")
            material_event = storage.read_json(storage.root / next(item["path"] for item in events if item["type"] == "material_usage_event"))
            self.assertEqual(material_event["content"]["source_eligibility"]["status"], "passed")


def _workspace(storage: LocalStorage, title: str) -> tuple[str, str]:
    workspace_path = init_workspace(storage, title)
    workspace = storage.read_asset(workspace_path)
    return str(workspace_path.relative_to(storage.root)), str(workspace.content["project_id"])


def _outline(storage: LocalStorage, project_id: str, workspace_ref: str) -> Path:
    return storage.write_asset_auto(
        Outline(
            title="Stage profile target",
            content={"premise": "a durable original project target"},
            metadata={"project_id": project_id, "workspace_path": workspace_ref},
        )
    )


def _replace_candidates(storage: LocalStorage, plan_path: str, paths: list[Path]) -> None:
    plan_file = storage.root / plan_path
    data = storage.read_json(plan_file)
    data["content"]["candidate_assets"] = [_candidate(storage, path) for path in paths]
    storage.write_json(plan_file, data)


def _candidate(storage: LocalStorage, path: Path) -> dict[str, object]:
    asset = storage.read_asset(path)
    return {
        "asset_id": asset.id,
        "path": _rel(storage, path),
        "type": asset.type,
        "title": asset.title,
        "categories": ["knowledge_cards" if asset.type == "knowledge_card" else "material_cards" if asset.type == "material_card" else "previous_summaries"],
        "score": 0.95,
        "ranker": "unit-test",
        "project_id": str(asset.metadata.get("project_id", "")),
        "workspace_path": str(asset.metadata.get("workspace_path", "")),
        "token_estimate": 32,
        "summary": f"{asset.title}: schema-backed summary only",
        "copyright": {"eligible": True, "risk_level": "low", "signals": []},
        "selected_by_default": True,
    }


def _rel(storage: LocalStorage, path: Path) -> str:
    return str(path.relative_to(storage.root))


if __name__ == "__main__":
    unittest.main()
