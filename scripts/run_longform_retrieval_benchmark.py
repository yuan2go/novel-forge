"""INVARIANT: benchmark evidence is written only to an explicit caller-owned path."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from novel_forge.modules.context_builder.retrieval_benchmark import (
    run_longform_retrieval_benchmark,
)
from novel_forge.tools.implementation_tree_identity import (
    build_git_implementation_tree_identity,
)


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", *arguments),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()


def _bind_revision(report: dict[str, object], repository: Path) -> dict[str, object]:
    if _git(repository, "status", "--porcelain", "--untracked-files=normal"):
        raise RuntimeError("benchmark evidence requires a clean worktree")
    commit_sha = _git(repository, "rev-parse", "HEAD")
    source_tree = _git(repository, "rev-parse", "HEAD^{tree}")
    identity = build_git_implementation_tree_identity(repository, commit_sha)
    body = {
        **{key: value for key, value in report.items() if key != "report_fingerprint"},
        "revision_identity": {
            "observed_at_sha": commit_sha,
            "source_tree": source_tree,
            "implementation_tree_sha": identity["implementation_tree_sha"],
        },
        "execution_identity": {
            "provider": "NONE_SYNTHETIC_DETERMINISTIC",
            "model": "NONE_SYNTHETIC_DETERMINISTIC",
            "configuration": "longform-retrieval-benchmark-v1",
            "instruction_identity": "retrieval-expansion-plan-v1",
        },
    }
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {
        **body,
        "report_fingerprint": "sha256:" + hashlib.sha256(encoded).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    output = Path(arguments.output).expanduser().resolve()
    repository = Path(__file__).resolve().parents[1]
    if output == repository or repository in output.parents:
        parser.error("--output must be a caller-owned path outside the repository")
    output.parent.mkdir(parents=True, exist_ok=True)
    report = _bind_revision(run_longform_retrieval_benchmark(), repository)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    print(json.dumps({"status": report["status"], "output": str(output)}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
