from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_ingestion import detect_corpus_type, scan_classical_modern_repository


class MkaosClassicalModernAdapterTests(unittest.TestCase):
    def test_scan_detects_classical_modern_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "古文原文" / "论语" / "学而").mkdir(parents=True)
            (root / "古文原文" / "论语" / "学而" / "text.txt").write_text("子曰：学而时习之。", encoding="utf-8")
            (root / "双语数据" / "论语").mkdir(parents=True)
            (root / "双语数据" / "论语" / "bitext.txt").write_text("子曰：学而时习之。|||孔子说：学习后复习。", encoding="utf-8")

            corpus = detect_corpus_type(root)
            scan = scan_classical_modern_repository(root)

            self.assertEqual(corpus["corpus_type"], "classical_modern_parallel_corpus")
            self.assertTrue(scan["detected_structure"]["has_classical_original"])
            self.assertEqual(scan["original_file_count"], 1)
            self.assertEqual(scan["pair_preview"][0]["raw_text_allowed_for_prose"], False)


if __name__ == "__main__":
    unittest.main()
