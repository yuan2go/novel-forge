from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.model_adapters.runtime import ProviderRuntimeGuard, evaluate_provider_runtime_guard
from novel_forge.modules.evaluation_center import create_evaluation_gate
from novel_forge.modules.publishing import create_publish_gate_report, create_release_package
from novel_forge.modules.feedback import create_reader_simulation_report, process_publish_feedback_loop, process_real_feedback_backflow
from novel_forge.modules.mkaos import create_knowledge_card, create_usage_binding, record_usage_event
from novel_forge.modules.platform_strategy import build_platform_strategy_pack
from novel_forge.modules.runtime_ledger import record_gate_result, record_model_call_log
from novel_forge.schemas import DraftChapter, ProjectWorkspaceState, ReaderFeedback, SourceChunk
from novel_forge.storage.local import LocalStorage
from tests.unit.publishing_fixtures import create_production_ready_release_inputs, production_envelope


class PublishFeedbackLoopTests(unittest.TestCase):
    def test_publish_gate_writes_envelope_context_mkaos_and_source_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = _workspace(storage, "publish-loop-p")
            draft_path = _draft(storage, workspace, project_id="publish-loop-p")

            gate_path = create_publish_gate_report(
                storage,
                draft_path,
                workspace_path=str(workspace.relative_to(storage.root)),
                human_override=True,
            )
            gate = storage.read_asset(gate_path)
            content = gate.content

            self.assertTrue(content["context_bundle_path"])
            self.assertTrue(content["os_envelope_id"])
            self.assertIn("mkaos_risk", content)
            self.assertFalse(content["source_isolation"]["source_chunk_raw_text_allowed"])
            self.assertFalse(content["source_isolation"]["raw_source_text_allowed"])
            context_bundle = storage.read_json(storage.root / content["context_bundle_path"])
            self.assertNotIn('"raw_text"', str(context_bundle))
            self.assertIn("os_envelope", gate.metadata)

    def test_publish_gate_production_requires_envelope_before_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = _workspace(storage, "publish-prod-p")
            draft_path = _draft(storage, workspace, project_id="publish-prod-p")
            before_contexts = len(storage.list_json("contexts"))

            with self.assertRaisesRegex(ValueError, "OS envelope required"):
                create_publish_gate_report(
                    storage,
                    draft_path,
                    workspace_path=str(workspace.relative_to(storage.root)),
                    environment="production",
                )

            self.assertEqual(len(storage.list_json("contexts")), before_contexts)

    def test_publish_gate_uses_production_environment_from_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = _workspace(storage, "publish-env-envelope-p")
            draft_path = _draft(storage, workspace, project_id="publish-env-envelope-p")
            _publish_knowledge(storage, "publish-env-envelope-p")

            gate_path = create_publish_gate_report(
                storage,
                draft_path,
                workspace_path=str(workspace.relative_to(storage.root)),
                envelope=_production_envelope("publish-env-envelope-p", "publish_gate_report", trace_id="trace-publish-env-envelope"),
            )
            gate = storage.read_asset(gate_path)

            self.assertEqual(gate.metadata["os_envelope"]["environment"], "production")
            self.assertEqual(gate.metadata["source_policy"]["empty_pack_policy"], "block")
            self.assertFalse(gate.metadata["source_policy"]["compat_warning_allowed"])
            self.assertFalse(gate.content["gates"]["provider_runtime_gate_passed"])
            self.assertTrue(gate.content["provider_runtime_gate"]["blocking"])
            self.assertTrue(any(issue["dimension"] == "provider_runtime_gate" for issue in gate.content["blocking_issues"]))

    def test_production_release_package_blocks_non_ready_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = _workspace(storage, "release-prod-block-p")
            draft_path = _draft(storage, workspace, project_id="release-prod-block-p")
            gate_path = create_publish_gate_report(storage, draft_path, workspace_path=str(workspace.relative_to(storage.root)))
            gate = storage.read_asset(gate_path)

            self.assertNotEqual(gate.content["decision"], "ready")
            with self.assertRaisesRegex(ValueError, "gate evidence"):
                create_release_package(
                    storage,
                    draft_path,
                    workspace_path=str(workspace.relative_to(storage.root)),
                    publish_gate_path=gate_path,
                    envelope=_production_envelope("release-prod-block-p", "release_package", trace_id="trace-release-prod-block"),
                )

    def test_production_release_package_checks_gate_evidence_even_if_decision_is_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = _workspace(storage, "release-evidence-block-p")
            draft_path = _draft(storage, workspace, project_id="release-evidence-block-p")
            gate_path = create_publish_gate_report(storage, draft_path, workspace_path=str(workspace.relative_to(storage.root)), human_override=True)
            gate_data = storage.read_json(gate_path)
            gate_data["content"]["decision"] = "ready"
            storage.write_json(gate_path, gate_data)

            with self.assertRaisesRegex(ValueError, "provider_runtime_gate"):
                create_release_package(
                    storage,
                    draft_path,
                    workspace_path=str(workspace.relative_to(storage.root)),
                    publish_gate_path=gate_path,
                    envelope=_production_envelope("release-evidence-block-p", "release_package", trace_id="trace-release-evidence-block"),
                )

    def test_publish_gate_accepts_provider_guard_success_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "provider-success-p"
            workspace = _workspace(storage, project_id)
            draft_path = _draft(storage, workspace, project_id=project_id)
            _publish_knowledge(storage, project_id)
            workspace_rel = str(workspace.relative_to(storage.root))
            _record_provider_runtime_evidence(storage, project_id, workspace_path=workspace_rel)
            build_platform_strategy_pack(
                storage,
                {
                    "project_id": project_id,
                    "workspace_path": workspace_rel,
                    "platform": "local_serial",
                    "topic": "账册追查",
                    "genre": "悬疑",
                },
            )
            create_evaluation_gate(
                storage,
                str(draft_path.relative_to(storage.root)),
                minimum_score=0.0,
                project_id=project_id,
                require_provider_runtime=True,
            )

            gate_path = create_publish_gate_report(
                storage,
                draft_path,
                workspace_path=workspace_rel,
                envelope=_production_envelope(project_id, "publish_gate_report", trace_id="trace-provider-success"),
            )
            gate = storage.read_asset(gate_path)

            self.assertEqual(gate.content["provider_runtime_gate"]["status"], "passed")
            self.assertFalse(gate.content["provider_runtime_gate"]["blocking"])
            self.assertTrue(gate.content["gates"]["provider_runtime_gate_passed"])

    def test_release_package_production_ready_fixture_creates_ready_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            fixture = create_production_ready_release_inputs(storage)
            gate = storage.read_asset(fixture["publish_gate_path"])

            self.assertEqual(gate.content["decision"], "ready", gate.content["blocking_issues"])
            self.assertEqual(gate.content["production_governance"]["status"], "passed")
            self.assertTrue(gate.content["production_governance"]["path"])
            governance = storage.read_json(storage.root / gate.content["production_governance"]["path"])
            self.assertEqual(governance["type"], "production_governance_report")
            self.assertEqual(governance["content"]["status"], "passed")
            self.assertFalse(governance["content"]["blocking"])
            for dimension in ["os_envelope", "context_bundle", "mkaos_risk", "review_issue", "evaluation_gate", "provider_runtime_gate", "platform_strategy_gate", "source_isolation"]:
                self.assertIn(dimension, governance["content"]["gate_statuses"])
            self.assertEqual(gate.content["evaluation_gate"]["status"], "passed")
            self.assertEqual(gate.content["provider_runtime_gate"]["status"], "passed")
            self.assertEqual(gate.content["platform_strategy_gate"]["status"], "passed")
            self.assertFalse(gate.content["mkaos_risk"]["blocking"])
            self.assertTrue(gate.content["gates"]["review_issue_blocking_clear"])

            package_path = create_release_package(
                storage,
                fixture["draft_path"],
                workspace_path=fixture["workspace_path"],
                publish_gate_path=fixture["publish_gate_path"],
                envelope=production_envelope(fixture["project_id"], "release_package", trace_id=f"trace-release-ready-{fixture['project_id']}"),
                environment="production",
                source_policy=fixture["source_policy"],
            )
            package = storage.read_asset(package_path)
            evidence = package.content["release_gate_evidence"]

            self.assertEqual(package.content["status"], "ready")
            self.assertFalse(evidence["blocking"], evidence["blocking_issues"])
            self.assertTrue(all(not check["blocking"] for check in evidence["checks"]))
            self.assertEqual(package.content["production_governance"]["status"], "passed")
            self.assertEqual(package.content["production_governance"]["path"], gate.content["production_governance"]["path"])
            self.assertEqual(package.content["evaluation_gate"]["status"], "passed")
            self.assertEqual(package.content["provider_runtime_gate"]["status"], "passed")
            self.assertEqual(package.content["platform_strategy_gate"]["status"], "passed")
            self.assertEqual(package.content["content_intelligence_gate"]["status"], "passed")
            self.assertEqual(package.content["platform_upload_checklist"]["status"], "passed")
            self.assertEqual(package.metadata["os_envelope"]["environment"], "production")
            self.assertEqual(package.metadata["os_envelope"]["asset_type"], "release_package")

    def test_publish_gate_blocks_without_v7_content_intelligence_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            fixture = create_production_ready_release_inputs(storage, include_v7=False)
            gate = storage.read_asset(fixture["publish_gate_path"])

            self.assertEqual(gate.content["decision"], "blocked")
            self.assertTrue(any(issue["dimension"] == "content_intelligence.genre_strategy" for issue in gate.content["blocking_issues"]))
            with self.assertRaisesRegex(ValueError, "publish gate decision"):
                create_release_package(
                    storage,
                    fixture["draft_path"],
                    workspace_path=fixture["workspace_path"],
                    publish_gate_path=fixture["publish_gate_path"],
                    envelope=production_envelope(fixture["project_id"], "release_package", trace_id=f"trace-release-no-v7-{fixture['project_id']}"),
                    environment="production",
                    source_policy=fixture["source_policy"],
                )

    def test_publish_gate_governance_blocks_missing_provider_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "provider-governance-block-p"
            workspace = _workspace(storage, project_id)
            draft_path = _draft(storage, workspace, project_id=project_id)
            _publish_knowledge(storage, project_id)

            gate_path = create_publish_gate_report(
                storage,
                draft_path,
                workspace_path=str(workspace.relative_to(storage.root)),
                envelope=_production_envelope(project_id, "publish_gate_report", trace_id="trace-provider-governance-block"),
            )
            gate = storage.read_asset(gate_path)
            governance = storage.read_json(storage.root / gate.content["production_governance"]["path"])

            self.assertEqual(gate.content["decision"], "blocked")
            self.assertEqual(gate.content["production_governance"]["status"], "blocked")
            self.assertEqual(governance["content"]["status"], "blocked")
            self.assertTrue(governance["content"]["blocking"])
            self.assertTrue(any(issue["dimension"] == "provider_runtime_gate" for issue in governance["content"]["blocking_issues"]))

    def test_release_package_blocks_mkaos_risk_and_excludes_raw_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = _workspace(storage, "publish-risk-p")
            draft_path = _draft(storage, workspace, project_id="publish-risk-p")
            create_knowledge_card(
                storage,
                {
                    "concept_name": "Risky canon note",
                    "core_explanation": "must be reviewed before publish",
                    "project_id": "publish-risk-p",
                    "risk_level": "critical",
                },
            )

            gate_path = create_publish_gate_report(storage, draft_path, workspace_path=str(workspace.relative_to(storage.root)))
            gate = storage.read_asset(gate_path)

            self.assertEqual(gate.content["decision"], "blocked")
            self.assertTrue(gate.content["mkaos_risk"]["blocking"])
            with self.assertRaisesRegex(ValueError, "MKAOS high/critical risk"):
                create_release_package(storage, draft_path, workspace_path=str(workspace.relative_to(storage.root)), publish_gate_path=gate_path)

    def test_publish_feedback_loop_writes_back_to_mkaos_weight(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = _workspace(storage, "feedback-loop-p")
            knowledge = create_knowledge_card(
                storage,
                {
                    "concept_name": "Hook pressure",
                    "core_explanation": "feedback should affect future hook pressure",
                    "project_id": "feedback-loop-p",
                    "weight": 1.0,
                },
            )
            record_usage_event(
                storage,
                {
                    "knowledge_id": knowledge["asset"]["id"],
                    "knowledge_pack_id": "feedback-loop-pack",
                    "project_id": "feedback-loop-p",
                    "flow": "review",
                    "agent_name": "ReviewAgent",
                    "used_as": "feedback_baseline",
                },
            )
            feedback_path = storage.write_asset(
                "feedback",
                ReaderFeedback(
                    title="Reader feedback",
                    content={"rows": [{"chapter": "1", "rating": "2", "comment": "weak hook, boring and I may drop"}]},
                    metadata={"project_id": "feedback-loop-p", "workspace_path": str(workspace.relative_to(storage.root))},
                ),
            )

            result = process_publish_feedback_loop(
                storage,
                feedback_paths=[str(feedback_path.relative_to(storage.root))],
                project_id="feedback-loop-p",
                workspace_path=str(workspace.relative_to(storage.root)),
                require_human_gate=True,
            )
            updated = storage.read_json(storage.root / knowledge["path"])

            self.assertEqual(result["status"], "waiting_human")
            self.assertTrue(result["sentiment_report_path"])
            self.assertTrue(result["backflow_plan_path"])
            self.assertEqual(result["mkaos_weight_update_count"], 1)
            self.assertLess(updated["content"]["weight"], 1.0)

    def test_reader_simulation_scores_personas_and_rejects_source_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = _workspace(storage, "reader-sim-p")
            draft_path = _draft(storage, workspace, project_id="reader-sim-p")

            result = create_reader_simulation_report(
                storage,
                draft_path=str(draft_path.relative_to(storage.root)),
                project_id="reader-sim-p",
                workspace_path=str(workspace.relative_to(storage.root)),
                platform="fanqie",
            )
            asset = result["asset"]

            self.assertEqual(asset["type"], "reader_simulation_report")
            self.assertEqual(len(asset["content"]["personas"]), 6)
            self.assertIn("predicted_score", asset["content"]["aggregate"])
            self.assertFalse(asset["content"]["source_policy"]["source_chunk_raw_text_allowed"])

            source_chunk_path = storage.write_asset(
                "raw",
                SourceChunk(
                    title="source chunk",
                    content={
                        "source_document_id": "source1",
                        "chunk_index": 0,
                        "clean_text": "cleaned reference",
                        "raw_text": "forbidden raw source text",
                        "content_hash": "hash1",
                    },
                    metadata={"project_id": "reader-sim-p"},
                ),
            )
            with self.assertRaisesRegex(ValueError, "must not use source_document or source_chunk"):
                create_reader_simulation_report(storage, draft_path=str(source_chunk_path.relative_to(storage.root)), project_id="reader-sim-p")

    def test_real_feedback_backflow_writes_learning_assets_and_mkaos_weight(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = _workspace(storage, "real-feedback-p")
            knowledge = create_knowledge_card(
                storage,
                {
                    "concept_name": "Retention hook",
                    "core_explanation": "real feedback should adjust hook strength",
                    "project_id": "real-feedback-p",
                    "weight": 1.0,
                },
            )
            record_usage_event(
                storage,
                {
                    "knowledge_id": knowledge["asset"]["id"],
                    "knowledge_pack_id": "real-feedback-pack",
                    "project_id": "real-feedback-p",
                    "flow": "publish",
                    "agent_name": "PublishingAgent",
                    "used_as": "release_strategy",
                },
            )

            result = process_real_feedback_backflow(
                storage,
                metrics={
                    "completion_rate": 0.42,
                    "follow_read_rate": 0.31,
                    "comments": ["节奏太拖", "看不懂设定", "想看更强反转"],
                    "favorites": 8,
                    "bookshelf_adds": 11,
                    "reward_count": 1,
                    "chapter_drop_points": [{"chapter": 3, "drop_rate": 0.36, "reason": "铺垫过长"}],
                    "negative_keywords": ["拖", "看不懂"],
                    "character_mentions": {"主角": 5},
                },
                project_id="real-feedback-p",
                workspace_path=str(workspace.relative_to(storage.root)),
                platform="qidian",
            )
            updated = storage.read_json(storage.root / knowledge["path"])
            learning_types = {storage.read_json(storage.root / path)["type"] for path in result["learning_asset_paths"]}
            platform_backflow = storage.read_json(storage.root / result["platform_backflow_path"])
            report = storage.read_json(storage.root / result["path"])

            self.assertEqual(result["mkaos_weight_update_count"], 1)
            self.assertLess(updated["content"]["weight"], 1.0)
            self.assertEqual(platform_backflow["type"], "platform_feedback_backflow")
            self.assertIn("review_rule_pack", learning_types)
            self.assertIn("topic_seed", learning_types)
            self.assertIn("writing_template", learning_types)
            self.assertEqual(report["type"], "reader_feedback_backflow_report")
            self.assertEqual(report["content"]["target_updates"]["platform_strategy"]["status"], "updated")


def _workspace(storage: LocalStorage, project_id: str) -> Path:
    return storage.write_asset(
        "workspaces",
        ProjectWorkspaceState(
            title=f"Workspace {project_id}",
            content={
                "project_id": project_id,
                "memory": {},
                "chapter_states": [],
                "continuity_threads": {},
                "open_issues": [],
                "project_config": {"target_platform": "local_serial", "publish_min_hook_score": 0.7},
            },
        ),
    )


def _draft(storage: LocalStorage, workspace_path: Path, *, project_id: str) -> Path:
    return storage.write_asset(
        "drafts",
        DraftChapter(
            title="Chapter 1",
            content={
                "chapter": 1,
                "text": "原创章节文本，主角在门口看见新税帖，决定连夜去县衙查账，结尾留下明确行动钩子。",
                "copyright_boundary": "project-owned unit fixture",
            },
            metadata={"project_id": project_id, "workspace_path": str(workspace_path.relative_to(storage.root))},
            references=[str(workspace_path.relative_to(storage.root))],
        ),
    )


def _publish_knowledge(storage: LocalStorage, project_id: str) -> None:
    card = create_knowledge_card(
        storage,
        {
            "concept_name": "Publish governance",
            "core_explanation": "production publish must carry a MKAOS pack",
            "project_id": project_id,
            "weight": 1.0,
        },
    )
    create_usage_binding(storage, card["asset"]["id"], {"flow": "publish", "usage_type": "required", "input_role": "publish_gate", "priority": 10})


def _record_provider_runtime_evidence(storage: LocalStorage, project_id: str, *, workspace_path: str = "") -> None:
    cancel_file = storage.root / "cancel.flag"
    cancel_file.write_text("cancel\n", encoding="utf-8")
    cases = [
        ("token", {"input_tokens": 80, "output_tokens": 40, "total_tokens": 120}, ProviderRuntimeGuard(max_total_tokens=100)),
        ("cost", {"input_tokens": 1000, "output_tokens": 1000, "total_tokens": 2000}, ProviderRuntimeGuard(max_cost=0.001, cost_profile={"per_1k": 0.01})),
        ("timeout", {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20, "elapsed_ms": 100}, ProviderRuntimeGuard(timeout_ms=20)),
        ("cancel", {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}, ProviderRuntimeGuard(cancel_file=str(cancel_file))),
    ]
    for label, usage, guard in cases:
        result = evaluate_provider_runtime_guard(operation=f"publish_{label}", provider="mock", usage=usage, guard=guard)
        record_gate_result(
            storage,
            gate_kind="provider_runtime_guard",
            status="failed",
            target_paths=[],
            result=result,
            trace={"trace_id": f"trace-publish-{label}", "span_id": f"span-publish-{label}"},
            project_id=project_id,
            workspace_path=workspace_path,
            message=result["message"],
        )
        record_model_call_log(
            storage,
            provider="mock",
            model="mock-publish",
            operation=f"publish_{label}",
            status="failed",
            usage=result.get("usage", {}),
            cost={"amount": 0.0, "currency": "USD", "source": "publish_guard_fixture"},
            trace={"trace_id": f"trace-publish-{label}", "span_id": f"span-publish-{label}"},
            project_id=project_id,
            workspace_path=workspace_path,
        )
    success = evaluate_provider_runtime_guard(
        operation="publish_success",
        provider="mock",
        usage={"input_tokens": 20, "output_tokens": 30, "total_tokens": 50, "elapsed_ms": 10},
        guard=ProviderRuntimeGuard(max_total_tokens=1000, timeout_ms=1000, max_cost=1.0, cost_profile={"per_1k": 0.01}),
    )
    record_gate_result(
        storage,
        gate_kind="provider_runtime_guard",
        status="passed",
        target_paths=[],
        result=success,
        trace={"trace_id": "trace-publish-success", "span_id": "span-publish-success"},
        project_id=project_id,
        workspace_path=workspace_path,
        message=success["message"],
    )
    record_model_call_log(
        storage,
        provider="mock",
        model="mock-publish",
        operation="publish_success",
        status="succeeded",
        usage=success.get("usage", {}),
        cost={"amount": 0.0005, "currency": "USD", "source": "publish_guard_fixture"},
        trace={"trace_id": "trace-publish-success", "span_id": "span-publish-success"},
        project_id=project_id,
        workspace_path=workspace_path,
    )


def _production_envelope(project_id: str, asset_type: str, *, trace_id: str) -> dict:
    return {
        "project_id": project_id,
        "task_type": "publish",
        "asset_type": asset_type,
        "actor_type": "unit_test",
        "source": "tests.unit.test_publish_feedback_loop",
        "trace_id": trace_id,
        "source_policy": {"raw_source_text_allowed": False, "generation_rag_allowed": True},
        "environment": "production",
    }


if __name__ == "__main__":
    unittest.main()
