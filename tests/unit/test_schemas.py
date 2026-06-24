from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.schemas import ReviewReport, SCHEMA_CLASSES, SourceDocument, validate_common_fields


class SchemaTests(unittest.TestCase):
    def test_required_schema_count(self):
        self.assertEqual(len(SCHEMA_CLASSES), 25)
        self.assertIn("source_document", SCHEMA_CLASSES)
        self.assertIn("review_report", SCHEMA_CLASSES)

    def test_common_fields_validate(self):
        asset = SourceDocument(title="Sample", source="input.txt", content={"text": "hello"})
        data = asset.to_dict()
        self.assertEqual(validate_common_fields(data), [])
        self.assertEqual(data["type"], "source_document")
        self.assertTrue(data["id"])

    def test_review_report_shape(self):
        report = ReviewReport(title="review", score=75, strengths=["hook"], weaknesses=["motive"])
        data = report.to_dict()
        self.assertEqual(data["score"], 75)
        self.assertIn("revision_suggestions", data)


if __name__ == "__main__":
    unittest.main()
