#!/usr/bin/env python3
"""Report durable Book Opening workflow progress without running production."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
from typing import Sequence

from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.book_authority.opening_progress import (
    PostgresBookOpeningWorkflowProgressQuery,
)


ROOT = Path(__file__).resolve().parents[1]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="report-opening-progress",
        description=(
            "Read planning-layer, reviewable-artifact, checkpoint, runtime-fence, "
            "blocking, and budget progress for one Book Opening."
        ),
    )
    parser.add_argument("--opening-run-id", required=True)
    parser.add_argument(
        "--database-url",
        default="",
        help="PostgreSQL URL; defaults to NOVEL_FORGE_DATABASE_URL.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional atomic JSON output path; the report is always printed.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    database_url = str(args.database_url).strip()
    if not database_url:
        database_url = IndustrialSettings.from_env(root=ROOT).database_url
    if not database_url:
        parser.error(
            "--database-url or NOVEL_FORGE_DATABASE_URL is required for the "
            "PostgreSQL progress read model"
        )
    report = PostgresBookOpeningWorkflowProgressQuery(database_url).progress(
        opening_run_id=str(args.opening_run_id)
    )
    serialized = json.dumps(
        report.to_dict(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    if args.output is not None:
        _atomic_write(args.output, serialized + "\n")
    print(serialized)
    return 0


def _atomic_write(path: Path, content: str) -> None:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, target)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
