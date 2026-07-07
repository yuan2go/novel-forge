from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules import mkaos
from novel_forge.modules.materials import build_materials
from novel_forge.modules.source_intake import create_source_policy, create_source_risk_report
from novel_forge.schemas import KnowledgeCard
from novel_forge.storage.local import LocalStorage


class MkaosSourceEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = LocalStorage(self.tmp.name)
        self.storage.ensure_layout()
        self.project_id = "mkaos-source-eligibility"

    def tearDown(self):
        self.tmp.cleanup()

    def test_source_eligibility_refs_are_written_to_production_knowledge_card(self):
        source_ref = "owned-source-notebook"
        source = mkaos.import_source_document(
            self.storage,
            {
                "project_id": self.project_id,
                "title": "Owned notebook",
                "source_uri": source_ref,
                "text": "自有素材：制度压力改变角色选择成本。",
                "rights": {"authorization": "public_domain", "allow_downstream_generation": True},
            },
        )
        policy = create_source_policy(self.storage, {"project_id": self.project_id, "source_ref": source_ref, "risk_tier": "R1"})
        risk = create_source_risk_report(
            self.storage,
            {
                "project_id": self.project_id,
                "source_ref": source_ref,
                "source_policy_path": policy["path"],
                "risk_tier": "R1",
            },
        )

        card = mkaos.create_knowledge_card(
            self.storage,
            {
                "project_id": self.project_id,
                "environment": "production",
                "os_envelope": _production_envelope(self.project_id),
                "concept_name": "制度压力转选择成本",
                "discipline": "历史制度",
                "knowledge_type": "conflict_mechanism",
                "core_explanation": "制度压力必须改变角色选择、代价和行动路径。",
                "source_chunk_ids": [source["chunks"][0]["id"]],
                "source_policy_path": policy["path"],
                "risk_report_path": risk["path"],
            },
        )

        content = card["asset"]["content"]
        eligibility = content["source_eligibility"]
        self.assertEqual(eligibility["status"], "passed")
        self.assertTrue(eligibility["generation_context_allowed"])
        self.assertIn(policy["asset"]["id"], eligibility["source_policy_refs"])
        self.assertIn(risk["asset"]["id"], eligibility["source_risk_report_refs"])
        self.assertEqual(card["asset"]["metadata"]["source_eligibility_status"], "passed")

    def test_production_knowledge_card_fails_closed_without_source_governance_evidence(self):
        source = mkaos.import_source_document(
            self.storage,
            {
                "project_id": self.project_id,
                "title": "Unreviewed source",
                "source_uri": "unreviewed-source",
                "text": "未评审资料只能作为 evidence，不能直接进入生产知识卡。",
            },
        )

        with self.assertRaisesRegex(ValueError, "source eligibility blocks production knowledge card"):
            mkaos.create_knowledge_card(
                self.storage,
                {
                    "project_id": self.project_id,
                    "environment": "production",
                    "os_envelope": _production_envelope(self.project_id),
                    "concept_name": "未治理来源知识",
                    "core_explanation": "这条知识缺少 SourcePolicy 和 SourceRiskReport。",
                    "source_chunk_ids": [source["chunks"][0]["id"]],
                },
            )

    def test_production_pack_selects_only_source_governed_knowledge(self):
        source_ref = "licensed-outline-source"
        source = mkaos.import_source_document(
            self.storage,
            {
                "project_id": self.project_id,
                "title": "Licensed source",
                "source_uri": source_ref,
                "text": "许可素材抽象成大纲阶段的冲突规则。",
                "rights": {"authorization": "licensed", "allow_downstream_generation": True},
            },
        )
        policy = create_source_policy(self.storage, {"project_id": self.project_id, "source_ref": source_ref, "risk_tier": "R1"})
        risk = create_source_risk_report(self.storage, {"project_id": self.project_id, "source_ref": source_ref, "source_policy_path": policy["path"], "risk_tier": "R1"})
        card = mkaos.create_knowledge_card(
            self.storage,
            {
                "project_id": self.project_id,
                "environment": "production",
                "os_envelope": _production_envelope(self.project_id),
                "concept_name": "许可冲突规则",
                "discipline": "叙事学",
                "core_explanation": "冲突规则必须转成目标、阻碍、代价和反转。",
                "source_chunk_ids": [source["chunks"][0]["id"]],
                "source_policy_path": policy["path"],
                "risk_report_path": risk["path"],
            },
        )
        mkaos.create_usage_binding(
            self.storage,
            card["asset"]["id"],
            {"flow": "outline", "usage_type": "required", "input_role": "required"},
        )

        pack = mkaos.build_knowledge_pack(
            self.storage,
            {
                "project_id": self.project_id,
                "flow": "outline",
                "task_id": "source-eligibility-pack",
                "environment": "production",
                "os_envelope": _production_envelope(self.project_id),
            },
        )

        selected = {item["knowledge_id"] for item in pack["asset"]["content"]["pack_items"]}
        self.assertIn(card["asset"]["id"], selected)
        self.assertEqual(pack["asset"]["content"]["pack_items"][0]["source_eligibility"]["status"], "passed")

    def test_material_card_inherits_source_eligibility_and_blocks_unreviewed_production_source(self):
        governed = self._governed_knowledge_card("material-governed-source")
        material_path = build_materials(self.storage, governed["path"], environment="production")
        material = self.storage.read_json(material_path)
        self.assertEqual(material["content"]["source_eligibility"]["status"], "passed")
        self.assertTrue(material["content"]["source_boundary"]["inherits_knowledge_source_eligibility"])
        self.assertTrue(material["metadata"]["source_policy_refs"])

        unreviewed_source = mkaos.import_source_document(
            self.storage,
            {
                "project_id": self.project_id,
                "title": "Local unreviewed source",
                "source_uri": "local-unreviewed-source",
                "text": "未评审资料在本地可以抽象，但不能进入 production 素材。",
            },
        )
        local_card = mkaos.create_knowledge_card(
            self.storage,
            {
                "project_id": self.project_id,
                "concept_name": "本地未评审机制",
                "core_explanation": "本地未评审机制只允许停留在 needs_review。",
                "source_chunk_ids": [unreviewed_source["chunks"][0]["id"]],
            },
        )
        with self.assertRaisesRegex(ValueError, "Material source eligibility blocks production material card"):
            build_materials(self.storage, local_card["path"], environment="production")

        legacy_path = self.storage.write_asset(
            "knowledge",
            KnowledgeCard(
                title="Legacy source-derived card",
                content={
                    "principles": ["legacy source-derived card without eligibility"],
                    "source_chunk_ids": ["legacy-source-chunk"],
                },
                metadata={"project_id": self.project_id},
            ),
        )
        with self.assertRaisesRegex(ValueError, "Material source eligibility blocks production material card: missing"):
            build_materials(self.storage, str(legacy_path), environment="production")

    def _governed_knowledge_card(self, source_ref: str) -> dict:
        source = mkaos.import_source_document(
            self.storage,
            {
                "project_id": self.project_id,
                "title": "Governed material source",
                "source_uri": source_ref,
                "text": "治理通过的素材可以抽象为素材卡。",
                "rights": {"authorization": "licensed", "allow_downstream_generation": True},
            },
        )
        policy = create_source_policy(self.storage, {"project_id": self.project_id, "source_ref": source_ref, "risk_tier": "R1"})
        risk = create_source_risk_report(self.storage, {"project_id": self.project_id, "source_ref": source_ref, "source_policy_path": policy["path"], "risk_tier": "R1"})
        return mkaos.create_knowledge_card(
            self.storage,
            {
                "project_id": self.project_id,
                "environment": "production",
                "os_envelope": _production_envelope(self.project_id),
                "concept_name": "治理通过素材机制",
                "core_explanation": "治理通过素材只能以抽象机制进入素材卡。",
                "source_chunk_ids": [source["chunks"][0]["id"]],
                "source_policy_path": policy["path"],
                "risk_report_path": risk["path"],
            },
        )


def _production_envelope(project_id: str) -> dict:
    return {
        "envelope_id": f"env-{project_id}",
        "trace_id": f"trace-{project_id}",
        "environment": "production",
        "project_id": project_id,
        "source_policy": {"raw_source_text_allowed": False, "generation_rag_allowed": False, "source_chunk_raw_text_allowed": False},
    }
