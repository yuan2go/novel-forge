from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.portfolio_os import build_book_potential_scores, build_resource_allocation_plan, create_portfolio_project
from novel_forge.schemas import ChapterPlan, DraftChapter, QualityScoreReport, ReviewIssue
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


if __name__ == "__main__":
    unittest.main()
