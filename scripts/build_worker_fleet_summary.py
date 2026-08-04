#!/usr/bin/env python3
"""Combine seven GitHub Actions worker artifacts into one fail-closed summary."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from novel_forge.tools.worker_fleet_evidence import (
    WORKER_SCENARIOS,
    build_worker_fleet_summary,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = []
    for worker in WORKER_SCENARIOS:
        path = args.input_dir / f"worker-e2e-{worker}-{args.commit_sha}.json"
        if not path.is_file():
            raise RuntimeError(f"missing Worker Fleet artifact: {path.name}")
        evidence.append(json.loads(path.read_text(encoding="utf-8")))
    summary = build_worker_fleet_summary(evidence, commit_sha=args.commit_sha)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
