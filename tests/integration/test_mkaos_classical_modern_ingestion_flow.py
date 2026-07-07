from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_converters import convert_creative_assets
from novel_forge.modules.mkaos_ingestion import create_repository, import_repository, run_source_type_extractor
from novel_forge.storage.local import LocalStorage


class MkaosClassicalModernIngestionFlowTests(unittest.TestCase):
    def test_classical_modern_flow_imports_extracts_and_converts(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp) / "corpus"
            (repo_root / "古文原文" / "论语" / "学而").mkdir(parents=True)
            (repo_root / "古文原文" / "论语" / "学而" / "text.txt").write_text("子曰：学而时习之，不亦说乎？礼法形成秩序压力。", encoding="utf-8")
            (repo_root / "双语数据" / "论语").mkdir(parents=True)
            (repo_root / "双语数据" / "论语" / "bitext.txt").write_text("子曰：学而时习之。|||孔子说：学习后复习。", encoding="utf-8")
            storage = LocalStorage(Path(tmp) / "workspace")
            storage.ensure_layout()

            repo = create_repository(storage, {"project_id": "flow", "name": "Classical Modern", "local_path": str(repo_root), "source_type": "classical_text"})["asset"]
            imported = import_repository(storage, repo["id"])
            extracted = run_source_type_extractor(storage, {"project_id": "flow", "source_type": "classical_text", "text": imported["chapters"][0]["content"]["abstract_preview"]})
            converted = convert_creative_assets(storage, {"project_id": "flow", "knowledge_ids": [extracted["created"][0]["id"]], "conversion_types": ["world_rule_card"], "dry_run": False})

            self.assertEqual(imported["report"]["content"]["failure_count"], 0)
            self.assertEqual(extracted["created_count"], 1)
            self.assertEqual(converted["converted"][0]["type"], "world_rule_card")
            self.assertNotIn("子曰", str(converted["converted"][0]["content"]))
            self.assertNotIn("孔子说", str(converted["converted"][0]["content"]))

    def test_classical_modern_import_can_run_in_bounded_window_without_parallel_pairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp) / "corpus"
            for book_name in ["论语", "孟子"]:
                (repo_root / "古文原文" / book_name / "篇一").mkdir(parents=True)
                (repo_root / "古文原文" / book_name / "篇一" / "text.txt").write_text(f"{book_name} 形成秩序压力。", encoding="utf-8")
                (repo_root / "双语数据" / book_name).mkdir(parents=True)
                (repo_root / "双语数据" / book_name / "bitext.txt").write_text("古文。|||现代文。", encoding="utf-8")
            storage = LocalStorage(Path(tmp) / "workspace")
            storage.ensure_layout()

            repo = create_repository(storage, {"project_id": "flow-window", "name": "Classical Modern", "local_path": str(repo_root), "source_type": "classical_modern_parallel_corpus"})["asset"]
            imported = import_repository(storage, repo["id"], {"max_books": 1, "include_parallel_pairs": False})

            self.assertEqual(imported["report"]["content"]["book_count"], 1)
            self.assertEqual(imported["report"]["content"]["chapter_count"], 1)
            self.assertEqual(imported["report"]["content"]["parallel_pair_count"], 0)
            self.assertTrue(imported["report"]["content"]["import_window"]["resume_recommended"])


if __name__ == "__main__":
    unittest.main()
