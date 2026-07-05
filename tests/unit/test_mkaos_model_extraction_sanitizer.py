from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_model_extraction import sanitize_provider_output


class MkaosModelExtractionSanitizerTests(unittest.TestCase):
    def test_sanitizer_removes_forbidden_provider_fields(self):
        output = {
            "candidates": [
                {
                    "concept_name": "礼法压力",
                    "creative_principle": "转成行动代价",
                    "raw_text": "forbidden raw",
                    "nested": {"source_text": "forbidden source"},
                }
            ],
            "quote": "forbidden quote",
        }

        result = sanitize_provider_output(output)

        self.assertEqual(result["forbidden_field_count"], 3)
        self.assertNotIn("quote", result["sanitized"])
        self.assertNotIn("raw_text", result["sanitized"]["candidates"][0])
        self.assertNotIn("source_text", result["sanitized"]["candidates"][0]["nested"])
        self.assertFalse(result["source_isolation"]["raw_text_included"])


if __name__ == "__main__":
    unittest.main()
