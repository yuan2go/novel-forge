from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.model_adapters.mock import MockModelAdapter


class MockModelTests(unittest.TestCase):
    def test_methods(self):
        model = MockModelAdapter()
        self.assertTrue(model.health_check()["ok"])
        self.assertIn("text", model.generate("hello"))
        self.assertIn("word_count", model.analyze("one two"))
        self.assertIn("score", model.review("long enough content for review"))
        self.assertEqual(len(model.batch(["a", "b"])), 2)


if __name__ == "__main__":
    unittest.main()
