from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.agent_registry import record_agent_lifecycle_event, sync_runtime_profiles
from novel_forge.modules.agent_runs import list_agent_runs, start_agent_run
from novel_forge.modules.agent_scheduler import dispatch_agent_run, list_agent_dispatch_queue, run_agent_scheduler_tick
from novel_forge.modules.chapter_production_bus import start_chapter_production
from novel_forge.modules.workspace.service import init_workspace
from novel_forge.schemas import DraftChapter, Outline, TopicSeed
from novel_forge.storage.local import LocalStorage
from tests.unit.publishing_fixtures import create_production_ready_release_inputs, production_envelope


class AgentRegistrySchedulerIntegrationTests(unittest.TestCase):
    def test_scheduler_records_registry_version_on_agent_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            sync_runtime_profiles(storage)
            run = start_agent_run(storage, agent_key="continuity", operation="create-continuity-graph-snapshot", status="prepared")
            dispatch_agent_run(storage, agent_run_path=run["path"])

            tick = run_agent_scheduler_tick(storage)
            runs = [row for row in list_agent_runs(storage) if row["operation"] == "create-continuity-graph-snapshot"]

            self.assertEqual(tick["status"], "completed")
            self.assertEqual(tick["acked_count"], 1)
            self.assertTrue(runs[0]["agent_registry_entry_id"])
            self.assertTrue(runs[0]["agent_registry_version"])

    def test_scheduler_fail_closed_for_deprecated_agent_registry_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            sync_runtime_profiles(storage)
            record_agent_lifecycle_event(storage, agent_id="continuity", to_state="deprecated", reason="unit test")
            run = start_agent_run(storage, agent_key="continuity", operation="create-continuity-graph-snapshot", status="prepared")
            dispatch_agent_run(storage, agent_run_path=run["path"], max_attempts=1)

            tick = run_agent_scheduler_tick(storage)
            queue = list_agent_dispatch_queue(storage)[0]

            self.assertEqual(tick["error_count"], 1)
            self.assertEqual(queue["status"], "dead_letter")
            self.assertIn("not schedulable", queue["last_error"])

    def test_scheduler_executes_longform_recap_as_longform_agent_operation(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            sync_runtime_profiles(storage)
            latest_path = _longform_recap_fixture(storage)
            run = start_agent_run(
                storage,
                agent_key="longform_recap",
                operation="run-longform-recap",
                input_assets=[latest_path],
                status="prepared",
                evidence={"project_id": "scheduler-recap-p", "chapter_count": 12, "force": True},
            )
            dispatch_agent_run(storage, agent_run_path=run["path"])

            tick = run_agent_scheduler_tick(storage)
            runs = [row for row in list_agent_runs(storage, operation="run-longform-recap")]
            queue = list_agent_dispatch_queue(storage)[0]
            queue_asset = storage.read_json(storage.root / queue["path"])
            output_assets = queue_asset["content"]["result"]["output_assets"]

            self.assertEqual(tick["status"], "completed")
            self.assertEqual(tick["acked_count"], 1)
            self.assertEqual(queue["status"], "acked")
            self.assertEqual(runs[0]["agent_type"], "Longform Recap Agent")
            self.assertTrue(any(str(path).endswith(".json") for path in output_assets))
            self.assertTrue(any(storage.read_json(storage.root / path)["type"] == "longform_recap_report" for path in output_assets))

    def test_scheduler_executes_platform_strategy_as_platform_compliance_operation(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            sync_runtime_profiles(storage)
            topic_path = _topic_fixture(storage, project_id="scheduler-platform-p")
            run = start_agent_run(
                storage,
                agent_key="platform_strategy",
                operation="create-platform-strategy-pack",
                input_assets=[topic_path],
                status="prepared",
                evidence={"project_id": "scheduler-platform-p", "platform": "fanqie"},
            )
            dispatch_agent_run(storage, agent_run_path=run["path"])

            tick = run_agent_scheduler_tick(storage)
            runs = [row for row in list_agent_runs(storage, operation="create-platform-strategy-pack")]
            queue = list_agent_dispatch_queue(storage)[0]
            queue_asset = storage.read_json(storage.root / queue["path"])
            output_assets = queue_asset["content"]["result"]["output_assets"]

            self.assertEqual(tick["status"], "completed")
            self.assertEqual(tick["acked_count"], 1)
            self.assertEqual(queue["status"], "acked")
            self.assertEqual(runs[0]["agent_type"], "Platform Compliance Agent")
            self.assertTrue(any(storage.read_json(storage.root / path)["type"] == "platform_strategy_pack" for path in output_assets))

    def test_scheduler_executes_training_exercise_as_training_agent_operation(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            sync_runtime_profiles(storage)
            topic_path = _topic_fixture(storage, project_id="scheduler-training-p")
            run = start_agent_run(
                storage,
                agent_key="training",
                operation="generate-training-exercise",
                input_assets=[topic_path],
                status="prepared",
                evidence={"project_id": "scheduler-training-p"},
            )
            dispatch_agent_run(storage, agent_run_path=run["path"])

            tick = run_agent_scheduler_tick(storage)
            runs = [row for row in list_agent_runs(storage, operation="generate-training-exercise")]
            queue = list_agent_dispatch_queue(storage)[0]
            queue_asset = storage.read_json(storage.root / queue["path"])
            output_assets = queue_asset["content"]["result"]["output_assets"]

            self.assertEqual(tick["status"], "completed")
            self.assertEqual(tick["acked_count"], 1)
            self.assertEqual(queue["status"], "acked")
            self.assertEqual(runs[0]["agent_type"], "Training Agent")
            self.assertTrue(any(storage.read_json(storage.root / path)["type"] == "training_exercise" for path in output_assets))

    def test_scheduler_release_package_preserves_production_runtime_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            sync_runtime_profiles(storage)
            fixture = create_production_ready_release_inputs(storage, title="Scheduler Release Ready")
            source_policy = {**fixture["source_policy"], "scheduler_policy_marker": "release-runner"}
            run = start_agent_run(
                storage,
                agent_key="publishing",
                operation="create-release-package",
                input_assets=[fixture["draft_path"]],
                status="prepared",
                evidence={
                    "project_id": fixture["project_id"],
                    "workspace_path": fixture["workspace_path"],
                    "publish_gate_path": str(fixture["publish_gate_path"].relative_to(storage.root)),
                    "environment": "production",
                    "os_envelope": production_envelope(
                        fixture["project_id"],
                        "release_package",
                        trace_id=f"trace-scheduler-release-{fixture['project_id']}",
                        source_policy=source_policy,
                    ),
                    "source_policy": source_policy,
                },
            )
            dispatch_agent_run(storage, agent_run_path=run["path"])

            tick = run_agent_scheduler_tick(storage)
            queue = list_agent_dispatch_queue(storage)[0]
            queue_asset = storage.read_json(storage.root / queue["path"])
            output_assets = queue_asset["content"]["result"]["output_assets"]
            package = storage.read_json(storage.root / output_assets[0])

            self.assertEqual(tick["status"], "completed")
            self.assertEqual(queue["status"], "acked")
            self.assertEqual(package["type"], "release_package")
            self.assertEqual(package["content"]["status"], "ready")
            self.assertEqual(package["metadata"]["os_envelope"]["environment"], "production")
            self.assertEqual(package["metadata"]["os_envelope"]["asset_type"], "release_package")
            self.assertEqual(package["metadata"]["source_policy"]["scheduler_policy_marker"], "release-runner")

    def test_scheduler_executes_chapter_production_start_with_runtime_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            sync_runtime_profiles(storage)
            fixture = _chapter_production_fixture(storage, project_title="Scheduler Chapter Start")
            source_policy = _scheduler_source_policy()
            run = start_agent_run(
                storage,
                agent_key="workflow",
                operation="start-chapter-production",
                input_assets=[fixture["outline_path"]],
                status="prepared",
                evidence={
                    "project_id": fixture["project_id"],
                    "workspace_path": fixture["workspace_path"],
                    "chapter": 1,
                    "run_to": "outline_checkpoint",
                    "task_status_mode": "compact",
                    "environment": "production",
                    "os_envelope": production_envelope(
                        fixture["project_id"],
                        "chapter_production_run",
                        trace_id=f"trace-scheduler-chapter-start-{fixture['project_id']}",
                        source_policy=source_policy,
                    ),
                    "source_policy": source_policy,
                    "provider_runtime_guard": _passed_provider_runtime_gate(),
                    "require_external_provider_proof": True,
                },
            )
            dispatch_agent_run(storage, agent_run_path=run["path"])

            tick = run_agent_scheduler_tick(storage)
            runs = [row for row in list_agent_runs(storage, operation="start-chapter-production")]
            queue = list_agent_dispatch_queue(storage)[0]
            queue_asset = storage.read_json(storage.root / queue["path"])
            output_assets = queue_asset["content"]["result"]["output_assets"]
            chapter_run_path = next(path for path in output_assets if storage.read_json(storage.root / path)["type"] == "chapter_production_run")
            chapter_run = storage.read_json(storage.root / chapter_run_path)
            policy = chapter_run["content"]["quality_loop_policy"]

            self.assertEqual(tick["status"], "completed")
            self.assertEqual(tick["acked_count"], 1)
            self.assertEqual(queue["status"], "acked")
            self.assertEqual(runs[0]["agent_type"], "Workflow Agent")
            self.assertEqual(chapter_run["content"]["current_step"], "outline_checkpoint")
            self.assertEqual(policy["environment"], "production")
            self.assertEqual(policy["source_policy"]["source_isolation_required"], True)
            self.assertEqual(policy["os_envelope"]["asset_type"], "chapter_production_run")
            self.assertEqual(policy["require_external_provider_proof"], True)
            self.assertEqual(queue_asset["content"]["result"]["evidence"]["production_governance_status"], "passed")

    def test_scheduler_executes_chapter_production_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            sync_runtime_profiles(storage)
            fixture = _chapter_production_fixture(storage, project_title="Scheduler Chapter Resume")
            planned = start_chapter_production(
                storage,
                outline_path=fixture["outline_path"],
                workspace_path=fixture["workspace_path"],
                chapter=1,
                run_to="outline_checkpoint",
                execute=False,
                task_status_mode="compact",
            )
            run = start_agent_run(
                storage,
                agent_key="workflow",
                operation="resume-chapter-production",
                input_assets=[planned["path"]],
                status="prepared",
                evidence={"project_id": fixture["project_id"], "workspace_path": fixture["workspace_path"], "run_to": "outline_checkpoint"},
            )
            dispatch_agent_run(storage, agent_run_path=run["path"])

            tick = run_agent_scheduler_tick(storage)
            queue = list_agent_dispatch_queue(storage)[0]
            queue_asset = storage.read_json(storage.root / queue["path"])
            output_assets = queue_asset["content"]["result"]["output_assets"]
            chapter_run = storage.read_json(storage.root / output_assets[0])

            self.assertEqual(tick["status"], "completed")
            self.assertEqual(queue["status"], "acked")
            self.assertEqual(chapter_run["type"], "chapter_production_run")
            self.assertEqual(chapter_run["content"]["status"], "succeeded")
            self.assertEqual(chapter_run["content"]["current_step"], "outline_checkpoint")


def _longform_recap_fixture(storage: LocalStorage) -> Path:
    latest_path = None
    for chapter in range(1, 13):
        latest_path = storage.write_asset(
            "drafts",
            DraftChapter(
                title=f"Scheduler recap chapter {chapter}",
                content={
                    "chapter": chapter,
                    "text": f"第{chapter}章。主角持续追查同一条账册线索，人物目标和伏笔都保持连续。",
                    "copyright_boundary": "project-owned scheduler recap fixture",
                },
                metadata={"project_id": "scheduler-recap-p"},
            ),
        )
    assert latest_path is not None
    return latest_path


def _topic_fixture(storage: LocalStorage, *, project_id: str) -> Path:
    return storage.write_asset(
        "topics",
        TopicSeed(
            title=f"Scheduler topic {project_id}",
            content={
                "logline": "主角在雨夜发现账册异常，被迫在家族和真相之间做选择。",
                "reader_attraction": "强冲突、低门槛、明确追查钩子",
                "differentiation": "原创账册追查机制，不复用受保护表达",
                "genre": "悬疑",
            },
            metadata={"project_id": project_id},
        ),
    )


def _chapter_production_fixture(storage: LocalStorage, *, project_title: str) -> dict[str, str]:
    workspace = init_workspace(storage, project_title)
    workspace_asset = storage.read_asset(workspace)
    project_id = workspace_asset.content["project_id"]
    workspace_ref = str(workspace.relative_to(storage.root))
    outline = storage.write_asset(
        "outlines",
        Outline(
            title=f"{project_title} Outline",
            content={"acts": [{"act": 1, "goal": "open with a governed scheduler chapter"}]},
            metadata={"project_id": project_id, "workspace_path": workspace_ref},
            references=[workspace_ref],
        ),
    )
    return {
        "project_id": project_id,
        "workspace_path": workspace_ref,
        "outline_path": str(outline.relative_to(storage.root)),
    }


def _scheduler_source_policy() -> dict[str, object]:
    return {
        "source_isolation_required": True,
        "raw_source_text_allowed": False,
        "generation_rag_allowed": False,
        "external_reference_mode": "evidence_only",
        "scheduler_policy_marker": "chapter-production-runner",
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
