from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_ingestion import (
    classical_text_extractor,
    extract_by_source_type,
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

    def test_provider_extraction_is_explicit_opt_in_and_source_safe(self):
        default_cards = extract_by_source_type("professional_book", {"text": "绝密原文句子推动制度选择。"})
        self.assertEqual(default_cards[0]["metadata"]["provider_mode"], "deterministic_local")
        self.assertNotIn("绝密原文句子", default_cards[0]["concept_name"])

        provider_cards = extract_by_source_type(
            "professional_book",
            {
                "text": "绝密原文句子推动制度选择。",
                "provider_mode": "mock",
                "enable_provider_extraction": True,
            },
        )
        metadata = provider_cards[0]["metadata"]
        self.assertEqual(metadata["provider_mode"], "mock_opt_in")
        self.assertIn("provider_output_hash", metadata)
        self.assertFalse(metadata["provider_output_source_text_included"])
        self.assertNotIn("绝密原文句子", str(metadata))


if __name__ == "__main__":
    unittest.main()
