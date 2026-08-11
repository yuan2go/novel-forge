from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_book_coordination_layers_do_not_own_sql_or_unit_of_work() -> None:
    coordination_layers = {
        "supervisor": _read("src/novel_forge/modules/book_authority/supervisor.py"),
        "governed scheduler": _read(
            "src/novel_forge/modules/book_authority/governed_scheduler.py"
        ),
        "composition": _read("src/novel_forge/modules/book_authority/composition.py"),
        "worker": _read("src/novel_forge/workers/book_authority.py"),
    }
    sql = re.compile(r"\b(?:SELECT|INSERT|UPDATE|DELETE)\s", re.IGNORECASE)
    for layer, source in coordination_layers.items():
        assert "AuthorityUnitOfWork" not in source, layer
        assert "execute_transaction_command" not in source, layer
        assert "cursor.execute" not in source, layer
        assert sql.search(source) is None, layer


def test_book_query_is_read_only_and_has_business_semantics() -> None:
    query = _read("src/novel_forge/modules/book_authority/queries.py")
    for operation in (
        "coordination_candidates",
        "active_plan_covering_chapter",
        "require_chapter_execution_plan",
        "checkpointable_chapter_request_id",
        "ending_reachability",
    ):
        assert f"def {operation}(" in query
    assert "SELECT " in query
    assert re.search(r"\b(?:INSERT|UPDATE|DELETE)\s", query, re.IGNORECASE) is None


def test_supervisor_mutations_cross_the_book_authority_command_boundary() -> None:
    supervisor = _read("src/novel_forge/modules/book_authority/supervisor.py")
    authority = _read("src/novel_forge/modules/book_authority/production.py")
    assert "self.authority.advance_supervisor_checkpoint(" in supervisor
    assert "def advance_supervisor_checkpoint(" in authority
    assert "self._execute_mutation(" in authority
    assert "self._cas_book_state(" in authority
    assert 'event_type="book.supervisor.checkpoint.advanced"' in authority


def test_chapter_command_adapter_uses_the_chapter_query_boundary() -> None:
    authority = _read("src/novel_forge/modules/book_authority/production.py")
    adapter = authority.split("class ChapterAuthorityCommandAdapter:", 1)[1]
    adapter = adapter.split("def stable_chapter_submission_key(", 1)[0]
    assert "self.application.query.require_operation_control_state(" in adapter
    assert "AuthorityUnitOfWork" not in adapter


def test_fixture_book_kernel_is_not_a_second_runtime() -> None:
    retired = (
        "application.py",
        "codecs.py",
        "definitions.py",
        "registry.py",
        "scheduler.py",
    )
    package = ROOT / "src/novel_forge/modules/book_authority"
    for name in retired:
        assert not (package / name).exists(), name

    composition = _read("src/novel_forge/modules/book_authority/composition.py")
    production = _read("src/novel_forge/modules/book_authority/production.py")
    api_models = _read("src/novel_forge/api/models.py")
    entry_manifest = _read("architecture/manifests/production-entry-manifest.yaml")
    assert "self.supervisor.tick(book_run_id)" in composition
    assert "LEGACY_FIXTURE_INPUT" not in composition
    assert "legacy_fixture_input_allowed: bool = False" in production
    assert 'Literal["RESOLVED_AUTHORITY_INPUT"]' in api_models
    assert '"name": "book.production.coordinate"' in entry_manifest
    assert "book.production.run" not in entry_manifest
