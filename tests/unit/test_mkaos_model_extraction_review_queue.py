from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_model_extraction import (
    approve_candidate,
    create_model_extraction_job,
    list_review_queue,
    reject_candidate,
    run_model_extraction_job,
)
from novel_forge.storage.local import LocalStorage


class MkaosModelExtractionReviewQueueTests(unittest.TestCase):
    def test_disabled_provider_job_uses_deterministic_candidate_and_review_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            job = create_model_extraction_job(storage, {"project_id": "extract-p", "source_type": "professional_book", "input_summary": "资源约束会制造选择代价。"})
            run = run_model_extraction_job(storage, job["id"], {"provider_mode": "disabled"})

            self.assertEqual(run["status"], "succeeded")
            self.assertEqual(run["candidate_count"], 1)
            queue = list_review_queue(storage, project_id="extract-p")
            self.assertEqual(len(queue), 1)
            self.assertIn(queue[0]["content"]["status"], {"pending", "auto_approved", "auto_rejected"})

    def test_approve_candidate_creates_knowledge_card_and_updates_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            job = create_model_extraction_job(storage, {"project_id": "extract-p", "source_type": "classical_text", "input_summary": "礼法迫使角色付出代价。"})
            run = run_model_extraction_job(storage, job["id"], {"provider_mode": "disabled"})
            candidate_id = run["candidates"][0]["asset"]["id"]

            approved = approve_candidate(storage, candidate_id, {"note": "safe"})

            self.assertEqual(approved["candidate"]["content"]["status"], "approved")
            self.assertEqual(approved["knowledge_card"]["asset"]["type"], "knowledge_card")
            self.assertEqual(list_review_queue(storage, project_id="extract-p")[0]["content"]["status"], "approved")

    def test_reject_candidate_updates_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            job = create_model_extraction_job(storage, {"project_id": "extract-p", "source_type": "mystery", "input_summary": "线索误导形成公平谜题。"})
            run = run_model_extraction_job(storage, job["id"], {"provider_mode": "disabled"})
            candidate_id = run["candidates"][0]["asset"]["id"]

            rejected = reject_candidate(storage, candidate_id, {"reason": "too weak"})

            self.assertEqual(rejected["candidate"]["content"]["status"], "rejected")
            self.assertEqual(list_review_queue(storage, project_id="extract-p")[0]["content"]["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
