from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules import mkaos
from novel_forge.modules.longform_stability import create_arc_plan, create_canon_database
from novel_forge.schemas import CharacterStateLedger, DraftChapter
from novel_forge.storage.local import LocalStorage


class MkaosCanonSemanticGraphTests(unittest.TestCase):
    def test_semantic_graph_check_extends_explicit_canon_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            create_canon_database(
                storage,
                project_id="canon-semantic",
                entities=[{"entity_id": "azhao", "entity_type": "character", "canonical_name": "阿照", "status": "active", "aliases": [], "forbidden_aliases": ["沈砚"]}],
            )
            create_arc_plan(
                storage,
                arc_id="tax-arc",
                title="旧税契卷",
                chapter_range="1-10",
                arc_question="竹筹是谁留下的",
                protagonist_goal="查明旧税契",
                villain_goal="拖延归档",
                required_payoffs=["解释竹筹来源"],
                forbidden_expansion=["无关宗门线"],
                project_id="canon-semantic",
            )
            storage.write_asset(
                "continuity",
                CharacterStateLedger(
                    title="Character state ledger",
                    content={"ledger_id": "ledger", "chapter_no": 2, "characters": [{"character_id": "azhao", "canonical_name": "阿照", "status": "dead"}]},
                    metadata={"project_id": "canon-semantic"},
                ),
            )
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Semantic canon conflict",
                    content={"chapter": 3, "text": "沈砚带着无关宗门线回到夜档司，还让阿照现身开口说话。"},
                    metadata={"project_id": "canon-semantic"},
                ),
            )

            report = mkaos.check_canon_semantic_graph_conflict(
                storage,
                {"project_id": "canon-semantic", "target_path": str(draft_path.relative_to(storage.root)), "persist": True},
            )["data"]

            self.assertFalse(report["passed"])
            self.assertTrue(report["graph_check"]["conflicts"])
            self.assertTrue(any(issue["issue_type"] == "canon_conflict" for issue in report["issue_candidates"]))
            self.assertEqual(report["reasoning_mode"], "explicit_claims_plus_canon_graph_reasoning")

            compat = mkaos.check_canon_conflict(
                storage,
                {"project_id": "canon-semantic", "target_path": str(draft_path.relative_to(storage.root)), "enable_semantic_graph": True},
            )
            self.assertFalse(compat["passed"])
            self.assertTrue(compat["semantic_graph"]["conflicts"])
