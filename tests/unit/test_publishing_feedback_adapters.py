from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.publishing_feedback_adapters import (
    build_platform_upload_package,
    cluster_platform_comments,
    create_feedback_mutation_proposal,
    import_platform_metrics,
    publish_platform_upload_package,
    record_platform_receipt,
)
from novel_forge.schemas import ReleasePackage
from novel_forge.storage.local import LocalStorage


class PlatformClient:
    def publish_upload_package(self, payload: dict, context: dict) -> dict:
        return {
            "platform_book_id": "book-api-1",
            "platform_chapter_id": "chapter-api-1",
            "review_status": "submitted",
            "receipt_raw": {"remote_receipt_id": "receipt-api-1", "token": "must-not-be-persisted"},
        }


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

    def test_platform_api_adapter_records_receipt_without_persisting_secret(self):
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

            result = publish_platform_upload_package(
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
            self.assertEqual(result["status_asset"]["content"]["review_status"], "submitted")

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
