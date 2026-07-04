from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_ingestion import parse_bitext_text, parse_parallel_pair_files


class MkaosParallelPairParserTests(unittest.TestCase):
    def test_parse_bitext_keeps_pairs_evidence_only(self):
        pairs = parse_bitext_text("子曰：学而时习之。|||孔子说：学习后复习。\n仁者爱人\t有仁德的人关爱他人。", book_id="book-1")

        self.assertEqual(len(pairs), 2)
        self.assertTrue(pairs[0]["evidence_layer_only"])
        self.assertFalse(pairs[0]["raw_text_allowed_for_prose"])
        self.assertIn("content_hash", pairs[0])

    def test_parse_source_target_files_aligns_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.txt"
            target = root / "target.txt"
            source.write_text("甲\n乙\n", encoding="utf-8")
            target.write_text("A\nB\nC\n", encoding="utf-8")

            pairs = parse_parallel_pair_files(source, target, book_id="book-1")

            self.assertEqual([pair["source_text"] for pair in pairs], ["甲", "乙"])
            self.assertEqual([pair["target_text"] for pair in pairs], ["A", "B"])


if __name__ == "__main__":
    unittest.main()
