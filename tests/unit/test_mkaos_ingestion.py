from pathlib import Path
import json
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_ingestion import cancel_ingestion_job, create_extraction_job, create_repository, import_repository, list_books, list_parallel_pairs, read_source_file, resume_ingestion_job, scan_repository
from novel_forge.storage.local import LocalStorage


class MkaosIngestionTests(unittest.TestCase):
    def test_repository_scan_and_import_creates_assets_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = _fixture_repo(Path(tmp) / "corpus")
            storage = LocalStorage(Path(tmp) / "workspace")
            storage.ensure_layout()

            repo = create_repository(storage, {"project_id": "ingest", "name": "Classical Modern", "local_path": str(repo_root), "source_type": "classical_text"})["asset"]
            scan = scan_repository(storage, repo["id"])
            imported = import_repository(storage, repo["id"])

            self.assertEqual(scan["manifest"]["type"], "repository_manifest")
            self.assertGreaterEqual(len(list_books(storage, project_id="ingest")), 1)
            pairs = list_parallel_pairs(storage, project_id="ingest")
            self.assertTrue(pairs)
            self.assertTrue(pairs[0]["content"]["evidence_layer_only"])
            self.assertFalse(pairs[0]["content"]["raw_text_allowed_for_prose"])
            self.assertEqual(imported["report"]["type"], "import_quality_report")
            chapter = imported["chapters"][0]
            self.assertIn("section_manifest", chapter["content"])
            self.assertFalse(chapter["content"]["source_isolation"]["section_text_included"])
            self.assertNotIn("text", chapter["content"]["section_manifest"][0])

    def test_format_adapters_support_p0_file_types_without_external_deps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("plain", encoding="utf-8")
            (root / "a.md").write_text("# title\nbody", encoding="utf-8")
            (root / "a.json").write_text(json.dumps({"x": "json text"}, ensure_ascii=False), encoding="utf-8")
            (root / "a.csv").write_text("a,b\n1,2\n", encoding="utf-8")
            (root / "a.pdf").write_bytes(b"%PDF-1.4\n(Hello PDF)\n%%EOF")
            with zipfile.ZipFile(root / "a.docx", "w") as archive:
                archive.writestr("word/document.xml", "<w:document><w:body><w:p><w:r><w:t>Hello DOCX</w:t></w:r></w:p></w:body></w:document>")
            with zipfile.ZipFile(root / "a.epub", "w") as archive:
                archive.writestr("OPS/chapter.xhtml", "<html><body>Hello EPUB</body></html>")

            for name in ["a.txt", "a.md", "a.json", "a.csv", "a.pdf", "a.docx", "a.epub"]:
                with self.subTest(name=name):
                    result = read_source_file(root / name)
                    self.assertTrue(result["text"])
                    self.assertIn("parser_quality", result["metadata"])
                    self.assertIn("sections", result)

    def test_docx_adapter_preserves_heading_manifest_without_external_dependency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with zipfile.ZipFile(root / "heading.docx", "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
                    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>第一章 机制</w:t></w:r></w:p>
                    <w:p><w:r><w:t>制度压力推动角色选择。</w:t></w:r></w:p>
                    </w:body></w:document>""",
                )
            result = read_source_file(root / "heading.docx")
            self.assertEqual(result["toc"][0]["title"], "第一章 机制")
            self.assertGreaterEqual(result["metadata"]["section_count"], 1)

    def test_ingestion_job_cancel_and_resume_records_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(Path(tmp) / "workspace")
            storage.ensure_layout()
            job = create_extraction_job(storage, {"project_id": "jobs", "source_type": "professional_book"})["job"]
            cancelled = cancel_ingestion_job(storage, job["id"], {"force": True, "reason": "unit-test"})
            self.assertEqual(cancelled["content"]["status"], "cancelled")
            resumed = resume_ingestion_job(storage, job["id"], {"force": True, "source_type": "professional_book"})
            self.assertEqual(resumed["resumed_from"], job["id"])
            self.assertIn("job", resumed)


def _fixture_repo(root: Path) -> Path:
    (root / "古文原文" / "论语" / "学而").mkdir(parents=True)
    (root / "古文原文" / "论语" / "学而" / "text.txt").write_text("子曰：学而时习之，不亦说乎？\n礼法造成行动约束。", encoding="utf-8")
    (root / "双语数据" / "论语").mkdir(parents=True)
    (root / "双语数据" / "论语" / "source.txt").write_text("子曰：学而时习之。\n仁者爱人。", encoding="utf-8")
    (root / "双语数据" / "论语" / "target.txt").write_text("孔子说：学习后复习。\n仁德的人关爱他人。", encoding="utf-8")
    return root


if __name__ == "__main__":
    unittest.main()
