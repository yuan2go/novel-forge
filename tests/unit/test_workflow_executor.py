from pathlib import Path
import sys
import tempfile
import unittest
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.agent_runs import list_agent_runs
from novel_forge.modules.chapter_production_bus import start_chapter_production
from novel_forge.modules.runtime_ledger import acquire_scheduler_lease, create_budget_policy, record_gate_result, scheduler_lease_status
from novel_forge.modules.publishing_feedback_adapters import create_feedback_mutation_proposal, resolve_feedback_mutation_proposal
from novel_forge.modules.workspace.service import init_workspace
from novel_forge.modules.workflow_nodes import (
    build_ready_node_queue,
    build_workflow_governance_drift_report,
    build_workflow_runtime_console,
    cancel_workflow_run,
    create_workflow_definition,
    create_v1_chapter_production_workflow_template,
    execute_workflow,
    list_processor_contracts,
    list_node_runs,
    parse_workflow_dag,
    pause_workflow_run,
    resolve_workflow_dependencies,
    resume_workflow,
    retry_workflow_run,
    run_workflow_governance_drift_gate,
    run_workflow_scheduler,
    run_workflow_scheduler_loop,
    validate_workflow_run_transition,
    workflow_state_machine,
)
from novel_forge.schemas import (
    CharacterCard,
    ChapterPlan,
    CleanedText,
    ContextBundle,
    DraftChapter,
    MKAOSSelectorGovernanceBindingApplicationReport,
    MKAOSSelectorGovernanceReport,
    Outline,
    ReviewReport,
    SourceDocument,
    WorldBible,
)
from novel_forge.storage.local import LocalStorage
from tests.unit.publishing_fixtures import production_envelope


class WorkflowExecutorTests(unittest.TestCase):
    def _write_selector_governance_context_bundle(
        self,
        storage: LocalStorage,
        plan_path: Path,
        *,
        project_id: str = "workflow-governance",
        status: str = "applied",
        include_source_gate: bool = True,
        source_gate_status: str = "passed",
    ) -> dict[str, str]:
        report_path = storage.write_asset(
            "runs",
            MKAOSSelectorGovernanceReport(
                title="Workflow selector governance report",
                content={
                    "selector_governance_report_id": "selector-governance-report-workflow",
                    "selector_policy_patch": {"weights": {"workflow_context": 1.0}},
                    "refresh_contract": {"selector_refresh_only": True, "raw_source_text_included": False},
                    "generated_at": "2026-07-08T00:00:00+00:00",
                },
                metadata={"project_id": project_id},
            ),
        )
        report_ref = str(report_path.relative_to(storage.root))
        application_path = storage.write_asset(
            "runs",
            MKAOSSelectorGovernanceBindingApplicationReport(
                title="Workflow selector governance binding application",
                content={
                    "binding_application_id": "selector-governance-binding-application-workflow",
                    "binding_proposal_path": "data/runs/selector-governance-binding-proposal-workflow.json",
                    "selector_governance_report_path": report_ref,
                    "context_builder_payload_patch": {
                        "selector_governance_report_path": report_ref,
                        "selector_governance_binding_application_report_id": "selector-governance-binding-application-workflow",
                    },
                    "status": status,
                    "application_contract": {
                        "approval_verified": True,
                        "context_build_executed": False,
                        "context_bundle_mutated": False,
                        "payload_patch_only": True,
                    },
                    "created_at": "2026-07-08T00:00:00+00:00",
                },
                metadata={"project_id": project_id, "asset_status": status},
                references=[report_ref],
            ),
        )
        application_ref = str(application_path.relative_to(storage.root))
        binding = {
            "application_report_path": application_ref,
            "selector_governance_report_path": report_ref,
            "application_contract": {"approval_verified": True, "payload_patch_only": True},
        }
        source_gate_ref = ""
        source_gate = {}
        if include_source_gate:
            source_gate_result = record_gate_result(
                storage,
                gate_kind="source_governance_runtime",
                status=source_gate_status,
                target_paths=[str(plan_path.relative_to(storage.root))],
                result={
                    "contract": "source-governance-runtime-gate-v1",
                    "summary": {"blocking_count": 0, "raw_source_text_included": False},
                    "mutation_policy": "read-only fixture evidence",
                },
                project_id=project_id,
                blocking=source_gate_status == "failed",
            )
            source_gate_ref = str(source_gate_result.get("path") or "")
            source_gate = {
                "status": source_gate_status,
                "blocking": source_gate_status == "failed",
                "gate_result_path": source_gate_ref,
                "readiness_report_path": "",
                "summary": {"blocking_count": 0, "raw_source_text_included": False},
            }
        context_content = {
            "build_plan_id": "workflow-context-plan",
            "target_asset_id": storage.read_asset(plan_path).id,
            "selected_assets": [],
            "compressed_context": {},
            "token_budget": {"max_tokens": 1000},
            "token_estimate": 16,
            "actual_context": "workflow governed context",
            "source_asset_ids": [],
            "knowledge_context_contract": {
                "selector_governance": {"report_path": report_ref},
                "selector_governance_binding_application": binding,
            },
            "selector_governance_binding_application": binding,
        }
        if source_gate:
            context_content["source_governance_runtime_gate"] = source_gate
        context_metadata = {
            "project_id": project_id,
            "selector_governance_report_path": report_ref,
            "selector_governance_binding_application_path": application_ref,
        }
        if source_gate_ref:
            context_metadata["source_governance_runtime_gate_path"] = source_gate_ref
            context_metadata["source_governance_runtime_gate_status"] = source_gate_status
        context_path = storage.write_asset(
            "contexts",
            ContextBundle(
                title="Workflow governed context",
                source=storage.read_asset(plan_path).id,
                content=context_content,
                metadata=context_metadata,
                references=[item for item in [str(plan_path.relative_to(storage.root)), report_ref, application_ref, source_gate_ref] if item],
            ),
        )
        return {"context_path": str(context_path.relative_to(storage.root)), "report_path": report_ref, "application_path": application_ref, "source_gate_path": source_gate_ref}

    def test_runtime_policy_blocks_generation_without_context_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(title="Plan", content={"chapter": 1, "objective": "open", "beats": ["beat"], "hook": "hook"}),
            )
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Draft",
                    source=storage.read_asset(plan_path).id,
                    content={"chapter": 1, "text": "原创测试章节。", "copyright_boundary": "unit test"},
                    references=[storage.read_asset(plan_path).id, str(plan_path.relative_to(storage.root))],
                ),
            )
            workflow = create_workflow_definition(
                storage,
                name="Strict Context Workflow",
                entry_node_id="draft-agent",
                runtime_policy={"mode": "operating_system", "require_context_bundle": True},
                nodes=[
                    {
                        "node_id": "draft-agent",
                        "node_type": "agent",
                        "operation": "draft",
                        "input_types": ["chapter_plan"],
                        "output_types": ["draft_chapter"],
                        "processor": {
                            "kind": "agent",
                            "agent_key": "draft",
                            "agent_status": "prepared",
                            "expected_output_assets": [str(draft_path.relative_to(storage.root))],
                        },
                    }
                ],
            )

            result = execute_workflow(storage, workflow["path"], input_assets=[plan_path], execute_agents=False)

            self.assertEqual(result["status"], "failed")
            self.assertIn("context_bundle", result["errors"][0])
            runs = list_node_runs(storage, run_id=result["run_id"])
            self.assertEqual(runs[0]["status"], "failed")
            gate_results = [storage.read_json(path) for path in storage.list_json("runs") if storage.read_json(path).get("type") == "gate_result"]
            runtime_policy_gates = [item for item in gate_results if item.get("content", {}).get("gate_kind") == "runtime_policy"]
            self.assertTrue(runtime_policy_gates)
            self.assertEqual(runtime_policy_gates[-1]["content"]["status"], "failed")

    def test_agent_event_policy_flows_from_workflow_runtime_policy_to_agent_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(title="Workflow event policy plan", content={"chapter": 1, "objective": "draft", "beats": ["beat"], "hook": "hook"}),
            )
            workflow = create_workflow_definition(
                storage,
                name="Agent Event Policy Workflow",
                entry_node_id="draft-agent",
                runtime_policy={"agent_event_policy": {"mode": "success_summary"}},
                nodes=[
                    {
                        "node_id": "draft-agent",
                        "node_type": "agent",
                        "operation": "draft",
                        "input_types": ["chapter_plan"],
                        "output_types": ["draft_chapter"],
                        "processor": {"kind": "agent", "agent_key": "draft", "agent_status": "prepared"},
                    }
                ],
            )

            result = execute_workflow(storage, workflow["path"], input_assets=[plan_path], execute_agents=False)

            self.assertEqual(result["status"], "running")
            agent_runs = _run_assets_by_type(storage, "agent_run")
            self.assertEqual(agent_runs[-1]["content"]["agent_event_policy"]["mode"], "success_summary")
            self.assertEqual(agent_runs[-1]["content"]["agent_event_summary"]["skipped_event_count"], 1)
            event_types = [row["content"]["event_type"] for row in _run_assets_by_type(storage, "agent_event")]
            self.assertNotIn("agent_run.started", event_types)
            self.assertIn("agent_dispatch.queued", event_types)
            span_names = [row["content"]["name"] for row in _run_assets_by_type(storage, "trace_span")]
            self.assertNotIn("agent_run.started", span_names)
            self.assertIn("agent_dispatch.queued", span_names)

    def test_runtime_policy_records_selector_governance_binding_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(title="Plan", content={"chapter": 1, "objective": "open", "beats": ["beat"], "hook": "hook"}, metadata={"project_id": "workflow-governance"}),
            )
            refs = self._write_selector_governance_context_bundle(storage, plan_path)
            workflow = create_workflow_definition(
                storage,
                name="Strict Governed Context Workflow",
                entry_node_id="draft-agent",
                runtime_policy={"mode": "operating_system", "require_context_bundle": True},
                nodes=[
                    {
                        "node_id": "draft-agent",
                        "node_type": "generation",
                        "operation": "draft",
                        "input_types": ["chapter_plan", "context_bundle"],
                        "output_types": ["draft_chapter"],
                        "processor": {"kind": "record_only", "context_bundle_path": refs["context_path"]},
                    }
                ],
            )

            result = execute_workflow(storage, workflow["path"], input_assets=[plan_path, storage.root / refs["context_path"]])

            self.assertEqual(result["status"], "completed")
            node_run = storage.read_asset(list_node_runs(storage, run_id=result["run_id"])[0]["path"])
            evidence = node_run.content["processor"]["runtime_policy_evidence"]
            self.assertEqual(evidence["context_bundle_path"], refs["context_path"])
            self.assertEqual(evidence["selector_governance_report_path"], refs["report_path"])
            self.assertEqual(evidence["selector_governance_binding_application_report_path"], refs["application_path"])
            self.assertEqual(evidence["selector_governance_binding_status"], "applied")
            self.assertEqual(evidence["source_governance_runtime_gate_path"], refs["source_gate_path"])
            self.assertEqual(evidence["source_governance_runtime_gate_status"], "passed")
            console = build_workflow_runtime_console(storage, workflow_run_path_or_id=result["workflow_run"]["path"])
            source_console = console["source_governance_runtime_evidence"]
            self.assertEqual(source_console["status"], "passed")
            self.assertEqual(source_console["count"], 1)
            self.assertEqual(source_console["latest"]["gate_result_path"], refs["source_gate_path"])

    def test_runtime_policy_blocks_context_without_source_governance_runtime_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(title="Plan", content={"chapter": 1, "objective": "open", "beats": ["beat"], "hook": "hook"}, metadata={"project_id": "workflow-governance"}),
            )
            refs = self._write_selector_governance_context_bundle(storage, plan_path, include_source_gate=False)
            workflow = create_workflow_definition(
                storage,
                name="Strict Context Without Source Gate Workflow",
                entry_node_id="draft-agent",
                runtime_policy={"mode": "operating_system", "require_context_bundle": True},
                nodes=[
                    {
                        "node_id": "draft-agent",
                        "node_type": "generation",
                        "operation": "draft",
                        "input_types": ["chapter_plan", "context_bundle"],
                        "output_types": ["draft_chapter"],
                        "processor": {"kind": "record_only", "context_bundle_path": refs["context_path"]},
                    }
                ],
            )

            result = execute_workflow(storage, workflow["path"], input_assets=[plan_path, storage.root / refs["context_path"]])

            self.assertEqual(result["status"], "failed")
            self.assertIn("source governance evidence requires", result["errors"][0])

    def test_runtime_policy_blocks_direct_selector_governance_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(title="Plan", content={"chapter": 1, "objective": "open", "beats": ["beat"], "hook": "hook"}, metadata={"project_id": "workflow-governance"}),
            )
            refs = self._write_selector_governance_context_bundle(storage, plan_path)
            workflow = create_workflow_definition(
                storage,
                name="Strict Mismatched Governed Context Workflow",
                entry_node_id="draft-agent",
                runtime_policy={"mode": "operating_system", "require_context_bundle": True},
                nodes=[
                    {
                        "node_id": "draft-agent",
                        "node_type": "generation",
                        "operation": "draft",
                        "input_types": ["chapter_plan", "context_bundle"],
                        "output_types": ["draft_chapter"],
                        "processor": {
                            "kind": "record_only",
                            "context_bundle_path": refs["context_path"],
                            "selector_governance_report_path": "data/runs/different-selector-governance-report.json",
                        },
                    }
                ],
            )

            result = execute_workflow(storage, workflow["path"], input_assets=[plan_path, storage.root / refs["context_path"]])

            self.assertEqual(result["status"], "failed")
            self.assertIn("selector_governance_report_path does not match", result["errors"][0])

    def test_runtime_policy_blocks_selector_governance_without_binding_application(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(title="Plan", content={"chapter": 1, "objective": "open", "beats": ["beat"], "hook": "hook"}, metadata={"project_id": "workflow-governance"}),
            )
            context_path = storage.write_asset(
                "contexts",
                ContextBundle(
                    title="Ungoverned selector context",
                    source=storage.read_asset(plan_path).id,
                    content={
                        "build_plan_id": "workflow-context-plan",
                        "target_asset_id": storage.read_asset(plan_path).id,
                        "selected_assets": [],
                        "compressed_context": {},
                        "token_budget": {"max_tokens": 1000},
                        "token_estimate": 16,
                        "actual_context": "workflow selector context without binding application",
                        "source_asset_ids": [],
                        "knowledge_context_contract": {"selector_governance": {"report_path": "data/runs/selector-report-without-application.json"}},
                    },
                    metadata={"project_id": "workflow-governance", "selector_governance_report_path": "data/runs/selector-report-without-application.json"},
                    references=[str(plan_path.relative_to(storage.root))],
                ),
            )
            workflow = create_workflow_definition(
                storage,
                name="Strict Ungoverned Selector Context Workflow",
                entry_node_id="draft-agent",
                runtime_policy={"mode": "operating_system", "require_context_bundle": True},
                nodes=[
                    {
                        "node_id": "draft-agent",
                        "node_type": "generation",
                        "operation": "draft",
                        "input_types": ["chapter_plan", "context_bundle"],
                        "output_types": ["draft_chapter"],
                        "processor": {"kind": "record_only", "context_bundle_path": str(context_path.relative_to(storage.root))},
                    }
                ],
            )

            result = execute_workflow(storage, workflow["path"], input_assets=[plan_path, context_path])

            self.assertEqual(result["status"], "failed")
            self.assertIn("requires selector_governance_binding_application_report_path", result["errors"][0])

    def test_executor_runs_dag_and_records_workflow_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            source_path = storage.write_asset(
                "raw",
                SourceDocument(
                    title="Raw",
                    source="fixture",
                    content={"text": "fixture"},
                    metadata={"rights": {"authorization": "test_fixture", "copyright_boundary": "fixture"}},
                ),
            )
            cleaned_path = storage.write_asset(
                "cleaned",
                CleanedText(title="Cleaned", source=storage.read_asset(source_path).id, content={"text": "clean"}),
            )
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Draft",
                    source=storage.read_asset(cleaned_path).id,
                    content={"chapter": 1, "text": "原创测试章节。"},
                    references=[storage.read_asset(cleaned_path).id, str(cleaned_path.relative_to(storage.root))],
                ),
            )
            workflow = create_workflow_definition(
                storage,
                name="Executor DAG",
                entry_node_id="clean",
                nodes=[
                    {
                        "node_id": "clean",
                        "node_type": "cleaning",
                        "operation": "clean",
                        "input_types": ["source_document"],
                        "output_types": ["cleaned_text"],
                        "processor": {"kind": "deterministic", "expected_output_assets": [str(cleaned_path.relative_to(storage.root))]},
                        "quality_gate": {"required": True, "min_input_count": 1},
                    },
                    {
                        "node_id": "draft",
                        "node_type": "draft",
                        "operation": "draft",
                        "depends_on": ["clean"],
                        "input_types": ["cleaned_text"],
                        "output_types": ["draft_chapter"],
                        "processor": {"kind": "deterministic", "expected_output_assets": [str(draft_path.relative_to(storage.root))]},
                    },
                ],
            )

            result = execute_workflow(storage, workflow["path"], input_assets=[source_path])

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["order"], ["clean", "draft"])
            self.assertEqual(storage.read_asset(result["workflow_run"]["path"]).type, "workflow_run")
            workflow_run_asset = storage.read_asset(result["workflow_run"]["path"])
            self.assertEqual(workflow_run_asset.content["status"], "completed")
            self.assertEqual(workflow_run_asset.content["state_machine"]["version"], "0.2.0")
            self.assertEqual(workflow_run_asset.content["state_transitions"][-1]["from"], "pending")
            self.assertEqual(workflow_run_asset.content["state_transitions"][-1]["to"], "completed")
            runs = list_node_runs(storage, run_id=result["run_id"])
            self.assertEqual([row["node_id"] for row in reversed(runs)], ["clean", "draft"])
            node_run = storage.read_asset(runs[-1]["path"])
            self.assertEqual(node_run.content["trace"]["trace_id"], result["run_id"])
            self.assertTrue(node_run.content["trace"]["span_id"])

    def test_dag_parser_and_dependency_resolver_are_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            source_path = storage.write_asset(
                "raw",
                SourceDocument(
                    title="Raw",
                    source="fixture",
                    content={"text": "fixture"},
                    metadata={"rights": {"authorization": "test_fixture", "copyright_boundary": "fixture"}},
                ),
            )
            workflow = create_workflow_definition(
                storage,
                name="DAG Plan",
                entry_node_id="clean",
                nodes=[
                    {
                        "node_id": "clean",
                        "node_type": "cleaning",
                        "operation": "clean",
                        "input_types": ["source_document"],
                        "output_types": ["cleaned_text"],
                        "processor": {"kind": "deterministic"},
                    },
                    {
                        "node_id": "draft",
                        "node_type": "draft",
                        "operation": "draft",
                        "depends_on": ["clean"],
                        "input_types": ["cleaned_text"],
                        "output_types": ["draft_chapter"],
                        "processor": {"kind": "deterministic"},
                    },
                ],
            )

            dag = parse_workflow_dag(storage, workflow["path"])
            plan = resolve_workflow_dependencies(storage, workflow["path"], input_assets=[source_path])

            self.assertEqual(dag["order"], ["clean", "draft"])
            self.assertEqual(dag["edges"], [{"from": "clean", "to": "draft"}])
            self.assertEqual(plan["ready_nodes"], ["clean"])
            draft_row = next(row for row in plan["nodes"] if row["node_id"] == "draft")
            self.assertEqual(draft_row["dependency_statuses"], {"clean": "planned"})
            self.assertEqual(_run_assets_by_type(storage, "node_run"), [])
            self.assertEqual(_run_assets_by_type(storage, "gate_result"), [])

    def test_runtime_console_exposes_state_machine_ready_queue_and_contracts(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            source_path = storage.write_asset(
                "raw",
                SourceDocument(
                    title="Raw",
                    source="fixture",
                    content={"text": "fixture"},
                    metadata={"rights": {"authorization": "test_fixture", "copyright_boundary": "fixture"}},
                ),
            )
            workflow = create_workflow_definition(
                storage,
                name="Runtime Console",
                entry_node_id="clean",
                nodes=[
                    {
                        "node_id": "clean",
                        "node_type": "cleaning",
                        "operation": "clean",
                        "input_types": ["source_document"],
                        "output_types": ["cleaned_text"],
                        "processor": {"kind": "deterministic"},
                    }
                ],
            )

            queue = build_ready_node_queue(storage, workflow_path_or_id=workflow["path"], input_assets=[source_path])
            console = build_workflow_runtime_console(storage, workflow_path_or_id=workflow["path"], input_assets=[source_path])
            contract_rows = list_processor_contracts()
            contracts = {item["operation"] for item in contract_rows}
            contract_map = {item["operation"]: item for item in contract_rows}
            transition = validate_workflow_run_transition("running", "paused", action="pause")

            self.assertTrue(transition["ok"])
            self.assertIn("running", workflow_state_machine()["allowed_transitions"])
            self.assertEqual(queue["ready_count"], 1)
            self.assertEqual(console["ready_queue"]["queue"][0]["node_id"], "clean")
            self.assertIn("publish_gate_report", contracts)
            self.assertEqual(contract_map["publish_gate_report"]["rollback_strategy"], "quarantine_outputs")
            self.assertEqual(contract_map["publish_gate_report"]["input_schema"], {"type": "asset_paths"})
            self.assertTrue(contract_map["publish_gate_report"]["resume_supported"])
            self.assertIn("review_revision_publish", contracts)
            self.assertTrue(contract_map["review_revision_publish"]["resume_supported"])

    def test_main_chain_workflow_service_defaults_to_loop_kernel(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Main chain draft",
                    content={"chapter": 1, "text": "原创主链 workflow 章节。", "copyright_boundary": "unit test"},
                    metadata={"project_id": "wf-loop"},
                ),
            )
            draft = storage.read_asset(draft_path)
            review_path = storage.write_asset(
                "reviews",
                ReviewReport(
                    title="Main chain review",
                    source=draft.id,
                    content={"summary": "needs governed revision", "target_asset_id": draft.id, "target_asset_path": str(draft_path.relative_to(storage.root))},
                    score=82.0,
                    issues=[{"issue_id": "main-chain-1", "issue_index": 0, "severity": "medium", "message": "tighten continuity", "status": "open"}],
                    revision_suggestions=["tighten continuity"],
                    metadata={"project_id": "wf-loop"},
                    references=[draft.id, str(draft_path.relative_to(storage.root))],
                ),
            )
            workflow = create_workflow_definition(
                storage,
                name="Loop Default Main Chain",
                entry_node_id="review-rework",
                nodes=[
                    {
                        "node_id": "review-rework",
                        "node_type": "revision",
                        "operation": "review_rework_loop",
                        "input_assets": [str(review_path.relative_to(storage.root))],
                        "input_types": ["review_report"],
                        "output_types": ["revision_task", "editor_patch", "draft_version", "review_report", "publish_gate_report", "loop_run", "loop_report"],
                        "processor": {
                            "kind": "service",
                            "operation": "review_rework_loop",
                            "review_path": str(review_path.relative_to(storage.root)),
                            "draft_path": str(draft_path.relative_to(storage.root)),
                            "issue_indexes": [0],
                            "human_override": True,
                            "project_id": "wf-loop",
                        },
                    }
                ],
            )

            result = execute_workflow(storage, workflow["path"], input_assets=[review_path])

            self.assertEqual(result["status"], "completed", result)
            node_run = storage.read_asset(result["node_runs"][0]["path"])
            payload = node_run.content["processor"]["registry_payload"]
            self.assertEqual(payload["workflow_default_executor"], "loop_kernel")
            self.assertTrue(payload["loop_run_path"])
            self.assertTrue(payload["loop_report_path"])
            self.assertEqual(storage.read_json(storage.root / payload["loop_run_path"])["type"], "loop_run")
            self.assertEqual(storage.read_json(storage.root / payload["revision_task_path"])["type"], "revision_task")
            output_paths = {row["path"] for row in node_run.content["output_assets"]}
            self.assertIn(payload["loop_run_path"], output_paths)
            self.assertIn(payload["loop_report_path"], output_paths)

    def test_executor_blocks_failed_quality_gate_before_downstream_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            source_path = storage.write_asset(
                "raw",
                SourceDocument(title="Raw", source="fixture", content={"text": "fixture"}),
            )
            workflow = create_workflow_definition(
                storage,
                name="Gate Block",
                entry_node_id="blocked",
                nodes=[
                    {
                        "node_id": "blocked",
                        "node_type": "quality",
                        "operation": "gate",
                        "input_types": ["source_document"],
                        "output_types": ["cleaned_text"],
                        "processor": {"kind": "deterministic"},
                        "quality_gate": {"required": True, "status": "failed", "message": "schema gate failed"},
                    },
                    {
                        "node_id": "downstream",
                        "node_type": "draft",
                        "operation": "draft",
                        "depends_on": ["blocked"],
                        "processor": {"kind": "deterministic"},
                    },
                ],
            )

            result = execute_workflow(storage, workflow["path"], input_assets=[source_path])

            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["blocked"]["node_id"], "blocked")
            node_runs = list_node_runs(storage, run_id=result["run_id"])
            self.assertEqual(len(node_runs), 1)
            self.assertEqual(node_runs[0]["status"], "failed")
            self.assertIn("schema gate failed", storage.read_asset(result["workflow_run"]["path"]).content["error_message"])

    def test_executor_dispatches_agent_run_from_workflow_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(title="Plan", content={"chapter": 1, "objective": "open", "beats": ["beat"], "hook": "hook"}),
            )
            workflow = create_workflow_definition(
                storage,
                name="Agent Dispatch",
                entry_node_id="draft-agent",
                nodes=[
                    {
                        "node_id": "draft-agent",
                        "node_type": "agent",
                        "operation": "draft",
                        "input_types": ["chapter_plan"],
                        "output_types": ["draft_chapter"],
                        "processor": {"kind": "agent", "agent_key": "draft", "agent_status": "prepared", "token_budget": 500},
                    }
                ],
            )

            result = execute_workflow(storage, workflow["path"], input_assets=[plan_path], execute_agents=False)

            self.assertEqual(result["status"], "running")
            self.assertEqual(result["blocked"]["status"], "prepared")
            self.assertEqual(len(result["agent_runs"]), 1)
            self.assertEqual(list_agent_runs(storage)[0]["status"], "prepared")
            self.assertEqual(list_node_runs(storage, run_id=result["run_id"])[0]["status"], "prepared")

    def test_resume_executes_prepared_agent_and_continues_downstream(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(title="Plan", content={"chapter": 1, "objective": "open", "beats": ["beat"], "hook": "hook"}),
            )
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Draft",
                    source=storage.read_asset(plan_path).id,
                    content={"chapter": 1, "text": "原创测试章节。", "copyright_boundary": "unit test"},
                    references=[storage.read_asset(plan_path).id, str(plan_path.relative_to(storage.root))],
                ),
            )
            workflow = create_workflow_definition(
                storage,
                name="Agent Resume",
                entry_node_id="draft-agent",
                nodes=[
                    {
                        "node_id": "draft-agent",
                        "node_type": "agent",
                        "operation": "draft",
                        "input_types": ["chapter_plan"],
                        "output_types": ["draft_chapter"],
                        "processor": {"kind": "agent", "agent_key": "draft", "agent_status": "prepared", "token_budget": 500},
                    },
                    {
                        "node_id": "review",
                        "node_type": "review",
                        "operation": "review",
                        "depends_on": ["draft-agent"],
                        "input_types": ["draft_chapter"],
                        "output_types": ["draft_chapter"],
                        "processor": {"kind": "deterministic", "expected_output_assets": [str(draft_path.relative_to(storage.root))]},
                    },
                ],
            )
            initial = execute_workflow(storage, workflow["path"], input_assets=[plan_path], execute_agents=False)
            self.assertEqual(initial["status"], "running")

            resumed = resume_workflow(
                storage,
                initial["workflow_run"]["path"],
                output_assets=[draft_path],
                token_used=120,
                cost_estimate=0.42,
                checkpoint={"status": "draft_completed", "chapter": 1},
            )

            self.assertEqual(resumed["status"], "completed")
            self.assertEqual(resumed["resume_node_id"], "draft-agent")
            self.assertEqual(storage.read_asset(resumed["workflow_run"]["path"]).content["lineage"]["resumed_from_run_id"], initial["run_id"])
            self.assertEqual(storage.read_asset(initial["workflow_run"]["path"]).content["status"], "superseded")
            resume_node_runs = list_node_runs(storage, run_id=resumed["run_id"])
            self.assertEqual([row["node_id"] for row in reversed(resume_node_runs)], ["draft-agent", "review"])
            agent_run = storage.read_asset(resumed["agent_runs"][0]["path"])
            self.assertEqual(agent_run.content["status"], "succeeded")
            self.assertEqual(agent_run.content["token_used"], 120)
            run_types = _run_asset_types(storage)
            self.assertIn("agent_budget", run_types)
            self.assertIn("agent_checkpoint", run_types)
            self.assertIn("agent_sla_report", run_types)
            self.assertIn("model_call_log", run_types)
            self.assertIn("cost_ledger", run_types)
            self.assertIn("trace_span", run_types)

    def test_resume_blocks_when_agent_budget_is_exceeded(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(title="Plan", content={"chapter": 1, "objective": "open", "beats": ["beat"], "hook": "hook"}),
            )
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(title="Draft", content={"chapter": 1, "text": "原创测试章节。", "copyright_boundary": "unit test"}),
            )
            workflow = create_workflow_definition(
                storage,
                name="Agent Budget Block",
                entry_node_id="draft-agent",
                nodes=[
                    {
                        "node_id": "draft-agent",
                        "node_type": "agent",
                        "operation": "draft",
                        "input_types": ["chapter_plan"],
                        "output_types": ["draft_chapter"],
                        "processor": {"kind": "agent", "agent_key": "draft", "agent_status": "prepared", "token_budget": 5},
                    }
                ],
            )
            initial = execute_workflow(storage, workflow["path"], input_assets=[plan_path], execute_agents=False)

            resumed = resume_workflow(storage, initial["workflow_run"]["path"], output_assets=[draft_path], token_used=50)

            self.assertEqual(resumed["status"], "failed")
            self.assertEqual(resumed["blocked"]["node_id"], "draft-agent")
            agent_runs = list_agent_runs(storage)
            self.assertEqual(agent_runs[0]["status"], "failed")
            run_types = _run_asset_types(storage)
            self.assertIn("agent_budget", run_types)
            self.assertIn("agent_gate", run_types)
            self.assertIn("agent_failure_report", run_types)
            resume_node_runs = list_node_runs(storage, run_id=resumed["run_id"])
            self.assertEqual(resume_node_runs[0]["status"], "failed")

    def test_resume_blocks_when_budget_policy_is_exceeded(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(title="Plan", content={"chapter": 1, "objective": "open", "beats": ["beat"], "hook": "hook"}),
            )
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(title="Draft", content={"chapter": 1, "text": "原创测试章节。", "copyright_boundary": "unit test"}),
            )
            create_budget_policy(storage, scope="local-system", limits={"max_cost": 0.1, "max_tokens_per_run": 1000}, project_id="local-system")
            workflow = create_workflow_definition(
                storage,
                name="Agent Budget Policy Block",
                entry_node_id="draft-agent",
                nodes=[
                    {
                        "node_id": "draft-agent",
                        "node_type": "agent",
                        "operation": "draft",
                        "input_types": ["chapter_plan"],
                        "output_types": ["draft_chapter"],
                        "processor": {"kind": "agent", "agent_key": "draft", "agent_status": "prepared", "token_budget": 500},
                    }
                ],
            )
            initial = execute_workflow(storage, workflow["path"], input_assets=[plan_path], execute_agents=False)

            resumed = resume_workflow(storage, initial["workflow_run"]["path"], output_assets=[draft_path], token_used=50, cost_estimate=0.42)

            self.assertEqual(resumed["status"], "failed")
            run_types = _run_asset_types(storage)
            self.assertIn("budget_policy", run_types)
            self.assertIn("cost_alert", run_types)
            self.assertIn("agent_failure_report", run_types)

    def test_resume_blocks_when_provider_runtime_guard_cuts_off_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(title="Plan", content={"chapter": 1, "objective": "open", "beats": ["beat"], "hook": "hook"}),
            )
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(title="Draft", content={"chapter": 1, "text": "原创测试章节。", "copyright_boundary": "unit test"}),
            )
            workflow = create_workflow_definition(
                storage,
                name="Provider Guard Block",
                entry_node_id="draft-agent",
                nodes=[
                    {
                        "node_id": "draft-agent",
                        "node_type": "agent",
                        "operation": "draft",
                        "input_types": ["chapter_plan"],
                        "output_types": ["draft_chapter"],
                        "processor": {"kind": "agent", "agent_key": "draft", "agent_status": "prepared", "token_budget": 500},
                    }
                ],
            )
            initial = execute_workflow(storage, workflow["path"], input_assets=[plan_path], execute_agents=False)

            resumed = resume_workflow(
                storage,
                initial["workflow_run"]["path"],
                output_assets=[draft_path],
                token_used=120,
                evidence={
                    "provider_runtime_guard": {"max_tokens": 50},
                    "provider_usage": {"total_tokens": 120, "elapsed_ms": 25},
                },
            )

            self.assertEqual(resumed["status"], "failed")
            self.assertEqual(resumed["blocked"]["node_id"], "draft-agent")
            self.assertIn("provider token cutoff exceeded", resumed["errors"][0])
            self.assertEqual(list_agent_runs(storage)[0]["status"], "failed")
            run_types = _run_asset_types(storage)
            self.assertIn("agent_gate", run_types)
            self.assertIn("agent_failure_report", run_types)
            self.assertIn("model_call_log", run_types)
            self.assertIn("trace_span", run_types)
            model_call = _run_assets_by_type(storage, "model_call_log")[0]
            self.assertEqual(model_call["content"]["status"], "failed")
            self.assertEqual(model_call["content"]["usage"]["total_tokens"], 120)

    def test_pause_retry_and_cancel_workflow_run_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            source_path = storage.write_asset(
                "raw",
                SourceDocument(
                    title="Raw",
                    source="fixture",
                    content={"text": "fixture"},
                    metadata={"rights": {"authorization": "test_fixture", "copyright_boundary": "fixture"}},
                ),
            )
            cleaned_path = storage.write_asset("cleaned", CleanedText(title="Cleaned", content={"text": "clean"}))
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(title="Draft", content={"chapter": 1, "text": "原创测试章节。", "copyright_boundary": "unit test"}),
            )
            workflow = create_workflow_definition(
                storage,
                name="Workflow Controls",
                entry_node_id="clean",
                nodes=[
                    {
                        "node_id": "clean",
                        "node_type": "cleaning",
                        "operation": "clean",
                        "input_types": ["source_document"],
                        "output_types": ["cleaned_text"],
                        "processor": {"kind": "deterministic", "expected_output_assets": [str(cleaned_path.relative_to(storage.root))]},
                    },
                    {
                        "node_id": "draft",
                        "node_type": "draft",
                        "operation": "draft",
                        "depends_on": ["clean"],
                        "input_types": ["cleaned_text"],
                        "output_types": ["draft_chapter"],
                        "processor": {"kind": "deterministic", "expected_output_assets": [str(draft_path.relative_to(storage.root))]},
                    },
                ],
            )
            initial = execute_workflow(storage, workflow["path"], input_assets=[source_path], max_nodes=1)
            self.assertEqual(initial["status"], "running")
            self.assertEqual(initial["blocked"]["status"], "paused")

            paused = pause_workflow_run(storage, initial["workflow_run"]["path"], reason="operator hold")
            self.assertEqual(paused["asset"]["content"]["status"], "paused")
            self.assertEqual(paused["asset"]["content"]["control"]["action"], "pause")
            self.assertEqual(paused["asset"]["content"]["state_transitions"][-1]["action"], "pause")
            retried = retry_workflow_run(storage, paused["path"])
            self.assertEqual(retried["status"], "completed")
            superseded_run = storage.read_asset(paused["path"])
            self.assertEqual(superseded_run.content["status"], "superseded")
            self.assertEqual(superseded_run.content["state_transitions"][-1]["to"], "superseded")

            cancellable = execute_workflow(storage, workflow["path"], input_assets=[source_path], max_nodes=1)
            cancelled = cancel_workflow_run(storage, cancellable["workflow_run"]["path"], reason="operator cancel")
            self.assertEqual(cancelled["asset"]["content"]["status"], "cancelled")
            self.assertEqual(cancelled["asset"]["content"]["blocked"]["status"], "cancelled")

    def test_executor_can_apply_downstream_invalidation(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
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
            workflow = create_workflow_definition(
                storage,
                name="Invalidate",
                entry_node_id="invalidate",
                nodes=[
                    {
                        "node_id": "invalidate",
                        "node_type": "impact",
                        "operation": "invalidate-downstream",
                        "input_types": ["outline"],
                        "output_types": ["change_impact_report"],
                        "processor": {"kind": "invalidation", "max_depth": 2, "reason": "unit test upstream change"},
                    }
                ],
            )

            result = execute_workflow(storage, workflow["path"], input_assets=[outline_path], apply_invalidation=True)

            self.assertEqual(result["status"], "completed")
            self.assertEqual(storage.read_json(plan_path)["metadata"]["asset_status"], "stale")
            self.assertTrue(result["invalidations"][0]["updated_assets"])
            self.assertEqual(list_node_runs(storage, run_id=result["run_id"])[0]["status"], "succeeded")

    def test_configured_downstream_invalidation_runs_after_successful_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
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
            workflow = create_workflow_definition(
                storage,
                name="Configured Invalidation",
                entry_node_id="touch-outline",
                nodes=[
                    {
                        "node_id": "touch-outline",
                        "node_type": "outline",
                        "operation": "touch",
                        "input_types": ["outline"],
                        "output_types": ["outline"],
                        "processor": {
                            "kind": "deterministic",
                            "expected_output_assets": [str(outline_path.relative_to(storage.root))],
                            "downstream_invalidation": {"enabled": True, "target_mode": "inputs", "max_depth": 2, "reason": "configured test"},
                        },
                    }
                ],
            )

            result = execute_workflow(storage, workflow["path"], input_assets=[outline_path], apply_invalidation=True)

            self.assertEqual(result["status"], "completed")
            self.assertEqual(storage.read_json(plan_path)["metadata"]["asset_status"], "stale")
            self.assertTrue(result["invalidations"][0]["configured"])
            self.assertTrue(result["invalidations"][0]["updated_assets"])

    def test_resume_node_records_configured_downstream_invalidation(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
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
            workflow = create_workflow_definition(
                storage,
                name="Resume Configured Invalidation",
                entry_node_id="prepare",
                nodes=[
                    {
                        "node_id": "prepare",
                        "node_type": "outline",
                        "operation": "prepare",
                        "input_types": ["outline"],
                        "output_types": ["outline"],
                        "processor": {"kind": "deterministic", "expected_output_assets": [str(outline_path.relative_to(storage.root))]},
                    },
                    {
                        "node_id": "touch-outline",
                        "node_type": "outline",
                        "operation": "touch",
                        "depends_on": ["prepare"],
                        "input_types": ["outline"],
                        "output_types": ["outline"],
                        "processor": {
                            "kind": "deterministic",
                            "expected_output_assets": [str(outline_path.relative_to(storage.root))],
                            "downstream_invalidation": {"enabled": True, "target_mode": "inputs", "max_depth": 2, "reason": "resume configured test"},
                        },
                    },
                ],
            )

            initial = execute_workflow(storage, workflow["path"], input_assets=[outline_path], max_nodes=1)
            resumed = retry_workflow_run(storage, initial["workflow_run"]["path"])
            run_log = resumed["workflow_run"]["asset"]["content"]["run_log"]

            self.assertEqual(resumed["status"], "completed")
            self.assertEqual(storage.read_json(plan_path)["metadata"]["asset_status"], "stale")
            self.assertTrue(resumed["invalidations"][0]["configured"])
            self.assertTrue(run_log[-1]["change_impact_report_path"])

    def test_scheduler_tick_resumes_prepared_agent_and_supersedes_old_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(title="Plan", content={"chapter": 1, "objective": "open", "beats": ["beat"], "hook": "hook"}),
            )
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Draft",
                    source=storage.read_asset(plan_path).id,
                    content={"chapter": 1, "text": "原创测试章节。", "copyright_boundary": "unit test"},
                    references=[storage.read_asset(plan_path).id, str(plan_path.relative_to(storage.root))],
                ),
            )
            workflow = create_workflow_definition(
                storage,
                name="Scheduler Resume",
                entry_node_id="draft-agent",
                nodes=[
                    {
                        "node_id": "draft-agent",
                        "node_type": "agent",
                        "operation": "draft",
                        "input_types": ["chapter_plan"],
                        "output_types": ["draft_chapter"],
                        "processor": {
                            "kind": "agent",
                            "agent_key": "draft",
                            "agent_status": "prepared",
                            "token_budget": 500,
                            "expected_output_assets": [str(draft_path.relative_to(storage.root))],
                            "token_used": 120,
                            "cost_estimate": 0.42,
                        },
                    },
                    {
                        "node_id": "review",
                        "node_type": "review",
                        "operation": "review",
                        "depends_on": ["draft-agent"],
                        "input_types": ["draft_chapter"],
                        "output_types": ["draft_chapter"],
                        "processor": {"kind": "deterministic", "expected_output_assets": [str(draft_path.relative_to(storage.root))]},
                    },
                ],
            )
            initial = execute_workflow(storage, workflow["path"], input_assets=[plan_path], execute_agents=False)
            self.assertEqual(initial["status"], "running")

            tick = run_workflow_scheduler(storage)

            self.assertEqual(tick["status"], "completed")
            self.assertEqual(tick["candidate_count"], 1)
            self.assertEqual(tick["resumed_count"], 1)
            self.assertEqual(tick["error_count"], 0)
            old_run = storage.read_asset(initial["workflow_run"]["path"])
            self.assertEqual(old_run.content["status"], "superseded")
            self.assertEqual(old_run.metadata["asset_status"], "superseded")
            self.assertTrue(old_run.content["superseded_by_run_id"])
            resumed_path = tick["resumed"][0]["resume_workflow_run_path"]
            resumed_run = storage.read_asset(resumed_path)
            self.assertEqual(resumed_run.content["status"], "completed")
            self.assertEqual(resumed_run.content["lineage"]["resumed_from_run_id"], initial["run_id"])
            agent_run = storage.read_asset(tick["resumed"][0]["agent_run_path"])
            self.assertEqual(agent_run.content["status"], "succeeded")
            self.assertEqual(agent_run.content["token_used"], 120)
            queue_item = storage.read_asset(tick["resumed"][0]["ready_node_queue_path"])
            self.assertEqual(queue_item.content["status"], "acked")
            self.assertEqual(queue_item.content["attempt_count"], 1)
            self.assertEqual(queue_item.content["resume_workflow_run_path"], resumed_path)
            run_types = _run_asset_types(storage)
            self.assertIn("ready_node_queue", run_types)
            self.assertIn("agent_budget", run_types)
            self.assertIn("agent_checkpoint", run_types)
            self.assertIn("agent_sla_report", run_types)
            self.assertIn("cost_ledger", run_types)

    def test_scheduler_tick_records_checkpoint_when_outputs_are_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(title="Plan", content={"chapter": 1, "objective": "open", "beats": ["beat"], "hook": "hook"}),
            )
            workflow = create_workflow_definition(
                storage,
                name="Scheduler Missing Outputs",
                entry_node_id="draft-agent",
                nodes=[
                    {
                        "node_id": "draft-agent",
                        "node_type": "agent",
                        "operation": "draft",
                        "input_types": ["chapter_plan"],
                        "output_types": ["draft_chapter"],
                        "processor": {"kind": "agent", "agent_key": "draft", "agent_status": "prepared", "token_budget": 500},
                    }
                ],
            )
            initial = execute_workflow(storage, workflow["path"], input_assets=[plan_path], execute_agents=False)

            tick = run_workflow_scheduler(storage)

            self.assertEqual(tick["resumed_count"], 0)
            self.assertEqual(tick["skipped_count"], 1)
            self.assertEqual(tick["skipped"][0]["reason"], "missing_output_assets")
            self.assertIn("checkpoint_path", tick["skipped"][0])
            queue_item = storage.read_asset(tick["skipped"][0]["ready_node_queue_path"])
            self.assertEqual(queue_item.content["status"], "dead_letter")
            self.assertEqual(queue_item.content["last_error"], "missing_output_assets")
            self.assertEqual(queue_item.content["attempt_count"], 1)
            self.assertEqual(storage.read_asset(initial["workflow_run"]["path"]).content["status"], "running")
            self.assertEqual(list_agent_runs(storage)[0]["status"], "prepared")
            self.assertIn("agent_checkpoint", _run_asset_types(storage))
            self.assertEqual(len(_run_assets_by_type(storage, "ready_node_queue")), 1)

            second_tick = run_workflow_scheduler(storage)

            self.assertEqual(second_tick["resumed_count"], 0)
            self.assertEqual(second_tick["skipped_count"], 1)
            self.assertEqual(second_tick["skipped"][0]["reason"], "queue_claim_unavailable")
            self.assertEqual(second_tick["skipped"][0]["queue_status"], "dead_letter")
            self.assertEqual(len(_run_assets_by_type(storage, "ready_node_queue")), 1)

    def test_scheduler_tick_resumes_ready_non_agent_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            source_path = storage.write_asset(
                "raw",
                SourceDocument(
                    title="Raw",
                    source="fixture",
                    content={"text": "fixture"},
                    metadata={"rights": {"authorization": "test_fixture", "copyright_boundary": "fixture"}},
                ),
            )
            cleaned_path = storage.write_asset("cleaned", CleanedText(title="Cleaned", content={"text": "clean"}))
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(title="Draft", content={"chapter": 1, "text": "原创测试章节。", "copyright_boundary": "unit test"}),
            )
            workflow = create_workflow_definition(
                storage,
                name="Ready Node Scheduler",
                entry_node_id="clean",
                nodes=[
                    {
                        "node_id": "clean",
                        "node_type": "cleaning",
                        "operation": "clean",
                        "input_types": ["source_document"],
                        "output_types": ["cleaned_text"],
                        "processor": {"kind": "deterministic", "expected_output_assets": [str(cleaned_path.relative_to(storage.root))]},
                    },
                    {
                        "node_id": "draft",
                        "node_type": "draft",
                        "operation": "draft",
                        "depends_on": ["clean"],
                        "input_types": ["cleaned_text"],
                        "output_types": ["draft_chapter"],
                        "processor": {"kind": "deterministic", "expected_output_assets": [str(draft_path.relative_to(storage.root))]},
                    },
                ],
            )
            initial = execute_workflow(storage, workflow["path"], input_assets=[source_path], max_nodes=1)

            tick = run_workflow_scheduler(storage)

            self.assertEqual(tick["resumed_count"], 1)
            self.assertEqual(tick["resumed"][0]["candidate_type"], "ready_node")
            resumed = storage.read_asset(tick["resumed"][0]["resume_workflow_run_path"])
            self.assertEqual(resumed.content["status"], "completed")
            self.assertEqual(storage.read_asset(initial["workflow_run"]["path"]).content["status"], "superseded")
            queue_item = storage.read_asset(tick["resumed"][0]["ready_node_queue_path"])
            self.assertEqual(queue_item.content["status"], "acked")
            self.assertEqual(queue_item.content["attempt_count"], 1)

    def test_scheduler_dead_letters_workflow_governance_preflight_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            source_path = storage.write_asset(
                "raw",
                SourceDocument(
                    title="Raw",
                    source="fixture",
                    content={"text": "fixture"},
                    metadata={"rights": {"authorization": "test_fixture", "copyright_boundary": "fixture"}},
                ),
            )
            cleaned_path = storage.write_asset("cleaned", CleanedText(title="Cleaned", content={"text": "clean"}))
            workflow = create_workflow_definition(
                storage,
                name="Scheduler Drifted Chapter Workflow",
                entry_node_id="clean",
                nodes=[
                    {
                        "node_id": "clean",
                        "node_type": "cleaning",
                        "operation": "clean",
                        "input_types": ["source_document"],
                        "output_types": ["cleaned_text"],
                        "processor": {"kind": "deterministic", "expected_output_assets": [str(cleaned_path.relative_to(storage.root))]},
                    },
                    {
                        "node_id": "chapter-start",
                        "node_type": "production",
                        "operation": "start-chapter-production",
                        "depends_on": ["clean"],
                        "input_types": ["cleaned_text"],
                        "output_types": ["chapter_production_run"],
                        "processor": {"kind": "service", "operation": "start-chapter-production", "environment": "local"},
                    },
                ],
            )
            initial = execute_workflow(storage, workflow["path"], input_assets=[source_path], max_nodes=1)
            workflow_json_path = storage.root / workflow["path"]
            workflow_json = storage.read_json(workflow_json_path)
            workflow_json["content"]["nodes"][1]["processor"]["environment"] = "production"
            storage.write_json(workflow_json_path, workflow_json)

            tick = run_workflow_scheduler(storage)

            self.assertEqual(initial["status"], "running")
            self.assertEqual(tick["status"], "failed")
            self.assertEqual(tick["resumed_count"], 0)
            self.assertEqual(tick["error_count"], 1)
            self.assertIn("workflow governance drift", tick["errors"][0]["error"])
            queue_item = storage.read_asset(tick["errors"][0]["ready_node_queue_path"])
            self.assertEqual(queue_item.content["status"], "dead_letter")
            self.assertEqual(queue_item.content["attempt_count"], 1)
            self.assertIn("workflow_governance_preflight", queue_item.content["dead_letter_evidence"])
            self.assertTrue(queue_item.content["dead_letter_evidence"]["workflow_governance_preflight"]["gate_result_path"])
            console = build_workflow_runtime_console(storage, workflow_run_path_or_id=tick["errors"][0]["resume_workflow_run_path"])
            self.assertEqual(console["workflow_governance_preflight"]["status"], "failed")
            self.assertEqual(console["workflow_governance_preflight"]["gate_status"], "failed")
            self.assertTrue(console["workflow_governance_preflight"]["gate_result_path"])
            self.assertEqual(console["governance_dead_letters"][0]["status"], "dead_letter")
            self.assertEqual(console["governance_dead_letters"][0]["ready_node_queue_path"], tick["errors"][0]["ready_node_queue_path"])
            self.assertTrue(console["governance_dead_letters"][0]["drift_report_path"])

    def test_scheduler_loop_respects_active_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            lease = acquire_scheduler_lease(storage, owner="worker-a", ttl_seconds=300)
            self.assertTrue(lease["acquired"])
            lease_asset = storage.read_json(storage.root / lease["lease"]["path"])
            self.assertEqual(lease_asset["metadata"]["project_id"], "local-system")
            self.assertEqual(lease_asset["metadata"]["scope_kind"], "system")

            loop = run_workflow_scheduler_loop(storage, iterations=1, interval_seconds=0, lease_owner="worker-b")

            self.assertEqual(loop["status"], "skipped")
            self.assertEqual(loop["recommendation"], "scheduler_lease_active")
            status = scheduler_lease_status(storage)
            self.assertEqual(status["owner"], "worker-a")
            self.assertEqual(status["status"], "active")

    def test_service_processor_registry_runs_module_completion_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workflow = create_workflow_definition(
                storage,
                name="Service Registry",
                entry_node_id="snapshot",
                nodes=[
                    {
                        "node_id": "snapshot",
                        "node_type": "metric",
                        "operation": "module_completion_snapshot",
                        "output_types": ["project_metric_snapshot"],
                        "processor": {"kind": "service"},
                    }
                ],
            )
            self.assertEqual(workflow["asset"]["metadata"]["project_id"], "local-system")
            self.assertEqual(workflow["asset"]["metadata"]["scope_kind"], "system")

            result = execute_workflow(storage, workflow["path"])

            self.assertEqual(result["status"], "completed")
            self.assertEqual(storage.read_asset(result["workflow_run"]["asset"]["content"]["outputs"][0]).type, "project_metric_snapshot")
            node_run = list_node_runs(storage, run_id=result["run_id"])[0]
            processor = storage.read_asset(node_run["path"]).content["processor"]
            self.assertEqual(processor["registry_operation"], "module_completion_snapshot")

    def test_service_processor_resumes_from_checkpoint_when_outputs_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            output_path = storage.write_asset(
                "drafts",
                DraftChapter(title="Recovered Draft", content={"chapter": 1, "text": "已存在输出。", "copyright_boundary": "unit test"}),
            )
            workflow = create_workflow_definition(
                storage,
                name="Checkpoint Resume",
                entry_node_id="recover",
                nodes=[
                    {
                        "node_id": "recover",
                        "node_type": "service",
                        "operation": "unknown_service_that_should_not_run",
                        "output_types": ["draft_chapter"],
                        "processor": {
                            "kind": "service",
                            "resume_from_checkpoint": True,
                            "expected_output_assets": [str(output_path.relative_to(storage.root))],
                            "checkpoint_schema": {"version": "0.1.0", "state": "output_exists"},
                        },
                    }
                ],
            )

            result = execute_workflow(storage, workflow["path"])

            self.assertEqual(result["status"], "completed")
            node_run = storage.read_asset(list_node_runs(storage, run_id=result["run_id"])[0]["path"])
            self.assertEqual(node_run.content["status"], "recovered")
            self.assertTrue(node_run.content["processor"]["resumed_from_checkpoint"])

    def test_service_processor_resumes_from_operation_checkpoint_node_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workflow = create_workflow_definition(
                storage,
                name="Operation Checkpoint",
                entry_node_id="snapshot",
                nodes=[
                    {
                        "node_id": "snapshot",
                        "node_type": "metric",
                        "operation": "module_completion_snapshot",
                        "output_types": ["project_metric_snapshot"],
                        "processor": {"kind": "service", "resume_from_checkpoint": True},
                    }
                ],
            )

            first = execute_workflow(storage, workflow["path"])
            second = execute_workflow(storage, workflow["path"])

            self.assertEqual(first["status"], "completed")
            self.assertEqual(second["status"], "completed")
            second_node = storage.read_asset(list_node_runs(storage, run_id=second["run_id"])[0]["path"])
            self.assertEqual(second_node.content["status"], "recovered")
            self.assertEqual(second_node.content["processor"]["checkpoint"]["contract"]["operation"], "module_completion_snapshot")

    def test_service_processor_starts_chapter_production_with_runtime_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            fixture = _chapter_production_fixture(storage, project_title="Workflow Chapter Start")
            source_policy = _workflow_source_policy()
            workflow = create_v1_chapter_production_workflow_template(
                storage,
                name="Workflow Chapter Production Start",
                chapter=1,
                run_to="outline_checkpoint",
                environment="production",
                workspace_path=fixture["workspace_path"],
                os_envelope=production_envelope(
                    fixture["project_id"],
                    "chapter_production_run",
                    trace_id=f"trace-workflow-chapter-start-{fixture['project_id']}",
                    source_policy=source_policy,
                ),
                source_policy=source_policy,
                provider_runtime_guard=_passed_provider_runtime_gate(),
                require_external_provider_proof=True,
            )

            result = execute_workflow(storage, workflow["path"], input_assets=[fixture["outline_path"]])
            output_path = result["workflow_run"]["asset"]["content"]["outputs"][0]
            chapter_run = storage.read_json(storage.root / output_path)
            node_run = storage.read_asset(list_node_runs(storage, run_id=result["run_id"])[0]["path"])
            policy = chapter_run["content"]["quality_loop_policy"]

            self.assertEqual(result["status"], "completed")
            self.assertEqual(chapter_run["type"], "chapter_production_run")
            self.assertEqual(chapter_run["content"]["current_step"], "outline_checkpoint")
            self.assertEqual(node_run.content["processor"]["registry_operation"], "chapter_production_start")
            self.assertEqual(policy["environment"], "production")
            self.assertEqual(policy["source_policy"]["source_isolation_required"], True)
            self.assertEqual(policy["os_envelope"]["asset_type"], "chapter_production_run")
            self.assertEqual(policy["require_external_provider_proof"], True)

    def test_service_processor_resumes_chapter_production(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            fixture = _chapter_production_fixture(storage, project_title="Workflow Chapter Resume")
            planned = start_chapter_production(
                storage,
                outline_path=fixture["outline_path"],
                workspace_path=fixture["workspace_path"],
                chapter=1,
                run_to="outline_checkpoint",
                execute=False,
                task_status_mode="compact",
            )
            workflow = create_workflow_definition(
                storage,
                name="Workflow Chapter Production Resume",
                entry_node_id="chapter-resume",
                nodes=[
                    {
                        "node_id": "chapter-resume",
                        "node_type": "production",
                        "operation": "resume-chapter-production",
                        "input_types": ["chapter_production_run"],
                        "output_types": ["chapter_production_run"],
                        "processor": {"kind": "service", "operation": "resume-chapter-production", "run_to": "outline_checkpoint"},
                    }
                ],
            )

            result = execute_workflow(storage, workflow["path"], input_assets=[planned["path"]])
            chapter_run = storage.read_json(storage.root / result["workflow_run"]["asset"]["content"]["outputs"][0])
            node_run = storage.read_asset(list_node_runs(storage, run_id=result["run_id"])[0]["path"])

            self.assertEqual(result["status"], "completed")
            self.assertEqual(chapter_run["type"], "chapter_production_run")
            self.assertEqual(chapter_run["content"]["status"], "succeeded")
            self.assertEqual(chapter_run["content"]["current_step"], "outline_checkpoint")
            self.assertEqual(node_run.content["processor"]["registry_operation"], "chapter_production_resume")

    def test_service_processor_blocks_production_chapter_without_governance_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            fixture = _chapter_production_fixture(storage, project_title="Workflow Chapter Block")
            workflow = create_workflow_definition(
                storage,
                name="Workflow Chapter Production Block",
                entry_node_id="chapter-start",
                nodes=[
                    {
                        "node_id": "chapter-start",
                        "node_type": "production",
                        "operation": "start-chapter-production",
                        "input_types": ["outline"],
                        "output_types": ["chapter_production_run"],
                        "processor": {"kind": "service", "operation": "start-chapter-production", "environment": "production", "run_to": "outline_checkpoint"},
                    }
                ],
            )

            result = execute_workflow(storage, workflow["path"], input_assets=[fixture["outline_path"]])
            run_content = result["workflow_run"]["asset"]["content"]
            preflight = run_content["lineage"]["workflow_governance_preflight"]

            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["node_runs"], [])
            self.assertEqual(result["blocked"]["gate_kind"], "workflow_governance_drift")
            self.assertEqual(preflight["status"], "failed")
            self.assertIn("workflow governance drift", result["errors"][0])
            self.assertTrue(preflight["gate_result_path"])
            self.assertTrue(preflight["drift_report_path"])

    def test_v1_chapter_production_workflow_template_creates_governed_definition(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            fixture = _chapter_production_fixture(storage, project_title="Workflow Template Project")
            source_policy = _workflow_source_policy()
            workflow = create_v1_chapter_production_workflow_template(
                storage,
                name="Template Fixture",
                chapter=1,
                run_to="outline_checkpoint",
                environment="production",
                workspace_path=fixture["workspace_path"],
                os_envelope=production_envelope(
                    fixture["project_id"],
                    "chapter_production_run",
                    trace_id=f"trace-workflow-template-{fixture['project_id']}",
                    source_policy=source_policy,
                ),
                source_policy=source_policy,
                provider_runtime_guard=_passed_provider_runtime_gate(),
                require_external_provider_proof=True,
            )
            workflow_asset = storage.read_json(storage.root / workflow["path"])
            template_contract = workflow_asset["content"]["template_contract"]
            node = workflow_asset["content"]["nodes"][0]

            self.assertEqual(template_contract["contract"], "v1-chapter-production-workflow-template-v1")
            self.assertEqual(template_contract["canonical_runtime"], "chapter_production_bus")
            self.assertFalse(template_contract["chapter_acceptance_executed"])
            self.assertEqual(node["processor"]["operation"], "start-chapter-production")
            self.assertEqual(node["processor"]["source_policy"]["workflow_policy_marker"], "chapter-production-processor")

            queue = build_ready_node_queue(storage, workflow_path_or_id=workflow["path"], input_assets=[fixture["outline_path"]])
            console = build_workflow_runtime_console(storage, workflow_path_or_id=workflow["path"], input_assets=[fixture["outline_path"]])
            self.assertEqual(queue["workflow_template_contract"]["contract"], "v1-chapter-production-workflow-template-v1")
            self.assertFalse(queue["workflow_template_contract"]["production_fail_closed"])
            self.assertEqual(console["workflow_template_contract"]["canonical_runtime"], "chapter_production_bus")
            self.assertFalse(console["workflow_template_contract"]["chapter_acceptance_executed"])
            self.assertEqual(console["ready_queue"]["queue"][0]["template_contract"]["processor_operation"], "start-chapter-production")
            self.assertFalse(console["ready_queue"]["queue"][0]["template_contract"]["production_fail_closed"])

            result = execute_workflow(storage, workflow["path"], input_assets=[fixture["outline_path"]])
            chapter_run = storage.read_json(storage.root / result["workflow_run"]["asset"]["content"]["outputs"][0])

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["preflight"]["status"], "passed")
            self.assertEqual(chapter_run["type"], "chapter_production_run")
            self.assertEqual(chapter_run["content"]["current_step"], "outline_checkpoint")
            lineage = result["workflow_run"]["asset"]["content"]["lineage"]["workflow_governance_preflight"]
            self.assertEqual(lineage["gate_status"], "passed")
            self.assertTrue(lineage["gate_result_path"])
            self.assertTrue(lineage["drift_report_path"])

    def test_v1_chapter_production_workflow_console_marks_missing_production_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            fixture = _chapter_production_fixture(storage, project_title="Workflow Template Missing Evidence")
            workflow = create_v1_chapter_production_workflow_template(
                storage,
                name="Template Missing Evidence Fixture",
                chapter=1,
                run_to="outline_checkpoint",
                environment="production",
                workspace_path=fixture["workspace_path"],
            )

            console = build_workflow_runtime_console(storage, workflow_path_or_id=workflow["path"], input_assets=[fixture["outline_path"]])
            queue = build_ready_node_queue(storage, workflow_path_or_id=workflow["path"], input_assets=[fixture["outline_path"]])
            missing = set(console["workflow_template_contract"]["missing_runtime_evidence"])
            row_missing = set(queue["queue"][0]["template_contract"]["missing_runtime_evidence"])

            self.assertEqual(console["workflow_template_contract"]["contract"], "v1-chapter-production-workflow-template-v1")
            self.assertTrue(console["workflow_template_contract"]["production_fail_closed"])
            self.assertEqual(missing, {"os_envelope", "source_policy", "provider_runtime_guard"})
            self.assertEqual(row_missing, {"os_envelope", "source_policy", "provider_runtime_guard"})
            self.assertTrue(queue["queue"][0]["template_contract"]["production_fail_closed"])
            self.assertEqual(queue["ready_count"], 1)

    def test_workflow_governance_drift_gate_passes_clean_canonical_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            fixture = _chapter_production_fixture(storage, project_title="Workflow Governance Clean")
            source_policy = _workflow_source_policy()
            workflow = create_v1_chapter_production_workflow_template(
                storage,
                name="Workflow Governance Clean Fixture",
                chapter=1,
                run_to="outline_checkpoint",
                environment="production",
                workspace_path=fixture["workspace_path"],
                os_envelope=production_envelope(
                    fixture["project_id"],
                    "chapter_production_run",
                    trace_id=f"trace-workflow-governance-{fixture['project_id']}",
                    source_policy=source_policy,
                ),
                source_policy=source_policy,
                provider_runtime_guard=_passed_provider_runtime_gate(),
            )

            gate = run_workflow_governance_drift_gate(
                storage,
                workflow_path_or_id=workflow["path"],
                environment="production",
            )

            self.assertEqual(gate["status"], "passed")
            self.assertFalse(gate["blocking"])
            self.assertEqual(gate["drift_report"]["summary"]["drift_count"], 0)
            self.assertEqual(gate["gate_result"]["asset"]["content"]["status"], "passed")
            self.assertFalse(gate["drift_report"]["asset"]["content"]["chapter_acceptance_executed"])

    def test_workflow_governance_drift_gate_blocks_drifted_workflow_in_production(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            fixture = _chapter_production_fixture(storage, project_title="Workflow Governance Drifted")
            workflow = create_workflow_definition(
                storage,
                name="Drifted Chapter Workflow",
                entry_node_id="chapter-production-start",
                nodes=[
                    {
                        "node_id": "chapter-production-start",
                        "node_type": "production",
                        "operation": "start-chapter-production",
                        "input_types": ["outline"],
                        "output_types": ["chapter_production_run"],
                        "processor": {"kind": "service", "operation": "start-chapter-production", "environment": "production"},
                    }
                ],
            )

            report = build_workflow_governance_drift_report(storage, workflow_path_or_id=workflow["path"], persist=False)
            gate = run_workflow_governance_drift_gate(
                storage,
                workflow_path_or_id=workflow["path"],
                environment="production",
            )
            drift_codes = {row["code"] for row in gate["drift_report"]["asset"]["content"]["drift_rows"]}

            self.assertGreater(report["summary"]["drift_count"], 0)
            self.assertEqual(gate["status"], "failed")
            self.assertTrue(gate["blocking"])
            self.assertIn("missing_template_contract", drift_codes)
            self.assertIn("missing_production_runtime_evidence", drift_codes)
            self.assertEqual(gate["gate_result"]["asset"]["content"]["status"], "failed")
            self.assertIn(workflow["path"], gate["gate_result"]["asset"]["content"]["target_paths"])
            self.assertFalse(gate["drift_report"]["asset"]["content"]["chapter_acceptance_executed"])
            self.assertTrue(fixture["outline_path"])

    def test_workflow_governance_drift_gate_warns_for_local_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workflow = create_workflow_definition(
                storage,
                name="Local Drifted Workflow",
                entry_node_id="chapter-production-start",
                nodes=[
                    {
                        "node_id": "chapter-production-start",
                        "node_type": "production",
                        "operation": "start-chapter-production",
                        "input_types": ["outline"],
                        "output_types": ["chapter_production_run"],
                        "processor": {"kind": "service", "operation": "start-chapter-production", "environment": "local"},
                    }
                ],
            )

            gate = run_workflow_governance_drift_gate(storage, workflow_path_or_id=workflow["path"], environment="local")

            self.assertEqual(gate["status"], "warning")
            self.assertFalse(gate["blocking"])
            self.assertGreater(gate["drift_report"]["summary"]["blocking_drift_count"], 0)

    def test_execute_workflow_blocks_drifted_production_definition_before_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            fixture = _chapter_production_fixture(storage, project_title="Workflow Execute Drifted")
            workflow = create_workflow_definition(
                storage,
                name="Execute Drifted Chapter Workflow",
                entry_node_id="chapter-production-start",
                nodes=[
                    {
                        "node_id": "chapter-production-start",
                        "node_type": "production",
                        "operation": "start-chapter-production",
                        "input_types": ["outline"],
                        "output_types": ["chapter_production_run"],
                        "processor": {"kind": "service", "operation": "start-chapter-production", "environment": "production"},
                    }
                ],
            )

            result = execute_workflow(storage, workflow["path"], input_assets=[fixture["outline_path"]])
            run_content = result["workflow_run"]["asset"]["content"]
            preflight = run_content["lineage"]["workflow_governance_preflight"]

            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["node_runs"], [])
            self.assertEqual(result["blocked"]["gate_kind"], "workflow_governance_drift")
            self.assertEqual(preflight["status"], "failed")
            self.assertTrue(preflight["gate_result_path"])
            self.assertTrue(preflight["drift_report_path"])
            self.assertEqual(run_content["node_runs"], [])
            gate = storage.read_asset(preflight["gate_result_path"])
            self.assertEqual(gate.type, "gate_result")
            self.assertEqual(gate.content["status"], "failed")

            resumed = resume_workflow(storage, result["workflow_run"]["path"])
            resumed_preflight = resumed["workflow_run"]["asset"]["content"]["lineage"]["workflow_governance_preflight"]
            self.assertEqual(resumed["status"], "failed")
            self.assertEqual(resumed["node_runs"], [])
            self.assertEqual(resumed["blocked"]["gate_kind"], "workflow_governance_drift")
            self.assertEqual(resumed_preflight["status"], "failed")

    def test_gate_registry_schema_gate_blocks_invalid_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            invalid_path = storage.data_dir("raw") / "invalid-source.json"
            storage.write_json(invalid_path, {"type": "source_document", "id": "invalid-source", "content": {}})
            workflow = create_workflow_definition(
                storage,
                name="Schema Gate Registry",
                entry_node_id="schema",
                nodes=[
                    {
                        "node_id": "schema",
                        "node_type": "quality",
                        "operation": "schema",
                        "processor": {"kind": "deterministic"},
                        "quality_gate": {"required": True, "kind": "schema"},
                    }
                ],
            )

            result = execute_workflow(storage, workflow["path"], input_assets=[invalid_path])

            self.assertEqual(result["status"], "failed")
            self.assertIn("gate_result", _run_asset_types(storage))
            node_run = storage.read_asset(list_node_runs(storage, run_id=result["run_id"])[0]["path"])
            self.assertEqual(node_run.content["status"], "failed")
            self.assertIn("registry_results", node_run.content["quality_gate"])

    def test_gate_registry_novel_kg_gate_blocks_graph_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "workflow-kg-block"
            workspace_path = "data/workspaces/workflow-kg-block.json"
            metadata = {"project_id": project_id, "workspace_path": workspace_path}
            storage.write_asset(
                "worlds",
                WorldBible(
                    title="KG world",
                    content={"factions": [{"name": "Shadow Court", "goal": "control the archive"}]},
                    metadata=metadata,
                ),
            )
            storage.write_asset(
                "characters",
                CharacterCard(
                    title="Shadow Court",
                    content={"name": "Shadow Court", "role": "protagonist"},
                    metadata=metadata,
                ),
            )
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="KG blocked plan",
                    content={"chapter": 1, "objective": "Shadow Court enters the archive", "beats": ["open"], "hook": "archive opens"},
                    metadata=metadata,
                ),
            )
            workflow = create_workflow_definition(
                storage,
                name="Novel KG Gate",
                entry_node_id="kg-gate",
                nodes=[
                    {
                        "node_id": "kg-gate",
                        "node_type": "quality",
                        "operation": "novel_kg_gate",
                        "input_assets": [str(plan_path.relative_to(storage.root))],
                        "processor": {"kind": "deterministic"},
                        "quality_gate": {
                            "required": True,
                            "gates": [
                                {
                                    "kind": "novel_kg",
                                    "required": True,
                                    "blocking": True,
                                    "project_id": project_id,
                                    "workspace_path": workspace_path,
                                }
                            ],
                        },
                    }
                ],
            )

            result = execute_workflow(storage, workflow["path"])

            self.assertEqual(result["status"], "failed")
            node_run = storage.read_asset(list_node_runs(storage, run_id=result["run_id"])[0]["path"])
            self.assertEqual(node_run.content["status"], "failed")
            registry = node_run.content["quality_gate"]["registry_results"]
            self.assertEqual(registry[0]["kind"], "novel_kg")
            self.assertEqual(registry[0]["status"], "failed")
            gate_results = _run_assets_by_type(storage, "gate_result")
            self.assertTrue(any(item["content"]["gate_kind"] == "novel_kg" and item["content"]["status"] == "failed" for item in gate_results))

    def test_post_gate_blocks_invalid_output_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            invalid_output = storage.data_dir("cleaned") / "invalid-cleaned.json"
            storage.write_json(invalid_output, {"type": "cleaned_text", "id": "invalid-cleaned", "content": {}})
            workflow = create_workflow_definition(
                storage,
                name="Post Gate",
                entry_node_id="post-schema",
                nodes=[
                    {
                        "node_id": "post-schema",
                        "node_type": "quality",
                        "operation": "post-schema",
                        "output_types": ["cleaned_text"],
                        "processor": {"kind": "deterministic", "expected_output_assets": [str(invalid_output.relative_to(storage.root))]},
                        "quality_gate": {"post_gates": [{"kind": "schema", "required": True, "phase": "post"}]},
                    }
                ],
            )

            result = execute_workflow(storage, workflow["path"])

            self.assertEqual(result["status"], "failed")
            node_run = storage.read_asset(list_node_runs(storage, run_id=result["run_id"])[0]["path"])
            self.assertEqual(node_run.content["status"], "failed")
            self.assertIn("post_gate", node_run.content["processor"])
            rollback = node_run.content["processor"]["rollback"]
            self.assertEqual(rollback["asset"]["type"], "processor_rollback")
            self.assertEqual(rollback["asset"]["content"]["status"], "applied")
            self.assertEqual(storage.read_json(invalid_output)["metadata"]["asset_status"], "quarantined")
            run_types = _run_asset_types(storage)
            self.assertIn("processor_rollback", run_types)
            self.assertIn("workflow_output_quarantine", run_types)

    def test_runtime_guard_blocks_expired_deadline_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            output_path = storage.data_dir("cleaned") / "should-not-matter.json"
            workflow = create_workflow_definition(
                storage,
                name="Runtime Guard",
                entry_node_id="guarded",
                nodes=[
                    {
                        "node_id": "guarded",
                        "node_type": "quality",
                        "operation": "guarded",
                        "output_types": ["cleaned_text"],
                        "processor": {
                            "kind": "deterministic",
                            "expected_output_assets": [str(output_path.relative_to(storage.root))],
                            "runtime_guard": {"enabled": True, "deadline_at": "2000-01-01T00:00:00Z"},
                        },
                    }
                ],
            )

            result = execute_workflow(storage, workflow["path"])

            self.assertEqual(result["status"], "failed")
            node_run = storage.read_asset(list_node_runs(storage, run_id=result["run_id"])[0]["path"])
            self.assertEqual(node_run.content["status"], "failed")
            self.assertIn("runtime_guard", node_run.content["processor"])

    def test_scheduler_loop_records_task_status_and_worker_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            loop = run_workflow_scheduler_loop(storage, iterations=2, interval_seconds=0, stop_when_idle=True)

            self.assertEqual(loop["status"], "completed")
            self.assertEqual(loop["tick_count"], 1)
            self.assertGreaterEqual(len(loop["task_status_paths"]), 3)
            task_statuses = _run_assets_by_type(storage, "task_status")
            self.assertIn("workflow-scheduler-loop", {item["content"]["step"] for item in task_statuses})
            self.assertIn("completed", {item["content"]["status"] for item in task_statuses})

            from novel_forge.workers.tasks import workflow_scheduler_loop_task

            worker = workflow_scheduler_loop_task(tmp, iterations=1, interval_seconds=0, request_id="scheduler-worker-test")
            self.assertEqual(worker["status"], "completed")
            self.assertTrue(worker["task_status_paths"])

    def test_service_processor_registry_runs_quality_originality_and_continuity_services(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(title="Plan", content={"chapter": 1, "objective": "open", "beats": ["beat"], "hook": "hook"}),
            )
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Draft",
                    source=storage.read_asset(plan_path).id,
                    content={"chapter": 1, "text": "林乔推开档案室的门，发现旧钟声和失踪名单有关。她决定先救人，再追查幕后。", "copyright_boundary": "unit test original draft"},
                    references=[storage.read_asset(plan_path).id, str(plan_path.relative_to(storage.root))],
                ),
            )
            workflow = create_workflow_definition(
                storage,
                name="Service Registry Gates",
                entry_node_id="preflight",
                nodes=[
                    {
                        "node_id": "preflight",
                        "node_type": "continuity",
                        "operation": "chapter_stability_preflight",
                        "input_assets": [str(plan_path.relative_to(storage.root))],
                        "output_types": ["chapter_continuity_report"],
                        "processor": {"kind": "service"},
                    },
                    {
                        "node_id": "quality",
                        "node_type": "quality",
                        "operation": "quality_score_report",
                        "depends_on": ["preflight"],
                        "input_assets": [str(draft_path.relative_to(storage.root))],
                        "output_types": ["quality_score_report"],
                        "processor": {"kind": "service"},
                    },
                    {
                        "node_id": "originality",
                        "node_type": "quality",
                        "operation": "originality_report",
                        "depends_on": ["quality"],
                        "input_assets": [str(draft_path.relative_to(storage.root))],
                        "output_types": ["originality_report"],
                        "processor": {"kind": "service"},
                    },
                ],
            )

            result = execute_workflow(storage, workflow["path"])

            self.assertEqual(result["status"], "completed")
            output_types = {storage.read_asset(path).type for path in result["workflow_run"]["asset"]["content"]["outputs"]}
            self.assertIn("chapter_continuity_report", output_types)
            self.assertIn("quality_score_report", output_types)
            self.assertIn("originality_report", output_types)
            registry_operations = [storage.read_asset(row["path"]).content["processor"]["registry_operation"] for row in list_node_runs(storage, run_id=result["run_id"])]
            self.assertIn("chapter_stability_preflight", registry_operations)
            self.assertIn("quality_score_report", registry_operations)
            self.assertIn("originality_report", registry_operations)

    def test_feedback_mutation_application_processor_executes_approved_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            outline_path = storage.write_asset(
                "outlines",
                Outline(title="Outline", content={"project_id": "p1", "volumes": [{"title": "V1"}]}, metadata={"project_id": "p1"}),
            )
            proposal = create_feedback_mutation_proposal(
                storage,
                source_feedback_paths=["data/feedback/comment-cluster.json"],
                target_assets=[{"asset_type": "outline", "path": str(outline_path.relative_to(storage.root))}],
                proposed_changes=[{"domain": "outline", "change": "tighten hook after reader dropoff"}],
            )
            resolved = resolve_feedback_mutation_proposal(
                storage,
                proposal_ref=proposal["path"],
                approved=True,
                actor="lead-editor",
                decision_note="approved for workflow test",
            )
            workflow = create_workflow_definition(
                storage,
                name="Feedback Mutation Application",
                entry_node_id="apply-feedback",
                nodes=[
                    {
                        "node_id": "apply-feedback",
                        "node_type": "feedback",
                        "operation": "feedback_mutation_application",
                        "output_types": ["feedback_mutation_application_report"],
                        "processor": {"kind": "service", "proposal_ref": resolved["path"], "apply_invalidation": False},
                    }
                ],
            )

            result = execute_workflow(storage, workflow["path"])

            self.assertEqual(result["status"], "completed")
            output_types = {storage.read_asset(path).type for path in result["workflow_run"]["asset"]["content"]["outputs"]}
            self.assertIn("feedback_mutation_application_report", output_types)
            reports = [storage.read_json(path) for path in storage.list_json("feedback") if storage.read_json(path).get("type") == "feedback_mutation_application_report"]
            self.assertEqual(reports[-1]["content"]["status"], "planned")
            self.assertTrue(reports[-1]["content"]["regeneration_tasks"])


def _run_asset_types(storage: LocalStorage) -> set[str]:
    types: set[str] = set()
    for path in storage.list_json("runs"):
        data = storage.read_json(path)
        if isinstance(data, dict):
            types.add(str(data.get("type", "")))
    return types


def _run_assets_by_type(storage: LocalStorage, asset_type: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in storage.list_json("runs"):
        data = storage.read_json(path)
        if isinstance(data, dict) and data.get("type") == asset_type:
            rows.append(data)
    return rows


def _chapter_production_fixture(storage: LocalStorage, *, project_title: str) -> dict[str, str]:
    workspace = init_workspace(storage, project_title)
    workspace_asset = storage.read_asset(workspace)
    project_id = workspace_asset.content["project_id"]
    workspace_ref = str(workspace.relative_to(storage.root))
    outline = storage.write_asset(
        "outlines",
        Outline(
            title=f"{project_title} Outline",
            content={"acts": [{"act": 1, "goal": "open with a governed workflow chapter"}]},
            metadata={"project_id": project_id, "workspace_path": workspace_ref},
            references=[workspace_ref],
        ),
    )
    return {
        "project_id": project_id,
        "workspace_path": workspace_ref,
        "outline_path": str(outline.relative_to(storage.root)),
    }


def _workflow_source_policy() -> dict[str, object]:
    return {
        "source_isolation_required": True,
        "raw_source_text_allowed": False,
        "generation_rag_allowed": False,
        "external_reference_mode": "evidence_only",
        "workflow_policy_marker": "chapter-production-processor",
    }


def _passed_provider_runtime_gate() -> dict[str, object]:
    return {
        "status": "passed",
        "blocking": False,
        "provider": "codex-fixture",
        "route": "approved-fixture-route",
        "summary": {
            "route_approved": True,
            "approval_ref": "unit-test-provider-runtime-approval",
            "mock_provider_test_mode": True,
        },
    }


if __name__ == "__main__":
    unittest.main()
