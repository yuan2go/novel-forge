from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosImportPipelineTests(MkaosP1TestCase):
    def test_dry_run_and_high_risk_policy(self):
        dry = mkaos.import_source_with_pipeline(self.storage, {"source_kind": "professional_book", "text": "制度资料", "dry_run": True})
        self.assertTrue(dry["import_report"]["dry_run"])
        self.assertFalse(dry["import_report"]["source_policy"]["allow_downstream_generation"])
        real = mkaos.import_source_with_pipeline(self.storage, {"project_id": self.project_id, "source_kind": "platform_rule", "text": "平台节奏规则"})
        self.assertTrue(real["source"]["chunks"])
        self.assertEqual(real["import_report"]["source_kind"], "platform_rule")
