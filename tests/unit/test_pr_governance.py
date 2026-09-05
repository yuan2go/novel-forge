from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from novel_forge.tools.implementation_tree_identity import (
    build_git_implementation_tree_identity,
)
from novel_forge.tools.pr_governance import (
    plan_pr_governance,
    run_pr_governance,
    validate_current_p0,
)


def _write(root: Path, path: str, content: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _commit(root: Path) -> str:
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Governance Test",
            "-c",
            "user.email=governance@example.invalid",
            "commit",
            "-qm",
            "test revision",
        ],
        cwd=root,
        check=True,
    )
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    root = tmp_path / "repository"
    _write(root, "src/example.py", "VALUE = 1\n")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root, _commit(root)


@pytest.mark.parametrize(
    "path",
    [
        "architecture/proposals/design.md",
        "docs/current.md",
        "architecture/evidence/run.json",
    ],
)
def test_nonimplementation_change_still_requires_governance(
    repository: tuple[Path, str], path: str
) -> None:
    root, base_sha = repository
    _write(root, path, "{}\n")
    _commit(root)
    plan = plan_pr_governance(root, base_sha=base_sha)
    assert plan["status"] == "NOT_RUN"
    assert plan["implementation_changed"] is False
    assert plan["qualification"] == "NOT_REQUIRED"
    assert plan["qualification_reason"] == "SAME_IMPLEMENTATION"


@pytest.mark.parametrize(
    "path",
    [
        "src/example.py",
        "tests/unit/test_new.py",
        "config/capability_packs/artifacts/prompt.md",
        "skills/runtime/SKILL.md",
        ".github/workflows/core-os-ci.yml",
        "Makefile",
    ],
)
def test_implementation_and_instruction_changes_require_complete_exact_p0(
    repository: tuple[Path, str], path: str
) -> None:
    root, base_sha = repository
    _write(root, path, "VALUE = 2\n")
    _commit(root)
    plan = plan_pr_governance(root, base_sha=base_sha)
    assert plan["implementation_changed"] is True
    assert plan["qualification"] == "REQUIRED_EXACT_SHA_P0"
    assert plan["changed_implementation_paths"] == [path]


def test_ignored_implementation_cannot_evade_source_preflight(
    repository: tuple[Path, str],
) -> None:
    root, base_sha = repository
    _write(root, ".gitignore", "src/hidden.py\n")
    _commit(root)
    _write(root, "src/hidden.py", "VALUE = 2\n")
    with pytest.raises(ValueError, match="ignored source"):
        plan_pr_governance(root, base_sha=base_sha)


def test_dirty_worktree_and_short_base_cannot_receive_pass(
    repository: tuple[Path, str],
) -> None:
    root, base_sha = repository
    with pytest.raises(ValueError, match="exact Git SHA"):
        plan_pr_governance(root, base_sha="HEAD~1")
    _write(root, "src/example.py", "VALUE = 2\n")
    with pytest.raises(ValueError, match="clean worktree"):
        plan_pr_governance(root, base_sha=base_sha)


def test_provider_evidence_becomes_stale_on_instruction_identity_change(
    repository: tuple[Path, str],
) -> None:
    root, base_sha = repository
    identity = build_git_implementation_tree_identity(root, base_sha)[
        "implementation_tree_sha"
    ]
    _write(
        root,
        "architecture/live-evidence/provider.json",
        json.dumps(
            {
                "evidence_class": "real_provider_runtime_qualification",
                "implementation_tree_sha": identity,
            }
        ),
    )
    _commit(root)
    plan = plan_pr_governance(root, base_sha=base_sha)
    assert (
        plan["provider_evidence"][0]["identity_status"]
        == "MATCHES_CURRENT_IMPLEMENTATION"
    )
    assert plan["provider_qualification"] == "NOT_ASSESSED_BY_PR_GATE"
    _write(root, "skills/runtime/SKILL.md", "New model instruction\n")
    _commit(root)
    plan = plan_pr_governance(root, base_sha=base_sha)
    assert plan["provider_evidence"][0]["identity_status"] == "STALE"
    assert plan["provider_qualification"] == "NOT_ASSESSED_BY_PR_GATE"


def test_same_implementation_skips_p0_only_after_governance_pass(
    repository: tuple[Path, str], tmp_path: Path
) -> None:
    root, base_sha = repository
    _write(root, "docs/current.md", "Current projection\n")
    _commit(root)
    commands = []
    report = run_pr_governance(
        root,
        base_sha=base_sha,
        output=tmp_path / "result.json",
        command_runner=lambda command: commands.append(command) or 0,
    )
    assert report["status"] == "PASS"
    assert report["qualification"] == "NOT_REQUIRED"
    assert commands == [("make", "pr-governance-checks")]
    assert (
        json.loads((tmp_path / "result.json").read_text())["head_sha"]
        == report["head_sha"]
    )


def test_governance_failure_prevents_p0_or_pass(
    repository: tuple[Path, str], tmp_path: Path
) -> None:
    root, base_sha = repository
    _write(root, "src/example.py", "VALUE = 2\n")
    _commit(root)
    commands = []
    report = run_pr_governance(
        root,
        base_sha=base_sha,
        output=tmp_path / "failure.json",
        command_runner=lambda command: commands.append(command) or 1,
    )
    assert report["status"] == "FAIL"
    assert commands == [("make", "pr-governance-checks")]


def test_focus_then_canonical_p0_failure_remains_failure(
    repository: tuple[Path, str], tmp_path: Path
) -> None:
    root, base_sha = repository
    _write(
        root, "tests/unit/test_contract.py", "def test_contract():\n    assert True\n"
    )
    _commit(root)
    commands = []

    def run(command: tuple[str, ...]) -> int:
        commands.append(command)
        return int("p0-backend-qualification" in command)

    report = run_pr_governance(
        root, base_sha=base_sha, output=tmp_path / "failure.json", command_runner=run
    )
    assert report["status"] == "FAIL"
    assert commands[1][1:3] == ("-m", "pytest")
    assert commands[2][:2] == ("make", "p0-backend-qualification")


def test_success_exit_code_without_p0_evidence_is_not_pass(
    repository: tuple[Path, str], tmp_path: Path
) -> None:
    root, base_sha = repository
    _write(root, "src/example.py", "VALUE = 2\n")
    _write(
        root, "tests/unit/test_contract.py", "def test_contract():\n    assert True\n"
    )
    _commit(root)
    report = run_pr_governance(
        root,
        base_sha=base_sha,
        output=tmp_path / "failure.json",
        command_runner=lambda _: 0,
    )
    assert report["status"] == "FAIL"
    assert "p0-backend-qualification-" in report["error"]


def test_implementation_without_focused_evidence_cannot_skip_to_p0(
    repository: tuple[Path, str], tmp_path: Path
) -> None:
    root, base_sha = repository
    _write(root, "src/example.py", "VALUE = 2\n")
    _commit(root)
    commands = []
    report = run_pr_governance(
        root,
        base_sha=base_sha,
        output=tmp_path / "failure.json",
        command_runner=lambda command: commands.append(command) or 0,
    )
    assert report["status"] == "FAIL"
    assert "FOCUSED_TEST_EVIDENCE_REQUIRED" in report["error"]
    assert commands == [("make", "pr-governance-checks")]


def test_moving_source_during_governance_cannot_receive_pass(
    repository: tuple[Path, str], tmp_path: Path
) -> None:
    root, base_sha = repository

    def run(_: tuple[str, ...]) -> int:
        _write(root, "src/example.py", "VALUE = 2\n")
        _commit(root)
        return 0

    report = run_pr_governance(
        root, base_sha=base_sha, output=tmp_path / "failure.json", command_runner=run
    )
    assert report["status"] == "FAIL"
    assert "changed while governance" in report["error"]


def test_previous_sha_and_superficial_p0_pass_are_rejected() -> None:
    plan = {"head_sha": "a" * 40, "implementation_tree_sha": "sha256:" + "1" * 64}
    report = {
        "schema_version": "novel-forge.p0-backend-qualification-report.v2",
        "status": "PASS",
        "decision": "PASS",
        "tested_sha": "b" * 40,
        "implementation_tree_sha": plan["implementation_tree_sha"],
    }
    with pytest.raises(ValueError, match="another SHA"):
        validate_current_p0(report, plan=plan)
    report["tested_sha"] = plan["head_sha"]
    with pytest.raises(ValueError, match="source tree"):
        validate_current_p0(report, plan=plan)
