from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.agent_runs import list_agent_runs, record_agent_budget, record_agent_checkpoint, record_agent_gate, start_agent_run, update_agent_run_status
from novel_forge.modules.agent_scheduler import (
    agent_center_snapshot,
    dispatch_revision_task_from_issue,
    dispatch_agent_run,
    list_agent_dispatch_queue,
    list_agent_operation_contracts,
    recover_agent_dispatch,
    repair_dead_letter_dispatch,
    run_agent_scheduler_tick,
    scheduler_status,
)
from novel_forge.modules.agent_scheduler import service as agent_scheduler_service
from novel_forge.modules.agent_scheduler.dead_letter_runner import fail_queue_item
from novel_forge.modules.agent_scheduler.queue_lifecycle import claim_queue_item
from novel_forge.modules.continuity_graph import create_continuity_graph_snapshot
from novel_forge.modules.loop_kernel import run_loop
from novel_forge.modules.review_issue import create_review_issue
from novel_forge.modules.runtime_ledger import record_gate_result
from novel_forge.modules.workflow_nodes import create_workflow_definition, execute_workflow, list_node_runs
from novel_forge.schemas import ChapterPlan, ContextBundle, DraftChapter, PublishGateReport
from novel_forge.storage.local import LocalStorage
from novel_forge.storage.rag_context import generation_context_policy
from tests.unit.publishing_fixtures import create_production_ready_release_inputs, production_envelope


class AgentSchedulerTests(unittest.TestCase):
    def test_operation_contracts_cover_governed_post_mkaos_operations(self):
        contracts = {row["operation"]: row for row in list_agent_operation_contracts()}

        for operation in [
            "build-context-bundle",
            "check-canon-graph",
            "run-review-revision-publish-loop",
            "preview-provider-fallback",
            "approve-provider-fallback",
            "run-platform-adapter-gate",
            "resolve-feedback-mutation-proposal",
            "apply-feedback-mutation-application-chain",
        ]:
            self.assertIn(operation, contracts)
            self.assertEqual(contracts[operation]["runner_kind"], "local_service")
            self.assertTrue(contracts[operation]["required_tools"])

    def test_build_context_runner_propagates_selector_governance_binding_application_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(title="Scheduler context target", content={"chapter": 1, "objective": "build context", "beats": ["beat"], "hook": "hook"}, metadata={"project_id": "sched-binding"}),
            )
            agent_run = {
                "content": {
                    "evidence": {
                        "target_path": str(plan_path.relative_to(storage.root)),
                        "flow": "prose",
                        "project_id": "sched-binding",
                        "workspace_path": "data/workspaces/sched-binding.json",
                        "selector_governance_report_path": "data/runs/selector-report.json",
                        "selector_governance_binding_application_report_path": "data/runs/binding-application.json",
                    }
                },
                "metadata": {"project_id": "sched-binding", "workspace_path": "data/workspaces/sched-binding.json"},
            }

            with patch("novel_forge.modules.context_builder.build_flow_context_bundle", return_value={"path": "data/context/fake.json", "asset": {"content": {}}}) as mocked:
                result = agent_scheduler_service._run_build_context_bundle(storage, {}, agent_run)

            self.assertEqual(result["path"], "data/context/fake.json")
            kwargs = mocked.call_args.kwargs
            self.assertEqual(kwargs["selector_governance_report_path"], "data/runs/selector-report.json")
            self.assertEqual(kwargs["selector_governance_binding_application_report_path"], "data/runs/binding-application.json")
            self.assertEqual(kwargs["project_id"], "sched-binding")

    def test_agent_center_snapshot_exposes_evidence_cockpit_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            run = start_agent_run(
                storage,
                agent_key="draft",
                operation="draft",
                status="prepared",
                token_budget=1000,
                evidence={"trace": {"trace_id": "trace-agent-center", "span_id": "span-agent-center"}},
            )
            dispatch_agent_run(storage, agent_run_path=run["path"], max_attempts=2)
            record_agent_checkpoint(
                storage,
                agent_run_path=run["path"],
                status="prompt_built",
                state={"operation": "draft", "status": "prompt_built"},
            )
            record_agent_budget(storage, agent_run_path=run["path"], token_budget=1000, token_used=120, cost_estimate=0.02)
            record_agent_gate(storage, agent_run_path=run["path"], gate_type="permission", status="passed", result={"allowed": True})
            record_gate_result(
                storage,
                gate_kind="context_governance_runtime_coverage",
                status="passed",
                target_paths=[],
                result={"coverage_report_path": "data/runs/context-governance-coverage.json", "summary": {"blocking_count": 0}},
                project_id="",
                message="context governance runtime coverage passed",
                blocking=False,
            )

            snapshot = agent_center_snapshot(storage)

            self.assertIn("run_graph", snapshot)
            self.assertIn("gate_timeline", snapshot)
            self.assertIn("checkpoints", snapshot)
            self.assertIn("budget_burn", snapshot)
            self.assertIn("retry_controls", snapshot)
            self.assertIn("dead_letter_queue", snapshot)
            self.assertIn("rollback_preview", snapshot)
            self.assertIn("sla_duration", snapshot)
            self.assertIn("evidence_drawer", snapshot)
            self.assertIn("operation_coverage", snapshot)
            self.assertTrue(snapshot["run_graph"]["nodes"])
            self.assertEqual(snapshot["budget_burn"]["token_used"], 120)
            self.assertTrue(snapshot["gate_timeline"])
            self.assertIn("context_governance_runtime_coverage", {row["gate_kind"] for row in snapshot["gate_timeline"]})

    def test_agent_center_snapshot_exposes_agent_event_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            run = start_agent_run(
                storage,
                agent_key="draft",
                operation="draft",
                status="running",
                agent_event_policy={"mode": "success_summary"},
                evidence={"trace": {"trace_id": "trace-agent-event-summary", "span_id": "span-agent-event-summary"}},
            )
            update_agent_run_status(storage, run["path"], status="succeeded", event_type="agent_run.succeeded", message="summary fixture done")

            snapshot = agent_center_snapshot(storage)

            self.assertEqual(snapshot["summary"]["agent_event_summary_count"], 1)
            self.assertEqual(snapshot["summary"]["agent_event_skipped_count"], 2)
            self.assertEqual(snapshot["agent_event_summaries"][0]["policy_mode"], "success_summary")
            self.assertEqual(set(snapshot["agent_event_summaries"][0]["skipped_event_types"]), {"agent_run.started", "agent_run.succeeded"})
            drawer_rows = [row for row in snapshot["evidence_drawer"] if row["type"] == "agent_event_summary"]
            self.assertTrue(drawer_rows)
            self.assertIn("compacted AgentRun", drawer_rows[0]["summary"])

    def test_agent_center_api_surfaces_agent_event_summary(self):
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")
        from novel_forge.api.app import create_app
        from novel_forge.infrastructure.settings import IndustrialSettings

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            storage = LocalStorage(root)
            storage.ensure_layout()
            run = start_agent_run(
                storage,
                agent_key="draft",
                operation="draft",
                status="running",
                agent_event_policy={"mode": "success_summary"},
                evidence={"trace": {"trace_id": "trace-agent-event-summary-api", "span_id": "span-agent-event-summary-api"}},
            )
            update_agent_run_status(storage, run["path"], status="succeeded", event_type="agent_run.succeeded", message="summary fixture done")
            client = TestClient(create_app(IndustrialSettings(root=root)))

            response = client.get("/product/agents/center")

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["summary"]["agent_event_summary_count"], 1)
            self.assertEqual(body["summary"]["agent_event_skipped_count"], 2)
            self.assertEqual(body["agent_event_summaries"][0]["policy_mode"], "success_summary")

    def test_release_package_runner_attaches_production_governance_drift_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            fixture = create_production_ready_release_inputs(storage)
            agent_run = {
                "content": {
                    "operation": "create-release-package",
                    "input_assets": [{"path": str(fixture["draft_path"].relative_to(storage.root))}],
                    "evidence": {
                        "publish_gate_path": fixture["publish_gate_path"],
                        "environment": "production",
                        "project_id": fixture["project_id"],
                        "workspace_path": fixture["workspace_path"],
                        "source_policy": fixture["source_policy"],
                        "os_envelope": production_envelope(
                            fixture["project_id"],
                            "release_package",
                            trace_id=f"trace-scheduler-release-{fixture['project_id']}",
                        ),
                    },
                },
                "metadata": {"project_id": fixture["project_id"], "workspace_path": fixture["workspace_path"]},
            }

            result = agent_scheduler_service._run_release_package(storage, {}, agent_run)
            gate = storage.read_asset(result["production_governance_drift_gate_path"])

            self.assertTrue(result["path"])
            self.assertEqual(result["production_governance_drift_gate"]["status"], "passed")
            self.assertEqual(gate.type, "gate_result")
            self.assertEqual(gate.content["gate_kind"], "production_governance_evidence_drift")

    def test_release_package_runner_fails_when_production_governance_drift_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            fixture = create_production_ready_release_inputs(storage)
            storage.write_asset_auto(
                PublishGateReport(
                    title="Drifted publish gate",
                    content={
                        "target_asset_id": "draft-drift",
                        "gates": {"provider_runtime_gate_passed": False},
                        "decision": "blocked",
                        "blocking_issues": [{"severity": "high", "message": "legacy blocker without dimension"}],
                        "required_reports": {},
                        "human_override": False,
                    },
                    metadata={"project_id": fixture["project_id"]},
                )
            )
            agent_run = {
                "content": {
                    "operation": "create-release-package",
                    "input_assets": [{"path": str(fixture["draft_path"].relative_to(storage.root))}],
                    "evidence": {
                        "publish_gate_path": fixture["publish_gate_path"],
                        "environment": "production",
                        "project_id": fixture["project_id"],
                        "workspace_path": fixture["workspace_path"],
                        "source_policy": fixture["source_policy"],
                        "os_envelope": production_envelope(
                            fixture["project_id"],
                            "release_package",
                            trace_id=f"trace-scheduler-release-drift-{fixture['project_id']}",
                        ),
                    },
                },
                "metadata": {"project_id": fixture["project_id"], "workspace_path": fixture["workspace_path"]},
            }

            with self.assertRaisesRegex(RuntimeError, "production governance drift gate failed"):
                agent_scheduler_service._run_release_package(storage, {}, agent_run)
            failed_gates = []
            for path in storage.list_json("runs"):
                data = storage.read_json(path)
                content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
                if data.get("type") == "gate_result" and content.get("gate_kind") == "production_governance_evidence_drift" and content.get("status") == "failed":
                    failed_gates.append(data)
            self.assertTrue(failed_gates)

    def test_publish_gate_runner_fails_when_production_governance_drift_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            fixture = create_production_ready_release_inputs(storage)
            storage.write_asset_auto(
                PublishGateReport(
                    title="Drifted publish gate",
                    content={
                        "target_asset_id": "draft-drift",
                        "gates": {"provider_runtime_gate_passed": False},
                        "decision": "blocked",
                        "blocking_issues": [{"severity": "high", "message": "legacy blocker without dimension"}],
                        "required_reports": {},
                        "human_override": False,
                    },
                    metadata={"project_id": fixture["project_id"]},
                )
            )
            agent_run = {
                "content": {
                    "operation": "create-publish-gate-report",
                    "input_assets": [{"path": str(fixture["draft_path"].relative_to(storage.root))}],
                    "evidence": {
                        "environment": "production",
                        "project_id": fixture["project_id"],
                        "workspace_path": fixture["workspace_path"],
                        "source_policy": fixture["source_policy"],
                        "os_envelope": production_envelope(
                            fixture["project_id"],
                            "publish_gate_report",
                            trace_id=f"trace-scheduler-publish-drift-{fixture['project_id']}",
                        ),
                    },
                },
                "metadata": {"project_id": fixture["project_id"], "workspace_path": fixture["workspace_path"]},
            }

            with self.assertRaisesRegex(RuntimeError, "production governance drift gate failed"):
                agent_scheduler_service._run_publish_gate_report(storage, {}, agent_run)

            failed_gates = []
            for path in storage.list_json("runs"):
                data = storage.read_json(path)
                content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
                if data.get("type") == "gate_result" and content.get("gate_kind") == "production_governance_evidence_drift" and content.get("status") == "failed":
                    failed_gates.append(data)
            self.assertTrue(failed_gates)

    def test_scheduler_tick_dead_letters_release_when_governance_drift_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            fixture = create_production_ready_release_inputs(storage)
            storage.write_asset_auto(
                PublishGateReport(
                    title="Drifted publish gate",
                    content={
                        "target_asset_id": "draft-drift",
                        "gates": {"provider_runtime_gate_passed": False},
                        "decision": "blocked",
                        "blocking_issues": [{"severity": "high", "message": "legacy blocker without dimension"}],
                        "required_reports": {},
                        "human_override": False,
                    },
                    metadata={"project_id": fixture["project_id"]},
                )
            )
            run = start_agent_run(
                storage,
                agent_key="publishing",
                operation="create-release-package",
                status="prepared",
                input_assets=[str(fixture["draft_path"].relative_to(storage.root))],
                token_budget=500,
                workspace_path=fixture["workspace_path"],
                evidence={
                    "publish_gate_path": str(Path(fixture["publish_gate_path"]).relative_to(storage.root)),
                    "environment": "production",
                    "project_id": fixture["project_id"],
                    "workspace_path": fixture["workspace_path"],
                    "source_policy": fixture["source_policy"],
                    "provider_runtime_guard": {
                        "status": "passed",
                        "provider": "scheduler-fixture",
                        "model": "local-release",
                        "path": "runs/provider-runtime-gate.json",
                    },
                    "os_envelope": production_envelope(
                        fixture["project_id"],
                        "release_package",
                        trace_id=f"trace-scheduler-release-dead-letter-{fixture['project_id']}",
                    ),
                },
            )
            dispatch_agent_run(storage, agent_run_path=run["path"], max_attempts=1)

            tick = run_agent_scheduler_tick(storage, project_id=fixture["project_id"])
            queue = list_agent_dispatch_queue(storage, project_id=fixture["project_id"])[0]
            agent = storage.read_json(storage.root / run["path"])
            checkpoints = [
                storage.read_json(path)
                for path in storage.list_json("runs")
                if storage.read_json(path).get("type") == "agent_checkpoint"
            ]

            self.assertEqual(tick["acked_count"], 0)
            self.assertEqual(tick["error_count"], 1)
            self.assertEqual(tick["dead_letter_count"], 0)
            self.assertEqual(queue["status"], "dead_letter")
            self.assertIn("production governance drift gate failed", queue["last_error"])
            self.assertIn("production governance drift gate failed", tick["errors"][0]["error"])
            self.assertEqual(agent["content"]["status"], "dead_letter")
            self.assertTrue(any(item.get("content", {}).get("status") == "agent_scheduler_service_failed" for item in checkpoints))

    def test_scheduler_tick_dead_letters_publish_gate_when_governance_drift_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            result = _create_drifted_publish_gate_dead_letter(storage)
            tick = result["tick"]
            queue = result["queue"]
            run = result["run"]
            fixture = result["fixture"]
            agent = storage.read_json(storage.root / run["path"])
            checkpoints = [
                storage.read_json(path)
                for path in storage.list_json("runs")
                if storage.read_json(path).get("type") == "agent_checkpoint"
            ]
            snapshot = agent_center_snapshot(storage, project_id=fixture["project_id"])

            self.assertEqual(tick["acked_count"], 0)
            self.assertEqual(tick["error_count"], 1)
            self.assertEqual(queue["status"], "dead_letter")
            self.assertIn("production governance drift gate failed", queue["last_error"])
            self.assertEqual(agent["content"]["status"], "dead_letter")
            self.assertTrue(any(item.get("content", {}).get("status") == "agent_scheduler_service_failed" for item in checkpoints))
            self.assertEqual(snapshot["summary"]["governance_dead_letter_count"], 1)
            self.assertEqual(snapshot["governance_dead_letters"][0]["operation"], "create-publish-gate-report")

    def test_agent_center_surfaces_governance_dead_letter_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            result = _create_drifted_release_dead_letter(storage)

            snapshot = agent_center_snapshot(storage, project_id=result["fixture"]["project_id"])

            self.assertEqual(snapshot["summary"]["governance_dead_letter_count"], 1)
            row = snapshot["governance_dead_letters"][0]
            self.assertEqual(row["queue_path"], result["queue"]["path"])
            self.assertEqual(row["agent_run_status"], "dead_letter")
            self.assertIn("production governance drift gate failed", row["last_error"])
            self.assertTrue(row["failed_checkpoint_paths"])
            self.assertTrue(row["failed_gate_paths"])
            self.assertIn("production_governance_evidence_drift", {gate["gate_kind"] for gate in row["failed_gates"]})
            self.assertFalse(row["repair"]["auto_repair"])
            self.assertEqual(row["repair"]["manual_operation"], "repair_dead_letter_dispatch")
            checks = {item["key"]: item["status"] for item in snapshot["readiness_checks"]}
            self.assertEqual(checks["governance_dead_letters"], "warning")
            self.assertTrue(any("governance_dead_letters" in item for item in snapshot["recommendations"]))

    def test_governance_dead_letter_repair_requires_review_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            result = _create_drifted_release_dead_letter(storage)

            with self.assertRaisesRegex(ValueError, "governance dead-letter repair requires"):
                repair_dead_letter_dispatch(
                    storage,
                    {
                        "queue_path": result["queue"]["path"],
                        "project_id": result["fixture"]["project_id"],
                        "reason": "operator retry without reviewing failed gates",
                    },
                )

            queue = list_agent_dispatch_queue(storage, project_id=result["fixture"]["project_id"])[0]
            self.assertEqual(queue["status"], "dead_letter")

    def test_governance_dead_letter_repair_accepts_explicit_review_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            result = _create_drifted_release_dead_letter(storage)
            snapshot = agent_center_snapshot(storage, project_id=result["fixture"]["project_id"])
            governance = snapshot["governance_dead_letters"][0]

            repaired = repair_dead_letter_dispatch(
                storage,
                {
                    "queue_path": result["queue"]["path"],
                    "project_id": result["fixture"]["project_id"],
                    "reason": "operator reviewed governance drift evidence",
                    "confirm_governance_review": True,
                    "reviewed_failed_gate_paths": governance["failed_gate_paths"],
                    "reviewed_failed_checkpoint_paths": governance["failed_checkpoint_paths"],
                    "governance_review_note": "unit test reviewed failed drift gate and checkpoint before retry",
                },
            )

            self.assertEqual(repaired["repair"]["status"], "queued")
            self.assertTrue(repaired["repair"]["governance_review"]["required"])
            self.assertTrue(repaired["repair"]["governance_review"]["confirmed"])
            queue = list_agent_dispatch_queue(storage, project_id=result["fixture"]["project_id"])[0]
            self.assertEqual(queue["status"], "queued")
            self.assertEqual(list_agent_runs(storage)[0]["status"], "prepared")
            repair_audit = agent_center_snapshot(storage, project_id=result["fixture"]["project_id"])["dead_letter_repairs"][0]
            self.assertTrue(repair_audit["governance_review_required"])
            self.assertTrue(repair_audit["governance_review_confirmed"])
            self.assertEqual(repair_audit["reviewed_failed_gate_count"], len(governance["failed_gate_paths"]))
            self.assertEqual(repair_audit["reviewed_failed_checkpoint_count"], len(governance["failed_checkpoint_paths"]))
            self.assertEqual(repair_audit["review_note"], "unit test reviewed failed drift gate and checkpoint before retry")
            self.assertEqual(repair_audit["recovered_status"], "queued")
            self.assertTrue(repair_audit["rollback_rehearsal_path"])

    def test_direct_recover_rejects_governance_dead_letter(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            result = _create_drifted_release_dead_letter(storage)

            with self.assertRaisesRegex(ValueError, "governance dead-letter recovery requires"):
                recover_agent_dispatch(storage, queue_path=result["queue"]["path"], reason="direct recover bypass")

            queue = list_agent_dispatch_queue(storage, project_id=result["fixture"]["project_id"])[0]
            self.assertEqual(queue["status"], "dead_letter")

    def test_agent_recover_api_rejects_governance_dead_letter(self):
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")
        from novel_forge.api.app import create_app
        from novel_forge.infrastructure.settings import IndustrialSettings

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            storage = LocalStorage(root)
            storage.ensure_layout()
            result = _create_drifted_release_dead_letter(storage)
            client = TestClient(create_app(IndustrialSettings(root=root)))

            response = client.post("/product/agents/recover", json={"queue_path": result["queue"]["path"], "reason": "api direct recover bypass"})

            self.assertEqual(response.status_code, 400)
            self.assertIn("governance dead-letter recovery requires", response.json()["detail"])

    def test_agent_dead_letter_repair_api_requires_governance_review_evidence(self):
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")
        from novel_forge.api.app import create_app
        from novel_forge.infrastructure.settings import IndustrialSettings

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            storage = LocalStorage(root)
            storage.ensure_layout()
            result = _create_drifted_release_dead_letter(storage)
            client = TestClient(create_app(IndustrialSettings(root=root)))

            response = client.post(
                "/product/agents/dead-letter-repair",
                json={
                    "queue_path": result["queue"]["path"],
                    "project_id": result["fixture"]["project_id"],
                    "reason": "api repair without governance review",
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("governance dead-letter repair requires", response.json()["detail"])

    def test_agent_dead_letter_repair_api_accepts_governance_review_evidence(self):
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")
        from novel_forge.api.app import create_app
        from novel_forge.infrastructure.settings import IndustrialSettings

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            storage = LocalStorage(root)
            storage.ensure_layout()
            result = _create_drifted_release_dead_letter(storage)
            governance = agent_center_snapshot(storage, project_id=result["fixture"]["project_id"])["governance_dead_letters"][0]
            client = TestClient(create_app(IndustrialSettings(root=root)))

            response = client.post(
                "/product/agents/dead-letter-repair",
                json={
                    "queue_path": result["queue"]["path"],
                    "project_id": result["fixture"]["project_id"],
                    "reason": "api repair with reviewed governance evidence",
                    "confirm_governance_review": True,
                    "reviewed_failed_gate_paths": governance["failed_gate_paths"],
                    "reviewed_failed_checkpoint_paths": governance["failed_checkpoint_paths"],
                },
            )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertTrue(body["repair"]["governance_review"]["required"])
            self.assertEqual(list_agent_dispatch_queue(storage, project_id=result["fixture"]["project_id"])[0]["status"], "queued")

    def test_agent_center_api_surfaces_governance_dead_letter_evidence(self):
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")
        from novel_forge.api.app import create_app
        from novel_forge.infrastructure.settings import IndustrialSettings

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            storage = LocalStorage(root)
            storage.ensure_layout()
            result = _create_drifted_release_dead_letter(storage)
            client = TestClient(create_app(IndustrialSettings(root=root)))

            response = client.get("/product/agents/center", params={"project_id": result["fixture"]["project_id"]})

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["summary"]["governance_dead_letter_count"], 1)
            row = body["governance_dead_letters"][0]
            self.assertEqual(row["queue_path"], result["queue"]["path"])
            self.assertTrue(row["failed_gate_paths"])
            self.assertTrue(row["failed_checkpoint_paths"])
            self.assertFalse(row["repair"]["auto_repair"])
            self.assertEqual(row["repair"]["manual_operation"], "repair_dead_letter_dispatch")

    def test_agent_center_api_surfaces_governance_repair_audit_evidence(self):
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")
        from novel_forge.api.app import create_app
        from novel_forge.infrastructure.settings import IndustrialSettings

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            storage = LocalStorage(root)
            storage.ensure_layout()
            result = _create_drifted_release_dead_letter(storage)
            client = TestClient(create_app(IndustrialSettings(root=root)))
            governance = client.get("/product/agents/center", params={"project_id": result["fixture"]["project_id"]}).json()["governance_dead_letters"][0]

            repair_response = client.post(
                "/product/agents/dead-letter-repair",
                json={
                    "queue_path": result["queue"]["path"],
                    "project_id": result["fixture"]["project_id"],
                    "reason": "api repair with reviewed audit trail evidence",
                    "confirm_governance_review": True,
                    "reviewed_failed_gate_paths": governance["failed_gate_paths"],
                    "reviewed_failed_checkpoint_paths": governance["failed_checkpoint_paths"],
                    "governance_review_note": "api route fixture reviewed governance repair evidence",
                },
            )
            self.assertEqual(repair_response.status_code, 200)

            center = client.get("/product/agents/center", params={"project_id": result["fixture"]["project_id"]})

            self.assertEqual(center.status_code, 200)
            body = center.json()
            self.assertEqual(body["summary"]["dead_letter_repair_count"], 1)
            self.assertEqual(body["summary"]["governance_repair_required_count"], 1)
            self.assertEqual(body["summary"]["governance_repair_confirmed_count"], 1)
            self.assertEqual(body["summary"]["governance_repair_missing_review_count"], 0)
            repair = body["dead_letter_repairs"][0]
            self.assertTrue(repair["governance_review_required"])
            self.assertTrue(repair["governance_review_confirmed"])
            self.assertEqual(repair["reviewed_failed_gate_count"], len(governance["failed_gate_paths"]))
            self.assertEqual(repair["reviewed_failed_checkpoint_count"], len(governance["failed_checkpoint_paths"]))
            self.assertEqual(repair["review_note"], "api route fixture reviewed governance repair evidence")
            self.assertEqual(repair["recovered_status"], "queued")
            self.assertTrue(repair["rollback_rehearsal_path"])

    def test_agent_center_evidence_drawer_includes_dead_letter_repair_assets(self):
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")
        from novel_forge.api.app import create_app
        from novel_forge.infrastructure.settings import IndustrialSettings

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            storage = LocalStorage(root)
            storage.ensure_layout()
            result = _create_drifted_release_dead_letter(storage)
            client = TestClient(create_app(IndustrialSettings(root=root)))
            governance = client.get("/product/agents/center", params={"project_id": result["fixture"]["project_id"]}).json()["governance_dead_letters"][0]
            client.post(
                "/product/agents/dead-letter-repair",
                json={
                    "queue_path": result["queue"]["path"],
                    "project_id": result["fixture"]["project_id"],
                    "reason": "api repair should appear in evidence drawer",
                    "confirm_governance_review": True,
                    "reviewed_failed_gate_paths": governance["failed_gate_paths"],
                    "reviewed_failed_checkpoint_paths": governance["failed_checkpoint_paths"],
                },
            )

            center = client.get("/product/agents/center", params={"project_id": result["fixture"]["project_id"]}).json()
            repair_rows = [row for row in center["evidence_drawer"] if row["type"] == "agent_dead_letter_repair"]

            self.assertTrue(repair_rows)
            self.assertEqual(repair_rows[0]["status"], "queued")
            self.assertEqual(repair_rows[0]["summary"], "Agent dead letter repair")

    def test_agent_center_readiness_warns_on_historical_governance_repair_missing_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "project-governance-repair-drift"
            _write_historical_governance_repair_missing_review(storage, project_id)

            snapshot = agent_center_snapshot(storage, project_id=project_id)
            repair_check = next(check for check in snapshot["readiness_checks"] if check["key"] == "governance_repair_review")

            self.assertEqual(snapshot["summary"]["governance_repair_required_count"], 1)
            self.assertEqual(snapshot["summary"]["governance_repair_confirmed_count"], 0)
            self.assertEqual(snapshot["summary"]["governance_repair_missing_review_count"], 1)
            self.assertEqual(repair_check["status"], "warning")
            self.assertIn("missing governance review", repair_check["recommendation"])

    def test_agent_center_api_surfaces_governance_repair_readiness_warning(self):
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")
        from novel_forge.api.app import create_app
        from novel_forge.infrastructure.settings import IndustrialSettings

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            storage = LocalStorage(root)
            storage.ensure_layout()
            project_id = "project-governance-repair-drift-api"
            _write_historical_governance_repair_missing_review(storage, project_id)
            client = TestClient(create_app(IndustrialSettings(root=root)))

            response = client.get("/product/agents/center", params={"project_id": project_id})

            self.assertEqual(response.status_code, 200)
            body = response.json()
            repair_check = next(check for check in body["readiness_checks"] if check["key"] == "governance_repair_review")
            self.assertEqual(body["summary"]["governance_repair_missing_review_count"], 1)
            self.assertEqual(repair_check["status"], "warning")
            self.assertIn("missing governance review", repair_check["recommendation"])

    def test_non_governance_dead_letter_repair_remains_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plain = _create_plain_dead_letter(storage)

            repaired = repair_dead_letter_dispatch(storage, {"queue_path": plain["queue"]["path"], "reason": "non-governance retry"})

            self.assertFalse(repaired["repair"]["governance_review"]["required"])
            self.assertEqual(list_agent_dispatch_queue(storage)[0]["status"], "queued")

    def test_direct_recover_non_governance_dead_letter_remains_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plain = _create_plain_dead_letter(storage)

            recovered = recover_agent_dispatch(storage, queue_path=plain["queue"]["path"], reason="plain direct recovery")

            self.assertEqual(recovered["status"], "queued")
            self.assertEqual(list_agent_dispatch_queue(storage)[0]["status"], "queued")

    def test_agent_center_links_tasks_loops_context_and_review_issues(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Agent Center draft",
                    content={"chapter": 1, "text": "原创章节文本，用于 Agent Center 串联测试。", "copyright_boundary": "project-owned test fixture"},
                    metadata={"project_id": "agent-center-p"},
                ),
            )
            draft = storage.read_asset(draft_path)
            loop = run_loop(
                storage,
                {
                    "loop_type": "chapter_review",
                    "target_path": str(draft_path.relative_to(storage.root)),
                    "project_id": "agent-center-p",
                    "steps": [{"step_type": "quality_gate", "operation": "quality_passed", "token_estimate": 1, "cost_estimate": 0.0}],
                },
            )
            issue = create_review_issue(
                storage,
                {
                    "project_id": "agent-center-p",
                    "target_asset_id": draft.id,
                    "target_asset_type": "draft_chapter",
                    "target_asset_path": str(draft_path.relative_to(storage.root)),
                    "issue_type": "canon_conflict",
                    "severity": "critical",
                    "message": "Agent Center must dispatch a governed revision task.",
                    "fix_suggestion": "Create a revision task and route it through the editor agent.",
                },
            )

            dispatch = dispatch_revision_task_from_issue(storage, issue["path"], token_budget=777, priority=12)
            snapshot = agent_center_snapshot(storage, project_id="agent-center-p")

            self.assertEqual(dispatch["status"], "queued")
            self.assertTrue(dispatch["revision_task_path"])
            self.assertGreaterEqual(snapshot["summary"]["agent_task_count"], 1)
            self.assertGreaterEqual(snapshot["summary"]["agent_run_count"], 1)
            self.assertGreaterEqual(snapshot["summary"]["loop_run_count"], 1)
            self.assertGreaterEqual(snapshot["summary"]["context_bundle_count"], 1)
            self.assertGreaterEqual(snapshot["summary"]["review_issue_count"], 1)
            self.assertGreaterEqual(snapshot["summary"]["revision_task_count"], 1)
            self.assertTrue(snapshot["runtime_links"]["agent_task_to_run"])
            self.assertTrue(snapshot["runtime_links"]["agent_task_to_review_issue"])
            self.assertTrue(snapshot["runtime_links"]["agent_task_to_revision_task"])
            self.assertTrue(snapshot["runtime_links"]["loop_to_context_bundle"])
            self.assertTrue(any(node.get("type") == "agent_task" for node in snapshot["run_graph"]["nodes"]))
            self.assertTrue(any(node.get("type") == "loop_run" for node in snapshot["run_graph"]["nodes"]))
            self.assertTrue(any(edge.get("type") == "task_run" for edge in snapshot["run_graph"]["edges"]))
            task_asset = storage.read_json(storage.root / dispatch["agent_task_path"])
            revision_task_asset = storage.read_json(storage.root / dispatch["revision_task_path"])
            self.assertFalse(generation_context_policy(task_asset)["eligible"])
            self.assertEqual(revision_task_asset["content"]["revision_strategy_ids"], ["canon_aligned_rewrite"])
            self.assertTrue(revision_task_asset["content"]["re_review_required"])
            self.assertIn("re_review_path", revision_task_asset["content"]["required_output_evidence"])
            self.assertEqual(storage.read_json(storage.root / loop["loop_run_path"])["metadata"]["project_id"], "agent-center-p")

    def test_strict_scheduler_requires_active_budget_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(title="Plan", content={"chapter": 1, "objective": "open", "beats": ["beat"], "hook": "hook"}),
            )
            context_path = storage.write_asset(
                "contexts",
                ContextBundle(
                    title="Context",
                    source=storage.read_asset(plan_path).id,
                    content={
                        "build_plan_id": "unit-context-plan",
                        "target_asset_id": storage.read_asset(plan_path).id,
                        "selected_assets": [],
                        "compressed_context": {},
                        "token_budget": {"max_tokens": 1000},
                        "token_estimate": 16,
                        "actual_context": "unit context",
                        "source_asset_ids": [],
                    },
                    references=[storage.read_asset(plan_path).id, str(plan_path.relative_to(storage.root))],
                ),
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
                name="Strict Agent Scheduler Workflow",
                entry_node_id="draft-agent",
                runtime_policy={"mode": "operating_system", "require_context_bundle": True, "require_budget_policy": True},
                nodes=[
                    {
                        "node_id": "draft-agent",
                        "node_type": "agent",
                        "operation": "draft",
                        "input_assets": [str(plan_path.relative_to(storage.root)), str(context_path.relative_to(storage.root))],
                        "input_types": ["chapter_plan", "context_bundle"],
                        "output_types": ["draft_chapter"],
                        "processor": {
                            "kind": "agent",
                            "agent_key": "draft",
                            "agent_status": "prepared",
                            "context_bundle_path": str(context_path.relative_to(storage.root)),
                            "expected_output_assets": [str(draft_path.relative_to(storage.root))],
                            "token_budget": 500,
                            "token_used": 120,
                            "cost_estimate": 0.42,
                        },
                    }
                ],
            )
            initial = execute_workflow(storage, workflow["path"], input_assets=[plan_path, context_path], execute_agents=False)
            self.assertEqual(initial["status"], "running")

            tick = run_agent_scheduler_tick(storage)

            self.assertEqual(tick["acked_count"], 0)
            self.assertEqual(tick["retry_count"], 1)
            queue = list_agent_dispatch_queue(storage)[0]
            self.assertEqual(queue["status"], "retry_scheduled")
            self.assertIn("budget_policy", queue["last_error"].lower())

    def test_scheduler_completes_prepared_agent_and_resumes_workflow(self):
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
                name="Agent Scheduler Workflow",
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

            queue = list_agent_dispatch_queue(storage)
            self.assertEqual(len(queue), 1)
            self.assertEqual(queue[0]["status"], "queued")
            self.assertEqual(list_agent_runs(storage)[0]["status"], "prepared")

            tick = run_agent_scheduler_tick(storage)

            self.assertEqual(tick["status"], "completed")
            self.assertEqual(tick["acked_count"], 1)
            self.assertEqual(tick["error_count"], 0)
            self.assertEqual(list_agent_dispatch_queue(storage)[0]["status"], "acked")
            agent = list_agent_runs(storage)[0]
            self.assertEqual(agent["status"], "succeeded")
            self.assertEqual(agent["token_used"], 120)
            old_run = storage.read_asset(initial["workflow_run"]["path"])
            self.assertEqual(old_run.content["status"], "superseded")
            resume = tick["acked"][0]["workflow_resume"]
            self.assertEqual(resume["status"], "completed")
            resumed_run = storage.read_asset(resume["workflow_run"]["path"])
            self.assertEqual(resumed_run.content["lineage"]["resumed_from_run_id"], initial["run_id"])
            node_statuses = {row["node_id"]: row["status"] for row in list_node_runs(storage, run_id=resume["run_id"])}
            self.assertEqual(node_statuses["draft-agent"], "succeeded")
            self.assertEqual(node_statuses["review"], "succeeded")
            status = scheduler_status(storage)
            self.assertEqual(status["by_status"]["acked"], 1)

    def test_workflow_agent_node_preserves_production_scheduler_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(title="Plan", content={"chapter": 1, "objective": "open", "beats": ["beat"], "hook": "hook"}),
            )
            workflow = create_workflow_definition(
                storage,
                name="Production Evidence Workflow",
                entry_node_id="continuity",
                nodes=[
                    {
                        "node_id": "continuity",
                        "node_type": "agent",
                        "operation": "create-continuity-graph-snapshot",
                        "input_types": ["chapter_plan"],
                        "output_types": ["continuity_graph_snapshot"],
                        "processor": {
                            "kind": "agent",
                            "agent_key": "continuity",
                            "agent_status": "prepared",
                            "token_budget": 500,
                            "environment": "production",
                            "os_envelope": _scheduler_production_envelope("workflow-scheduler-prod-p"),
                            "source_policy": {"source_isolation_required": True},
                            "provider_runtime_guard": {"status": "passed", "provider": "workflow-fixture", "model": "local-continuity"},
                        },
                    }
                ],
            )

            execute_workflow(storage, workflow["path"], input_assets=[plan_path], execute_agents=False)
            agent = list_agent_runs(storage)[0]
            evidence = storage.read_json(storage.root / agent["path"])["content"]["evidence"]

            self.assertEqual(evidence["environment"], "production")
            self.assertEqual(evidence["os_envelope"]["project_id"], "workflow-scheduler-prod-p")
            self.assertEqual(evidence["source_policy"]["source_isolation_required"], True)
            self.assertEqual(evidence["provider_runtime_guard"]["status"], "passed")

    def test_scheduler_waits_for_human_when_prepared_agent_has_no_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(title="Plan", content={"chapter": 1, "objective": "open", "beats": ["beat"], "hook": "hook"}),
            )
            workflow = create_workflow_definition(
                storage,
                name="Agent Scheduler Waiting",
                entry_node_id="draft-agent",
                nodes=[
                    {
                        "node_id": "draft-agent",
                        "node_type": "agent",
                        "operation": "manual-human-operation",
                        "input_types": ["chapter_plan"],
                        "output_types": ["draft_chapter"],
                        "processor": {"kind": "agent", "agent_key": "draft", "agent_status": "prepared", "token_budget": 500},
                    }
                ],
            )
            execute_workflow(storage, workflow["path"], input_assets=[plan_path], execute_agents=False)

            tick = run_agent_scheduler_tick(storage)

            self.assertEqual(tick["acked_count"], 0)
            self.assertEqual(tick["waiting_human_count"], 1)
            queue = list_agent_dispatch_queue(storage)[0]
            self.assertEqual(queue["status"], "waiting_human")
            self.assertEqual(list_agent_runs(storage)[0]["status"], "waiting_human")
            recovered = recover_agent_dispatch(storage, queue_path=queue["path"], reason="unit test recovery")
            self.assertEqual(recovered["status"], "queued")
            self.assertEqual(list_agent_runs(storage)[0]["status"], "prepared")

    def test_scheduler_runs_registered_local_service_operation_without_expected_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            contracts = list_agent_operation_contracts()
            self.assertIn("create-continuity-graph-snapshot", {item["operation"] for item in contracts})
            workflow = create_workflow_definition(
                storage,
                name="Agent Scheduler Local Service",
                entry_node_id="continuity",
                nodes=[
                    {
                        "node_id": "continuity",
                        "node_type": "agent",
                        "operation": "create-continuity-graph-snapshot",
                        "output_types": ["continuity_graph_snapshot"],
                        "processor": {"kind": "agent", "agent_key": "continuity", "agent_status": "prepared", "token_budget": 500},
                    }
                ],
            )
            initial = execute_workflow(storage, workflow["path"], execute_agents=False)

            tick = run_agent_scheduler_tick(storage)

            self.assertEqual(tick["status"], "completed")
            self.assertEqual(tick["acked_count"], 1)
            self.assertEqual(tick["waiting_human_count"], 0)
            self.assertEqual(tick["error_count"], 0)
            output_assets = tick["acked"][0]["output_assets"]
            self.assertEqual(len(output_assets), 1)
            produced = storage.read_json(storage.root / output_assets[0])
            self.assertEqual(produced["type"], "continuity_graph_snapshot")
            queue = list_agent_dispatch_queue(storage)[0]
            self.assertEqual(queue["status"], "acked")
            old_run = storage.read_asset(initial["workflow_run"]["path"])
            self.assertEqual(old_run.content["status"], "superseded")
            resume = tick["acked"][0]["workflow_resume"]
            self.assertEqual(resume["status"], "completed")
            scheduler_agent = [row for row in list_agent_runs(storage) if row["operation"] == "create-continuity-graph-snapshot" and row["status"] == "succeeded"]
            self.assertGreaterEqual(len(scheduler_agent), 1)

    def test_production_scheduler_blocks_registered_operation_missing_provider_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            run = start_agent_run(
                storage,
                agent_key="continuity",
                operation="create-continuity-graph-snapshot",
                status="prepared",
                token_budget=500,
                evidence={
                    "environment": "production",
                    "os_envelope": _scheduler_production_envelope("scheduler-prod-p"),
                    "source_policy": {"source_isolation_required": True},
                    "trace": {"trace_id": "trace-scheduler-prod-missing"},
                },
            )
            dispatch_agent_run(storage, agent_run_path=run["path"], max_attempts=1)

            tick = run_agent_scheduler_tick(storage)

            self.assertEqual(tick["acked_count"], 0)
            self.assertEqual(tick["error_count"], 1)
            queue = list_agent_dispatch_queue(storage)[0]
            self.assertEqual(queue["status"], "dead_letter")
            self.assertIn("provider_runtime_gate", queue["last_error"])

    def test_production_scheduler_records_governance_for_registered_operation(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            run = start_agent_run(
                storage,
                agent_key="continuity",
                operation="create-continuity-graph-snapshot",
                status="prepared",
                token_budget=500,
                evidence={
                    "environment": "production",
                    "os_envelope": _scheduler_production_envelope("scheduler-prod-p"),
                    "source_policy": {"source_isolation_required": True},
                    "provider_runtime_guard": {"status": "passed", "provider": "scheduler-fixture", "model": "local-continuity", "path": "runs/provider-runtime-gate.json"},
                    "trace": {"trace_id": "trace-scheduler-prod-ready"},
                },
            )
            dispatch_agent_run(storage, agent_run_path=run["path"], max_attempts=1)

            tick = run_agent_scheduler_tick(storage)

            self.assertEqual(tick["acked_count"], 1)
            agent = storage.read_json(storage.root / run["path"])
            governance_path = agent["content"]["evidence"]["production_governance_path"]
            governance = storage.read_json(storage.root / governance_path)

            self.assertEqual(governance["type"], "production_governance_report")
            self.assertEqual(governance["content"]["operation"], "agent_scheduler.create-continuity-graph-snapshot")
            self.assertEqual(agent["content"]["evidence"]["production_governance_path"], governance_path)

    def test_scheduler_resumes_registered_operation_from_completed_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workflow = create_workflow_definition(
                storage,
                name="Agent Scheduler Checkpoint Resume",
                entry_node_id="continuity",
                nodes=[
                    {
                        "node_id": "continuity",
                        "node_type": "agent",
                        "operation": "create-continuity-graph-snapshot",
                        "output_types": ["continuity_graph_snapshot"],
                        "processor": {"kind": "agent", "agent_key": "continuity", "agent_status": "prepared", "token_budget": 500},
                    }
                ],
            )
            execute_workflow(storage, workflow["path"], execute_agents=False)
            queue = list_agent_dispatch_queue(storage)[0]
            prepared = [row for row in list_agent_runs(storage) if row["status"] == "prepared"][0]
            produced = create_continuity_graph_snapshot(storage)
            record_agent_checkpoint(
                storage,
                agent_run_path=prepared["path"],
                status="agent_scheduler_service_completed",
                state={
                    "status": "agent_scheduler_service_completed",
                    "operation": "create-continuity-graph-snapshot",
                    "idempotency_key": queue["idempotency_key"],
                    "input_assets": [],
                    "output_assets": [produced["path"]],
                    "service_result": produced,
                },
            )
            before_count = len([path for path in storage.list_json("continuity") if storage.read_json(path).get("type") == "continuity_graph_snapshot"])

            tick = run_agent_scheduler_tick(storage)

            after_count = len([path for path in storage.list_json("continuity") if storage.read_json(path).get("type") == "continuity_graph_snapshot"])
            self.assertEqual(after_count, before_count)
            self.assertEqual(tick["acked_count"], 1)
            self.assertEqual(tick["acked"][0]["output_assets"], [produced["path"]])
            queue_data = storage.read_json(storage.root / list_agent_dispatch_queue(storage)[0]["path"])
            result = queue_data["content"]["result"]
            self.assertEqual(result["evidence"]["agent_scheduler"], "checkpoint_resume")
            self.assertTrue(result["checkpoint"]["resumed_from_checkpoint"])

    def test_scheduler_rolls_back_service_outputs_when_agent_execution_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workflow = create_workflow_definition(
                storage,
                name="Agent Scheduler Rollback",
                entry_node_id="continuity",
                nodes=[
                    {
                        "node_id": "continuity",
                        "node_type": "agent",
                        "operation": "create-continuity-graph-snapshot",
                        "output_types": ["continuity_graph_snapshot"],
                        "processor": {"kind": "agent", "agent_key": "continuity", "agent_status": "prepared", "token_budget": 1},
                    }
                ],
            )
            execute_workflow(storage, workflow["path"], execute_agents=False)

            tick = run_agent_scheduler_tick(storage)

            self.assertEqual(tick["acked_count"], 0)
            self.assertEqual(tick["retry_count"], 1)
            queue = list_agent_dispatch_queue(storage)[0]
            queue_data = storage.read_json(storage.root / queue["path"])
            rollback = queue_data["content"]["result"]["rollback"]
            self.assertEqual(rollback["status"], "applied")
            self.assertEqual(rollback["rollback_strategy"], "mark_outputs_rolled_back")
            rolled_back_path = rollback["applied_asset_paths"][0]
            asset = storage.read_json(storage.root / rolled_back_path)
            self.assertEqual(asset["metadata"]["rollback_status"], "rolled_back")
            self.assertEqual(asset["metadata"]["asset_status"], "rolled_back")
            self.assertIn("rolled-back", asset["tags"])


def _write_historical_governance_repair_missing_review(storage: LocalStorage, project_id: str) -> Path:
    return storage.write_json(
        storage.data_dir("runs") / f"historical-governance-repair-missing-review-{project_id}.json",
        {
            "id": f"historical-governance-repair-missing-review-{project_id}",
            "type": "agent_dead_letter_repair",
            "title": "Historical governance repair missing review",
            "content": {
                "status": "queued",
                "queue_path": "runs/queue-governance-dead-letter.json",
                "governance_review": {
                    "required": True,
                    "confirmed": False,
                    "reviewed_failed_gate_paths": [],
                    "reviewed_failed_checkpoint_paths": [],
                },
                "created_at": "2026-07-08T00:00:00Z",
            },
            "metadata": {"project_id": project_id},
            "references": [],
        },
    )


def _create_drifted_release_dead_letter(storage: LocalStorage) -> dict[str, object]:
    fixture = create_production_ready_release_inputs(storage)
    storage.write_asset_auto(
        PublishGateReport(
            title="Drifted publish gate",
            content={
                "target_asset_id": "draft-drift",
                "gates": {"provider_runtime_gate_passed": False},
                "decision": "blocked",
                "blocking_issues": [{"severity": "high", "message": "legacy blocker without dimension"}],
                "required_reports": {},
                "human_override": False,
            },
            metadata={"project_id": fixture["project_id"]},
        )
    )
    run = start_agent_run(
        storage,
        agent_key="publishing",
        operation="create-release-package",
        status="prepared",
        input_assets=[str(fixture["draft_path"].relative_to(storage.root))],
        token_budget=500,
        workspace_path=fixture["workspace_path"],
        evidence={
            "publish_gate_path": str(Path(fixture["publish_gate_path"]).relative_to(storage.root)),
            "environment": "production",
            "project_id": fixture["project_id"],
            "workspace_path": fixture["workspace_path"],
            "source_policy": fixture["source_policy"],
            "provider_runtime_guard": {
                "status": "passed",
                "provider": "scheduler-fixture",
                "model": "local-release",
                "path": "runs/provider-runtime-gate.json",
            },
            "os_envelope": production_envelope(
                fixture["project_id"],
                "release_package",
                trace_id=f"trace-scheduler-release-dead-letter-{fixture['project_id']}",
            ),
        },
    )
    dispatch_agent_run(storage, agent_run_path=run["path"], max_attempts=1)
    tick = run_agent_scheduler_tick(storage, project_id=fixture["project_id"])
    queue = list_agent_dispatch_queue(storage, project_id=fixture["project_id"])[0]
    return {"fixture": fixture, "run": run, "tick": tick, "queue": queue}


def _create_drifted_publish_gate_dead_letter(storage: LocalStorage) -> dict[str, object]:
    fixture = create_production_ready_release_inputs(storage)
    storage.write_asset_auto(
        PublishGateReport(
            title="Drifted publish gate",
            content={
                "target_asset_id": "draft-drift",
                "gates": {"provider_runtime_gate_passed": False},
                "decision": "blocked",
                "blocking_issues": [{"severity": "high", "message": "legacy blocker without dimension"}],
                "required_reports": {},
                "human_override": False,
            },
            metadata={"project_id": fixture["project_id"]},
        )
    )
    run = start_agent_run(
        storage,
        agent_key="publishing",
        operation="create-publish-gate-report",
        status="prepared",
        input_assets=[str(fixture["draft_path"].relative_to(storage.root))],
        token_budget=500,
        workspace_path=fixture["workspace_path"],
        evidence={
            "environment": "production",
            "project_id": fixture["project_id"],
            "workspace_path": fixture["workspace_path"],
            "source_policy": fixture["source_policy"],
            "provider_runtime_guard": {
                "status": "passed",
                "provider": "scheduler-fixture",
                "model": "local-publish-gate",
                "path": "runs/provider-runtime-gate.json",
            },
            "os_envelope": production_envelope(
                fixture["project_id"],
                "publish_gate_report",
                trace_id=f"trace-scheduler-publish-dead-letter-{fixture['project_id']}",
            ),
        },
    )
    dispatch_agent_run(storage, agent_run_path=run["path"], max_attempts=1)
    tick = run_agent_scheduler_tick(storage, project_id=fixture["project_id"])
    queue = list_agent_dispatch_queue(storage, project_id=fixture["project_id"])[0]
    return {"fixture": fixture, "run": run, "tick": tick, "queue": queue}


def _create_plain_dead_letter(storage: LocalStorage) -> dict[str, object]:
    run = start_agent_run(
        storage,
        agent_key="continuity",
        operation="create-continuity-graph-snapshot",
        status="prepared",
        token_budget=500,
    )
    queue = dispatch_agent_run(storage, agent_run_path=run["path"], max_attempts=1)
    claim_queue_item(storage, queue["path"], owner="unit-test", ttl_seconds=30)
    failed = fail_queue_item(storage, queue["path"], reason="plain unit failure", retry_delay_seconds=0)
    return {"run": run, "queue": failed}


def _scheduler_production_envelope(project_id: str) -> dict[str, object]:
    return {
        "environment": "production",
        "project_id": project_id,
        "task_type": "agent_scheduler",
        "asset_type": "agent_run",
        "actor_type": "agent_scheduler",
        "source": "unit-test",
        "trace_id": f"trace-{project_id}",
        "source_policy": {"source_isolation_required": True},
    }


if __name__ == "__main__":
    unittest.main()
