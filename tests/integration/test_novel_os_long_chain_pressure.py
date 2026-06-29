from pathlib import Path
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.operations import create_long_chain_acceptance_report
from novel_forge.modules.production_chain import create_draft_version
from novel_forge.modules.runtime_ledger import record_model_call_log
from novel_forge.modules.workspace import service as workspace_service
from novel_forge.schemas import ChapterContinuityReport, ChapterProductionRun, ContextBundle, DraftChapter, FeedbackBackflowPlan, ReviewReport
from novel_forge.storage.local import LocalStorage


@unittest.skipUnless(os.environ.get("NOVEL_FORGE_RUN_LONG_CHAIN_PRESSURE") == "1", "set NOVEL_FORGE_RUN_LONG_CHAIN_PRESSURE=1 to run 12/50 chapter OS pressure acceptance")
class NovelOSLongChainPressureTests(unittest.TestCase):
    def test_pressure_acceptance_report_scales_beyond_smoke(self):
        chapter_count = max(12, int(os.environ.get("NOVEL_FORGE_LONG_CHAIN_CHAPTERS", "12") or 12))
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = workspace_service.init_workspace(storage, "Novel OS Pressure", "Clockverse", chapter_count)
            workspace_ref = str(workspace.relative_to(storage.root))
            project_id = str(storage.read_asset(workspace).content["project_id"])
            metadata = {"project_id": project_id, "workspace_path": workspace_ref}

            for chapter in range(1, chapter_count + 1):
                storage.write_asset(
                    "runs",
                    ChapterProductionRun(
                        title=f"Chapter {chapter} production run",
                        tags=["pressure", "succeeded"],
                        content={"run_id": f"pressure-run-{chapter}", "status": "succeeded", "current_step": "final_draft", "chapter": chapter, "steps": {"final_draft": {"status": "completed"}}, "outputs": {}},
                        metadata={**metadata, "chapter": chapter},
                    ),
                )
                storage.write_asset(
                    "contexts",
                    ContextBundle(
                        title=f"Chapter {chapter} context",
                        tags=["pressure", "context", "kg-backed"],
                        content={"chapter": chapter, "actual_context": f"chapter {chapter} continuity and KG memory", "kg_context": {"items": [{"name": "Memory Key", "chapter": chapter, "confidence": 0.9}]}},
                        metadata=metadata,
                    ),
                )
                draft_path = storage.write_asset(
                    "drafts",
                    DraftChapter(
                        title=f"Chapter {chapter} draft",
                        tags=["pressure", "draft"],
                        content={"chapter": chapter, "text": f"第{chapter}章，林乔继续支付代价并推进钟楼伏笔。", "copyright_boundary": "original deterministic pressure fixture"},
                        metadata=metadata,
                    ),
                )
                create_draft_version(storage, draft_path)
                storage.write_asset(
                    "reviews",
                    ReviewReport(
                        title=f"Chapter {chapter} review",
                        source=storage.read_asset(draft_path).id,
                        score=82,
                        strengths=["continuity stable", "hook present"],
                        weaknesses=[],
                        issues=[],
                        risk_level="low",
                        revision_suggestions=[],
                        next_action="accept",
                        content={"chapter": chapter, "summary": "pressure review passed"},
                        metadata=metadata,
                    ),
                )
                storage.write_asset(
                    "continuity",
                    ChapterContinuityReport(
                        title=f"Chapter {chapter} continuity",
                        source=storage.read_asset(draft_path).id,
                        tags=["pressure", "continuity"],
                        content={"chapter": chapter, "blocking_violations": [], "violations": [], "dimensions": {"foreshadowing_lifecycle": {"open_count": 0}}, "recommendation": "pass"},
                        metadata=metadata,
                    ),
                )
                record_model_call_log(
                    storage,
                    provider="mock",
                    model="mock-pressure",
                    operation="pressure_chapter",
                    usage={"input_tokens": 160, "output_tokens": 320, "total_tokens": 480, "usage_source": "pressure"},
                    cost={"amount": 0.01, "currency": "USD", "source": "pressure"},
                    project_id=project_id,
                    workspace_path=workspace_ref,
                    source_id=storage.read_asset(draft_path).id,
                    trace={"trace_id": f"pressure-trace-{chapter}", "span_id": f"pressure-span-{chapter}"},
                )

            storage.write_asset(
                "feedback",
                FeedbackBackflowPlan(
                    title="Pressure feedback backflow",
                    tags=["pressure", "feedback-backflow"],
                    content={"status": "waiting_human", "clusters": [{"kind": "payoff_delay", "chapter": chapter_count // 2}], "proposals": [{"type": "plan_adjustment_proposal", "chapter": chapter_count}]},
                    metadata=metadata,
                ),
            )

            report = create_long_chain_acceptance_report(storage, project_id=project_id, chapter_count=chapter_count)
            content = storage.read_asset(report["path"]).content

            self.assertEqual(content["recommendation"], "pass")
            self.assertGreaterEqual(content["scale_metrics"]["observed_chapter_count"], chapter_count)
            self.assertEqual(content["scale_metrics"]["continuity_conflict_count"], 0)
            self.assertEqual(content["scale_metrics"]["feedback_backflow_count"], 1)
            self.assertGreaterEqual(content["scale_metrics"]["model_call_count"], chapter_count)


if __name__ == "__main__":
    unittest.main()
