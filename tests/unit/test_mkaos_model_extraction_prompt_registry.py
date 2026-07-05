from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_model_extraction import create_prompt_version, ensure_default_prompt_versions, list_prompt_versions
from novel_forge.storage.local import LocalStorage


class MkaosModelExtractionPromptRegistryTests(unittest.TestCase):
    def test_default_prompt_versions_are_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            prompts = ensure_default_prompt_versions(storage, project_id="prompt-p")

            self.assertGreaterEqual(len(prompts), 4)
            self.assertTrue(any(row["content"]["source_type"] == "professional_book" for row in prompts))
            self.assertTrue(all("raw_text" in row["content"]["forbidden_fields"] for row in prompts))

    def test_custom_prompt_version_can_be_listed_by_source_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            create_prompt_version(storage, {"project_id": "prompt-p", "source_type": "training", "prompt_id": "training_extraction_custom", "instruction": "Extract training mechanisms.", "status": "active"})
            rows = list_prompt_versions(storage, project_id="prompt-p", source_type="training")

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["content"]["prompt_id"], "training_extraction_custom")


if __name__ == "__main__":
    unittest.main()
