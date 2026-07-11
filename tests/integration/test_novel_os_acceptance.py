from pathlib import Path
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.model_adapters.mock import MockModelAdapter
from novel_forge.modules.agent_runs import list_agent_runs
from novel_forge.modules.agent_scheduler import list_agent_dispatch_queue, run_agent_scheduler_loop
from novel_forge.modules.context_builder import create_context_build_plan, create_context_bundle
from novel_forge.modules.operations import create_long_chain_acceptance_report
from novel_forge.modules.review import service as review_service
from novel_forge.modules.runtime_ledger import create_budget_policy, create_cost_quality_dashboard, list_cost_ledgers, trace_timeline_payload
from novel_forge.modules.source_intake import run_source_governance_runtime_gate
from novel_forge.modules.workflow_nodes import create_workflow_definition, execute_workflow, list_node_runs, resume_workflow
from novel_forge.modules.workspace import service as workspace_service
from novel_forge.schemas import CharacterCard, ChapterPlan, ContinuityBible, DraftChapter, Outline, WorldBible, validate_common_fields
from novel_forge.storage.local import LocalStorage
from tests.unit.source_governance_fixtures import record_clean_source_governance_evidence


class NovelOSAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self._previous_provider = os.environ.get("NOVEL_FORGE_MODEL_PROVIDER")
        os.environ["NOVEL_FORGE_MODEL_PROVIDER"] = "mock"

    def tearDown(self):
        if self._previous_provider is None:
            os.environ.pop("NOVEL_FORGE_MODEL_PROVIDER", None)
        else:
            os.environ["NOVEL_FORGE_MODEL_PROVIDER"] = self._previous_provider

    def test_operating_system_acceptance_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            model = MockModelAdapter()
            fixture = _create_project_fixture(storage)
            context_plan = create_context_build_plan(
                storage,
                fixture["chapter_plan_path"],
                query="Clock City chapter one drafting and rework context",
                workspace_path=fixture["workspace_path"],
            )
            context_bundle = create_context_bundle(storage, context_plan["path"])
            context_bundle_path = context_bundle["path"]
            budget_policy = create_budget_policy(
                storage,
                scope=fixture["project_id"],
                limits={"max_cost": 10.0, "max_tokens_per_run": 5000},
                project_id=fixture["project_id"],
                workspace_path=fixture["workspace_path"],
            )
            draft_rel = fixture["draft_path"]
            review_path = review_service.review(storage, draft_rel, model=model)
            review_rel = _rel(storage, review_path)
            self.assertTrue(storage.read_asset(review_path).issues)
            record_clean_source_governance_evidence(storage, project_id=fixture["project_id"], workspace_path=fixture["workspace_path"])
            source_gate = run_source_governance_runtime_gate(storage, project_id=fixture["project_id"], environment="production")

            workflow = create_workflow_definition(
                storage,
                name="Novel OS acceptance workflow",
                entry_node_id="draft-agent",
                runtime_policy={
                    "mode": "operating_system",
                    "enforce_required_evidence": True,
                    "require_context_bundle": True,
                    "require_budget_policy": True,
                    "project_id": fixture["project_id"],
                    "workspace_path": fixture["workspace_path"],
                    "source_governance_runtime_gate_path": source_gate["gate_result"]["path"],
                },
                nodes=[
                    {
                        "node_id": "draft-agent",
                        "node_type": "agent",
                        "operation": "draft",
                        "input_assets": [fixture["chapter_plan_path"], context_bundle_path],
                        "input_types": ["chapter_plan", "context_bundle"],
                        "output_types": ["draft_chapter"],
                        "processor": {
                            "kind": "agent",
                            "agent_key": "draft",
                            "agent_status": "prepared",
                            "expected_output_assets": [draft_rel],
                            "context_bundle_path": context_bundle_path,
                            "token_used": 180,
                            "cost_estimate": 0.18,
                            "token_budget": 1000,
                            "model_provider": "mock",
                            "model_name": "mock-model",
                        },
                    },
                    {
                        "node_id": "kg-gate",
                        "node_type": "quality_gate",
                        "operation": "novel_kg_gate",
                        "depends_on": ["draft-agent"],
                        "input_assets": [draft_rel],
                        "input_types": ["draft_chapter"],
                        "output_types": ["draft_chapter"],
                        "processor": {"kind": "deterministic", "expected_output_assets": [draft_rel]},
                        "quality_gate": {
                            "kind": "novel_kg",
                            "required": True,
                            "blocking": True,
                            "target_path": draft_rel,
                            "project_id": fixture["project_id"],
                            "workspace_path": fixture["workspace_path"],
                        },
                    },
                    {
                        "node_id": "review-rework",
                        "node_type": "revision",
                        "operation": "review_rework_loop",
                        "depends_on": ["kg-gate"],
                        "input_assets": [review_rel],
                        "input_types": ["review_report"],
                        "output_types": ["revision_task", "editor_patch", "draft_version", "review_report", "publish_gate_report"],
                        "processor": {
                            "kind": "service",
                            "operation": "review_rework_loop",
                            "review_path": review_rel,
                            "draft_path": draft_rel,
                            "issue_indexes": [0],
                            "context_bundle_path": context_bundle_path,
                            "workspace_path": fixture["workspace_path"],
                            "human_override": True,
                        },
                    },
                ],
            )

            initial = execute_workflow(
                storage,
                workflow["path"],
                input_assets=[fixture["chapter_plan_path"]],
                execute_agents=False,
                workspace_path=fixture["workspace_path"],
            )
            self.assertEqual(initial["status"], "running", initial)
            self.assertEqual(initial["blocked"]["node_id"], "draft-agent")
            self.assertEqual(list_agent_dispatch_queue(storage)[0]["status"], "queued")

            scheduler = run_agent_scheduler_loop(storage, project_id=fixture["project_id"], iterations=2, force_lease=True)
            self.assertEqual(scheduler["status"], "completed")
            self.assertEqual(scheduler["acked_count"], 1)
            self.assertEqual(scheduler["error_count"], 0)

            resume = scheduler["ticks"][0]["acked"][0]["workflow_resume"]
            self.assertEqual(resume["status"], "completed", resume)
            self.assertEqual(storage.read_asset(initial["workflow_run"]["path"]).content["status"], "superseded")
            node_statuses = {row["node_id"]: row["status"] for row in list_node_runs(storage, run_id=resume["run_id"])}
            self.assertEqual(node_statuses["draft-agent"], "succeeded")
            self.assertEqual(node_statuses["kg-gate"], "succeeded")
            self.assertEqual(node_statuses["review-rework"], "succeeded")
            self.assertEqual(list_agent_runs(storage)[0]["status"], "succeeded")

            kg_gate_path = _latest_gate_result(storage, "novel_kg")
            revision_task_path = _latest_path_by_type(storage, "reviews", "revision_task")
            task = storage.read_asset(revision_task_path)
            final_draft_path = task.content["outputs"]["final_draft_path"]
            rework_publish_gate_path = task.content["outputs"]["publish_gate_report_path"]
            self.assertTrue(final_draft_path)
            self.assertEqual(storage.read_asset(rework_publish_gate_path).type, "publish_gate_report")

            invalidation_workflow = create_workflow_definition(
                storage,
                name="Novel OS invalidation resume workflow",
                entry_node_id="invalidate-outline",
                nodes=[
                    {
                        "node_id": "invalidate-outline",
                        "node_type": "invalidation",
                        "operation": "invalidate_downstream",
                        "input_assets": [fixture["outline_path"]],
                        "input_types": ["outline"],
                        "output_types": ["change_impact_report"],
                        "processor": {
                            "kind": "invalidation",
                            "target_path": fixture["outline_path"],
                            "max_depth": 3,
                            "reason": "OS acceptance upstream outline change",
                            "project_id": fixture["project_id"],
                            "apply": True,
                        },
                    },
                    {
                        "node_id": "resume-publish-gate",
                        "node_type": "publishing",
                        "operation": "publish_gate_report",
                        "depends_on": ["invalidate-outline"],
                        "input_assets": [rework_publish_gate_path],
                        "input_types": ["publish_gate_report"],
                        "output_types": ["publish_gate_report"],
                        "processor": {"kind": "deterministic", "expected_output_assets": [rework_publish_gate_path]},
                    },
                ],
            )
            invalidation_run = execute_workflow(
                storage,
                invalidation_workflow["path"],
                input_assets=[fixture["outline_path"]],
                max_nodes=1,
                workspace_path=fixture["workspace_path"],
            )
            self.assertEqual(invalidation_run["status"], "running")
            self.assertEqual(invalidation_run["blocked"]["node_id"], "resume-publish-gate")
            self.assertEqual(storage.read_json(storage.root / fixture["chapter_plan_path"])["metadata"]["asset_status"], "stale")

            publish_resume = resume_workflow(
                storage,
                invalidation_run["workflow_run"]["path"],
                workspace_path=fixture["workspace_path"],
            )
            self.assertEqual(publish_resume["status"], "completed")
            publish_gate_path = storage.root / rework_publish_gate_path
            self.assertEqual(storage.read_asset(publish_gate_path).type, "publish_gate_report")
            invalidation_report_path = invalidation_run["invalidations"][0]["impact_report"]["path"]

            ledgers = list_cost_ledgers(storage, project_id=fixture["project_id"])
            self.assertGreaterEqual(len(ledgers), 1)
            model_call_log_path = _latest_path_by_type(storage, "runs", "model_call_log")
            timeline = trace_timeline_payload(storage, project_id=fixture["project_id"])
            self.assertGreaterEqual(timeline["summary"]["span_count"], 1)
            self.assertIn("node_run", timeline["summary"]["by_type"])
            self.assertIn("agent_run", timeline["summary"]["by_type"])
            self.assertIn("gate", timeline["summary"]["by_type"])
            self.assertIn("model_call", timeline["summary"]["by_type"])
            self.assertIn("cost", timeline["summary"]["by_type"])
            dashboard = create_cost_quality_dashboard(storage, project_id=fixture["project_id"], chapter=1)
            self.assertEqual(storage.read_asset(dashboard["path"]).type, "cost_quality_dashboard")

            report = create_long_chain_acceptance_report(
                storage,
                project_id=fixture["project_id"],
                chapter_count=1,
                acceptance_evidence={
                    "workflow_run_path": resume["workflow_run"]["path"],
                    "agent_scheduler_loop": {
                        "scheduler_loop_id": scheduler["scheduler_loop_id"],
                        "acked_count": scheduler["acked_count"],
                        "error_count": scheduler["error_count"],
                    },
                    "context_bundle_path": context_bundle_path,
                    "kg_gate_path": kg_gate_path,
                    "budget_policy_path": budget_policy["path"],
                    "model_call_log_path": _rel(storage, model_call_log_path),
                    "revision_task_path": _rel(storage, revision_task_path),
                    "cost_ledger_path": ledgers[0]["path"],
                    "trace_timeline_summary": timeline["summary"],
                    "invalidation_report_path": invalidation_report_path,
                    "resume_workflow_run_path": publish_resume["workflow_run"]["path"],
                    "publish_gate_report_path": _rel(storage, publish_gate_path),
                    "cost_quality_dashboard_path": dashboard["path"],
                },
            )
            report_asset = storage.read_asset(report["path"])
            self.assertEqual(report_asset.type, "long_chain_acceptance_report")
            self.assertEqual(validate_common_fields(report_asset.to_dict()), [])
            self.assertEqual(report_asset.content["acceptance_mode"], "operating_system")
            self.assertEqual(report_asset.content["recommendation"], "pass")
            checks = {item["check"]: item["status"] for item in report_asset.content["checks"]}
            for check in [
                "workflow_run",
                "context_bundle",
                "agent_scheduler_loop",
                "kg_gate",
                "budget_policy",
                "model_call_log",
                "review_rework",
                "cost_ledger",
                "trace_span_coverage",
                "invalidation",
                "resume",
                "publish_gate",
                "cost_quality_dashboard",
            ]:
                self.assertEqual(checks[check], "passed")


def _create_project_fixture(storage: LocalStorage) -> dict[str, str]:
    workspace = workspace_service.init_workspace(storage, "Novel OS Acceptance", "Clockverse", 1)
    workspace_ref = _rel(storage, workspace)
    workspace_asset = storage.read_asset(workspace)
    project_id = str(workspace_asset.content["project_id"])
    metadata = {"project_id": project_id, "workspace_path": workspace_ref}
    world_path = storage.write_asset(
        "worlds",
        WorldBible(
            title="Clock City",
            content={
                "setting": "Clock City",
                "rules": ["Every bell choice has a visible memory cost."],
                "factions": [{"name": "Archive Guild", "goal": "control the Memory Key"}],
                "locations": [{"name": "North Tower", "risk": "unstable bell chamber"}],
                "props": [{"name": "Memory Key", "function": "opens sealed hour rooms"}],
            },
            metadata=metadata,
            references=[workspace_ref],
        ),
    )
    character_path = storage.write_asset(
        "characters",
        CharacterCard(
            title="Lin Qiao",
            content={
                "name": "林乔",
                "aliases": ["钟城行者"],
                "role": "protagonist",
                "external_goal": "recover the Memory Key",
                "internal_need": "trust allies before the tower opens",
                "faction": "Archive Guild",
                "current_location": "North Tower",
            },
            metadata=metadata,
            references=[storage.read_asset(world_path).id, _rel(storage, world_path)],
        ),
    )
    storage.write_asset(
        "continuity",
        ContinuityBible(
            title="Clock City continuity",
            content={
                "project_id": project_id,
                "worldview_rules": ["Memory Key access always requires a cost."],
                "timeline": [{"chapter": 1, "event": "林乔 enters North Tower"}],
                "constraints": ["Do not open the sealed hour room for free."],
            },
            metadata=metadata,
            references=[storage.read_asset(character_path).id, _rel(storage, character_path)],
        ),
    )
    outline_path = storage.write_asset(
        "outlines",
        Outline(
            title="Clockverse outline",
            content={"acts": [{"act": 1, "goal": "林乔 must choose whether to pay the Memory Key cost."}]},
            metadata=metadata,
            references=[workspace_ref, storage.read_asset(character_path).id, _rel(storage, character_path)],
        ),
    )
    chapter_plan_path = storage.write_asset(
        "chapter_plans",
        ChapterPlan(
            title="Chapter 1 plan",
            source=storage.read_asset(outline_path).id,
            content={
                "chapter": 1,
                "objective": "林乔 enters North Tower to find the Memory Key.",
                "beats": ["Archive Guild pressure", "North Tower clue", "choice with memory cost"],
                "hook": "The Memory Key opens by itself behind the bell wall.",
            },
            metadata=metadata,
            references=[storage.read_asset(outline_path).id, _rel(storage, outline_path)],
        ),
    )
    draft_path = storage.write_asset(
        "drafts",
        DraftChapter(
            title="Chapter 1 draft",
            source=storage.read_asset(chapter_plan_path).id,
            content={
                "chapter": 1,
                "text": (
                    "为了找回 Memory Key，林乔必须在 North Tower 的钟室里选择相信 Archive Guild 的旧盟友。"
                    "因为钟声会吞掉记忆，所以她把母亲留下的线索压进掌心，但仍然推开铁门。"
                    "雨声、铜锈和齿轮声挤在一起，她看见墙缝里浮出一枚刻着钟城印记的钥匙。"
                    "最后一声钟响传来，Memory Key 忽然打开了墙后的门，里面有人喊出她失去的名字。"
                ),
                "copyright_boundary": "self-authored OS acceptance fixture",
            },
            metadata=metadata,
            references=[storage.read_asset(chapter_plan_path).id, _rel(storage, chapter_plan_path)],
        ),
    )
    return {
        "project_id": project_id,
        "workspace_path": workspace_ref,
        "world_path": _rel(storage, world_path),
        "character_path": _rel(storage, character_path),
        "outline_path": _rel(storage, outline_path),
        "chapter_plan_path": _rel(storage, chapter_plan_path),
        "draft_path": _rel(storage, draft_path),
    }


def _latest_gate_result(storage: LocalStorage, gate_kind: str) -> str:
    for path in reversed(storage.list_json("runs")):
        data = storage.read_json(path)
        if data.get("type") == "gate_result" and data.get("content", {}).get("gate_kind") == gate_kind:
            return _rel(storage, path)
    raise AssertionError(f"gate_result not found: {gate_kind}")


def _latest_path_by_type(storage: LocalStorage, category: str, asset_type: str) -> Path:
    for path in reversed(storage.list_json(category)):
        data = storage.read_json(path)
        if data.get("type") == asset_type:
            return path
    raise AssertionError(f"{asset_type} not found in data/{category}")


def _rel(storage: LocalStorage, path: str | Path) -> str:
    value = Path(path)
    if value.is_absolute():
        return str(value.relative_to(storage.root))
    return str(value)


if __name__ == "__main__":
    unittest.main()
