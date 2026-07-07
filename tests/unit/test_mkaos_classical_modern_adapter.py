from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_ingestion import detect_corpus_type, scan_classical_modern_repository
from novel_forge.modules.mkaos_ingestion.manifest_builder import build_repository_manifest


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

    def test_classical_modern_manifest_excludes_vcs_and_reproduction_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text("[remote]\n", encoding="utf-8")
            (root / "复现").mkdir()
            (root / "复现" / "train.py").write_text("print('do not import')", encoding="utf-8")
            (root / "README.md").write_text("# corpus", encoding="utf-8")
            (root / "古文原文" / "论语" / "学而").mkdir(parents=True)
            (root / "古文原文" / "论语" / "学而" / "text.txt").write_text("子曰：学而时习之。", encoding="utf-8")
            (root / "双语数据" / "论语").mkdir(parents=True)
            (root / "双语数据" / "论语" / "bitext.txt").write_text("子曰：学而时习之。|||孔子说：学习后复习。", encoding="utf-8")

            manifest = build_repository_manifest(root)

            paths = {row["path"] for row in manifest["files"]}
            self.assertEqual(paths, {"古文原文/论语/学而/text.txt", "双语数据/论语/bitext.txt"})
            self.assertEqual(manifest["stats"]["book_count"], 1)


if __name__ == "__main__":
    unittest.main()
