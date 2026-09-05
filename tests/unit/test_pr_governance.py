from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from novel_forge.tools.pr_governance import assess_provider_evidence, build_pr_plan, run_pr_governance


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def _commit(root: Path) -> str:
    _git(root, "add", ".")
    _git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "revision")
    return _git(root, "rev-parse", "HEAD")


def _repository(root: Path) -> str:
    _git(root, "init", "-q")
    path = root / "src/example.py"
    path.parent.mkdir()
    path.write_text("VALUE = 1\n")
    return _commit(root)


def test_proposal_only_commit_requires_governance_without_new_qualification(tmp_path: Path) -> None:
    base = _repository(tmp_path)
    path = tmp_path / "architecture/proposals/example.md"
    path.parent.mkdir(parents=True)
    path.write_text("PROPOSAL NOT_RUNTIME_AUTHORITY")
    head = _commit(tmp_path)
    plan = build_pr_plan(tmp_path, base)
    assert plan["head_sha"] == head
    assert plan["status"] == "PLANNED"
    assert plan["implementation_changed"] is False
    assert plan["qualification"] == "NOT_REQUIRED"
    assert plan["qualification_reason"] == "SAME_IMPLEMENTATION"


@pytest.mark.parametrize("target", [
    "src/example.py", "src/novel_forge/modules/context_builder/domain.py",
    "src/novel_forge/modules/production_execution/policies.py",
    "config/capability_packs/artifacts/prompt.md", "skills/review/SKILL.md",
    ".github/workflows/core-os-ci.yml",
])
def test_runtime_instruction_and_governance_changes_require_exact_sha_p0(tmp_path: Path, target: str) -> None:
    base = _repository(tmp_path)
    path = tmp_path / target
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("changed implementation\n")
    _commit(tmp_path)
    plan = build_pr_plan(tmp_path, base)
    assert plan["implementation_changed"] is True
    assert plan["qualification"] == "EXACT_SHA_P0_REQUIRED"
    assert plan["changed_implementation_paths"] == [target]
    assert plan["provider_evidence_policy"] == "EXACT_IMPLEMENTATION_IDENTITY_REQUIRED"


def test_pr_source_preflight_rejects_dirty_and_ignored_runtime_content(tmp_path: Path) -> None:
    base = _repository(tmp_path)
    (tmp_path / "src/example.py").write_text("VALUE = 2\n")
    with pytest.raises(ValueError, match="clean worktree"):
        build_pr_plan(tmp_path, base)
    _commit(tmp_path)
    (tmp_path / ".gitignore").write_text("src/ignored.py\n")
    _commit(tmp_path)
    (tmp_path / "src/ignored.py").write_text("VALUE = 3\n")
    with pytest.raises(ValueError, match="ignored implementation"):
        build_pr_plan(tmp_path, base)


def test_failed_governance_cannot_report_pass_or_start_p0(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    base = _repository(root)
    (root / "Makefile").write_text("sync-skills:\n\ttrue\nvalidate:\n\tfalse\nhead-integrity-check:\n\ttrue\ncheck-skills:\n\ttrue\n")
    _commit(root)
    output = tmp_path / "evidence/pr.json"
    result = run_pr_governance(root, base_sha=base, output=output, profile="local")
    assert result["status"] == "FAIL"
    assert [check["name"] for check in result["checks"]] == ["governance"]
    assert json.loads(output.read_text())["status"] == "FAIL"


def test_same_implementation_gate_runs_real_governance_and_no_p0(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _repository(root)
    (root / "Makefile").write_text("sync-skills validate head-integrity-check check-skills:\n\ttrue\n")
    base = _commit(root)
    (root / "README.md").write_text("Documentation only\n")
    _commit(root)
    result = run_pr_governance(root, base_sha=base, output=tmp_path / "pr.json", profile="local")
    assert result["status"] == "PASS"
    assert result["qualification"] == "NOT_REQUIRED"
    assert result["qualification_reason"] == "SAME_IMPLEMENTATION"
    assert [check["name"] for check in result["checks"]] == ["governance"]
    assert result["current_real_provider"]["status"] == "NOT_PROVEN"
    result = run_pr_governance(root, base_sha=base, output=tmp_path / "claim.json", profile="local", claim_provider_qualified=True)
    assert result["status"] == "FAIL"
    assert "requalification" in result["error"]


def test_old_or_scripted_provider_report_cannot_qualify_current_identity() -> None:
    current = "sha256:" + "b" * 64
    old = {"implementation_identity": "sha256:" + "a" * 64, "result": "PASS"}
    assert assess_provider_evidence(old, implementation_identity=current)["status"] == "STALE"
    fixture = {**old, "implementation_identity": current, "fixture_protocol_only": True}
    assert assess_provider_evidence(fixture, implementation_identity=current)["status"] == "NOT_PROVEN"


def test_provider_receipt_projection_requires_complete_recovery_evidence() -> None:
    identity = "sha256:" + "b" * 64
    report = {
        "schema_version": "novel-forge.real-provider-qualification.v1",
        "implementation_identity": identity, "result": "PASS",
        "qualification": {"status": "PASSED"},
        "external_effect": {
            "external_effect_id": "effect", "request_hash": "request-hash", "response_hash": "response-hash",
            "provider_request_identity": "provider-receipt", "dispatch_count": 1, "receipt_count": 1,
            "reconciliation_count": 1, "provider_execution_count": 1, "duplicate_external_effect_count": 0,
            "initial_outcome": "EFFECT_EXTERNAL_STATE_UNKNOWN", "ambiguous_response_injected": True,
            "recovery_runtime_restarted": True, "recovered_without_resend": True, "replayed": True,
        },
        "usage": {"measurement": "MEASURED", "input_tokens": 10, "output_tokens": 20},
        "latency": {"duration_ms": 12}, "provider": "openai", "backend_id": "remote-provider-openai", "model": "model",
        "request_object_ref": "request-object", "response_object_ref": "response-object",
        "route_snapshot_id": "route", "prompt_hash": "prompt", "instruction_hash": "instruction", "skill_hash": "skill",
        "proof_scope": {"ceiling": "REAL_PROVIDER_RUNTIME"},
    }
    assert assess_provider_evidence(report, implementation_identity=identity)["status"] == "QUALIFIED"
    for field, invalid in (("dispatch_count", 2), ("receipt_count", 0), ("recovered_without_resend", False), ("recovery_runtime_restarted", False)):
        changed = {**report, "external_effect": {**report["external_effect"], field: invalid}}
        assert assess_provider_evidence(changed, implementation_identity=identity)["status"] == "NOT_PROVEN"
    assert assess_provider_evidence({**report, "fixture_protocol_only": True}, implementation_identity=identity)["status"] == "NOT_PROVEN"
    for provider, backend in (("mock", "scripted-fixture"), ("scripted_provider_v2", "remote-provider-scripted-provider-v2"), ("openai", "scripted-fixture"), ("offline", "remote-provider-openai")):
        assert assess_provider_evidence({**report, "provider": provider, "backend_id": backend, "fixture_protocol_only": False}, implementation_identity=identity)["status"] == "NOT_PROVEN"
    assert assess_provider_evidence({**report, "proof_scope": "invalid"}, implementation_identity=identity)["status"] == "NOT_PROVEN"


def test_governance_make_targets_include_proposal_lifecycle() -> None:
    root = Path(__file__).resolve().parents[2]
    makefile = (root / "Makefile").read_text()
    for name in ("validate", "p0-backend-static"):
        assert "proposal-lifecycle-check" in makefile.split(name + ":", 1)[1].split("\n", 1)[0]
