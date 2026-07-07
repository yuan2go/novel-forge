from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.portfolio_os import (
    build_book_potential_scores,
    build_cross_book_similarity_report,
    build_multi_book_scheduler_plan,
    build_resource_allocation_plan,
    create_portfolio_project,
)
from novel_forge.schemas import ChapterPlan, DraftChapter, GenreProfile, Outline, QualityScoreReport, ReviewIssue, StyleProfile
from novel_forge.storage.local import LocalStorage


class PortfolioOSTests(unittest.TestCase):
    def test_portfolio_project_scores_and_allocation_preserve_book_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.write_asset_auto(ChapterPlan(title="A plan", metadata={"project_id": "book-a"}))
            storage.write_asset_auto(DraftChapter(title="A draft", metadata={"project_id": "book-a"}))
            storage.write_asset_auto(QualityScoreReport(title="A quality", content={"score": 0.82}, metadata={"project_id": "book-a"}))
            storage.write_asset_auto(ChapterPlan(title="B plan", metadata={"project_id": "book-b"}))
            storage.write_asset_auto(
                ReviewIssue(
                    title="B blocker",
                    content={"issue_id": "b-1", "issue_type": "canon", "blocking": True, "severity": "high"},
                    metadata={"project_id": "book-b"},
                )
            )

            portfolio = create_portfolio_project(storage, title="Two Book Portfolio", project_ids=["book-a", "book-b"])
            scores = build_book_potential_scores(storage, portfolio_ref=portfolio["path"])
            allocation = build_resource_allocation_plan(storage, portfolio_ref=portfolio["path"], provider_budget=20.0, max_parallel_books=2)

            self.assertEqual(portfolio["asset"]["type"], "portfolio_project")
            self.assertFalse(portfolio["asset"]["content"]["isolation_contract"]["cross_book_assets_allowed"])
            self.assertEqual({row["type"] for row in scores["scores"]}, {"book_potential_score"})
            score_by_project = {row["content"]["project_id"]: row["content"] for row in scores["scores"]}
            self.assertGreater(score_by_project["book-a"]["score_total"], score_by_project["book-b"]["score_total"])
            self.assertEqual(allocation["asset"]["type"], "resource_allocation_plan")
            content = allocation["asset"]["content"]
            self.assertFalse(content["dispatch_boundary"]["automatic_dispatch"])
            self.assertTrue(content["isolation_contract"]["requires_cross_book_similarity_guard_before_shared_assets"])
            blocked = [row for row in content["allocations"] if row["project_id"] == "book-b"][0]
            self.assertTrue(blocked["blocked"])
            self.assertEqual(blocked["recommended_action"], "resolve_blocking_review_issues")

    def test_cross_book_similarity_report_blocks_shared_context_for_high_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            self._write_book_identity(storage, "book-a", "都市刑侦", "冷峻第一人称", "旧案重启 证据链 嫌疑人 反转 真相")
            self._write_book_identity(storage, "book-b", "都市刑侦", "冷峻第一人称", "旧案重启 证据链 嫌疑人 反转 真相")
            self._write_book_identity(storage, "book-c", "科幻远征", "明快第三人称", "星舰 生态危机 外星规则 技术代价")
            portfolio = create_portfolio_project(storage, title="Guard Portfolio", project_ids=["book-a", "book-b", "book-c"])

            report = build_cross_book_similarity_report(storage, portfolio_ref=portfolio["path"], high_threshold=0.45)

            self.assertEqual(report["asset"]["type"], "cross_book_similarity_report")
            content = report["asset"]["content"]
            self.assertEqual(content["guard_decision"]["status"], "blocked")
            pair_by_books = {frozenset([row["left_project_id"], row["right_project_id"]]): row for row in content["pairwise_similarity"]}
            self.assertEqual(pair_by_books[frozenset(["book-a", "book-b"])]["risk_level"], "high")
            self.assertNotEqual(pair_by_books[frozenset(["book-a", "book-c"])]["risk_level"], "high")
            self.assertFalse(content["guard_decision"]["shared_context_allowed"])
            self.assertTrue(content["generation_context_boundary"]["stores_fingerprint_only"])

    def test_multi_book_scheduler_plan_requires_approval_and_never_dispatches(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            self._write_book_identity(storage, "book-a", "都市刑侦", "冷峻第一人称", "旧案重启 证据链 嫌疑人 反转 真相")
            self._write_book_identity(storage, "book-c", "科幻远征", "明快第三人称", "星舰 生态危机 外星规则 技术代价")
            portfolio = create_portfolio_project(storage, title="Scheduler Portfolio", project_ids=["book-a", "book-c"])

            plan = build_multi_book_scheduler_plan(storage, portfolio_ref=portfolio["path"], provider_budget=12.0, environment="production")

            self.assertEqual(plan["status"], "needs_approval")
            self.assertEqual(plan["approval_request"]["asset"]["type"], "approval_request")
            self.assertTrue(plan["approval_request"]["asset"]["content"]["blocking"])
            self.assertGreaterEqual(plan["scheduler_plan"]["task_count"], 1)
            self.assertFalse(plan["scheduler_plan"]["automatic_dispatch"])
            self.assertEqual(plan["scheduler_plan"]["dispatch_queue_paths"], [])
            task = plan["task_plans"][0]["asset"]["content"]
            self.assertEqual(task["status"], "needs_approval")
            self.assertEqual(task["operation"], "generate-chapter-plan")
            self.assertEqual(task["dispatch_queue_path"], "")

    def test_multi_book_scheduler_plan_blocks_high_similarity_before_task_plans(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            self._write_book_identity(storage, "book-a", "都市刑侦", "冷峻第一人称", "旧案重启 证据链 嫌疑人 反转 真相")
            self._write_book_identity(storage, "book-b", "都市刑侦", "冷峻第一人称", "旧案重启 证据链 嫌疑人 反转 真相")
            portfolio = create_portfolio_project(storage, title="Blocked Portfolio", project_ids=["book-a", "book-b"])
            similarity = build_cross_book_similarity_report(storage, portfolio_ref=portfolio["path"], high_threshold=0.45)

            plan = build_multi_book_scheduler_plan(storage, portfolio_ref=portfolio["path"], similarity_ref=similarity["path"])

            self.assertEqual(plan["status"], "blocked_by_similarity")
            self.assertEqual(plan["scheduler_plan"]["task_count"], 0)
            self.assertFalse(plan["scheduler_plan"]["guard_decision"]["shared_context_allowed"])
            self.assertEqual(plan["approval_request"]["asset"]["type"], "approval_request")

    def _write_book_identity(self, storage: LocalStorage, project_id: str, genre: str, style: str, premise: str) -> None:
        metadata = {"project_id": project_id}
        storage.write_asset_auto(GenreProfile(title=f"{project_id} genre", content={"genre": genre, "core_conflict": premise, "core_reader_promise": premise}, metadata=metadata))
        storage.write_asset_auto(StyleProfile(title=f"{project_id} style", content={"voice": style, "rhythm": style, "tone": style}, metadata=metadata))
        storage.write_asset_auto(Outline(title=f"{project_id} outline", content={"premise": premise, "main_arc": premise, "hook_plan": premise}, metadata=metadata))


if __name__ == "__main__":
    unittest.main()
