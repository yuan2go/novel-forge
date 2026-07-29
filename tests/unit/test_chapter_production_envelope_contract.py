from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.chapter_production_bus import start_chapter_production
from novel_forge.modules.chapter_production_bus import service as chapter_bus_service
from novel_forge.modules.workspace.service import init_workspace
from novel_forge.schemas import Outline
from novel_forge.storage.local import LocalStorage


class ChapterProductionEnvelopeContractTests(unittest.TestCase):
    def test_production_rejects_missing_envelope_before_run_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace_path = init_workspace(storage, "Envelope contract project")
            workspace = storage.read_asset(workspace_path)
            project_id = str(workspace.content["project_id"])
            outline_path = storage.write_asset(
                "outlines",
                Outline(
                    title="Envelope contract outline",
                    content={"acts": [{"act": 1, "goal": "open the case", "chapters": [{"chapter": 1, "hook": "the bell rings"}]}]},
                    metadata={"project_id": project_id, "workspace_path": str(workspace_path.relative_to(storage.root))},
                ),
            )

            before = _chapter_runs(storage)
            with self.assertRaisesRegex(
                ValueError, "LEGACY_CHAPTER_BUS_PRODUCTION_DISABLED"
            ):
                start_chapter_production(
                    storage,
                    outline_path=outline_path,
                    workspace_path=str(workspace_path.relative_to(storage.root)),
                    chapter=1,
                    execute=False,
                    environment="production",
                )

            self.assertEqual(_chapter_runs(storage), before)

    def test_context_step_propagates_production_envelope_and_source_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            data = {
                "metadata": {"project_id": "context-project", "workspace_path": "data/workspaces/context.json"},
                "content": {
                    "chapter": 1,
                    "outputs": {"stability_preflight_path": "data/reports/preflight.json", "chapter_plan_path": "data/chapter_plans/plan.json"},
                    "quality_loop_policy": {
                        "environment": "production",
                        "os_envelope": {"project_ref": "context-project", "schema_version": 2},
                        "source_policy": {"raw_source_text_allowed": False},
                    },
                },
            }
            result = {
                "context_plan": {"path": "data/contexts/plan.json"},
                "path": "data/contexts/bundle.json",
                "asset": {"content": {}, "metadata": {}},
                "mkaos_pack": {"path": "data/contexts/pack.json"},
            }

            with (
                patch("novel_forge.modules.chapter_production_bus.service.build_flow_context_bundle", return_value=result) as build,
                patch("novel_forge.modules.chapter_production_bus.service._context_query", return_value="context query"),
            ):
                chapter_bus_service._perform_step(storage, Path("data/runs/run.json"), data, "context_bundle")

            self.assertEqual(build.call_args.kwargs["environment"], "production")
            self.assertEqual(build.call_args.kwargs["os_envelope"]["project_ref"], "context-project")
            self.assertFalse(build.call_args.kwargs["source_policy"]["raw_source_text_allowed"])


def _chapter_runs(storage: LocalStorage) -> list[dict]:
    rows = []
    for path in storage.list_json("runs"):
        data = storage.read_json(path)
        if isinstance(data, dict) and data.get("type") == "chapter_production_run":
            rows.append(data)
    return rows


if __name__ == "__main__":
    unittest.main()
