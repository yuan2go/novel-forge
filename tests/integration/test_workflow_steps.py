from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.workflows import pipeline


class WorkflowStepTests(unittest.TestCase):
    def test_ingest_clean_decompose_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.txt"
            input_path.write_text("Line 1\n\nLine 2 with clue", encoding="utf-8")
            raw = pipeline.ingest(root, str(input_path))
            cleaned = pipeline.clean(root, str(raw))
            decomp = pipeline.decompose(root, str(cleaned))
            knowledge = pipeline.extract_knowledge(root, str(decomp))
            material = pipeline.build_materials(root, str(knowledge))
            topic = pipeline.generate_topic(root, str(material))
            world = pipeline.generate_world(root, str(topic))
            char = pipeline.generate_characters(root, str(world))
            outline = pipeline.generate_outline(root, str(char))
            chapter = pipeline.generate_chapter_plan(root, str(outline))
            draft = pipeline.draft(root, str(chapter))
            review = pipeline.review(root, str(draft))
            revision = pipeline.revise(root, str(review))
            self.assertTrue(revision.exists())


if __name__ == "__main__":
    unittest.main()
