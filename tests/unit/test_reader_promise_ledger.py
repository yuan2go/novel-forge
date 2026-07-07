from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.reader_promise import build_reader_promise_ledger_for_draft, create_reader_promise
from novel_forge.schemas import DraftChapter, validate_common_fields
from novel_forge.storage.local import LocalStorage


class ReaderPromiseLedgerTests(unittest.TestCase):
    def test_reader_promise_ledger_creates_promise_from_draft_blueprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Chapter 1",
                    content={
                        "chapter": 1,
                        "text": "阿照把旧账公开，家族代价露出第一角。谁伪造了家族印记仍未回答。",
                        "chapter_plan_blueprint": {
                            "reader_promise": "a public institution hides a family cost",
                            "payoff_target": {
                                "promise_payoff": "family cost becomes visible",
                                "withheld_question": "who forged the family mark",
                            },
                        },
                        "copyright_boundary": "test fixture original draft",
                    },
                    metadata={"project_id": "promise-p1", "workspace_path": "workspaces/promise-p1"},
                ),
            )

            result = build_reader_promise_ledger_for_draft(storage, draft_path, workspace_path="workspaces/promise-p1")
            ledger = result["asset"]

            self.assertEqual(validate_common_fields(ledger), [])
            self.assertEqual(ledger["type"], "reader_promise_ledger")
            self.assertEqual(ledger["content"]["project_id"], "promise-p1")
            self.assertEqual(ledger["content"]["chapter_no"], 1)
            self.assertEqual(ledger["content"]["open_count"], 1)
            self.assertEqual(ledger["content"]["broken_count"], 0)
            self.assertEqual(ledger["content"]["recommendation"], "ready")
            self.assertTrue(ledger["content"]["created_promise_path"])
            promise = storage.read_json(storage.root / ledger["content"]["created_promise_path"])
            self.assertEqual(validate_common_fields(promise), [])
            self.assertEqual(promise["type"], "reader_promise")

    def test_broken_reader_promise_creates_review_issue_and_revision_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            promise = create_reader_promise(
                storage,
                {
                    "project_id": "promise-p1",
                    "workspace_path": "workspaces/promise-p1",
                    "chapter_opened": 1,
                    "promise_text": "the forged seal will identify the hidden clerk",
                    "promise_type": "mystery_clue",
                    "status": "open",
                    "payoff_due_chapter": 2,
                    "evidence_refs": ["operator-plan-note"],
                },
            )
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Chapter 5",
                    content={
                        "chapter": 5,
                        "text": "阿照在旧井旁查到税契，官署又封了桥南账册。新的威胁逼近，但无人解释旧印。",
                        "copyright_boundary": "test fixture original draft",
                    },
                    metadata={"project_id": "promise-p1", "workspace_path": "workspaces/promise-p1"},
                    references=[promise["path"]],
                ),
            )

            result = build_reader_promise_ledger_for_draft(
                storage,
                draft_path,
                workspace_path="workspaces/promise-p1",
                persist_issues=True,
            )
            ledger = result["asset"]

            self.assertEqual(ledger["content"]["broken_count"], 1)
            self.assertEqual(ledger["content"]["recommendation"], "blocked")
            self.assertTrue(result["review_issue_paths"])
            self.assertTrue(result["revision_task_paths"])
            issue = storage.read_json(storage.root / result["review_issue_paths"][0])
            task = storage.read_json(storage.root / result["revision_task_paths"][0])
            self.assertEqual(issue["content"]["issue_type"], "reader_promise_drop")
            self.assertTrue(issue["content"]["blocking"])
            self.assertEqual(task["content"]["status"], "open")
            self.assertEqual(task["content"]["revision_strategy_plan"]["strategy_ids"], ["restore_reader_promise_payoff"])


if __name__ == "__main__":
    unittest.main()
