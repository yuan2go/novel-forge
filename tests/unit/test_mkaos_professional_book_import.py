from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


BOOK_FIXTURE = """
# 第一章 制度如何制造冲突

制度会改变资源分配。权力结构会让一方获利，另一方承担代价。
小说生产中，这类专业知识必须转成人物行动、选择和场景阻碍。

## 税源与地方豪强

税源减少会迫使县衙追索田契，地方豪强会利用组织优势扩大控制。
这可以转成主角被卷入案卷、粮仓和佃户冲突。

# 第二章 证据链与推理

证据链需要公平线索、因果顺序和可复盘位置。
突然反转必须有前置证据，否则会造成读者理解断裂。

# 第三章 动机与选择

人物心理不是说明文字，而是目标受阻后的选择。
动机必须通过行为、关系债务和代价体现。
"""


class MkaosProfessionalBookImportTests(MkaosP1TestCase):
    def test_professional_book_import_run_builds_sections_candidates_approvals_and_relations(self):
        result = mkaos.run_professional_book_import(
            self.storage,
            {
                "project_id": self.project_id,
                "title": "专业书导入样例",
                "source_format": "markdown",
                "text": BOOK_FIXTURE,
                "target_chars": 120,
                "max_extraction_chunks": 10,
            },
        )["data"]

        self.assertEqual(result["parser_report"]["status"], "parsed")
        self.assertGreaterEqual(result["section_count"], 3)
        self.assertGreaterEqual(result["chunk_count"], 3)
        self.assertGreaterEqual(result["candidate_counts"]["knowledge_card_candidate"], 3)
        self.assertGreaterEqual(result["candidate_counts"]["rule_card_candidate"], 1)
        self.assertGreaterEqual(result["candidate_counts"]["template_card_candidate"], 1)
        self.assertGreaterEqual(result["approval_queue"]["approval_count"], result["candidate_counts"]["knowledge_card_candidate"])
        self.assertGreaterEqual(result["relation_report"]["relation_count"], 1)
        self.assertFalse(result["source_isolation"]["raw_text_included"])
        self.assertNotIn("制度会改变资源分配", str(result))

    def test_professional_book_approval_can_promote_knowledge_candidate(self):
        result = mkaos.run_professional_book_import(
            self.storage,
            {
                "project_id": self.project_id,
                "title": "审批样例",
                "source_format": "markdown",
                "text": BOOK_FIXTURE,
                "target_chars": 180,
                "max_extraction_chunks": 3,
            },
        )["data"]
        approval = next(item for item in result["approval_queue"]["approvals"] if item["action_type"] == "approve_knowledge_candidate")

        resolved = mkaos.resolve_governance_approval(
            self.storage,
            approval["approval_id"],
            {"status": "approved", "apply": True, "actor": "unit-test"},
        )

        self.assertEqual(resolved["asset"]["content"]["status"], "applied")
        self.assertEqual(resolved["applied"]["asset_type"], "knowledge_card")
        cards = mkaos.list_knowledge_cards(self.storage, project_id=self.project_id)
        self.assertTrue(any(row["id"] == resolved["applied"]["asset_id"] for row in cards))
