from __future__ import annotations

import sys
from pathlib import Path

import pytest


class _NoSkipPlugin:
    def __init__(self) -> None:
        self.skipped: list[str] = []

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.skipped:
            self.skipped.append(report.nodeid)

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.skipped:
            self.skipped.append(report.nodeid)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    paths: set[Path] = set()
    for pattern in (
        "test_authority_*_postgres.py",
        "test_asset_blob_*_postgres.py",
        "test_command_kernel_*_postgres.py",
        "test_external_effect_*_postgres.py",
        "test_production_execution_*_postgres.py",
        "test_mkaos_authority_postgres.py",
        "test_narrative_*_postgres.py",
        "test_source_document_authority_postgres.py",
        "test_source_deconstruction_authority_postgres.py",
        "test_agent_collaboration_postgres.py",
        "test_book_followup_authority_postgres.py",
        "test_book_to_chapter_authority_vertical_postgres.py",
        "test_chapter_authority_*_postgres.py",
        "test_postgresql_only_chapter_slice.py",
        "test_core_functional_loops_postgres.py",
        "test_hierarchy_*_postgres.py",
        "test_quality_*_postgres.py",
        "test_reader_calibration_postgres.py",
        "test_bounded_quality_campaign_postgres.py",
    ):
        paths.update((root / "tests" / "integration").glob(pattern))
    plugin = _NoSkipPlugin()
    result = pytest.main(
        ["-v", *(str(path.relative_to(root)) for path in sorted(paths))],
        plugins=[plugin],
    )
    if plugin.skipped:
        for node_id in plugin.skipped:
            print(f"CORE_POSTGRES_SKIP_FORBIDDEN: {node_id}", file=sys.stderr)
        return 1
    return 0 if result == pytest.ExitCode.OK else 1


if __name__ == "__main__":
    raise SystemExit(main())
