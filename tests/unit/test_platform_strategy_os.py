from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.planning_context import build_planning_context
from novel_forge.modules.platform_strategy import (
    assess_platform_retention_risk,
    build_platform_strategy_pack,
    create_platform_feedback_backflow,
    ensure_default_platform_strategy_assets,
    evaluate_platform_chapter_gate,
    evaluate_platform_opening_gate,
    prepare_platform_publish_adapter,
)
from novel_forge.modules.workspace.service import init_workspace
from novel_forge.schemas import CharacterCard
from novel_forge.storage.local import LocalStorage
from tests.unit.legacy_compatibility import legacy_settings


class PlatformStrategyOSTests(unittest.TestCase):
    def test_same_topic_gets_different_platform_strategy_packs(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            defaults = ensure_default_platform_strategy_assets(storage)

            qidian = build_platform_strategy_pack(storage, {"platform": "起点", "topic": "县城诡案", "genre": "悬疑", "project_id": "platform-p"})
            fanqie = build_platform_strategy_pack(storage, {"platform": "番茄", "topic": "县城诡案", "genre": "悬疑", "project_id": "platform-p"})
            feilu = build_platform_strategy_pack(storage, {"platform": "飞卢", "topic": "县城诡案", "genre": "悬疑", "project_id": "platform-p"})

            self.assertGreaterEqual(defaults["platform_count"], 6)
            self.assertEqual(qidian["asset"]["content"]["platform_id"], "qidian")
            self.assertEqual(fanqie["asset"]["content"]["platform_id"], "fanqie")
            self.assertIn("世界规则压力", qidian["asset"]["content"]["chapter_strategy"]["beat_cadence"])
            self.assertIn("直接压力", fanqie["asset"]["content"]["chapter_strategy"]["beat_cadence"])
            self.assertIn("身份差展示", feilu["asset"]["content"]["chapter_strategy"]["beat_cadence"])
            self.assertGreater(qidian["asset"]["content"]["chapter_strategy"]["word_budget"]["ideal"], fanqie["asset"]["content"]["chapter_strategy"]["word_budget"]["ideal"])

    def test_platform_gates_retention_publish_and_feedback_backflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            opening = evaluate_platform_opening_gate(
                storage,
                {
                    "platform": "番茄",
                    "project_id": "platform-p",
                    "topic": "县城诡案",
                    "opening_text": "三段内冲突爆发：她刚进门就发现合同不见了。母亲哭着说出强情绪痛点，低门槛问题立刻成立，首章反转逼她选择。",
                },
            )
            chapter = evaluate_platform_chapter_gate(
                storage,
                {
                    "platform": "飞卢",
                    "project_id": "platform-p",
                    "topic": "县城诡案",
                    "chapter_text": "身份差摆在众人面前，对方当众压制或挑衅。主角反手打脸，奖励反馈立刻到账，下一次更大挑衅已经堵在门外。",
                },
            )
            risk = assess_platform_retention_risk(
                storage,
                {
                    "platform": "知乎盐选",
                    "project_id": "platform-p",
                    "topic": "县城诡案",
                    "metrics": {"completion_rate": 0.42, "follow_read_rate": 0.38, "reversal_gap_chapters": 3},
                    "feedback": ["开头慢", "证据看不懂"],
                },
            )
            publish = prepare_platform_publish_adapter(storage, {"platform": "微信读书/出版向", "project_id": "platform-p", "topic": "县城诡案"})
            backflow = create_platform_feedback_backflow(storage, {"platform": "起点", "project_id": "platform-p", "signals": ["付费前留存下降"]})

            self.assertTrue(opening["passed"])
            self.assertTrue(chapter["passed"])
            self.assertEqual(risk["asset"]["type"], "platform_retention_risk")
            self.assertIn(risk["asset"]["content"]["risk_level"], {"high", "critical"})
            self.assertTrue(publish["release_payload_contract"]["checklist"])
            self.assertEqual(backflow["asset"]["type"], "platform_feedback_backflow")
            self.assertTrue(backflow["asset"]["content"]["plan_adjustments"])

    def test_planning_context_injects_platform_strategy_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = init_workspace(storage, "Platform Project")
            workspace_ref = str(workspace.relative_to(storage.root))
            workspace_data = storage.read_json(workspace)
            workspace_data["content"]["project_config"]["target_platform"] = "番茄"
            workspace_data["content"]["project_config"]["genre"] = "悬疑"
            storage.write_json(workspace, workspace_data)
            project_id = workspace_data["content"]["project_id"]
            character_path = storage.write_asset(
                "characters",
                CharacterCard(
                    title="主角",
                    content={"role": "protagonist", "external_goal": "查清合同消失", "internal_need": "承担家庭代价", "motivation_chain": ["保护母亲", "追查真相"]},
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                ),
            )

            context = build_planning_context(storage, storage.read_asset(character_path), input_path=character_path, workspace_path=workspace_ref, chapter=1)

            self.assertEqual(context["platform_strategy"]["platform_id"], "fanqie")
            self.assertTrue(context["platform_strategy"]["path"])
            self.assertTrue(context["required_context"]["platform_strategy"])
            self.assertIn("直接压力", context["platform_strategy"]["content"]["chapter_strategy"]["beat_cadence"])

    def test_platform_strategy_api_smoke(self):
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")

        from novel_forge.api.app import create_app
        from novel_forge.infrastructure.settings import IndustrialSettings

        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(create_app(legacy_settings(root=Path(tmp).resolve())))
            pack = client.post("/product/platform-strategy/pack", json={"platform": "晋江", "topic": "县城诡案", "project_id": "api-platform-p"})
            self.assertEqual(pack.status_code, 200, pack.text)
            self.assertEqual(pack.json()["asset"]["content"]["platform_id"], "jinjiang")
            assets = client.get("/product/platform-strategy/assets?platform=晋江")
            self.assertEqual(assets.status_code, 200, assets.text)
            self.assertTrue(any(row["type"] == "platform_opening_gate" for row in assets.json()))


if __name__ == "__main__":
    unittest.main()
