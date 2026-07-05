from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_model_extraction import approve_candidate, create_model_extraction_job, run_model_extraction_job
from novel_forge.storage.local import LocalStorage


class MkaosModelExtractionToKnowledgeCardTests(unittest.TestCase):
    def test_model_extraction_candidate_can_be_approved_into_creative_knowledge_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            job = create_model_extraction_job(storage, {"project_id": "mx-chain", "source_type": "professional_book", "input_summary": "治理机制必须转成角色行动和成本。"})
            run = run_model_extraction_job(storage, job["id"], {"provider_mode": "disabled"})
            candidate_id = run["candidates"][0]["asset"]["id"]
            approved = approve_candidate(storage, candidate_id, {"note": "deterministic safe fixture"})

            card = approved["knowledge_card"]["asset"]
            self.assertEqual(card["type"], "knowledge_card")
            self.assertEqual(card["content"]["knowledge_subtype"], "creative_knowledge_card")
            self.assertEqual(card["source"], candidate_id)
            self.assertNotIn("forbidden raw", str(card["content"]))


if __name__ == "__main__":
    unittest.main()
