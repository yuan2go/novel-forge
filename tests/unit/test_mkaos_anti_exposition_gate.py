from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_quality import check_anti_exposition


class MkaosAntiExpositionGateTests(unittest.TestCase):
    def test_blocks_encyclopedia_style_explanation(self):
        result = check_anti_exposition({"text": "礼法是指古代社会规范的概念，主要包括宗族、伦理、秩序等内容。"})
        self.assertFalse(result["passed"])
        self.assertIn("转成人物目标", result["rewrite_suggestions"])

    def test_accepts_conflict_application(self):
        result = check_anti_exposition({"text": "族规逼主角在母亲安危和案卷真相之间选择，代价是失去继承权。"})
        self.assertTrue(result["passed"])


if __name__ == "__main__":
    unittest.main()
