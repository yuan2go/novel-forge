from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.agent_registry import resolve_agent_registry_entry, sync_runtime_profiles
from novel_forge.modules.agent_runs import start_agent_run, update_agent_run_status
from novel_forge.modules.audit_log import build_audit_trail, record_audit_event
from novel_forge.modules.clickhouse_analytics import analytics_dashboard_snapshot, sync_analytics
from novel_forge.modules.context_builder import build_flow_context_bundle
from novel_forge.modules.editor_chief import build_editor_chief_snapshot
from novel_forge.modules.evaluation_center import create_evaluation_gate
from novel_forge.modules.long_memory import create_memory_record
from novel_forge.modules.pgvector_store import build_embedding_job, hybrid_retrieve
from novel_forge.modules.review_issue import list_review_issues
from novel_forge.schemas import ChapterPlan
from novel_forge.storage.local import LocalStorage


class NovelOSGovernanceLoopTests(unittest.TestCase):
    def test_registry_retrieval_agent_audit_evaluation_analytics_governance_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "governance-loop-p"
            trace_id = "trace-governance-loop"
            sync_runtime_profiles(storage)
            registry = resolve_agent_registry_entry(storage, agent_id="draft", operation="draft", require_schedulable=True)
            memory = create_memory_record(
                storage,
                project_id=project_id,
                level="L4",
                memory_type="world_rule",
                title="Gate Law",
                summary="The city gate opens only when the archive bell rings.",
                content={"rule": "archive bell"},
            )
            build_embedding_job(storage, source_paths=[memory["path"]], project_id=project_id)
            retrieval = hybrid_retrieve(storage, query="archive bell gate", project_id=project_id, persist=True)
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="Governance chapter plan",
                    content={"chapter": 1, "objective": "enter gate", "beats": ["bell", "gate"], "hook": "the archive answers"},
                    metadata={"project_id": project_id, "trace_id": trace_id},
                ),
            )
            context = build_flow_context_bundle(storage, str(plan_path.relative_to(storage.root)), flow="prose", environment="compat")
            run = start_agent_run(
                storage,
                agent_key="draft",
                operation="draft",
                status="running",
                evidence={
                    "trace": {"trace_id": trace_id},
                    "agent_registry": registry,
                    "knowledge_context_contract": context.get("knowledge_context_contract", {}),
                },
            )
            update_agent_run_status(storage, run["path"], status="succeeded", output_assets=[str(plan_path.relative_to(storage.root))], event_type="agent_run.succeeded", message="governance fixture")
            record_audit_event(
                storage,
                event_type="governance_loop",
                action="draft_review_publish_gate_minimal",
                actor_id="draft",
                project_id=project_id,
                trace_id=trace_id,
                input_refs=[str(plan_path.relative_to(storage.root))],
                output_refs=[run["path"], retrieval["path"], context["path"]],
            )
            gate = create_evaluation_gate(storage, str(plan_path.relative_to(storage.root)), minimum_score=0.99, project_id=project_id)
            issues = list_review_issues(storage, project_id=project_id)
            trail = build_audit_trail(storage, project_id=project_id, trace_id=trace_id)
            sync = sync_analytics(storage, project_id=project_id, online=False)
            dashboard = analytics_dashboard_snapshot(storage, project_id=project_id)
            editor = build_editor_chief_snapshot(storage, project_id=project_id)

            self.assertTrue(registry["scheduler_enabled"])
            self.assertTrue(context["knowledge_context_contract"]["context_bundle_id"])
            self.assertTrue(context["knowledge_context_contract"]["knowledge_pack_id"])
            self.assertTrue(retrieval["context_builder_evidence"]["result_refs"])
            self.assertEqual(gate["asset"]["content"]["status"], "blocked")
            self.assertTrue(issues)
            self.assertGreaterEqual(trail["event_count"], 1)
            self.assertGreaterEqual(sync["event_count"], 1)
            self.assertEqual(dashboard["asset"]["type"], "analytics_dashboard_snapshot")
            self.assertIn("governance_loop", editor)
            self.assertEqual(editor["governance_loop"]["status"], "ready")
