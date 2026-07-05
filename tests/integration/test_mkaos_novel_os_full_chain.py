from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.context_builder import build_flow_context_bundle
from novel_forge.modules.editor_chief import build_editor_chief_snapshot
from novel_forge.modules.mkaos import create_usage_binding
from novel_forge.modules.mkaos_lineage import apply_lineage_weight_governance, attribute_feedback_to_knowledge, build_lineage_index, query_lineage_path
from novel_forge.modules.mkaos_model_extraction import approve_candidate, create_model_extraction_job, run_model_extraction_job
from novel_forge.modules.mkaos_production_gate import list_gate_reports
from novel_forge.schemas import BaseAsset, ChapterPlan
from novel_forge.storage.local import LocalStorage


class MkaosNovelOsFullChainTests(unittest.TestCase):
    def test_mkaos_full_chain_remains_source_isolated_and_governed(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "mkaos-full"
            source = BaseAsset(id="source-1", type="source_document", title="Book", source="fixture", content={"source_kind": "professional_book"}, metadata={"project_id": project_id})
            storage.write_asset("raw", source)

            job = create_model_extraction_job(storage, {"project_id": project_id, "source_type": "professional_book", "input_summary": "制度和资源约束会推动角色选择。", "source_refs": [source.id]})
            run = run_model_extraction_job(storage, job["id"], {"provider_mode": "disabled"})
            card = approve_candidate(storage, run["candidates"][0]["asset"]["id"], {"note": "safe fixture"})["knowledge_card"]["asset"]
            create_usage_binding(storage, card["id"], {"flow": "prose", "usage_type": "required", "input_role": "constraint", "priority": 20})

            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(title="Plan", content={"chapter": 1, "objective": "use MKAOS", "beats": ["choice", "cost"], "hook": "old rule returns"}, metadata={"project_id": project_id}),
            )
            context = build_flow_context_bundle(storage, plan_path, flow="prose", project_id=project_id, chapter_id="1", current_goal="draft with abstract mechanism")
            draft = BaseAsset(
                id="draft-1",
                type="draft_chapter",
                title="Draft",
                source=context["asset"]["id"],
                content={"context_bundle_id": context["asset"]["id"], "text": "角色面对旧规付出代价，形成下一章钩子。"},
                metadata={"project_id": project_id},
                references=[context["asset"]["id"]],
            )
            storage.write_asset("drafts", draft)

            index = build_lineage_index(storage, project_id=project_id)
            path = query_lineage_path(storage, {"project_id": project_id, "source_asset_id": source.id, "target_asset_id": draft.id, "persist": False})
            attribution = attribute_feedback_to_knowledge(storage, {"project_id": project_id, "feedback_id": "feedback-1", "generated_asset_id": draft.id, "feedback_text": "很好看，想追"})
            governance = apply_lineage_weight_governance(storage, {"project_id": project_id, "knowledge_id": card["id"], "dry_run": True})
            snapshot = build_editor_chief_snapshot(storage, project_id=project_id)

            text = str(context["asset"]["content"])
            self.assertIn(card["id"], text)
            self.assertNotIn("制度和资源约束会推动角色选择", text)
            self.assertFalse(context["asset"]["content"]["source_isolation"]["source_chunk_raw_text_allowed"])
            self.assertTrue(list_gate_reports(storage, project_id=project_id))
            self.assertGreater(index["edge_count"], 0)
            self.assertGreater(path["path_count"], 0)
            self.assertIn(card["id"], attribution["knowledge_ids_used"])
            self.assertTrue(governance["recommendations"])
            self.assertIn("mkaos_gate", snapshot["governance_loop"])


if __name__ == "__main__":
    unittest.main()
