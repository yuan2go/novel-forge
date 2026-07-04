from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_ingestion import (
    classical_text_extractor,
    mystery_extractor,
    professional_book_extractor,
    source_type_profile,
    webnovel_extractor,
)


class MkaosSourceTypeExtractorTests(unittest.TestCase):
    def test_all_first_slice_extractors_return_creative_payloads(self):
        extractors = [
            classical_text_extractor,
            webnovel_extractor,
            professional_book_extractor,
            mystery_extractor,
        ]
        for extractor in extractors:
            with self.subTest(extractor=extractor.__name__):
                cards = extractor({"text": "人物在秩序压力下做选择，并承担代价。"})
                self.assertEqual(cards[0]["knowledge_subtype"], "creative_knowledge_card")
                self.assertTrue(cards[0]["creative_principle"])
                self.assertTrue(cards[0]["applicable_flows"])
                self.assertIn("originality_boundary", cards[0])

    def test_source_type_registry_has_recommended_flows(self):
        profile = source_type_profile("mystery")
        self.assertIn("review", profile["recommended_flows"])


if __name__ == "__main__":
    unittest.main()
