from __future__ import annotations

import argparse
import json
from pathlib import Path

from novel_forge.modules.chapter_quality_authority.paired_regression import (
    FindingsAnnotation, Result, build_request, load_corpus, plan, score,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline paired review diagnostics; no Provider dispatch or native admission")
    parser.add_argument("action", choices=("plan", "request", "score"))
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--results", type=Path)
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--arm")
    parser.add_argument("--turn", type=int, default=0)
    parser.add_argument("--parent-request-id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        corpus = load_corpus(args.corpus)
        results = [Result.model_validate(item) for item in json.loads(args.results.read_text())] if args.results else []
        annotations = [FindingsAnnotation.model_validate(item) for item in json.loads(args.annotations.read_text())] if args.annotations else []
        if args.action == "plan":
            payload = plan(corpus)
        else:
            report = score(corpus, results, annotations)
            if args.action == "score":
                payload = report
            else:
                if not args.case_id or not args.arm:
                    raise ValueError("request requires --case-id and --arm")
                parent = next((r for r in results if r.request.request_id == args.parent_request_id), None)
                if args.parent_request_id and parent is None:
                    raise ValueError("parent result is missing")
                payload = build_request(corpus, case_id=args.case_id, arm=args.arm, turn=args.turn, parent=parent).model_dump()
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    except (ValueError, OSError) as exc:
        parser.exit(2, f"{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
