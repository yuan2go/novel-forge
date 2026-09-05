from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
from typing import Sequence

from novel_forge.modules.chapter_quality_authority.narrative_qualification import (
    build_narrative_qualification_report,
)
from novel_forge.modules.chapter_quality_authority.narrative_qualification_sources import (
    load_native_narrative_receipts,
)
from novel_forge.tools.implementation_tree_identity import (
    build_git_implementation_tree_identity,
    build_implementation_tree_identity,
)
from novel_forge.tools.pr_governance import validate_current_p0
from novel_forge.tools.release_run_evidence import write_atomic_evidence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--book-id", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--implementation-tree-sha", required=True)
    parser.add_argument("--p0-report")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve()
    output = Path(args.output).resolve()
    if not Path(args.output).is_absolute() or output.is_relative_to(root):
        parser.error("Narrative evidence output must be absolute and outside the source checkout")
    actual_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tree_sha = build_implementation_tree_identity(root)["implementation_tree_sha"]
    tested_tree = build_git_implementation_tree_identity(root, args.expected_sha)[
        "implementation_tree_sha"
    ]
    if tested_tree != tree_sha or tree_sha != args.implementation_tree_sha:
        parser.error("Narrative qualification implementation identity changed")
    database_url = os.environ.get("NOVEL_FORGE_DATABASE_URL", "")
    if not database_url:
        parser.error("NOVEL_FORGE_DATABASE_URL is required; no fixture fallback")
    engineering = (
        json.loads(Path(args.p0_report).read_text(encoding="utf-8"))
        if args.p0_report
        else None
    )
    if engineering is not None:
        validate_current_p0(
            engineering,
            plan={"head_sha": args.expected_sha, "implementation_tree_sha": tree_sha},
        )
    receipts = load_native_narrative_receipts(
        database_url, project_id=args.project_id, book_id=args.book_id
    )
    report = build_narrative_qualification_report(
        project_id=args.project_id,
        book_id=args.book_id,
        implementation_sha=args.expected_sha,
        implementation_tree_sha=tree_sha,
        receipts=receipts,
        engineering_evidence=engineering,
    )
    if build_implementation_tree_identity(root)["implementation_tree_sha"] != tree_sha:
        parser.error(
            "Narrative qualification implementation changed during evidence read"
        )
    final_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if final_head != actual_sha:
        parser.error("Narrative qualification HEAD changed during evidence read")
    write_atomic_evidence(output, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "report_digest": report["report_digest"],
                "output": args.output,
            },
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
