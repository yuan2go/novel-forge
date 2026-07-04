from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules import mkaos
from novel_forge.storage.local import LocalStorage


class MkaosP1TestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = LocalStorage(self.tmp.name)
        self.storage.ensure_layout()
        self.project_id = "mkaos-p1"

    def tearDown(self):
        self.tmp.cleanup()

    def seed_knowledge_system(self):
        source = mkaos.import_source_document(
            self.storage,
            {
                "project_id": self.project_id,
                "title": "P1 fixture source",
                "text": "历史制度会改变资源分配。叙事爽点需要选择代价。悬疑证据链需要公平线索。",
                "source_kind": "manual_note",
            },
        )
        chunk_id = source["chunks"][0]["id"]
        span = mkaos.create_evidence_span(self.storage, chunk_id, {"project_id": self.project_id, "chapter_title": "fixture"})
        history = mkaos.create_knowledge_card(
            self.storage,
            {
                "project_id": self.project_id,
                "concept_name": "土地制度冲突",
                "discipline": "历史制度",
                "knowledge_type": "conflict_mechanism",
                "core_explanation": "制度变化应转成豪强、小农、县衙之间的利益冲突和行动代价。",
                "source_chunk_ids": [chunk_id],
                "evidence_span_refs": [span["asset"]["id"]],
                "applicable_genres": ["历史", "玄幻"],
                "applicable_platforms": ["qidian", "fanqie", "publishing"],
                "platform_weights": {"fanqie": 1.4, "publishing": 0.5},
                "genre_weights": {"历史": 1.5, "玄幻": 0.6},
                "quality_dimensions": {"abstraction_score": 0.9, "actionability_score": 0.9, "copyright_risk_score": 0.05},
                "weight": 1.0,
            },
        )
        mystery = mkaos.create_knowledge_card(
            self.storage,
            {
                "project_id": self.project_id,
                "concept_name": "公平证据链",
                "discipline": "逻辑学",
                "knowledge_type": "mystery_chain",
                "core_explanation": "悬疑线索必须可复盘，误导和真相都要有证据位置。",
                "source_chunk_ids": [chunk_id],
                "evidence_span_refs": [span["asset"]["id"]],
                "applicable_genres": ["悬疑"],
                "applicable_platforms": ["zhihu_yanxuan", "publishing"],
                "genre_weights": {"悬疑": 1.6},
                "quality_dimensions": {"abstraction_score": 0.85, "actionability_score": 0.82, "copyright_risk_score": 0.05},
                "weight": 1.0,
            },
        )
        risky = mkaos.create_knowledge_card(
            self.storage,
            {
                "project_id": self.project_id,
                "concept_name": "高风险原文式知识",
                "discipline": "叙事学",
                "core_explanation": "该知识用于测试隔离和降权。",
                "source_chunk_ids": [chunk_id],
                "risk_level": "high",
                "quality_dimensions": {"copyright_risk_score": 0.9, "abstraction_score": 0.2},
                "weight": 1.0,
            },
        )
        for knowledge in [history, mystery, risky]:
            kid = knowledge["asset"]["id"]
            for flow in ["outline", "chapter_outline", "prose", "review", "revision", "recap", "publish", "feedback"]:
                mkaos.create_usage_binding(
                    self.storage,
                    kid,
                    {
                        "flow": flow,
                        "usage_type": "required" if flow != "prose" else "optional",
                        "input_role": "required" if flow != "prose" else "optional",
                        "output_form": "abstract constraint",
                        "constraint_text": "知识必须转成行动、冲突、场景、证据或审稿检查。",
                        "priority": 10 if kid == history["asset"]["id"] else 20,
                    },
                )
        return {
            "source": source,
            "chunk_id": chunk_id,
            "span": span,
            "history": history,
            "mystery": mystery,
            "risky": risky,
        }
