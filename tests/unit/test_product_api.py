from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.api.product import (
    attach_assets_to_project,
    archive_task_events,
    asset_detail,
    asset_reference_graph,
    asset_versions_and_diff,
    bind_handoff_output,
    continue_batch_handoff,
    create_local_backup,
    create_publish_record,
    create_product_deconstruction_handoff,
    create_product_knowledge_handoff,
    create_batch_deconstruct_items,
    draft_workbench,
    duplicate_project,
    draft_editor,
    export_draft,
    fail_handoff,
    handoff_acceptance_status,
    apply_revision_plan,
    list_series,
    list_projects,
    list_handoffs,
    list_local_backups,
    postgres_strict_local_prod_check,
    project_detail,
    project_assets,
    project_health_report,
    project_scope_audit,
    qdrant_search_operation,
    list_batch_items,
    receive_uploads,
    regenerate_batch_handoff,
    review_batch_item,
    run_batch_deconstruct,
    process_batch_item_step,
    retry_handoff,
    retry_batch_item,
    retry_batch_items_bulk,
    restore_local_backup,
    save_draft_edit,
    save_asset_collection,
    task_center,
    task_control_status,
    task_recovery_report,
    task_timeline,
    retry_task,
    transition_project_status,
    update_review_issue_status,
    update_handoff_acceptance,
    update_task_control,
    update_asset_content,
    update_asset_metadata,
    update_typed_asset_fields,
    update_project_config,
    validate_handoff_output,
    void_batch_handoff,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.schemas import BaseAsset, DecompositionReport, KnowledgeCard, SourceDocument, TaskStatus
from novel_forge.storage.local import LocalStorage
from novel_forge.workflows import pipeline
from novel_forge.workflows.status import write_task_status


class ProductApiTests(unittest.TestCase):
    def setUp(self):
        self._previous_model_provider = os.environ.get("NOVEL_FORGE_MODEL_PROVIDER")
        os.environ["NOVEL_FORGE_MODEL_PROVIDER"] = "mock"

    def tearDown(self):
        if self._previous_model_provider is None:
            os.environ.pop("NOVEL_FORGE_MODEL_PROVIDER", None)
        else:
            os.environ["NOVEL_FORGE_MODEL_PROVIDER"] = self._previous_model_provider

    def test_project_space_lists_and_resolves_workspace_detail(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace_path = pipeline.init_workspace(tmp, "Factory Project", "Factory Saga", 1)
            storage = LocalStorage(tmp)

            projects = list_projects(storage)
            detail = project_detail(storage, projects[0]["project_id"])

            self.assertEqual(len(projects), 1)
            self.assertEqual(projects[0]["title"], "Factory Project")
            self.assertEqual(detail["series_title"], "Factory Saga")
            self.assertIn("content", detail)
            self.assertEqual(detail["project_config"]["quality_threshold"], 80)
            self.assertEqual(detail["path"], str(workspace_path.relative_to(Path(tmp).resolve())))

    def test_project_config_update_and_asset_assignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace_path = pipeline.init_workspace(tmp, "Configured Project")
            source = Path(tmp) / "source.txt"
            source.write_text("Project-specific clue", encoding="utf-8")
            raw_path = pipeline.ingest(tmp, str(source), rights_authorization="test_fixture")
            storage = LocalStorage(tmp)

            updated = update_project_config(
                storage,
                str(workspace_path),
                {
                    "genre": "urban suspense",
                    "target_platform": "serial-web",
                    "target_word_count": 90000,
                    "quality_threshold": 86,
                },
            )
            attached = attach_assets_to_project(storage, [raw_path], str(workspace_path), role="source")
            rows = project_assets(storage, updated["project_id"], category="raw")
            detail = asset_detail(storage, attached[0])

            self.assertEqual(updated["project_config"]["genre"], "urban suspense")
            self.assertEqual(updated["project_config"]["quality_threshold"], 86)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["project_role"], "source")
            self.assertEqual(detail["asset"]["metadata"]["project_id"], updated["project_id"])

    def test_validate_fails_on_project_scope_issues_until_repaired(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline.init_workspace(tmp, "Strict Scope Project")
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            raw_path = storage.write_asset(
                "raw",
                SourceDocument(
                    title="Unscoped source",
                    source="source.txt",
                    content={"text": "Unscoped project material"},
                    metadata={
                        "rights": {
                            "authorization": "test_fixture",
                            "allow_downstream_generation": True,
                            "copyright_boundary": "test fixture",
                        }
                    },
                ),
            )

            _ok, errors = pipeline.validate_project(tmp)
            scope_errors = [error for error in errors if error.startswith("project-scope")]
            repaired = project_scope_audit(storage, repair=True)
            _ok_after, errors_after = pipeline.validate_project(tmp)
            scope_errors_after = [error for error in errors_after if error.startswith("project-scope")]

            self.assertTrue(raw_path.exists())
            self.assertTrue(scope_errors)
            self.assertGreaterEqual(repaired["summary"]["repaired_count"], 1)
            self.assertEqual(scope_errors_after, [])

    def test_project_scope_audit_repairs_legacy_system_runtime_assets_as_system_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline.init_workspace(tmp, "System Scope Project")
            storage = LocalStorage(tmp)
            workflow_path = storage.write_asset(
                "runs",
                BaseAsset(
                    type="workflow_definition",
                    title="Legacy system workflow",
                    content={
                        "workflow_id": "legacy-system-workflow",
                        "name": "Legacy system workflow",
                        "version": "0.1.0",
                        "nodes": [],
                        "entry_node_id": "noop",
                        "status": "active",
                        "runtime_policy": {},
                    },
                ),
            )
            lease_path = storage.write_asset(
                "runs",
                BaseAsset(
                    type="scheduler_lease",
                    title="Legacy scheduler lease",
                    content={
                        "lease_key": "agent_scheduler",
                        "owner": "legacy-worker",
                        "status": "released",
                        "acquired_at": "2026-07-01T00:00:00+00:00",
                        "expires_at": "2026-07-01T00:05:00+00:00",
                    },
                ),
            )

            before = project_scope_audit(storage, repair=False)
            repaired = project_scope_audit(storage, repair=True)

            self.assertGreaterEqual(before["summary"]["unscoped_count"], 2)
            self.assertEqual(repaired["summary"]["unscoped_count"], 0)
            for path in [workflow_path, lease_path]:
                metadata = storage.read_json(path)["metadata"]
                self.assertEqual(metadata["project_id"], "local-system")
                self.assertEqual(metadata["workspace_path"], "local-system")
                self.assertEqual(metadata["scope_kind"], "system")

    def test_cross_project_lineage_write_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            one = project_detail(storage, str(pipeline.init_workspace(tmp, "Project One")))
            two = project_detail(storage, str(pipeline.init_workspace(tmp, "Project Two")))
            first_path = storage.write_asset(
                "raw",
                SourceDocument(
                    title="Project one source",
                    source="one.txt",
                    content={"text": "project one"},
                    metadata={"project_id": one["project_id"], "workspace_path": one["path"]},
                ),
            )
            first = storage.read_json(first_path)

            with self.assertRaises(ValueError) as raised:
                storage.write_asset(
                    "raw",
                    SourceDocument(
                        title="Project two mixed source",
                        source="two.txt",
                        content={"text": "project two"},
                        metadata={"project_id": two["project_id"], "workspace_path": two["path"]},
                        references=[first["id"]],
                    ),
                )

            self.assertIn("cross-project write rejected", str(raised.exception))

    def test_project_lifecycle_duplicate_and_soft_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace_path = pipeline.init_workspace(tmp, "Lifecycle Project", "Saga", 1)
            storage = LocalStorage(tmp)

            archived = transition_project_status(storage, str(workspace_path), "archived", "archive")
            duplicated = duplicate_project(storage, archived["project_id"], {"title": "Lifecycle Copy", "book_number": 2})
            deleted = transition_project_status(storage, archived["project_id"], "deleted", "soft-delete")
            visible = list_projects(storage)
            all_projects = list_projects(storage, include_deleted=True)

            self.assertEqual(archived["project_config"]["status"], "archived")
            self.assertEqual(duplicated["title"], "Lifecycle Copy")
            self.assertNotEqual(duplicated["project_id"], archived["project_id"])
            self.assertEqual(deleted["project_config"]["status"], "deleted")
            self.assertEqual(len(visible), 1)
            self.assertEqual(len(all_projects), 2)

    def test_series_groups_multi_book_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline.init_workspace(tmp, "Saga Book One", "Clock Saga", 1)
            pipeline.init_workspace(tmp, "Saga Book Two", "Clock Saga", 2)
            storage = LocalStorage(tmp)

            series = list_series(storage)

            self.assertEqual(len(series), 1)
            self.assertEqual(series[0]["series_title"], "Clock Saga")
            self.assertEqual(series[0]["book_count"], 2)
            self.assertEqual([item["book_number"] for item in series[0]["projects"]], [1, 2])

    def test_postgres_strict_mode_blocks_missing_database_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = IndustrialSettings(root=Path(tmp), database_url="", postgres_write_strict=True)

            report = postgres_strict_local_prod_check(settings, raise_on_failure=False)

            self.assertFalse(report["ready"])
            self.assertIn("DATABASE_URL", report["errors"][0])
            with self.assertRaises(RuntimeError):
                postgres_strict_local_prod_check(settings)

    def test_task_center_lists_task_status_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            storage.write_asset(
                "runs",
                TaskStatus(
                    title="draft completed",
                    source="run_1",
                    tags=["task-status", "draft", "completed"],
                    content={
                        "run_id": "run_1",
                        "step": "draft",
                        "status": "completed",
                        "input_paths": ["data/chapter_plans/a.json"],
                        "output_paths": ["data/drafts/b.json"],
                        "error_message": "",
                    },
                ),
            )

            center = task_center(storage, status="completed")

            self.assertEqual(center["summary"]["by_status"]["completed"], 1)
            self.assertEqual(center["tasks"][0]["step"], "draft")
            self.assertIn("draft", center["steps"])
            self.assertEqual(center["timeline"]["summary"]["event_count"], 1)

    def test_task_center_defaults_to_latest_status_and_keeps_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            for status in ["pending", "running", "completed"]:
                storage.write_asset(
                    "runs",
                    TaskStatus(
                        title=f"clean {status}",
                        source="run_latest",
                        tags=["task-status", "clean", status],
                        content={
                            "run_id": "run_latest",
                            "step": "clean",
                            "status": status,
                            "input_paths": ["data/raw/a.json"],
                            "output_paths": ["data/cleaned/b.json"] if status == "completed" else [],
                            "error_message": "",
                        },
                    ),
                )

            center = task_center(storage)
            running = task_center(storage, status="running")
            completed = task_center(storage, status="completed")

            self.assertEqual(len(center["tasks"]), 1)
            self.assertEqual(center["tasks"][0]["status"], "completed")
            self.assertEqual(center["tasks"][0]["event_count"], 3)
            self.assertEqual(center["summary"]["by_status"], {"completed": 1})
            self.assertEqual(center["timeline"]["summary"]["event_count"], 3)
            self.assertEqual(running["tasks"], [])
            self.assertEqual(completed["tasks"][0]["status"], "completed")

    def test_task_center_filters_and_pages_latest_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            for step in ["clean", "draft"]:
                storage.write_asset(
                    "runs",
                    TaskStatus(
                        title=f"{step} completed",
                        source=f"run_{step}",
                        tags=["task-status", step, "completed"],
                        content={
                            "run_id": f"run_{step}",
                            "step": step,
                            "status": "completed",
                            "input_paths": [f"data/raw/{step}.json"],
                            "output_paths": [f"data/{step}/out.json"],
                            "error_message": "",
                        },
                    ),
                )

            draft_only = task_center(storage, step="draft")
            first_page = task_center(storage, offset=0, limit=1)
            second_page = task_center(storage, offset=1, limit=1)

            self.assertEqual([task["step"] for task in draft_only["tasks"]], ["draft"])
            self.assertEqual(first_page["page"]["total"], 2)
            self.assertEqual(len(first_page["tasks"]), 1)
            self.assertEqual(len(second_page["tasks"]), 1)
            self.assertNotEqual(first_page["tasks"][0]["path"], second_page["tasks"][0]["path"])

    def test_task_center_includes_claude_handoff_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.txt"
            source.write_text("A concise domain note about credible constraints.", encoding="utf-8")
            raw_path = pipeline.ingest(
                tmp,
                str(source),
                rights_authorization="test_fixture",
                copyright_note="self-authored test fixture",
                allow_downstream_generation=True,
            )
            create_product_knowledge_handoff(
                tmp,
                {
                    "input_path": str(raw_path),
                    "discipline": "forensic accounting",
                    "project_context": "modern suspense",
                },
            )

            center = task_center(LocalStorage(tmp))
            handoff_tasks = [task for task in center["tasks"] if task.get("task_type") == "handoff"]

            self.assertEqual(len(handoff_tasks), 1)
            self.assertEqual(handoff_tasks[0]["status"], "pending")
            self.assertTrue(handoff_tasks[0]["step"].startswith("handoff:"))
            self.assertEqual(handoff_tasks[0]["event_count"], 1)
            self.assertTrue(any(event.get("task_type") == "handoff" for event in center["timeline"]["events"]))

    def test_task_recovery_timeline_and_retry_from_failed_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.txt"
            source.write_text("Recoverable source text", encoding="utf-8")
            raw_path = pipeline.ingest(tmp, str(source), rights_authorization="test_fixture")
            storage = LocalStorage(tmp)
            failed_status = storage.write_asset(
                "runs",
                TaskStatus(
                    title="clean failed",
                    source="run_failed",
                    tags=["task-status", "clean", "failed"],
                    content={
                        "run_id": "run_failed",
                        "step": "clean",
                        "status": "failed",
                        "input_paths": [str(raw_path.relative_to(root.resolve()))],
                        "output_paths": [],
                        "error_message": "ValueError: fixture failure",
                    },
                ),
            )

            recovery = task_recovery_report(storage, status_path=str(failed_status))
            retried = retry_task(tmp, status_path=str(failed_status))
            timeline = task_timeline(storage, run_id=retried["retry_run_id"])

            self.assertEqual(recovery["failed_step"], "clean")
            self.assertIn("Recover by inspecting step", recovery["recovery_instruction"])
            self.assertTrue(retried["output_path"].startswith("data/cleaned/"))
            self.assertEqual(timeline["runs"][0]["status"], "completed")
            self.assertEqual(timeline["runs"][0]["progress_percent"], 100.0)

    def test_asset_detail_returns_lineage_and_blocks_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.txt"
            source.write_text("Hidden clue", encoding="utf-8")
            raw_path = pipeline.ingest(tmp, str(source), rights_authorization="test_fixture")
            storage = LocalStorage(tmp)

            detail = asset_detail(storage, str(raw_path))

            self.assertEqual(detail["summary"]["type"], "source_document")
            self.assertEqual(detail["path"], str(raw_path.relative_to(root.resolve())))
            with self.assertRaises(ValueError):
                asset_detail(storage, "../outside.json")

    def test_product_handoffs_create_project_scoped_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace_path = pipeline.init_workspace(tmp, "Handoff Project")
            source = root / "source.txt"
            source.write_text("第一章 钟声线索\n结尾留下追读义务。", encoding="utf-8")
            raw_path = pipeline.ingest(tmp, str(source), rights_authorization="test_fixture")
            cleaned_path = pipeline.clean(tmp, str(raw_path))

            deconstruct = create_product_deconstruction_handoff(
                tmp,
                {
                    "input_path": str(cleaned_path),
                    "genre": "urban suspense",
                    "target_reader": "serial readers",
                    "workspace_path": str(workspace_path),
                },
            )
            knowledge = create_product_knowledge_handoff(
                tmp,
                {
                    "input_path": str(raw_path),
                    "discipline": "forensic accounting",
                    "project_context": "modern suspense",
                    "workspace_path": str(workspace_path),
                },
            )
            rows = list_handoffs(LocalStorage(tmp), project_id=str(workspace_path))

            self.assertEqual(deconstruct["asset"]["type"], "claude_code_handoff")
            self.assertEqual(deconstruct["asset"]["content"]["expected_output_type"], "decomposition_report")
            self.assertEqual(knowledge["asset"]["content"]["expected_output_type"], "knowledge_card")
            self.assertEqual(len(rows), 2)
            self.assertEqual({row["operation"] for row in rows}, {"hot_novel_deconstruction", "multidisciplinary_knowledge_parse"})
            self.assertTrue(all(row["project_id"] for row in rows))

    def test_handoff_output_validation_and_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace_path = pipeline.init_workspace(tmp, "Handoff Output Project")
            source = root / "source.txt"
            source.write_text("A concise domain note about credible constraints.", encoding="utf-8")
            raw_path = pipeline.ingest(
                tmp,
                str(source),
                rights_authorization="test_fixture",
                copyright_note="self-authored test fixture",
                allow_downstream_generation=True,
            )
            handoff = create_product_knowledge_handoff(
                tmp,
                {
                    "input_path": str(raw_path),
                    "discipline": "forensic accounting",
                    "project_context": "modern suspense",
                    "workspace_path": str(workspace_path),
                },
            )
            storage = LocalStorage(tmp)
            output_path = storage.write_asset(
                "knowledge",
                KnowledgeCard(
                    title="Manual handoff knowledge",
                    source=handoff["asset"]["id"],
                    tags=["knowledge", "manual"],
                    content={"principles": ["turn professional constraints into story checks"]},
                    metadata={"copyright_boundary": "abstract structure transformed knowledge"},
                    references=[handoff["asset"]["id"], handoff["path"]],
                ),
            )

            validation = validate_handoff_output(tmp, {"handoff_path": handoff["path"], "output_path": str(output_path)})
            bound = bind_handoff_output(
                tmp,
                {
                    "handoff_path": handoff["path"],
                    "output_path": str(output_path),
                },
            )
            mismatch = validate_handoff_output(tmp, {"handoff_path": handoff["path"], "output_path": str(raw_path)})
            project = project_detail(storage, str(workspace_path))

            self.assertTrue(validation["valid"])
            self.assertEqual(validation["expected_output_type"], "knowledge_card")
            self.assertIn("semantic_review", validation)
            self.assertGreaterEqual(validation["semantic_review"]["score"], 70)
            self.assertEqual(bound["handoff"]["asset"]["content"]["status"], "completed")
            self.assertIn("semantic_review", bound["handoff"]["asset"]["content"]["output_validation"])
            self.assertEqual(bound["handoff"]["asset"]["content"]["bound_outputs"][0]["path"], str(output_path.relative_to(root.resolve())))
            self.assertEqual(bound["handoff"]["asset"]["metadata"]["project_id"], project["project_id"])
            self.assertEqual(bound["handoff"]["asset"]["metadata"]["workspace_path"], project["path"])
            self.assertEqual(bound["output"]["asset"]["metadata"]["project_id"], project["project_id"])
            self.assertEqual(bound["output"]["asset"]["metadata"]["workspace_path"], project["path"])
            self.assertEqual(bound["output"]["asset"]["metadata"]["project_asset_role"], "handoff-output:knowledge_card")
            self.assertFalse(mismatch["valid"])
            self.assertIn("output type mismatch", mismatch["errors"][0])
            with self.assertRaises(ValueError):
                bind_handoff_output(tmp, {"handoff_path": handoff["path"], "output_path": str(raw_path)})

    def test_handoff_semantic_quality_blocks_unreferenced_or_unbounded_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace_path = pipeline.init_workspace(tmp, "Semantic Handoff Project")
            source = root / "source.txt"
            source.write_text("A concise domain note about credible constraints.", encoding="utf-8")
            raw_path = pipeline.ingest(
                tmp,
                str(source),
                rights_authorization="test_fixture",
                copyright_note="self-authored test fixture",
                allow_downstream_generation=True,
            )
            handoff = create_product_knowledge_handoff(
                tmp,
                {
                    "input_path": str(raw_path),
                    "discipline": "forensic accounting",
                    "workspace_path": str(workspace_path),
                },
            )
            output_path = LocalStorage(tmp).write_asset(
                "knowledge",
                KnowledgeCard(
                    title="Weak handoff knowledge",
                    source="manual",
                    tags=["knowledge", "manual"],
                    content={"principles": ["usable rule"]},
                    metadata={},
                    references=[],
                ),
            )

            validation = validate_handoff_output(tmp, {"handoff_path": handoff["path"], "output_path": str(output_path)})

            self.assertFalse(validation["valid"])
            self.assertIn("output must reference the handoff id or path", validation["errors"])
            self.assertTrue(any("copyright boundary" in error for error in validation["errors"]))

    def test_source_compliance_gate_blocks_unknown_handoff_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.txt"
            source.write_text("Unlicensed source material", encoding="utf-8")
            raw_path = pipeline.ingest(
                tmp,
                str(source),
                rights_authorization="unknown",
                allow_downstream_generation=True,
            )

            with self.assertRaises(ValueError) as raised:
                create_product_knowledge_handoff(
                    tmp,
                    {
                        "input_path": str(raw_path),
                        "discipline": "forensic accounting",
                    },
                )

            self.assertIn("source compliance gate blocked", str(raised.exception))

    def test_project_scope_audit_repairs_unscoped_handoff_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace_path = pipeline.init_workspace(tmp, "Scope Audit Project")
            source = root / "source.txt"
            source.write_text("Domain note for scoped output.", encoding="utf-8")
            raw_path = pipeline.ingest(tmp, str(source), rights_authorization="test_fixture")
            handoff = create_product_knowledge_handoff(
                tmp,
                {
                    "input_path": str(raw_path),
                    "discipline": "forensic accounting",
                    "workspace_path": str(workspace_path),
                },
            )
            storage = LocalStorage(tmp)
            output_path = storage.write_asset(
                "knowledge",
                KnowledgeCard(
                    title="Unscoped manual knowledge",
                    source=handoff["asset"]["id"],
                    tags=["knowledge", "manual"],
                    content={"principles": ["scope should follow the handoff"]},
                    metadata={"copyright_boundary": "abstract structure transformed knowledge"},
                    references=[handoff["asset"]["id"], handoff["path"]],
                ),
            )
            handoff_file = root / handoff["path"]
            handoff_data = storage.read_json(handoff_file)
            handoff_data["content"]["output_paths"] = [str(output_path.relative_to(root.resolve()))]
            storage.write_json(handoff_file, handoff_data)

            audit = project_scope_audit(storage, project_id=str(workspace_path), repair=False)
            repaired = project_scope_audit(storage, project_id=str(workspace_path), repair=True)
            detail = asset_detail(storage, str(output_path))
            project = project_detail(storage, str(workspace_path))

            self.assertGreaterEqual(audit["summary"]["repairable_count"], 1)
            self.assertTrue(any(issue["kind"] == "handoff_output_mismatch" for issue in audit["issues"]))
            self.assertGreaterEqual(repaired["summary"]["repaired_count"], 1)
            self.assertEqual(detail["asset"]["metadata"]["project_id"], project["project_id"])
            self.assertEqual(detail["asset"]["metadata"]["project_asset_role"], "handoff-output:knowledge_card")

    def test_handoff_acceptance_failure_and_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace_path = pipeline.init_workspace(tmp, "Acceptance Project")
            source = root / "source.txt"
            source.write_text("Domain note for acceptance.", encoding="utf-8")
            raw_path = pipeline.ingest(tmp, str(source), rights_authorization="test_fixture")
            handoff = create_product_knowledge_handoff(
                tmp,
                {
                    "input_path": str(raw_path),
                    "discipline": "forensic accounting",
                    "workspace_path": str(workspace_path),
                },
            )

            acceptance = handoff_acceptance_status(tmp, handoff["path"])
            updated = update_handoff_acceptance(
                tmp,
                {
                    "handoff_path": handoff["path"],
                    "check_index": 0,
                    "status": "accepted",
                    "note": "schema expectation reviewed",
                },
            )
            failed = fail_handoff(tmp, {"handoff_path": handoff["path"], "reason": "manual output incomplete"})
            retried = retry_handoff(tmp, {"handoff_path": handoff["path"], "workspace_path": str(workspace_path), "reason": "retry after failed output"})

            self.assertEqual(acceptance["summary"]["total"], len(handoff["asset"]["content"]["acceptance_checks"]))
            self.assertEqual(updated["checks"][0]["status"], "accepted")
            self.assertEqual(failed["asset"]["content"]["status"], "failed")
            self.assertEqual(retried["previous"]["asset"]["content"]["status"], "superseded")
            self.assertEqual(retried["handoff"]["asset"]["content"]["status"], "pending")
            self.assertEqual(retried["handoff"]["asset"]["metadata"]["project_id"], project_detail(LocalStorage(tmp), str(workspace_path))["project_id"])

    def test_batch_deconstruct_creates_material_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "book.txt"
            source.write_text("第一章 钟声线索\n结尾留下追读义务。", encoding="utf-8")
            workspace_path = pipeline.init_workspace(tmp, "Batch Project")

            result = run_batch_deconstruct(
                tmp,
                str(source),
                rights_authorization="test_fixture",
                copyright_note="self-authored fixture",
                allow_downstream_generation=True,
                workspace_path=str(workspace_path),
            )
            material_detail = asset_detail(LocalStorage(tmp), result["items"][0]["material"])

            self.assertEqual(result["processed"], 1)
            self.assertEqual(result["succeeded"], 1)
            self.assertTrue(result["items"][0]["material"].startswith("data/materials/"))
            self.assertEqual(material_detail["asset"]["metadata"]["project_asset_role"], "deconstruction")

    def test_batch_claude_mode_waits_for_handoff_and_continues_with_manual_knowledge(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "book.txt"
            source.write_text("第一章 钟声线索\n结尾留下追读义务。", encoding="utf-8")
            workspace_path = pipeline.init_workspace(tmp, "Claude Batch Project")

            result = run_batch_deconstruct(
                tmp,
                str(source),
                rights_authorization="test_fixture",
                copyright_note="self-authored fixture",
                allow_downstream_generation=True,
                workspace_path=str(workspace_path),
                analysis_mode="claude_code",
            )
            item = result["items"][0]
            storage = LocalStorage(tmp)
            handoff_detail = asset_detail(storage, item["handoff_path"])
            knowledge_path = storage.write_asset(
                "knowledge",
                KnowledgeCard(
                    title="Manual batch knowledge",
                    source=item["handoff_id"],
                    tags=["knowledge", "manual", "batch"],
                    content={
                        "principles": [
                            "turn clues into decision pressure",
                            "keep chapter endings tied to concrete obligations",
                        ]
                    },
                    metadata={
                        "copyright_boundary": "abstract structure transformed knowledge",
                        "batch_item_id": item["id"],
                        "handoff_id": item["handoff_id"],
                        "handoff_path": item["handoff_path"],
                    },
                    references=[item["id"], item["handoff_id"]],
                ),
            )

            continued = continue_batch_handoff(
                tmp,
                {
                    "item_path": item["path"],
                    "knowledge_path": str(knowledge_path),
                },
            )
            completed_handoff = asset_detail(storage, item["handoff_path"])
            knowledge_detail = asset_detail(storage, str(knowledge_path))
            material_detail = asset_detail(storage, continued["material"])
            project = project_detail(storage, str(workspace_path))

            self.assertEqual(result["succeeded"], 0)
            self.assertEqual(result["waiting_handoff"], 1)
            self.assertEqual(item["status"], "waiting_handoff")
            self.assertEqual(item["analysis_mode"], "claude_code")
            self.assertTrue(item["handoff_path"].startswith("data/runs/"))
            self.assertEqual(handoff_detail["asset"]["type"], "claude_code_handoff")
            self.assertEqual(handoff_detail["asset"]["content"]["batch_item"]["path"], item["path"])
            self.assertEqual(continued["status"], "completed")
            self.assertTrue(continued["material"].startswith("data/materials/"))
            self.assertEqual(completed_handoff["asset"]["content"]["status"], "completed")
            self.assertEqual(completed_handoff["asset"]["metadata"]["project_id"], project["project_id"])
            self.assertEqual(knowledge_detail["asset"]["metadata"]["project_id"], project["project_id"])
            self.assertEqual(material_detail["asset"]["metadata"]["project_id"], project["project_id"])
            self.assertEqual(material_detail["asset"]["metadata"]["workspace_path"], project["path"])
            self.assertEqual(material_detail["asset"]["metadata"]["project_asset_role"], "deconstruction")

    def test_binding_batch_handoff_output_auto_continues_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "book.txt"
            source.write_text("第一章 自动继续\n结尾留下拆解验收。", encoding="utf-8")
            workspace_path = pipeline.init_workspace(tmp, "Auto Continue Batch Project")

            result = run_batch_deconstruct(
                tmp,
                str(source),
                rights_authorization="test_fixture",
                copyright_note="self-authored fixture",
                allow_downstream_generation=True,
                workspace_path=str(workspace_path),
                analysis_mode="claude_code",
            )
            item = result["items"][0]
            storage = LocalStorage(tmp)
            decomposition_path = storage.write_asset(
                "decompositions",
                DecompositionReport(
                    title="Manual batch decomposition",
                    source=item["handoff_id"],
                    tags=["decomposition", "manual", "batch"],
                    content={
                        "summary": "A schema-backed manual decomposition for auto-continue.",
                        "commercial_patterns": ["chapter ending creates an obligation"],
                        "narrative_patterns": ["clue to consequence"],
                        "character_mechanisms": ["choice pressure"],
                        "conflict_patterns": ["known risk versus delayed action"],
                        "emotion_curve": ["setup", "pressure", "hook"],
                        "hook_patterns": ["unresolved obligation"],
                    },
                    metadata={
                        "copyright_boundary": "abstract structure transformed knowledge",
                        "batch_item_id": item["id"],
                        "handoff_id": item["handoff_id"],
                        "handoff_path": item["handoff_path"],
                    },
                    references=[item["id"], item["handoff_id"], item["handoff_path"]],
                ),
            )

            bound = bind_handoff_output(
                tmp,
                {
                    "handoff_path": item["handoff_path"],
                    "output_path": str(decomposition_path),
                },
            )

            self.assertTrue(bound["validation"]["valid"])
            self.assertIsNotNone(bound["continued_batch_item"])
            self.assertEqual(bound["continued_batch_item"]["status"], "completed")
            self.assertTrue(bound["continued_batch_item"]["material"].startswith("data/materials/"))

    def test_batch_claude_handoff_regenerate_and_void(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "book.txt"
            source.write_text("第一章 分步交接\n结尾留下手工解析任务。", encoding="utf-8")
            workspace_path = pipeline.init_workspace(tmp, "Regenerate Batch Project")

            result = run_batch_deconstruct(
                tmp,
                str(source),
                rights_authorization="test_fixture",
                copyright_note="self-authored fixture",
                allow_downstream_generation=True,
                workspace_path=str(workspace_path),
                analysis_mode="claude_code",
            )
            storage = LocalStorage(tmp)
            item = result["items"][0]
            old_handoff_path = item["handoff_path"]

            regenerated = regenerate_batch_handoff(
                tmp,
                {
                    "item_path": item["path"],
                    "workspace_path": str(workspace_path),
                    "reason": "manual packet incomplete",
                },
            )
            old_handoff = asset_detail(storage, old_handoff_path)
            new_handoff = asset_detail(storage, regenerated["handoff_path"])
            voided = void_batch_handoff(
                tmp,
                {
                    "item_path": regenerated["path"],
                    "reason": "operator rejected handoff",
                },
            )
            voided_handoff = asset_detail(storage, regenerated["handoff_path"])

            self.assertEqual(regenerated["status"], "waiting_handoff")
            self.assertEqual(regenerated["handoff_generation"], 2)
            self.assertNotEqual(regenerated["handoff_path"], old_handoff_path)
            self.assertEqual(len(regenerated["handoff_history"]), 2)
            self.assertEqual(old_handoff["asset"]["content"]["status"], "superseded")
            self.assertEqual(new_handoff["asset"]["content"]["status"], "pending")
            self.assertEqual(voided["status"], "failed")
            self.assertEqual(voided["handoff_status"], "superseded")
            self.assertIn("operator rejected handoff", voided["error_message"])
            self.assertEqual(voided_handoff["asset"]["content"]["status"], "superseded")

    def test_batch_item_step_processing_advances_one_step_at_a_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "book.txt"
            source.write_text("第一章 分步拆书\n结尾留下钩子。", encoding="utf-8")
            created = create_batch_deconstruct_items(tmp, str(source), rights_authorization="test_fixture")

            first = process_batch_item_step(tmp, created["item_paths"][0], step="ingest", enqueue_next=False)
            second = process_batch_item_step(tmp, first["path"], step="clean", enqueue_next=False)

            self.assertEqual(created["items"][0]["status"], "pending")
            self.assertEqual(first["status"], "pending")
            self.assertTrue(first["raw"].startswith("data/raw/"))
            self.assertTrue(second["cleaned"].startswith("data/cleaned/"))
            self.assertEqual([step["step"] for step in second["steps"] if step["status"] == "completed"][:2], ["queued", "ingest"])

    def test_batch_item_records_failure_and_retries_single_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "sources"
            source_dir.mkdir()
            good = source_dir / "good.txt"
            bad = source_dir / "bad.txt"
            good.write_text("第一章 有效文本\n结尾留下义务。", encoding="utf-8")
            bad.write_text("", encoding="utf-8")

            result = run_batch_deconstruct(tmp, str(source_dir), rights_authorization="test_fixture")
            failed_items = list_batch_items(LocalStorage(tmp), batch_id=result["batch_id"], status="failed")
            bad.write_text("修复后的文本\n可以拆解。", encoding="utf-8")
            bulk = retry_batch_items_bulk(tmp, [failed_items[0]["path"]])
            retried = bulk["results"][0]["result"]
            reviewed = review_batch_item(LocalStorage(tmp), {"item_path": retried["path"], "decision": "approved", "note": "ready"})

            self.assertEqual(result["processed"], 2)
            self.assertEqual(result["failed"], 1)
            self.assertEqual(len(failed_items), 1)
            self.assertEqual(retried["status"], "completed")
            self.assertEqual(bulk["requested"], 1)
            self.assertEqual(bulk["succeeded"], 1)
            self.assertTrue(retried["material"].startswith("data/materials/"))
            self.assertEqual(reviewed["review_status"], "approved")
            self.assertEqual(reviewed["review_gate"]["note"], "ready")

    def test_upload_sources_records_preview_dedupe_and_minio_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            boundary = "----NovelForgeTestBoundary"
            body = (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="rights_authorization"\r\n\r\n'
                "test_fixture\r\n"
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="allow_downstream_generation"\r\n\r\n'
                "true\r\n"
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="files"; filename="one.txt"\r\n'
                "Content-Type: text/plain\r\n\r\n"
                "upload text\r\n"
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="files"; filename="two.txt"\r\n'
                "Content-Type: text/plain\r\n\r\n"
                "upload text\r\n"
                f"--{boundary}--\r\n"
            ).encode("utf-8")

            result = receive_uploads(
                IndustrialSettings(root=Path(tmp).resolve()),
                body,
                f"multipart/form-data; boundary={boundary}",
            )

            self.assertEqual(len(result["items"]), 2)
            self.assertTrue(result["items"][1]["duplicate"])
            self.assertTrue((Path(tmp) / result["input_path"] / "one.txt").exists())
            self.assertEqual(result["rights"]["authorization"], "test_fixture")

    def test_upload_sources_requires_license_gate_for_downstream_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            boundary = "----NovelForgeUnknownBoundary"
            body = (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="rights_authorization"\r\n\r\n'
                "unknown\r\n"
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="allow_downstream_generation"\r\n\r\n'
                "true\r\n"
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="files"; filename="one.txt"\r\n'
                "Content-Type: text/plain\r\n\r\n"
                "upload text\r\n"
                f"--{boundary}--\r\n"
            ).encode("utf-8")

            with self.assertRaises(ValueError) as raised:
                receive_uploads(
                    IndustrialSettings(root=Path(tmp).resolve()),
                    body,
                    f"multipart/form-data; boundary={boundary}",
                )

            self.assertIn("allow_downstream_generation requires", str(raised.exception))

    def test_task_control_config_and_health_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            settings = IndustrialSettings(root=root)
            storage = LocalStorage(root)
            storage.ensure_layout()
            raw = storage.write_asset("raw", SourceDocument(title="Health source", source="a.txt", content={"text": "health"}))
            write_task_status(storage, "health-run", "clean", "completed", input_paths=[raw], output_paths=[raw])
            write_task_status(storage, "health-fail", "decompose", "failed", input_paths=[raw], error_message="Injected failure")

            config = update_task_control(tmp, {"max_concurrent_batches": 2, "max_concurrent_steps": 3})
            status = task_control_status(settings)
            health = project_health_report(settings)

            self.assertEqual(config["max_concurrent_batches"], 2)
            self.assertEqual(status["config"]["max_concurrent_steps"], 3)
            self.assertIn("celery", status)
            self.assertIn("queue_trend", health)
            self.assertIn("postgres", health)
            self.assertIn("embedding", health)
            self.assertGreaterEqual(health["summary"]["asset_count"], 3)
            self.assertEqual(health["summary"]["failed_task_count"], 1)
            self.assertEqual({task["status"] for task in health["recent_failures"]}, {"failed"})

    def test_task_event_archive_previews_and_confirms(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            raw = storage.write_asset("raw", SourceDocument(title="Archive source", source="a.txt", content={"text": "archive"}))
            write_task_status(storage, "archive-run-1", "clean", "completed", input_paths=[raw], output_paths=[raw])
            write_task_status(storage, "archive-run-2", "decompose", "failed", input_paths=[raw], error_message="old failure")

            preview = archive_task_events(tmp, keep_latest=1, confirm=False)
            archived = archive_task_events(tmp, keep_latest=1, confirm=True)

            self.assertEqual(preview["candidate_count"], 1)
            self.assertEqual(archived["archived_count"], 1)
            self.assertTrue((Path(tmp) / archived["archive_path"]).exists())
            self.assertEqual(len([path for path in storage.list_json("runs") if storage.read_json(path).get("type") == "task_status"]), 1)

    def test_qdrant_search_operation_adds_hit_explanations(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            asset_path = storage.write_asset(
                "knowledge",
                KnowledgeCard(
                    title="Vector knowledge",
                    source="manual",
                    tags=["knowledge"],
                    content={"principles": ["vector hit should explain source asset"]},
                    metadata={"copyright_boundary": "abstract structure transformed knowledge"},
                ),
            )
            relative = str(asset_path.relative_to(Path(tmp).resolve()))
            with patch("novel_forge.api.product.pipeline.qdrant_search") as mocked:
                mocked.return_value = [{"path": relative, "type": "knowledge_card", "score": 0.91}]
                result = qdrant_search_operation(tmp, "story constraint", project_id="project-a", limit=3)

            self.assertEqual(result["backend"], "qdrant")
            self.assertEqual(result["count"], 1)
            self.assertEqual(result["filters"]["project_id"], "project-a")
            self.assertEqual(mocked.call_args.kwargs["project_id"], "project-a")
            self.assertEqual(result["results"][0]["explanation"]["backend"], "qdrant")
            self.assertIn("vector hit", result["results"][0]["preview"])

    def test_local_backup_list_and_confirmed_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            raw_path = storage.write_asset(
                "raw",
                SourceDocument(title="Backup source", source="source.txt", content={"text": "before restore"}),
            )
            settings = IndustrialSettings(root=root.resolve())

            backup = create_local_backup(settings)
            data = storage.read_json(raw_path)
            data["content"]["text"] = "after backup edit"
            storage.write_json(raw_path, data)
            with self.assertRaises(ValueError):
                restore_local_backup(tmp, backup["path"], confirm=False)
            restored = restore_local_backup(tmp, backup["path"], confirm=True)
            listed = list_local_backups(tmp)

            self.assertGreater(restored["restored_count"], 0)
            self.assertEqual(storage.read_json(raw_path)["content"]["text"], "before restore")
            self.assertEqual(listed[0]["path"], backup["path"])

    def test_asset_metadata_edit_updates_safe_workbench_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.txt"
            source.write_text("Editable source", encoding="utf-8")
            raw_path = pipeline.ingest(tmp, str(source), rights_authorization="test_fixture")
            storage = LocalStorage(tmp)

            edited = update_asset_metadata(
                storage,
                str(raw_path),
                {
                    "title": "Edited Source",
                    "tags": ["edited", "source", "edited"],
                    "status": "approved",
                    "notes": "ready for downstream abstraction",
                    "risk_level": "low",
                    "copyright_note": "operator confirmed fixture",
                    "allow_downstream_generation": True,
                },
            )

            self.assertEqual(edited["summary"]["title"], "Edited Source")
            self.assertEqual(edited["summary"]["tags"], ["edited", "source"])
            self.assertEqual(edited["summary"]["asset_status"], "approved")
            self.assertEqual(edited["summary"]["operator_notes"], "ready for downstream abstraction")
            self.assertEqual(edited["summary"]["risk_level"], "low")
            self.assertTrue(edited["summary"]["rights"]["allow_downstream_generation"])

    def test_asset_content_edit_validates_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.txt"
            source.write_text("Editable content", encoding="utf-8")
            raw_path = pipeline.ingest(tmp, str(source), rights_authorization="test_fixture")
            storage = LocalStorage(tmp)

            edited = update_asset_content(storage, str(raw_path), {"text": "operator-edited content"})

            self.assertEqual(edited["asset"]["content"]["text"], "operator-edited content")
            self.assertIn("content_edited_at", edited["asset"]["metadata"])
            with self.assertRaises(ValueError):
                update_asset_content(storage, str(raw_path), {})

    def test_typed_asset_edit_updates_declared_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            path = storage.write_asset(
                "knowledge",
                KnowledgeCard(
                    title="Editable knowledge",
                    source="manual",
                    tags=["knowledge"],
                    content={"principles": ["old rule"]},
                    metadata={"copyright_boundary": "abstract structure transformed knowledge"},
                ),
            )

            edited = update_typed_asset_fields(
                storage,
                str(path),
                {
                    "principles": "new rule\nsecond rule",
                    "license_review_status": "fixture license accepted",
                    "raw_text_used": False,
                },
            )

            self.assertEqual(edited["asset"]["content"]["principles"], ["new rule", "second rule"])
            self.assertEqual(edited["asset"]["metadata"]["license_review_status"], "fixture license accepted")
            self.assertFalse(edited["asset"]["metadata"]["raw_text_used"])
            self.assertTrue((Path(tmp) / "data" / "runs" / "audit-log.jsonl").exists())
            with self.assertRaises(ValueError):
                update_typed_asset_fields(storage, str(path), {"unknown": "blocked"})

    def test_asset_versions_graph_and_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.txt"
            source.write_text("Collection source", encoding="utf-8")
            raw_path = pipeline.ingest(tmp, str(source), rights_authorization="test_fixture")
            workspace_path = pipeline.init_workspace(tmp, "Asset Workbench Project")
            storage = LocalStorage(tmp)

            update_asset_metadata(storage, str(raw_path), {"title": "Versioned Source", "status": "approved"})
            versions = asset_versions_and_diff(storage, str(raw_path))
            graph = asset_reference_graph(storage, str(raw_path))
            collection = save_asset_collection(
                storage,
                {
                    "title": "Search Set",
                    "purpose": "task_input",
                    "asset_paths": [versions["path"]],
                    "tags": ["fixture"],
                    "workspace_path": str(workspace_path),
                },
            )

            self.assertGreaterEqual(len(versions["versions"]), 2)
            self.assertIn("Versioned Source", versions["diff"]["unified_diff"])
            self.assertEqual(graph["nodes"][0]["type"], "source_document")
            self.assertEqual(graph["layout"]["algorithm"], "deterministic_bfs_layered")
            self.assertIn("layout", graph["nodes"][0])
            self.assertIn("x", graph["nodes"][0]["layout"])
            self.assertEqual(collection["summary"]["type"], "asset_collection")
            self.assertEqual(collection["asset"]["content"]["item_count"], 1)
            self.assertEqual(collection["asset"]["metadata"]["project_asset_role"], "asset-collection")

    def test_draft_editor_save_diff_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.txt"
            source.write_text("Hook line\nConflict line\nReader obligation.", encoding="utf-8")
            for command in [
                lambda: pipeline.ingest(tmp, str(source), rights_authorization="test_fixture"),
                lambda: pipeline.clean(tmp),
                lambda: pipeline.decompose(tmp),
                lambda: pipeline.extract_knowledge(tmp),
                lambda: pipeline.build_materials(tmp),
                lambda: pipeline.generate_topic(tmp),
                lambda: pipeline.generate_world(tmp),
                lambda: pipeline.generate_characters(tmp),
                lambda: pipeline.generate_outline(tmp),
                lambda: pipeline.generate_chapter_plan(tmp),
                lambda: pipeline.draft(tmp),
            ]:
                command()
            storage = LocalStorage(tmp)
            original = storage.latest("drafts")
            editor = draft_editor(storage, str(original))
            saved = save_draft_edit(
                tmp,
                {
                    "draft_path": str(original),
                    "text": editor["text"] + "\n新增人工修改。",
                    "title": "Edited Draft",
                    "status": "edited",
                },
            )
            exported = export_draft(tmp, saved["draft_path"], "markdown")
            published = create_publish_record(tmp, exported["path"], channel="local", note="fixture release")

            self.assertTrue(saved["draft_path"].startswith("data/drafts/"))
            self.assertEqual(saved["editor"]["version_index"], 1)
            self.assertTrue((root / exported["path"]).exists())
            self.assertTrue(published["record_path"].startswith("data/runs/"))
            self.assertEqual(published["record"]["content"]["channel"], "local")
            self.assertEqual(len(published["record"]["content"]["sha256"]), 64)

    def test_review_issue_status_and_revision_apply_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.txt"
            source.write_text("Hook line\nConflict line\nReader obligation.", encoding="utf-8")
            for command in [
                lambda: pipeline.ingest(tmp, str(source), rights_authorization="test_fixture"),
                lambda: pipeline.clean(tmp),
                lambda: pipeline.decompose(tmp),
                lambda: pipeline.extract_knowledge(tmp),
                lambda: pipeline.build_materials(tmp),
                lambda: pipeline.generate_topic(tmp),
                lambda: pipeline.generate_world(tmp),
                lambda: pipeline.generate_characters(tmp),
                lambda: pipeline.generate_outline(tmp),
                lambda: pipeline.generate_chapter_plan(tmp),
                lambda: pipeline.draft(tmp),
                lambda: pipeline.review(tmp),
                lambda: pipeline.revise(tmp),
            ]:
                command()
            storage = LocalStorage(tmp)
            review_path = storage.latest("reviews")
            while storage.read_json(review_path).get("type") != "review_report":
                review_path = sorted(path for path in storage.list_json("reviews") if storage.read_json(path).get("type") == "review_report")[-1]
            revision_path = sorted(path for path in storage.list_json("reviews") if storage.read_json(path).get("type") == "revision_plan")[-1]

            updated = update_review_issue_status(
                storage,
                {"review_path": str(review_path), "issue_index": 0, "status": "accepted", "note": "fix now"},
            )
            preview = apply_revision_plan(tmp, {"revision_path": str(revision_path), "confirmed": False})
            applied = apply_revision_plan(tmp, {"revision_path": str(revision_path), "confirmed": True, "review_after": True})

            self.assertEqual(updated["asset"]["issues"][0]["status"], "accepted")
            self.assertEqual(preview["mode"], "confirmation_required")
            self.assertEqual(applied["mode"], "applied")
            self.assertTrue(applied["draft_path"].startswith("data/drafts/"))
            self.assertTrue(applied["after_review_path"].startswith("data/reviews/"))

    def test_draft_workbench_groups_drafts_reviews_and_revisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.txt"
            source.write_text("Hook line\nConflict line\nReader obligation.", encoding="utf-8")
            for command in [
                lambda: pipeline.ingest(tmp, str(source), rights_authorization="test_fixture"),
                lambda: pipeline.clean(tmp),
                lambda: pipeline.decompose(tmp),
                lambda: pipeline.extract_knowledge(tmp),
                lambda: pipeline.build_materials(tmp),
                lambda: pipeline.generate_topic(tmp),
                lambda: pipeline.generate_world(tmp),
                lambda: pipeline.generate_characters(tmp),
                lambda: pipeline.generate_outline(tmp),
                lambda: pipeline.generate_chapter_plan(tmp),
                lambda: pipeline.draft(tmp),
                lambda: pipeline.review(tmp),
                lambda: pipeline.revise(tmp),
            ]:
                command()

            workbench = draft_workbench(LocalStorage(tmp))

            self.assertEqual(len(workbench["chapter_plans"]), 1)
            self.assertEqual(len(workbench["drafts"]), 1)
            self.assertEqual(len(workbench["revised_drafts"]), 1)
            self.assertEqual(len(workbench["reviews"]), 1)
            self.assertEqual(len(workbench["post_revision_reviews"]), 1)
            self.assertEqual(len(workbench["revision_plans"]), 1)


if __name__ == "__main__":
    unittest.main()
