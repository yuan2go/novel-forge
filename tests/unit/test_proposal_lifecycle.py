from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import subprocess

import pytest

from novel_forge.tools.implementation_tree_identity import (
    build_git_implementation_tree_identity,
)
from novel_forge.tools.proposal_lifecycle import check_proposal_lifecycle


TODAY = date(2026, 9, 5)


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def proposal(tmp_path: Path) -> tuple[Path, dict]:
    _write(tmp_path, "src/example.py", "def current_contract():\n    return True\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Governance Test",
            "-c",
            "user.email=governance@example.invalid",
            "commit",
            "-qm",
            "baseline",
        ],
        cwd=tmp_path,
        check=True,
    )
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    metadata = {
        "schema_version": "novel-forge.proposal-lifecycle.v1",
        "status": "ACTIVE",
        "reviewed_on": "2026-09-05",
        "review_due": "2026-10-05",
        "reality_baseline": {
            "sha": sha,
            "implementation_tree_sha": build_git_implementation_tree_identity(
                tmp_path, sha
            )["implementation_tree_sha"],
        },
        "scope": ["src/example.py"],
        "implemented_refs": [],
        "superseding_refs": [],
        "remaining_decisions": [
            {
                "id": "owner",
                "description": "Choose owner for missing transition",
                "evidence_refs": [
                    {"path": "src/example.py", "symbol": "current_contract"}
                ],
                "absent_refs": [
                    {"path": "src/example.py", "symbol": "future_contract"}
                ],
            }
        ],
        "remaining_work": [],
    }
    return tmp_path, metadata


def _check(proposal: tuple[Path, dict], *, extra: str = "") -> dict:
    root, metadata = proposal
    _write(
        root,
        "architecture/proposals/design.md",
        (
            "# Design\n\n> **PROPOSAL**\n> **NOT_RUNTIME_AUTHORITY**\n"
            "<!-- proposal-lifecycle\n" + json.dumps(metadata) + "\n-->\n" + extra
        ),
    )
    return check_proposal_lifecycle(root, today=TODAY)


def test_unresolved_proposal_has_bounded_code_bound_lifecycle(
    proposal: tuple[Path, dict],
) -> None:
    report = _check(proposal)
    assert report["status"] == "PASS", report["errors"]
    assert report["retained_terminal_count"] == 0
    assert report["proposals"][0]["remaining_decisions"] == 1


@pytest.mark.parametrize("status", ["REJECTED", "RESOLVED"])
def test_terminal_proposals_must_be_deleted(
    proposal: tuple[Path, dict], status: str
) -> None:
    proposal[1]["status"] = status
    report = _check(proposal)
    assert report["status"] == "FAIL"
    assert report["retained_terminal_count"] == 1
    assert any("projected and deleted" in error for error in report["errors"])


def test_completed_scope_cannot_be_retained(proposal: tuple[Path, dict]) -> None:
    proposal[1]["remaining_decisions"] = []
    report = _check(proposal)
    assert any("no remaining decisions or work" in error for error in report["errors"])


def test_approved_but_unimplemented_scope_has_a_closure_deadline(
    proposal: tuple[Path, dict],
) -> None:
    metadata = proposal[1]
    metadata["remaining_work"] = metadata["remaining_decisions"]
    metadata["remaining_decisions"] = []
    metadata["decision_free_since"] = "2026-08-01"
    assert any("closure window" in error for error in _check(proposal)["errors"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("reviewed_on", "2026-09-06"),
        ("review_due", "2026-09-04"),
        ("review_due", "2026-12-01"),
    ],
)
def test_review_window_is_not_indefinite(
    proposal: tuple[Path, dict], field: str, value: str
) -> None:
    proposal[1][field] = value
    assert any("review window" in error for error in _check(proposal)["errors"])


def test_scope_changes_invalidate_review_even_when_references_still_exist(
    proposal: tuple[Path, dict],
) -> None:
    _write(proposal[0], "src/example.py", "def current_contract():\n    return False\n")
    assert any(
        "implementation scope changed" in error for error in _check(proposal)["errors"]
    )


def test_new_untracked_scope_code_invalidates_review(
    proposal: tuple[Path, dict],
) -> None:
    proposal[1]["scope"] = ["src"]
    _write(proposal[0], "src/new_contract.py", "VALUE = True\n")
    assert any(
        "implementation scope changed" in error for error in _check(proposal)["errors"]
    )


def test_baseline_digest_must_match_exact_git_source(
    proposal: tuple[Path, dict],
) -> None:
    proposal[1]["reality_baseline"]["implementation_tree_sha"] = "sha256:" + "0" * 64
    assert any("identity mismatch" in error for error in _check(proposal)["errors"])


def test_partial_implementation_cannot_claim_nothing_implemented(
    proposal: tuple[Path, dict],
) -> None:
    proposal[1]["status"] = "PARTIALLY_IMPLEMENTED"
    proposal[1]["implemented_refs"] = [
        {"path": "src/example.py", "symbol": "current_contract"}
    ]
    assert _check(proposal)["status"] == "PASS"
    assert any(
        "still claims NOT_IMPLEMENTED" in error
        for error in _check(proposal, extra="**NOT_IMPLEMENTED**")["errors"]
    )


def test_remaining_absence_claim_cannot_contradict_current_symbol(
    proposal: tuple[Path, dict],
) -> None:
    proposal[1]["remaining_decisions"][0]["absent_refs"][0]["symbol"] = (
        "current_contract"
    )
    assert any("already implemented" in error for error in _check(proposal)["errors"])


def test_implemented_evidence_cannot_reference_missing_symbol(
    proposal: tuple[Path, dict],
) -> None:
    proposal[1]["status"] = "PARTIALLY_IMPLEMENTED"
    proposal[1]["implemented_refs"] = [{"path": "src/example.py", "symbol": "missing"}]
    assert any(
        "contradicts current code" in error for error in _check(proposal)["errors"]
    )


def test_proposal_cannot_supply_its_own_implementation_evidence(
    proposal: tuple[Path, dict],
) -> None:
    proposal[1]["implemented_refs"] = [{"path": "architecture/proposals/design.md"}]
    assert any(
        "cannot be implementation evidence" in error
        for error in _check(proposal)["errors"]
    )


@pytest.mark.parametrize(
    "surface",
    [
        "architecture/reality-evidence.json",
        "architecture/manifests/backend-qualification-manifest.yaml",
        "architecture/manifests/test-manifest.yaml",
        "architecture/evidence/qualification.json",
        "architecture/live-evidence/provider.json",
        "skills/runtime/SKILL.md",
    ],
)
def test_proposal_cannot_be_promoted_to_current_or_runtime_evidence(
    proposal: tuple[Path, dict], surface: str
) -> None:
    root, _ = proposal
    _write(root, surface, '{"evidence":"architecture/proposals/design.md"}')
    _write(
        root,
        "architecture/manifests/ai-instruction-manifest.yaml",
        json.dumps(
            {
                "sources": [{"patterns": ["skills/*/SKILL.md"]}],
            }
        ),
    )
    assert any(
        "proposal reference in current/runtime Authority" in error
        for error in _check(proposal)["errors"]
    )


def test_missing_markers_or_malformed_metadata_fail_closed(
    proposal: tuple[Path, dict],
) -> None:
    root, _ = proposal
    _write(root, "architecture/proposals/design.md", "<!-- proposal-lifecycle\n[]\n-->")
    report = check_proposal_lifecycle(root, today=TODAY)
    assert report["status"] == "FAIL"
    assert any("must be an object" in error for error in report["errors"])


def test_deleting_resolved_proposal_leaves_no_retained_history(
    proposal: tuple[Path, dict],
) -> None:
    report = check_proposal_lifecycle(proposal[0], today=TODAY)
    assert report["status"] == "PASS"
    assert report["proposal_count"] == 0
