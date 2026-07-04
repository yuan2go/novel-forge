from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosAntiEncyclopediaTests(MkaosP1TestCase):
    def test_regression_examples(self):
        examples = [
            ("历史制度百科化反例", "土地兼并是一种制度现象。\n\n它的本质是税源变化。", False),
            ("历史制度行动化正例", "田契被拍在案上，佃户的手抖了一下。", True),
            ("哲学概念堆叠反例", "所谓自由，本质上是选择。因此概念需要解释。\n\n这种概念导致人物变化。", False),
            ("哲学人物选择正例", "他看着两扇门，只能救一个人。", True),
            ("心理学解释堆叠反例", "他的心理防御机制导致回避。\n\n这种概念本质上是创伤反应。", False),
            ("心理学行为呈现正例", "她把信塞回抽屉，笑着说没事。", True),
            ("玄幻设定堆叠反例", "灵脉制度的本质是资源规则。\n\n因此等级概念必须说明。", False),
            ("玄幻冲突呈现正例", "灵石裂开，护阵暗了一格，门外的人笑了。", True),
            ("平台规则机械解释反例", "番茄规则要求强反转，因此章节需要节奏概念。", False),
            ("平台节奏转章节钩子正例", "门开时，欠条上多了主角的名字。", True),
        ]
        for name, text, expected_passed in examples:
            with self.subTest(name=name):
                result = mkaos.anti_encyclopedia_diagnostics(self.storage, {"text": text})
                self.assertEqual(result["passed"], expected_passed)
                self.assertFalse(result["source_isolation"]["raw_text_included"])
