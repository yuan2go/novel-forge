from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from novel_forge.tools.implementation_tree_identity import build_git_implementation_tree_identity
from novel_forge.tools.proposal_lifecycle import check_proposal_lifecycle, review_witness


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def _repository(root: Path) -> tuple[Path, dict]:
    source = root / "src/novel_forge/modules/example.py"
    source.parent.mkdir(parents=True)
    source.write_text("class CurrentContract:\n    enabled = True\n")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "baseline")
    sha = _git(root, "rev-parse", "HEAD")
    ref = {"path": source.relative_to(root).as_posix(), "symbol": "CurrentContract"}
    record = {
        "schema_version": "proposal-lifecycle.v1", "status": "PARTIALLY_IMPLEMENTED",
        "reality_baseline": {"commit_sha": sha, "implementation_tree_sha": build_git_implementation_tree_identity(root, sha)["implementation_tree_sha"]},
        "scope": [ref["path"]], "implemented_refs": [ref], "superseding_refs": [],
        "reviewed_sources": [{**ref, "sha256": review_witness(root, ref)}],
        "remaining_decisions": [{"id": "approval", "decision": "Choose independent approval criteria", "evidence_refs": [ref["path"]]}],
    }
    return source, record


def _write(root: Path, record: dict, text: str = "") -> Path:
    path = root / "architecture/proposals/example.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("**PROPOSAL**\n**NOT_RUNTIME_AUTHORITY**\n<!-- proposal-lifecycle\n" + json.dumps(record) + "\n-->\n" + text)
    return path


def test_partial_proposal_uses_exact_reviewed_scope_and_tolerates_unrelated_symbols(tmp_path: Path) -> None:
    source, record = _repository(tmp_path)
    _write(tmp_path, record)
    assert check_proposal_lifecycle(tmp_path)["status"] == "PASS"
    source.write_text(source.read_text() + "\ndef unrelated():\n    return 42\n")
    assert check_proposal_lifecycle(tmp_path)["status"] == "PASS"
    source.write_text(source.read_text().replace("enabled = True", "enabled = False"))
    report = check_proposal_lifecycle(tmp_path)
    assert report["status"] == "FAIL"
    assert any("stale lifecycle" in error for error in report["errors"])


@pytest.mark.parametrize("mutation, message", [
    (lambda record: record.update(status=[]), "unsupported lifecycle status"),
    (lambda record: record["reviewed_sources"][0].update(path=[]), "reference requires"),
    (lambda record: record.update(status="RESOLVED"), "closed proposal"),
    (lambda record: record.update(status="REJECTED"), "closed proposal"),
    (lambda record: record.update(status="ACTIVE"), "contradicts lifecycle"),
    (lambda record: record.update(remaining_decisions=[]), "retire resolved proposals"),
    (lambda record: record.update(scope=[]), "scoped production path"),
    (lambda record: record["reality_baseline"].update(implementation_tree_sha="sha256:" + "0" * 64), "baseline implementation identity differs"),
    (lambda record: record["remaining_decisions"][0].update(evidence_refs=["missing.py"]), "reference missing"),
    (lambda record: record["reviewed_sources"][0].update(symbol="Missing"), "contradicts executable symbol"),
])
def test_invalid_lifecycle_cannot_pass(tmp_path: Path, mutation, message: str) -> None:
    _, record = _repository(tmp_path)
    mutation(record)
    _write(tmp_path, record)
    report = check_proposal_lifecycle(tmp_path)
    assert report["status"] == "FAIL"
    assert any(message in error for error in report["errors"])


def test_implemented_not_implemented_and_current_projection_contradictions_fail(tmp_path: Path) -> None:
    _, record = _repository(tmp_path)
    _write(tmp_path, record, "NOT_IMPLEMENTED")
    assert any("NOT_IMPLEMENTED" in error for error in check_proposal_lifecycle(tmp_path)["errors"])
    current = tmp_path / "architecture/reality-evidence.json"
    current.write_text(json.dumps({"capabilities": [{"implemented": True}]}))
    ref = {"path": current.relative_to(tmp_path).as_posix(), "json_pointer": "/capabilities/0/implemented", "expected": False}
    record["scope"].append(ref["path"])
    record["reviewed_sources"].append({**ref, "sha256": "not-an-allowed-override"})
    _write(tmp_path, record)
    assert any("contradicts current projection" in error for error in check_proposal_lifecycle(tmp_path)["errors"])


@pytest.mark.parametrize("target", ["architecture/reality-evidence.json", "architecture/manifests/ai-instruction-manifest.yaml", "config/pack.json", "skills/review/SKILL.md", "src/novel_forge/modules/runtime.py"])
def test_proposal_reference_cannot_establish_runtime_authority(tmp_path: Path, target: str) -> None:
    _, record = _repository(tmp_path)
    _write(tmp_path, record)
    path = tmp_path / target
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"source": "architecture/proposals/example.md"}))
    assert check_proposal_lifecycle(tmp_path)["status"] == "FAIL"


def test_retired_proposal_can_be_deleted_after_projection(tmp_path: Path) -> None:
    _, record = _repository(tmp_path)
    path = _write(tmp_path, {**record, "status": "RESOLVED"})
    assert check_proposal_lifecycle(tmp_path)["status"] == "FAIL"
    path.unlink()
    report = check_proposal_lifecycle(tmp_path)
    assert report["status"] == "PASS"
    assert report["proposal_count"] == report["stale_resolved_proposals"] == 0


def test_reference_symlink_escape_and_malformed_metadata_fail_closed(tmp_path: Path) -> None:
    _, record = _repository(tmp_path)
    record["reviewed_sources"] = ["invalid"]
    _write(tmp_path, record)
    assert check_proposal_lifecycle(tmp_path)["status"] == "FAIL"
    link = tmp_path / "escape"
    link.symlink_to(tmp_path.parent)
    with pytest.raises(ValueError, match="outside repository"):
        review_witness(tmp_path, {"path": "../secret"})
