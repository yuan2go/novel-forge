from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.publishing_feedback_adapters import (
    build_platform_upload_package,
    cluster_platform_comments,
    create_feedback_mutation_proposal,
    fanqie_manual_adapter,
    import_platform_metrics,
    apply_feedback_mutation_application_chain,
    parse_platform_receipt,
    run_platform_adapter_gate,
    publish_platform_upload_package,
    qidian_manual_adapter,
    record_platform_receipt,
    resolve_feedback_mutation_proposal,
)
from novel_forge.modules.publishing import create_release_package
from novel_forge.schemas import ReleasePackage
from novel_forge.storage.local import LocalStorage
from tests.unit.publishing_fixtures import create_production_ready_release_inputs, production_envelope


class PlatformClient:
    def publish_upload_package(self, payload: dict, context: dict) -> dict:
        return {
            "platform_book_id": "book-api-1",
            "platform_chapter_id": "chapter-api-1",
            "review_status": "submitted",
            "receipt_raw": {"remote_receipt_id": "receipt-api-1", "token": "must-not-be-persisted"},
        }


class FailingPlatformClient:
    def publish_upload_package(self, payload: dict, context: dict) -> dict:
        raise RuntimeError("remote timeout with token=secret")


class PublishingFeedbackAdapterTests(unittest.TestCase):
    def test_manual_upload_package_receipt_metrics_comments_and_mutation_proposal(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            release = ReleasePackage(
                title="release",
                content={
                    "target_asset_id": "draft-1",
                    "publish_gate_report_id": "gate-1",
                    "title_candidates": ["好看的书"],
                    "summary": "简介",
                    "tags": ["悬疑"],
                    "channel": "manual",
                    "status": "ready",
                    "chapters": [{"title": "第一章", "body": "正文"}],
                },
                metadata={"project_id": "p1"},
            )
            release_path = storage.write_asset_auto(release)

            upload = build_platform_upload_package(storage, release_package_path=release_path, platform_id="manual")
            receipt = record_platform_receipt(storage, platform_id="manual", platform_book_id="b1", upload_package_path=upload["path"])
            metrics = import_platform_metrics(
                storage,
                platform_id="manual",
                chapter_metrics=[
                    {"chapter_no": 1, "retention": 0.9},
                    {"chapter_no": 2, "retention": 0.7},
                    {"chapter_no": 3, "retention": 0.68},
                ],
            )
            comments = cluster_platform_comments(
                storage,
                platform_id="manual",
                comments=[
                    {"text": "这一章很好看，反转刺激", "characters": ["侦探"]},
                    {"text": "节奏太慢，有点想弃书", "characters": ["侦探"]},
                ],
            )
            proposal = create_feedback_mutation_proposal(
                storage,
                source_feedback_paths=[comments["report_path"], metrics["dropoff_report_path"]],
                target_assets=[{"asset_type": "outline", "path": "data/outlines/o1.json"}],
                proposed_changes=[{"domain": "outline", "change": "tighten chapter 2 hook"}],
            )

            self.assertEqual(upload["asset"]["type"], "platform_upload_package")
            self.assertEqual(receipt["asset"]["type"], "platform_publish_receipt")
            self.assertTrue(metrics["dropoff_report_path"])
            self.assertEqual(comments["asset"]["type"], "comment_cluster_report")
            self.assertTrue(comments["asset"]["content"]["pain_points"])
            self.assertTrue(proposal["asset"]["content"]["human_gate"]["required"])
            self.assertFalse(proposal["asset"]["content"]["risk_assessment"]["silent_mutation_allowed"])

    def test_feedback_mutation_approval_creates_planned_application_chain_without_silent_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            proposal = create_feedback_mutation_proposal(
                storage,
                source_feedback_paths=["data/feedback/comment-cluster.json"],
                target_assets=[
                    {"asset_type": "outline", "path": "data/outlines/o1.json"},
                    {"asset_type": "chapter_plan", "path": "data/chapter_plans/c2.json"},
                    {"asset_type": "style", "path": "data/styles/style-policy.json"},
                    {"asset_type": "genre", "path": "data/genres/genre-pack.json"},
                ],
                proposed_changes=[
                    {"domain": "outline", "change": "tighten act two dropoff"},
                    {"domain": "chapter_plan", "change": "increase hook pressure"},
                    {"domain": "style", "change": "reduce slow exposition"},
                    {"domain": "genre", "change": "make reader promise visible"},
                ],
            )

            resolved = resolve_feedback_mutation_proposal(
                storage,
                proposal_ref=proposal["path"],
                approved=True,
                actor="lead-editor",
                decision_note="approved for workflow execution",
            )

            content = resolved["asset"]["content"]
            self.assertEqual(content["human_gate"]["status"], "approved")
            self.assertEqual(content["application_status"], "planned")
            self.assertFalse(content["application_chain"]["silent_mutation_allowed"])
            self.assertEqual(content["application_chain"]["patch_plan"]["outline_patch"]["status"], "needs_review")
            self.assertEqual(content["application_chain"]["patch_plan"]["chapter_plan_patch"]["status"], "needs_review")
            self.assertEqual(content["application_chain"]["patch_plan"]["style_policy_update"]["status"], "needs_review")
            self.assertEqual(content["application_chain"]["patch_plan"]["genre_strategy_update"]["status"], "needs_review")
            self.assertFalse(content["application_chain"]["downstream_invalidation"]["apply"])
            self.assertTrue(content["application_chain"]["regeneration_task"]["requires_re_review"])
            self.assertTrue(content["auto_application"]["application_report_path"])
            self.assertNotEqual(resolved["path"], proposal["path"])

            application = apply_feedback_mutation_application_chain(
                storage,
                proposal_ref=resolved["path"],
                apply_invalidation=False,
                actor="workflow",
            )

            app_content = application["asset"]["content"]
            self.assertEqual(application["asset"]["type"], "feedback_mutation_application_report")
            self.assertEqual(app_content["status"], "planned")
            self.assertFalse(app_content["silent_mutation_allowed"])
            self.assertTrue(app_content["regeneration_tasks"])
            self.assertTrue(app_content["re_review_required"])
            self.assertTrue(app_content["patch_artifacts"])
            patch = storage.read_json(storage.root / app_content["patch_artifacts"][0]["path"])
            self.assertEqual(patch["type"], "feedback_mutation_patch")
            self.assertEqual(patch["content"]["status"], "needs_review")

    def test_comment_cluster_can_persist_review_issue_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)

            result = cluster_platform_comments(
                storage,
                platform_id="manual",
                comments=[{"text": "节奏太慢，看不下去，想弃书"}],
                persist_issues=True,
            )

            self.assertTrue(result["review_issues"])
            issue = storage.read_json(storage.root / result["review_issues"][0])
            self.assertEqual(issue["type"], "review_issue")
            self.assertEqual(issue["content"]["issue_type"], "feedback_mutation_risk")

    def test_platform_specific_upload_profile_and_embedding_feedback_clusters(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            release = ReleasePackage(
                title="release",
                content={
                    "target_asset_id": "draft-1",
                    "publish_gate_report_id": "gate-1",
                    "title_candidates": ["好看的书"],
                    "summary": "简介",
                    "tags": ["悬疑"],
                    "channel": "manual",
                    "status": "ready",
                    "chapters": [{"title": "第一章", "body": "正文"}],
                },
                metadata={"project_id": "p1"},
            )
            release_path = storage.write_asset_auto(release)

            fanqie = build_platform_upload_package(storage, release_package_path=release_path, platform_id="fanqie")
            qidian = build_platform_upload_package(storage, release_package_path=release_path, platform_id="qidian", book_metadata={"title": "好看的书", "synopsis": "简介", "volume_title": "第一卷", "cover_status": "not_required"})
            comments = cluster_platform_comments(
                storage,
                platform_id="fanqie",
                comments=[
                    {"text": "第二章节奏太慢", "embedding": [1.0, 0.0, 0.0]},
                    {"text": "这里有点水，想弃书", "embedding": [0.98, 0.02, 0.0]},
                    {"text": "反转刺激", "embedding": [0.0, 1.0, 0.0]},
                ],
            )

            self.assertTrue(fanqie["asset"]["content"]["platform_profile"]["specific_adapter"])
            self.assertEqual(fanqie["asset"]["content"]["platform_profile"]["rules_version"], "fanqie-manual-2026-07")
            self.assertEqual(fanqie["asset"]["content"]["manual_adapter_contract"]["adapter_id"], "fanqie_manual_adapter")
            self.assertFalse(fanqie["asset"]["content"]["manual_adapter_contract"]["production_boundaries"]["official_sdk_bound"])
            self.assertEqual(fanqie["asset"]["content"]["platform_rule_snapshot"]["automation_boundary"]["official_sdk_bound"], False)
            self.assertEqual(fanqie["asset"]["content"]["platform_rule_snapshot"]["upload_constraints"]["chapter_body_min_chars"], 800)
            adapter_asset = storage.read_json(storage.root / fanqie["asset"]["content"]["platform_publish_adapter_path"])
            self.assertEqual(adapter_asset["type"], "platform_publish_adapter")
            self.assertEqual(adapter_asset["content"]["export_contract"]["rate_limit_policy"], "manual_operator_controlled")
            self.assertTrue(fanqie["asset"]["content"]["platform_package_sections"])
            self.assertFalse(fanqie["asset"]["content"]["feedback_import_contract"]["mutation_policy"]["silent_mutation_allowed"])
            self.assertIn("chapter_format_report", fanqie["asset"]["content"])
            self.assertIn("sensitive_terms", fanqie["asset"]["content"]["platform_profile"]["review_risk_gate"])
            self.assertEqual(qidian["asset"]["content"]["platform_profile"]["package_shape"], "volume_chapter_package")
            self.assertTrue(qidian["asset"]["content"]["checklist"]["volume_present"])
            self.assertEqual(comments["asset"]["content"]["embedding_mode"], "provided_embeddings")
            self.assertTrue(any(cluster["size"] == 2 for cluster in comments["asset"]["content"]["embedding_clusters"]))

            fanqie_wrapper = fanqie_manual_adapter(storage, release_package_path=release_path)
            qidian_wrapper = qidian_manual_adapter(storage, release_package_path=release_path, book_metadata={"volume_title": "第一卷"})
            self.assertEqual(fanqie_wrapper["asset"]["content"]["manual_adapter_contract"]["adapter_id"], "fanqie_manual_adapter")
            self.assertEqual(qidian_wrapper["asset"]["content"]["manual_adapter_contract"]["adapter_id"], "qidian_manual_adapter")

    def test_platform_adapter_gate_blocks_missing_rule_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            release = ReleasePackage(
                title="release",
                content={
                    "target_asset_id": "draft-1",
                    "publish_gate_report_id": "gate-1",
                    "title_candidates": ["好看的书"],
                    "summary": "简介",
                    "tags": ["悬疑"],
                    "channel": "manual",
                    "status": "ready",
                    "chapters": [{"title": "第一章", "body": "正文" * 500}],
                },
                metadata={"project_id": "p1"},
            )
            release_path = storage.write_asset_auto(release)
            upload = build_platform_upload_package(
                storage,
                release_package_path=release_path,
                platform_id="fanqie",
                book_metadata={"title": "好看的书", "synopsis": "简介" * 60, "cover_status": "not_required", "sensitive_word_checked": True},
            )
            upload_asset = storage.read_json(storage.root / upload["path"])
            upload_asset["content"].pop("platform_rule_snapshot", None)
            storage.write_json(storage.root / upload["path"], upload_asset)

            gate = run_platform_adapter_gate(storage, upload_package_path=upload["path"], platform_id="fanqie")

            self.assertTrue(gate["blocking"])
            self.assertEqual(gate["asset"]["content"]["review_status"], "blocked")
            self.assertIn("platform_rule_snapshot:missing", gate["asset"]["content"]["adapter_gate"]["blocking_reasons"])

    def test_platform_specific_adapter_gate_blocks_missing_qidian_volume(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            release = ReleasePackage(
                title="release",
                content={
                    "target_asset_id": "draft-1",
                    "publish_gate_report_id": "gate-1",
                    "title_candidates": ["好看的书"],
                    "summary": "简介",
                    "tags": ["悬疑"],
                    "channel": "manual",
                    "status": "ready",
                    "chapters": [{"title": "第一章", "body": "正文" * 400}],
                },
                metadata={"project_id": "p1"},
            )
            release_path = storage.write_asset_auto(release)
            upload = build_platform_upload_package(storage, release_package_path=release_path, platform_id="qidian", book_metadata={"title": "好看的书", "synopsis": "简介", "cover_status": "not_required"})

            gate = run_platform_adapter_gate(storage, upload_package_path=upload["path"], platform_id="qidian")

            self.assertEqual(gate["asset"]["type"], "platform_review_status")
            self.assertEqual(gate["asset"]["content"]["review_status"], "blocked")
            self.assertTrue(gate["asset"]["content"]["adapter_gate"]["blocking"])
            self.assertIn("volume_present", gate["asset"]["content"]["adapter_gate"]["missing_checklist"])
            self.assertIn("qidian-manual-2026-07", gate["asset"]["content"]["adapter_gate"]["rules_version"])

    def test_fanqie_qidian_receipt_parser_normalizes_review_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)

            fanqie = parse_platform_receipt(
                storage,
                platform_id="fanqie",
                receipt_text="作品ID：fq-book-7\n章节ID：fq-ch-9\n审核状态：审核中\n提交时间：2026-07-06",
                upload_package_path="data/publishing/fanqie-package.json",
            )
            qidian = parse_platform_receipt(
                storage,
                platform_id="qidian",
                receipt_text="作品号: qd-book-1\n卷号: vol-1\n章节号: qd-ch-2\n状态: 已退回\n原因: 标题格式不合规",
                upload_package_path="data/publishing/qidian-package.json",
            )

            fanqie_content = fanqie["asset"]["content"]
            qidian_content = qidian["asset"]["content"]
            qidian_status = storage.read_json(storage.root / qidian["status_path"])["content"]

            self.assertEqual(fanqie_content["platform_book_id"], "fq-book-7")
            self.assertEqual(fanqie_content["platform_chapter_id"], "fq-ch-9")
            self.assertEqual(fanqie_content["review_status"], "reviewing")
            self.assertEqual(fanqie_content["receipt_parser"]["rules_version"], "fanqie-manual-2026-07")
            self.assertEqual(fanqie_content["receipt_parser"]["parser_confidence"]["level"], "high")
            self.assertEqual(qidian_content["platform_book_id"], "qd-book-1")
            self.assertEqual(qidian_content["receipt_parser"]["parsed_fields"]["volume_id"], "vol-1")
            self.assertEqual(qidian_content["review_status"], "rejected")
            self.assertIn("submitted_at", qidian_content["receipt_parser"]["parser_confidence"]["missing_required_fields"])
            self.assertIn("manual_fix_required", qidian_status["status_contract"]["next_actions"])
            self.assertEqual(qidian_status["status_contract"]["status_category"], "blocking")

    def test_platform_receipt_redacts_sensitive_raw_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)

            receipt = record_platform_receipt(
                storage,
                platform_id="fanqie",
                platform_book_id="fq-book-1",
                review_status="submitted",
                receipt_raw={"token": "secret-token", "remote_receipt_id": "rr-1"},
            )

            content = receipt["asset"]["content"]
            self.assertEqual(content["receipt_raw"]["token"], "[redacted]")
            self.assertTrue(content["receipt_parser"]["redaction_applied"])

    def test_platform_api_adapter_records_receipt_without_persisting_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            fixture = create_production_ready_release_inputs(storage, title="Platform API Ready")
            release_path = create_release_package(
                storage,
                fixture["draft_path"],
                workspace_path=fixture["workspace_path"],
                publish_gate_path=fixture["publish_gate_path"],
                envelope=production_envelope(fixture["project_id"], "release_package", trace_id=f"trace-platform-release-{fixture['project_id']}"),
                environment="production",
                source_policy=fixture["source_policy"],
            )
            upload = build_platform_upload_package(storage, release_package_path=release_path, platform_id="api-platform")

            result = publish_platform_upload_package(
                storage,
                upload_package_path=upload["path"],
                platform_client=PlatformClient(),
                platform_config={"platform_id": "api-platform", "endpoint": "https://platform.example/upload", "token_env": "PLATFORM_TOKEN"},
                environment="production",
                envelope={
                    "project_id": fixture["project_id"],
                    "task_type": "platform_publish",
                    "asset_type": "platform_publish_receipt",
                    "actor_type": "service",
                    "source": "test",
                    "trace_id": "trace-platform-api",
                    "source_policy": {"raw_source_text_allowed": False, "generation_rag_allowed": False},
                    "environment": "production",
                },
            )

            receipt = result["asset"]
            self.assertEqual(receipt["type"], "platform_publish_receipt")
            self.assertEqual(receipt["content"]["platform_book_id"], "book-api-1")
            self.assertEqual(receipt["content"]["receipt_raw"]["token"], "[redacted]")
            self.assertEqual(receipt["content"]["platform_api_evidence"]["mode"], "api_adapter")
            self.assertEqual(receipt["content"]["platform_api_evidence"]["production_governance"]["status"], "passed")
            self.assertEqual(result["status_asset"]["content"]["review_status"], "submitted")

    def test_platform_api_adapter_failure_writes_denied_fallback_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            fixture = create_production_ready_release_inputs(storage, title="Platform API Failure")
            release_path = create_release_package(
                storage,
                fixture["draft_path"],
                workspace_path=fixture["workspace_path"],
                publish_gate_path=fixture["publish_gate_path"],
                envelope=production_envelope(fixture["project_id"], "release_package", trace_id=f"trace-platform-release-fail-{fixture['project_id']}"),
                environment="production",
                source_policy=fixture["source_policy"],
            )
            upload = build_platform_upload_package(storage, release_package_path=release_path, platform_id="api-platform")

            with self.assertRaisesRegex(RuntimeError, "failed closed"):
                publish_platform_upload_package(
                    storage,
                    upload_package_path=upload["path"],
                    platform_client=FailingPlatformClient(),
                    platform_config={"platform_id": "api-platform", "endpoint": "https://platform.example/upload", "token_env": "PLATFORM_TOKEN"},
                    environment="production",
                    envelope={
                        "project_id": fixture["project_id"],
                        "task_type": "platform_publish",
                        "asset_type": "platform_publish_receipt",
                        "actor_type": "service",
                        "source": "test",
                        "trace_id": "trace-platform-api-failure",
                        "source_policy": {"raw_source_text_allowed": False, "generation_rag_allowed": False},
                        "environment": "production",
                    },
                )

            decisions = [
                storage.read_json(path)
                for path in storage.list_json("runs")
                if storage.read_json(path).get("type") == "fallback_decision"
            ]
            statuses = [
                storage.read_json(path)
                for path in storage.list_json("publishing")
                if storage.read_json(path).get("type") == "platform_review_status"
            ]

            self.assertTrue(decisions)
            self.assertFalse(decisions[-1]["content"]["allowed"])
            self.assertEqual(decisions[-1]["content"]["fallback_type"], "external_platform_adapter")
            self.assertNotIn("secret", str(decisions[-1]["content"]))
            self.assertTrue(statuses)
            self.assertEqual(statuses[-1]["content"]["review_status"], "failed")

    def test_production_platform_publish_blocks_upload_package_without_release_governance(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            release = ReleasePackage(
                title="release",
                content={
                    "target_asset_id": "draft-1",
                    "publish_gate_report_id": "gate-1",
                    "title_candidates": ["好看的书"],
                    "summary": "简介",
                    "tags": ["悬疑"],
                    "channel": "manual",
                    "status": "ready",
                    "chapters": [{"title": "第一章", "body": "正文"}],
                },
                metadata={"project_id": "p1"},
            )
            release_path = storage.write_asset_auto(release)
            upload = build_platform_upload_package(storage, release_package_path=release_path, platform_id="api-platform")

            with self.assertRaisesRegex(ValueError, "production governance"):
                publish_platform_upload_package(
                    storage,
                    upload_package_path=upload["path"],
                    platform_client=PlatformClient(),
                    platform_config={"platform_id": "api-platform", "endpoint": "https://platform.example/upload", "token_env": "PLATFORM_TOKEN"},
                    environment="production",
                    envelope={
                        "project_id": "p1",
                        "task_type": "platform_publish",
                        "asset_type": "platform_publish_receipt",
                        "actor_type": "service",
                        "source": "test",
                        "trace_id": "trace-platform-api-missing-governance",
                        "source_policy": {"raw_source_text_allowed": False, "generation_rag_allowed": False},
                        "environment": "production",
                    },
                )

    def test_production_platform_publish_fails_closed_without_client_or_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            release = ReleasePackage(
                title="release",
                content={"target_asset_id": "draft-1", "publish_gate_report_id": "gate-1", "status": "ready", "chapters": [{"title": "第一章", "body": "正文"}]},
                metadata={"project_id": "p1"},
            )
            release_path = storage.write_asset_auto(release)
            upload = build_platform_upload_package(storage, release_package_path=release_path, platform_id="api-platform")

            with self.assertRaises(ValueError):
                publish_platform_upload_package(
                    storage,
                    upload_package_path=upload["path"],
                    environment="production",
                    envelope={
                        "project_id": "p1",
                        "task_type": "platform_publish",
                        "asset_type": "platform_publish_receipt",
                        "actor_type": "service",
                        "source": "test",
                        "trace_id": "trace-platform-api-missing",
                        "source_policy": {"raw_source_text_allowed": False, "generation_rag_allowed": False},
                        "environment": "production",
                    },
                )


if __name__ == "__main__":
    unittest.main()
