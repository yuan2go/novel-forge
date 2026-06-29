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
from novel_forge.schemas import (
    ChapterContinuityReport,
    ChapterProductionRun,
    ContextBundle,
    DraftChapter,
    FeedbackBackflowPlan,
    ReviewReport,
    validate_common_fields,
)
from novel_forge.storage.local import LocalStorage


class NovelOSLongChainSmokeTests(unittest.TestCase):
    def setUp(self):
        self._previous_provider = os.environ.get("NOVEL_FORGE_MODEL_PROVIDER")
        os.environ["NOVEL_FORGE_MODEL_PROVIDER"] = "mock"

    def tearDown(self):
        if self._previous_provider is None:
            os.environ.pop("NOVEL_FORGE_MODEL_PROVIDER", None)
        else:
            os.environ["NOVEL_FORGE_MODEL_PROVIDER"] = self._previous_provider

    def test_three_chapter_scale_acceptance_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = workspace_service.init_workspace(storage, "Novel OS Scale Smoke", "Clockverse", 3)
            workspace_ref = str(workspace.relative_to(storage.root))
            workspace_asset = storage.read_asset(workspace)
            project_id = str(workspace_asset.content["project_id"])
            metadata = {"project_id": project_id, "workspace_path": workspace_ref}

            for chapter in range(1, 4):
                run = ChapterProductionRun(
                    title=f"Chapter {chapter} production run",
                    tags=["scale-smoke", "succeeded"],
                    content={
                        "run_id": f"scale-smoke-run-{chapter}",
                        "status": "succeeded",
                        "current_step": "final_draft",
                        "chapter": chapter,
                        "steps": {"final_draft": {"status": "completed"}},
                        "outputs": {},
                    },
                    metadata={**metadata, "chapter": chapter},
                )
                storage.write_asset("runs", run)
                bundle = ContextBundle(
                    title=f"Chapter {chapter} context bundle",
                    tags=["scale-smoke", "context"],
                    content={
                        "chapter": chapter,
                        "actual_context": f"chapter {chapter} continuity, open hook, power rule",
                        "kg_context": {"items": [{"name": "Memory Key", "chapter": chapter}]},
                    },
                    metadata=metadata,
                )
                storage.write_asset("contexts", bundle)
                draft = DraftChapter(
                    title=f"Chapter {chapter} draft",
                    tags=["scale-smoke", "draft"],
                    content={
                        "chapter": chapter,
                        "text": f"第{chapter}章，林乔选择支付记忆代价，钟楼线索继续推进。",
                        "copyright_boundary": "original deterministic scale fixture",
                    },
                    metadata=metadata,
                )
                draft_path = storage.write_asset("drafts", draft)
                create_draft_version(storage, draft_path)
                review = ReviewReport(
                    title=f"Chapter {chapter} review",
                    source=draft.id,
                    score=78 + chapter,
                    strengths=["hook present"],
                    weaknesses=[],
                    issues=[],
                    risk_level="low",
                    revision_suggestions=[],
                    next_action="accept",
                    content={"chapter": chapter, "summary": "scale smoke review passed"},
                    metadata=metadata,
                    references=[draft.id, str(draft_path.relative_to(storage.root))],
                )
                storage.write_asset("reviews", review)
                continuity = ChapterContinuityReport(
                    title=f"Chapter {chapter} continuity",
                    source=draft.id,
                    tags=["scale-smoke", "continuity"],
                    content={
                        "chapter": chapter,
                        "blocking_violations": [],
                        "violations": [],
                        "dimensions": {"foreshadowing_lifecycle": {"open_count": 0}},
                        "recommendation": "pass",
                    },
                    metadata=metadata,
                    references=[draft.id],
                )
                storage.write_asset("continuity", continuity)
                record_model_call_log(
                    storage,
                    provider="mock",
                    model="mock-model",
                    operation="scale_smoke_chapter",
                    usage={"input_tokens": 120, "output_tokens": 240, "total_tokens": 360, "usage_source": "scale_smoke"},
                    cost={"amount": 0.03 * chapter, "currency": "USD", "source": "scale_smoke"},
                    project_id=project_id,
                    workspace_path=workspace_ref,
                    source_id=draft.id,
                    trace={"trace_id": f"scale-smoke-trace-{chapter}", "span_id": f"model-call-{chapter}"},
                )

            storage.write_asset(
                "feedback",
                FeedbackBackflowPlan(
                    title="Scale smoke feedback backflow",
                    tags=["scale-smoke", "feedback-backflow"],
                    content={
                        "status": "waiting_human",
                        "clusters": [{"kind": "weak_hook", "chapter": 2}],
                        "proposals": [{"type": "plan_adjustment_proposal", "chapter": 3}],
                    },
                    metadata=metadata,
                ),
            )

            report = create_long_chain_acceptance_report(storage, project_id=project_id, chapter_count=3)
            report_asset = storage.read_asset(report["path"])
            self.assertEqual(report_asset.type, "long_chain_acceptance_report")
            self.assertEqual(validate_common_fields(report_asset.to_dict()), [])
            self.assertEqual(report_asset.content["acceptance_mode"], "long_chain")
            self.assertEqual(report_asset.content["recommendation"], "pass")
            checks = {item["check"]: item["status"] for item in report_asset.content["checks"]}
            self.assertEqual(checks["chapter_production_runs"], "passed")
            self.assertEqual(checks["draft_versions"], "passed")
            self.assertEqual(checks["context_bundles"], "passed")
            self.assertEqual(checks["continuity_reports"], "passed")
            self.assertEqual(checks["feedback_backflow"], "passed")
            metrics = report_asset.content["scale_metrics"]
            self.assertEqual(metrics["target_chapter_count"], 3)
            self.assertEqual(metrics["observed_chapter_count"], 3)
            self.assertEqual(metrics["chapter_production_run_count"], 3)
            self.assertEqual(metrics["draft_version_count"], 3)
            self.assertEqual(metrics["context_bundle_count"], 3)
            self.assertEqual(metrics["continuity_conflict_count"], 0)
            self.assertEqual(metrics["model_call_count"], 3)
            self.assertGreater(metrics["cost_total"], 0)
            self.assertEqual(metrics["feedback_backflow_count"], 1)


if __name__ == "__main__":
    unittest.main()
