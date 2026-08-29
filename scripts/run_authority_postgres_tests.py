from __future__ import annotations

import json
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
        "test_core_functional_loops_postgres.py",
        "test_external_effect_*_postgres.py",
        "test_operation_graph_saga_postgres.py",
        "test_production_execution_*_postgres.py",
        "test_provider_budget_scope_postgres.py",
        "test_retrieval_embedding_projection_postgres.py",
        "test_mkaos_authority_postgres.py",
        "test_narrative_*_postgres.py",
        "test_source_document_authority_postgres.py",
        "test_source_deconstruction_authority_postgres.py",
        "test_agent_collaboration_postgres.py",
        "test_agent_harness_scheduler_postgres.py",
        "test_capability_pack_*_postgres.py",
        "test_book_opening_*_postgres.py",
        "test_book_projection_repair_upgrade_postgres.py",
        "test_book_followup_authority_postgres.py",
        "test_book_to_chapter_authority_vertical_postgres.py",
        "test_chapter_authority_*_postgres.py",
        "test_postgresql_only_chapter_slice.py",
        "test_core_functional_loops_postgres.py",
        "test_hierarchy_*_postgres.py",
        "test_quality_*_postgres.py",
        "test_reader_calibration_postgres.py",
        "test_bounded_quality_campaign_postgres.py",
        "test_d0_provider_qualification_authority_postgres.py",
        "test_maintenance_worker_postgres.py",
        "test_outbox_authority_worker_postgres.py",
        "test_unified_agent_runtime_postgres.py",
        "test_worker_health_postgres.py",
    ):
        paths.update((root / "tests" / "integration").glob(pattern))
    manifest = json.loads(
        (root / "architecture" / "manifests" / "test-manifest.yaml").read_text(
            encoding="utf-8"
        )
    )
    required_postgres = {
        Path(item)
        for item in manifest.get("required_modules", [])
        if str(item).startswith("tests/integration/")
        and str(item).endswith("_postgres.py")
    }
    collected = {path.relative_to(root) for path in paths}
    missing_required = sorted(required_postgres - collected)
    if missing_required:
        for path in missing_required:
            print(f"CORE_POSTGRES_REQUIRED_TEST_MISSING: {path}", file=sys.stderr)
        return 2
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
