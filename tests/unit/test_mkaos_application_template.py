from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosApplicationTemplateTests(MkaosP1TestCase):
    def test_knowledge_converts_to_template_with_anti_copy_rules(self):
        seeded = self.seed_knowledge_system()
        template = mkaos.knowledge_to_application_template(self.storage, seeded["history"]["asset"]["id"], {"flow": "outline"})
        content = template["asset"]["content"]
        template_metadata = content["metadata"]
        self.assertIn("no raw source expression", content["anti_copy_rules"])
        self.assertIn("success_criteria", template_metadata)
        self.assertNotIn("历史制度会改变资源分配", str(template))
