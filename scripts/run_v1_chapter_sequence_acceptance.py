from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from novel_forge.core.ids import utc_now
from novel_forge.modules.chapter_production_bus import run_chapter_production_sequence
from novel_forge.modules.workspace.service import init_workspace
from novel_forge.schemas import Outline
from novel_forge.storage.local import LocalStorage


def main() -> int:
    args = _parse_args()
    root = Path(args.root).resolve()
    storage = LocalStorage(root)
    storage.ensure_layout()
    if args.model_provider:
        os.environ["NOVEL_FORGE_MODEL_PROVIDER"] = args.model_provider
    workspace_path, outline_path = _resolve_or_create_inputs(storage, args)
    progress_events: list[dict[str, Any]] = []

    def on_progress(event: dict[str, Any]) -> None:
        progress_events.append(event)
        if args.progress_jsonl:
            print(json.dumps(event, ensure_ascii=False), flush=True)
        elif str(event.get("event", "")) in {"chapter_completed", "chapter_failed", "sequence_finished"}:
            print(_progress_line(event), flush=True)

    interrupted = False
    try:
        result = run_chapter_production_sequence(
            storage,
            outline_path=outline_path,
            workspace_path=workspace_path,
            start_chapter=args.start_chapter,
            chapter_count=args.chapter_count,
            max_chapters=args.max_chapters,
            progress_callback=on_progress,
        )
    except KeyboardInterrupt:
        interrupted = True
        result = _interrupted_result(args, workspace_path=workspace_path, outline_path=outline_path, progress_events=progress_events)
    report_path = Path(args.report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_report(args, root=root, result=result, progress_events=progress_events), encoding="utf-8")
    summary = {
        "status": result.get("status", ""),
        "completed_chapters": result.get("completed_chapters", 0),
        "requested_chapters": result.get("chapter_count", args.chapter_count),
        "duration_seconds": result.get("duration_seconds", 0),
        "acceptance_report_path": result.get("acceptance_report_path", ""),
        "markdown_report_path": str(report_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if interrupted:
        return 130
    return 0 if result["status"] == "succeeded" else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the true V1 chapter production bus as an explicit slow acceptance.")
    parser.add_argument("--root", default=".local/v1-chapter-sequence-acceptance", help="Local isolated workspace root for the slow run.")
    parser.add_argument("--report-path", default="docs/reports/v1-chapter-sequence-slow-acceptance.md", help="Markdown report path.")
    parser.add_argument("--chapter-count", type=int, default=10, help="Number of true chapters to run through the chapter bus.")
    parser.add_argument("--max-chapters", type=int, default=30, help="Safety cap for a single slow run.")
    parser.add_argument("--start-chapter", type=int, default=1)
    parser.add_argument("--workspace-path", default="", help="Existing workspace asset path. If omitted, a workspace is created.")
    parser.add_argument("--outline-path", default="", help="Existing outline asset path. If omitted, a deterministic outline is created.")
    parser.add_argument("--workspace-title", default="V1 Slow Acceptance Project")
    parser.add_argument("--model-provider", default=os.environ.get("NOVEL_FORGE_MODEL_PROVIDER", "mock"), help="Model provider for local slow acceptance; default is mock.")
    parser.add_argument("--progress-jsonl", action="store_true", help="Print progress events as JSON lines.")
    return parser.parse_args()


def _resolve_or_create_inputs(storage: LocalStorage, args: argparse.Namespace) -> tuple[str, str]:
    workspace_path = str(args.workspace_path or "")
    outline_path = str(args.outline_path or "")
    if not workspace_path:
        workspace_file = init_workspace(storage, args.workspace_title)
        workspace_path = str(workspace_file.relative_to(storage.root))
    workspace = storage.read_asset(workspace_path)
    project_id = str(workspace.content.get("project_id") or workspace.id)
    if not outline_path:
        outline_file = storage.write_asset(
            "outlines",
            Outline(
                title="V1 slow acceptance outline",
                content={
                    "acts": [
                        {
                            "act": 1,
                            "goal": "open a clock-tower mystery, escalate pressure, and preserve a clear next-chapter hook for ten chapters",
                        }
                    ],
                    "acceptance_scope": "local deterministic v1 chapter bus slow acceptance",
                },
                metadata={"project_id": project_id, "workspace_path": workspace_path},
                references=[workspace_path],
            ),
        )
        outline_path = str(outline_file.relative_to(storage.root))
    return workspace_path, outline_path


def _progress_line(event: dict[str, Any]) -> str:
    name = str(event.get("event", ""))
    if name == "sequence_finished":
        return (
            f"[sequence] {event.get('status')} "
            f"{event.get('completed_chapters')}/{event.get('requested_chapter_count')} chapters "
            f"in {event.get('duration_seconds')}s"
        )
    return (
        f"[chapter {event.get('chapter')}] {name} "
        f"status={event.get('status', '')} duration={event.get('duration_seconds', '')}s "
        f"run={event.get('run_path', '')}"
    )


def _render_report(args: argparse.Namespace, *, root: Path, result: dict[str, Any], progress_events: list[dict[str, Any]]) -> str:
    acceptance = result.get("acceptance_report", {}).get("asset", {})
    content = acceptance.get("content", {}) if isinstance(acceptance, dict) else {}
    runtime = content.get("runtime_summary", {}) if isinstance(content, dict) else {}
    lines = [
        "# V1 Chapter Sequence Slow Acceptance",
        "",
        f"Generated at: `{utc_now()}`",
        f"Workspace root: `{root}`",
        f"Model provider: `{args.model_provider}`",
        f"Requested chapters: `{result.get('chapter_count')}`",
        f"Completed chapters: `{result.get('completed_chapters')}`",
        f"Status: `{result.get('status')}`",
        f"Duration seconds: `{result.get('duration_seconds')}`",
        f"Acceptance report asset: `{result.get('acceptance_report_path')}`",
        "",
        "## Runtime Summary",
        "",
        "```json",
        json.dumps(runtime, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Chapter Coverage",
        "",
        "| Chapter | Status | Coverage | Duration seconds | Run | Missing outputs |",
        "|---:|---|---|---:|---|---|",
    ]
    for row in result.get("runs", []):
        coverage = row.get("coverage", {}) if isinstance(row.get("coverage", {}), dict) else {}
        missing = ", ".join(str(item) for item in coverage.get("missing_outputs", [])) if isinstance(coverage.get("missing_outputs", []), list) else ""
        lines.append(
            f"| {row.get('chapter', '')} | {row.get('status', '')} | {coverage.get('status', '')} | "
            f"{row.get('duration_seconds', '')} | `{row.get('run_path', '')}` | {missing} |"
        )
    lines.extend(
        [
            "",
            "## Output Counts",
            "",
            "```json",
            json.dumps(content.get("output_counts", {}), ensure_ascii=False, indent=2),
            "```",
            "",
            "## Failures",
            "",
            "```json",
            json.dumps(result.get("failures", []), ensure_ascii=False, indent=2),
            "```",
            "",
            "## Progress Events",
            "",
            "```json",
            json.dumps(progress_events, ensure_ascii=False, indent=2),
            "```",
            "",
            "## Next Step",
            "",
            _next_step(result),
            "",
        ]
    )
    return "\n".join(lines)


def _next_step(result: dict[str, Any]) -> str:
    if result.get("status") == "interrupted":
        return "The run was interrupted. Inspect the per-chapter durations, keep the generated local assets as evidence, optimize the slow path, and rerun."
    if result.get("status") != "succeeded":
        return "Inspect the failed chapter row, fix the failing gate or runtime issue, and rerun this slow acceptance with the same root."
    if int(result.get("chapter_count", 0) or 0) < 30:
        return "Repeat with `--chapter-count 30` after reviewing runtime and artifact growth."
    return "Promote this path into the v1 30-chapter acceptance evidence set."


def _interrupted_result(args: argparse.Namespace, *, workspace_path: str, outline_path: str, progress_events: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [event for event in progress_events if event.get("event") == "chapter_completed"]
    started = [event for event in progress_events if event.get("event") == "chapter_started"]
    last_started = started[-1] if started else {}
    failures = [
        {
            "chapter": last_started.get("chapter", ""),
            "status": "interrupted",
            "error": "KeyboardInterrupt",
            "run_path": "",
        }
    ]
    duration = sum(float(event.get("duration_seconds", 0) or 0) for event in completed)
    return {
        "status": "interrupted",
        "project_id": "",
        "workspace_path": workspace_path,
        "outline_path": outline_path,
        "start_chapter": args.start_chapter,
        "chapter_count": args.chapter_count,
        "completed_chapters": len(completed),
        "runs": completed,
        "failures": failures,
        "duration_seconds": round(duration, 3),
        "acceptance_report_path": "",
        "acceptance_report": {"asset": {"content": {"runtime_summary": {"interrupted": True}, "output_counts": {}}}},
    }


if __name__ == "__main__":
    raise SystemExit(main())
