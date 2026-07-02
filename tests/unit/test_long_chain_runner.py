from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.runtime_ledger import record_model_call_log
from novel_forge.storage.local import LocalStorage


def _load_runner():
    path = Path(__file__).resolve().parents[2] / "scripts" / "run_long_chain_webnovel.py"
    spec = importlib.util.spec_from_file_location("run_long_chain_webnovel", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class LongChainRunnerReportTests(unittest.TestCase):
    def test_canonicalize_generated_text_repairs_lead_name_alias_drift(self):
        runner = _load_runner()

        repaired, repairs = runner._canonicalize_generated_text("江砚走到夜档司门口，沈砚看见旧账。")

        self.assertEqual(repaired, "沈砚走到夜档司门口，沈砚看见旧账。")
        self.assertEqual(repairs[0]["kind"], "canonical_lead_name_alias_repair")
        self.assertEqual(repairs[0]["count"], 1)

    def test_force_chapter_filter_removes_stale_summary(self):
        runner = _load_runner()

        filtered = runner._filter_forced_chapter_summaries(
            [{"chapter": 118, "summary": "old"}, {"chapter": 119, "summary": "stale"}],
            {119},
        )

        self.assertEqual(filtered, [{"chapter": 118, "summary": "old"}])

    def test_extract_generated_text_unwraps_nested_json_text(self):
        runner = _load_runner()

        text, repairs = runner._extract_generated_text({"text": "{\"text\":\"正文\"}"})

        self.assertEqual(text, "正文")
        self.assertEqual(repairs, [{"kind": "nested_json_text_unwrapped", "field": "text"}])

    def test_foreshadow_lifecycle_uses_payoff_evidence_spans(self):
        runner = _load_runner()
        with tempfile.TemporaryDirectory() as tmp:
            export_dir = Path(tmp) / "export"
            chapter_dir = export_dir / "chapters"
            chapter_dir.mkdir(parents=True)
            (chapter_dir / "chapter_046.md").write_text(
                "# 第046章\n\n沈砚终于在城籍院旧册里补回那条缺一行，户名得以归位。\n",
                encoding="utf-8",
            )
            bible = {
                "long_hooks": [
                    {
                        "id": "ledger_origin",
                        "setup": "missing registry line",
                        "payoff_window": "chapters 35-45",
                    }
                ]
            }

            lifecycle = runner._foreshadow_lifecycle(bible, generated_chapters=47, export_dir=export_dir)

            self.assertEqual(lifecycle["overall_status"], "passed")
            self.assertEqual(lifecycle["overdue_count"], 0)
            self.assertEqual(lifecycle["hooks"][0]["status"], "paid_off")
            self.assertEqual(lifecycle["hooks"][0]["payoff_evidence"][0]["chapter"], 46)

    def test_pressure_report_materializes_acceptance_assets_and_metrics(self):
        runner = _load_runner()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = LocalStorage(root / "workspace")
            storage.ensure_layout()
            export_dir = root / "export"
            chapter_dir = export_dir / "chapters"
            chapter_dir.mkdir(parents=True)
            summaries = []
            for chapter, score, tokens in [(1, 92.0, 1000), (2, 91.0, 1100), (3, 90.0, 1120)]:
                text = f"第{chapter}章，巡档人发现旧案线索，偏偏街坊一句玩笑又把代价推高。"
                (chapter_dir / f"chapter_{chapter:03d}.md").write_text(f"# 第{chapter:03d}章\n\n{text}\n", encoding="utf-8")
                summaries.append({"chapter": chapter, "summary": text, "char_count": len(text), "warnings": [], "quality_score": score})
                record_model_call_log(
                    storage,
                    provider="mock",
                    model="mock-longchain",
                    operation="generate_chapter",
                    usage={"total_tokens": tokens},
                    cost={"amount": 0.0, "currency": "USD"},
                    project_id=runner.PROJECT_ID,
                    source_id=f"chapter-{chapter}",
                )

            bible = {
                "title": "夜档巡遗录",
                "long_hooks": [
                    {"id": "ledger_origin", "setup": "missing registry line", "payoff_window": "chapters 35-45"},
                    {"id": "mentor_debt", "setup": "debt measured in solved cases", "payoff_window": "chapters 55-70"},
                ],
            }

            created = runner._ensure_acceptance_assets(storage, export_dir, summaries, bible, target_chars=5000)
            report = runner._quality_report(storage, export_dir, 100, 5000, summaries, [], {"path": "data/runs/report.json"}, bible, created)

            self.assertEqual(created["chapter_production_run"], 3)
            self.assertEqual(created["context_bundle"], 3)
            self.assertEqual(created["chapter_continuity_report"], 3)
            self.assertEqual(created["feedback_backflow_plan"], 1)
            self.assertEqual(report["cost_drift"]["model_call_count"], 3)
            self.assertEqual(report["quality_drift"]["status"], "passed")
            self.assertEqual(report["foreshadowing_lifecycle"]["overall_status"], "passed")
            self.assertEqual(report["feedback_backflow"]["status"], "passed")
            self.assertIn(report["pressure_acceptance"]["recommendation"], {"continue", "continue_with_watch"})


if __name__ == "__main__":
    unittest.main()
