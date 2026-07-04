from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosReaderFeedbackAttributionTests(MkaosP1TestCase):
    def test_feedback_text_is_attributed_to_candidate_knowledge(self):
        seeded = self.seed_knowledge_system()
        result = mkaos.attribute_reader_feedback_to_knowledge(
            self.storage,
            {"project_id": self.project_id, "feedback_text": "设定太多，节奏慢", "candidate_knowledge_ids": [seeded["history"]["asset"]["id"]]},
        )
        content = result["asset"]["content"]
        self.assertEqual(content["sentiment"], "negative")
        self.assertIn("pacing", content["issue_tags"])
        self.assertFalse(content["needs_human_review"])
        self.assertFalse(content["source_isolation"]["raw_text_included"])

    def test_unattributed_feedback_needs_human_review(self):
        result = mkaos.attribute_reader_feedback_to_knowledge(self.storage, {"feedback_text": "不知道怎么说"})
        self.assertTrue(result["asset"]["content"]["needs_human_review"])
