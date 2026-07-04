from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_quality import check_quote_leakage


class MkaosQuoteLeakageDetectorTests(unittest.TestCase):
    def test_detects_exact_reuse_without_returning_snippet(self):
        result = check_quote_leakage({"candidate_text": "这里直接复用子曰学而时习之不亦说乎", "source_text": "子曰：学而时习之，不亦说乎？", "min_chars": 8})

        self.assertFalse(result["passed"])
        self.assertIn("span_hash", result["exact_hits"][0])
        self.assertNotIn("子曰", str(result["exact_hits"]))

    def test_clean_candidate_passes(self):
        result = check_quote_leakage({"candidate_text": "人物把伦理压力转成一次无法回避的选择。", "source_text": "子曰：学而时习之，不亦说乎？"})
        self.assertTrue(result["passed"])


if __name__ == "__main__":
    unittest.main()
