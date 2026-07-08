from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.agent_runs import (
    ensure_agent_contract,
    list_agent_events,
    list_agent_runs,
    record_agent_checkpoint,
    start_agent_run,
    update_agent_run_status,
)
from novel_forge.modules.change_impact import create_change_impact_report
from novel_forge.modules.workflow_nodes import list_node_runs, record_node_run
from novel_forge.schemas import ChapterPlan, DecompositionReport, DraftChapter, Outline, SourceDocument
from novel_forge.storage.local import LocalStorage


class AgentWorkflowImpactTests(unittest.TestCase):
    def test_agent_run_event_checkpoint_write_growth_is_characterized(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            baseline = _count_assets_by_type(storage)
            run = start_agent_run(
                storage,
                agent_key="draft",
                operation="chapter-production-growth-fixture",
                status="running",
                evidence={"trace": {"trace_id": "trace-agent-growth", "span_id": "span-agent-growth"}},
            )
            after_start = _count_assets_by_type(storage)

            self.assertEqual(after_start.get("agent_run", 0) - baseline.get("agent_run", 0), 1)
            self.assertEqual(after_start.get("agent_event", 0) - baseline.get("agent_event", 0), 1)
            self.assertEqual(after_start.get("trace_span", 0) - baseline.get("trace_span", 0), 2)

            record_agent_checkpoint(
                storage,
                agent_run_path=run["path"],
                status="prompt_built",
                state={"step": "prompt_built", "status": "succeeded"},
            )
            after_checkpoint = _count_assets_by_type(storage)

            self.assertEqual(after_checkpoint.get("agent_checkpoint", 0) - after_start.get("agent_checkpoint", 0), 1)
            self.assertEqual(after_checkpoint.get("agent_event", 0) - after_start.get("agent_event", 0), 1)
            self.assertEqual(after_checkpoint.get("trace_span", 0) - after_start.get("trace_span", 0), 3)

            update_agent_run_status(
                storage,
                run["path"],
                status="succeeded",
                event_type="agent_run.succeeded",
                message="growth fixture complete",
            )
            after_success = _count_assets_by_type(storage)

            self.assertEqual(after_success.get("agent_run", 0) - baseline.get("agent_run", 0), 1)
            self.assertEqual(after_success.get("agent_checkpoint", 0) - baseline.get("agent_checkpoint", 0), 1)
            self.assertEqual(after_success.get("agent_event", 0) - baseline.get("agent_event", 0), 3)
            self.assertEqual(after_success.get("trace_span", 0) - baseline.get("trace_span", 0), 7)

    def test_node_run_agent_run_and_change_impact_are_persisted_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            source_path = storage.write_asset(
                "raw",
                SourceDocument(
                    title="Source",
                    source="fixture.txt",
                    content={"text": "fixture"},
                    metadata={
                        "rights": {
                            "authorization": "test_fixture",
                            "copyright_boundary": "test fixture",
                            "allow_downstream_generation": True,
                        }
                    },
                ),
            )
            output_path = storage.write_asset(
                "decompositions",
                DecompositionReport(
                    title="Decomposition",
                    source=storage.read_asset(source_path).id,
                    content={
                        "summary": "abstract fixture",
                        "commercial_patterns": [],
                        "narrative_patterns": [],
                        "character_mechanisms": [],
                        "conflict_patterns": [],
                        "emotion_curve": [],
                        "hook_patterns": [],
                    },
                    metadata={"copyright_boundary": "abstract structure only"},
                    references=[storage.read_asset(source_path).id],
                ),
            )

            node = record_node_run(
                storage,
                run_id="run-1",
                node_id="decompose",
                node_type="analysis",
                operation="decompose",
                status="succeeded",
                input_assets=[source_path],
                output_assets=[output_path],
            )
            self.assertEqual(storage.read_asset(node["path"]).type, "node_run")
            self.assertEqual(list_node_runs(storage, run_id="run-1")[0]["operation"], "decompose")

            contract = ensure_agent_contract(
                storage,
                skill="hot-novel-deconstruction",
                operation="hot_novel_deconstruction",
                input_types=["source_document"],
                output_types=["decomposition_report"],
            )
            run = start_agent_run(
                storage,
                skill="hot-novel-deconstruction",
                operation="hot_novel_deconstruction",
                input_assets=[source_path],
                status="waiting_human",
                contract_path=contract["path"],
            )
            self.assertEqual(storage.read_asset(run["path"]).type, "agent_run")
            self.assertEqual(list_agent_runs(storage)[0]["status"], "waiting_human")
            updated = update_agent_run_status(storage, run["path"], status="succeeded", output_assets=[output_path])
            self.assertEqual(updated["asset"]["content"]["status"], "succeeded")
            self.assertTrue(list_agent_events(storage, agent_run_path=run["path"]))

            outline_path = storage.write_asset(
                "outlines",
                Outline(title="Outline", content={"acts": [{"act": 1, "goal": "open"}]}),
            )
            outline = storage.read_asset(outline_path)
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="Plan",
                    source=outline.id,
                    content={"chapter": 1, "objective": "open", "beats": ["beat"], "hook": "hook"},
                    references=[outline.id, str(outline_path.relative_to(storage.root))],
                ),
            )
            plan = storage.read_asset(plan_path)
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Draft",
                    source=plan.id,
                    content={"chapter": 1, "text": "原创测试章节。", "copyright_boundary": "test fixture"},
                    references=[plan.id, str(plan_path.relative_to(storage.root))],
                ),
            )
            self.assertTrue(draft_path.exists())

            impact = create_change_impact_report(storage, outline_path)
            impacted_types = {item["type"] for item in impact["asset"]["content"]["impacted_assets"]}
            self.assertIn("chapter_plan", impacted_types)
            self.assertIn("draft_chapter", impacted_types)
            self.assertEqual(storage.read_asset(impact["path"]).type, "change_impact_report")


def _count_assets_by_type(storage: LocalStorage) -> dict[str, int]:
    counts: dict[str, int] = {}
    for category in storage.counts():
        for path in storage.list_json(category):
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if isinstance(data, dict):
                asset_type = str(data.get("type", ""))
                if asset_type:
                    counts[asset_type] = counts.get(asset_type, 0) + 1
    return counts


if __name__ == "__main__":
    unittest.main()
