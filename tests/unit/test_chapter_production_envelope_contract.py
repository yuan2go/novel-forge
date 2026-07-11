from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.chapter_production_bus import start_chapter_production
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
            with self.assertRaisesRegex(ValueError, "OS envelope required"):
                start_chapter_production(
                    storage,
                    outline_path=outline_path,
                    workspace_path=str(workspace_path.relative_to(storage.root)),
                    chapter=1,
                    execute=False,
                    environment="production",
                )

            self.assertEqual(_chapter_runs(storage), before)


def _chapter_runs(storage: LocalStorage) -> list[dict]:
    rows = []
    for path in storage.list_json("runs"):
        data = storage.read_json(path)
        if isinstance(data, dict) and data.get("type") == "chapter_production_run":
            rows.append(data)
    return rows


if __name__ == "__main__":
    unittest.main()
