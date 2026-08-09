from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

from novel_forge.modules.book_authority import BookProductionSupervisorTick


def _load_script():
    root = Path(__file__).resolve().parents[2]
    scripts = root / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        spec = importlib.util.spec_from_file_location(
            "run_short_longform_runtime_proof",
            scripts / "run_short_longform_runtime_proof.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(scripts))


def test_proof_object_store_buckets_are_stable_and_run_isolated(tmp_path: Path) -> None:
    proof = _load_script()

    first = proof._proof_bucket_names(tmp_path / "attempt-a")
    replay = proof._proof_bucket_names(tmp_path / "attempt-a")
    second = proof._proof_bucket_names(tmp_path / "attempt-b")

    assert first == replay
    assert first != second
    assert set(first) == {"raw", "artifact", "export"}
    assert all(name.startswith("novel-forge-proof-") for name in first.values())
    assert all(len(name) <= 63 for name in first.values())


def test_proof_script_only_references_defined_longform_checkpoint_members() -> None:
    proof = _load_script()
    script_path = Path(proof.__file__)
    tree = ast.parse(script_path.read_text(encoding="utf-8"))
    referenced = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "LongformCheckpointType"
    }

    assert referenced <= set(proof.LongformCheckpointType.__members__)


def test_resume_returns_existing_active_chapter_before_supervisor_polling() -> None:
    proof = _load_script()
    calls = []
    request = {
        "chapter_request_id": "chapter-request:1",
        "chapter_number": 1,
        "chapter_root_operation_id": "chapter-root:1",
    }
    authority = SimpleNamespace(
        require=lambda _book_run_id: {
            "active_chapter_request_id": request["chapter_request_id"]
        },
        require_chapter_request=lambda _request_id: dict(request),
    )
    supervisor = SimpleNamespace(
        authority=authority,
        tick=lambda _book_run_id: calls.append("tick"),
    )

    resumed, ticks = proof._drive_to_chapter_dispatch(
        supervisor, book_run_id="book-run:1", chapter_number=1
    )

    assert resumed == request
    assert ticks == []
    assert calls == []


def test_drive_accepts_supervisor_generated_future_chapter_plan() -> None:
    proof = _load_script()
    request = {
        "chapter_request_id": "chapter-request:2",
        "chapter_number": 2,
        "chapter_root_operation_id": "chapter-root:2",
    }
    authority = SimpleNamespace(
        require=lambda _book_run_id: {"active_chapter_request_id": ""},
        require_chapter_request=lambda _request_id: dict(request),
    )
    results = iter(
        [
            BookProductionSupervisorTick(
                book_run_id="book-run:1",
                previous_state="READY",
                state="READY",
                action=proof.SupervisorAction.GENERATE_CHAPTER_PLAN,
                operation_id="planning-operation:2",
                evidence_ref="chapter-plan:2",
            ),
            BookProductionSupervisorTick(
                book_run_id="book-run:1",
                previous_state="READY",
                state="CHAPTER_RUNNING",
                action=proof.SupervisorAction.DISPATCH_CHAPTER,
                operation_id="chapter-root:2",
                evidence_ref=request["chapter_request_id"],
            ),
        ]
    )
    supervisor = SimpleNamespace(
        authority=authority,
        tick=lambda _book_run_id: next(results),
    )

    dispatched, ticks = proof._drive_to_chapter_dispatch(
        supervisor, book_run_id="book-run:1", chapter_number=2
    )

    assert dispatched == request
    assert [tick["action"] for tick in ticks] == [
        proof.SupervisorAction.GENERATE_CHAPTER_PLAN,
        proof.SupervisorAction.DISPATCH_CHAPTER,
    ]
