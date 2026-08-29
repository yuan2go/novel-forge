from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/report_book_opening_progress.py"


def _module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "report_book_opening_progress", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_report_opening_progress_is_an_independent_non_campaign_command(
    tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    module = _module()
    calls: list[tuple[str, str]] = []
    report = {
        "schema_version": "novel-forge.book-opening-workflow-progress.v1",
        "opening_run_id": "opening:1",
        "project_id": "project:1",
        "current_layer": {"node_kind": "BOOK_PLAN"},
        "furthest_completed_layer": None,
        "nodes": [],
        "reviewable_artifact": {"status": "NOT_FORMED"},
        "persistent_checkpoint": {"status": "NOT_FORMED"},
        "blocking_reason": {"is_blocked": False},
        "runtime_fence": {"status": "NOT_REQUIRED"},
        "budget_usage": {"status": "OPEN"},
    }

    class Query:
        def __init__(self, database_url: str) -> None:
            calls.append(("database", database_url))

        def progress(self, *, opening_run_id: str):  # type: ignore[no-untyped-def]
            calls.append(("opening", opening_run_id))
            return SimpleNamespace(to_dict=lambda: report)

    module.PostgresBookOpeningWorkflowProgressQuery = Query
    output = tmp_path / "opening-progress.json"

    assert module._parser().prog == "report-opening-progress"
    assert (
        module.main(
            [
                "--database-url",
                "postgresql:///novel_forge",
                "--opening-run-id",
                "opening:1",
                "--output",
                str(output),
            ]
        )
        == 0
    )

    assert json.loads(output.read_text(encoding="utf-8")) == report
    assert json.loads(capsys.readouterr().out) == report
    assert calls == [
        ("database", "postgresql:///novel_forge"),
        ("opening", "opening:1"),
    ]
    assert "campaign_id" not in report
    assert "chapter_end" not in report
