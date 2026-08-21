import pytest

from novel_forge.modules.book_authority.projection_repair import (
    book_projection_repair_definition,
    validate_terminal_repair_rows,
)
from novel_forge.modules.command_kernel.errors import KernelError


def _row(chapter: int) -> dict:
    projection_id = f"projection:{chapter}"
    return {
        "chapter_number": chapter,
        "acceptance_id": f"acceptance:{chapter}",
        "acceptance_projection_set_id": projection_id,
        "acceptance_chapter_outcome_asset_version_id": f"outcome:{chapter}",
        "acceptance_story_state_asset_version_id": f"state:{chapter}",
        "acceptance_canon_snapshot_asset_version_id": f"canon:{chapter}",
        "projection_set_id": projection_id,
        "projection_status": "COMPLETE",
        "projection_chapter_outcome_asset_version_id": f"outcome:{chapter}",
        "projection_story_state_asset_version_id": f"state:{chapter}",
        "projection_canon_snapshot_asset_version_id": f"canon:{chapter}",
        "projection_hash": "sha256:" + str(chapter) * 64,
        "checkpoint_id": f"checkpoint:{chapter}",
        "checkpoint_projection_hash": "sha256:" + str(chapter) * 64,
    }


def test_terminal_validation_accepts_complete_contiguous_history() -> None:
    proof = validate_terminal_repair_rows(
        target_chapter=2, rows=[_row(1), _row(2)]
    )

    assert proof["chapter_sequence"] == [1, 2]
    assert proof["final_projection_set_id"] == "projection:2"
    assert proof["terminal_digest"].startswith("sha256:")


def test_partial_repair_cannot_be_terminal_complete() -> None:
    with pytest.raises(KernelError, match="contiguous accepted chapters"):
        validate_terminal_repair_rows(target_chapter=2, rows=[_row(1)])


def test_terminal_validation_rejects_pointer_or_source_drift() -> None:
    pointer = _row(1)
    pointer["acceptance_projection_set_id"] = "projection:other"
    with pytest.raises(KernelError, match="pointer"):
        validate_terminal_repair_rows(target_chapter=1, rows=[pointer])

    source = _row(1)
    source["projection_story_state_asset_version_id"] = "state:other"
    with pytest.raises(KernelError, match="source differs"):
        validate_terminal_repair_rows(target_chapter=1, rows=[source])


def test_terminal_validation_rejects_checkpoint_drift() -> None:
    row = _row(1)
    row["checkpoint_projection_hash"] = "sha256:" + "f" * 64

    with pytest.raises(KernelError, match="hashes differ"):
        validate_terminal_repair_rows(target_chapter=1, rows=[row])


def test_repair_definition_requires_worker_attempts_and_forbids_effects() -> None:
    definition = book_projection_repair_definition(
        application_build_id="repair-test", commit_sha="a" * 40
    )

    assert definition["execution_mode"] == "worker"
    assert definition["retry_policy"]["max_attempts"] == 3
    assert definition["external_capabilities"] == []
    assert definition["policy"]["terminal_pointer_activation"] == "fenced_cas"
