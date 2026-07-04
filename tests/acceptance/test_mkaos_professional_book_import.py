from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules import mkaos
from novel_forge.storage.local import LocalStorage


class MkaosProfessionalBookImportAcceptanceTests(unittest.TestCase):
    def test_professional_book_import_acceptance_slice(self):
        text = """
# 制度、证据与人物选择

制度知识要进入小说，必须转成资源分配、行动阻碍和选择代价。

## 权力结构

权力结构会改变谁能调动资源，谁承担税负，谁被迫承担风险。

## 证据链

证据链需要公平线索、因果顺序和可复盘位置，不能靠突然解释解决。

## 人物动机

人物动机通过行为、关系债务和选择代价体现，而不是心理学说明。
"""
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            result = mkaos.run_professional_book_import(
                storage,
                {
                    "project_id": "professional-book-acceptance",
                    "title": "专业书导入验收样例",
                    "source_format": "markdown",
                    "text": text,
                    "target_chars": 120,
                    "max_extraction_chunks": 8,
                    "persist_graph": True,
                },
            )["data"]

            self.assertTrue(result["source_document_id"])
            self.assertGreaterEqual(result["chunk_count"], 3)
            self.assertGreaterEqual(result["evidence_span_count"], result["chunk_count"])
            self.assertGreaterEqual(result["candidate_counts"]["knowledge_card_candidate"], 3)
            self.assertGreaterEqual(result["candidate_counts"]["rule_card_candidate"], 1)
            self.assertGreaterEqual(result["candidate_counts"]["template_card_candidate"], 1)
            self.assertGreaterEqual(result["approval_queue"]["approval_count"], 3)
            self.assertGreaterEqual(result["relation_report"]["relation_count"], 1)
            self.assertFalse(result["source_isolation"]["raw_text_included"])
            self.assertNotIn("权力结构会改变谁能调动资源", str(result))


if __name__ == "__main__":
    unittest.main()
