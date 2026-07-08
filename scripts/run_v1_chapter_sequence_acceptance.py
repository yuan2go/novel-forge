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
from novel_forge.modules.chapter_runtime_growth import run_chapter_runtime_growth_threshold_gate
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
    result = _apply_runtime_growth_acceptance_preflight(storage, args, result)
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
    parser.add_argument("--runtime-growth-max-linked-asset-refs", type=int, default=120, help="Maximum linked asset refs per chapter_production_run allowed by the runtime-growth preflight.")
    parser.add_argument("--allow-full-runtime-mode", action="store_true", help="Allow full task_status_mode in the runtime-growth preflight. Defaults to false.")
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
    runtime_growth_preflight = result.get("runtime_growth_preflight", {}) if isinstance(result.get("runtime_growth_preflight", {}), dict) else {}
    unified_preflight_manifest = result.get("unified_acceptance_preflight_manifest", {}) if isinstance(result.get("unified_acceptance_preflight_manifest", {}), dict) else {}
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
        "## Runtime Growth Preflight",
        "",
        "```json",
        json.dumps(runtime_growth_preflight, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Unified Acceptance Preflight Manifest",
        "",
        "```json",
        json.dumps(unified_preflight_manifest, ensure_ascii=False, indent=2),
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


def _apply_runtime_growth_acceptance_preflight(storage: LocalStorage, args: argparse.Namespace, result: dict[str, Any]) -> dict[str, Any]:
    project_id = str(result.get("project_id") or "")
    gate = run_chapter_runtime_growth_threshold_gate(
        storage,
        project_id=project_id,
        environment="production",
        max_linked_asset_refs=int(getattr(args, "runtime_growth_max_linked_asset_refs", 120) or 120),
        allow_full_mode=bool(getattr(args, "allow_full_runtime_mode", False)),
        persist_profile=True,
    )
    updated = _with_runtime_growth_acceptance_preflight(result, gate)
    _persist_runtime_growth_acceptance_preflight(storage, updated)
    return updated


def _with_runtime_growth_acceptance_preflight(result: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
    updated = dict(result)
    preflight = {
        "contract": "v1-acceptance-runtime-growth-preflight-v1",
        "status": str(gate.get("status") or "missing"),
        "blocking": bool(gate.get("blocking")),
        "gate_result_path": str(gate.get("gate_result_path") or ""),
        "message": str(gate.get("message") or ""),
        "summary": gate.get("summary", {}) if isinstance(gate.get("summary", {}), dict) else {},
        "blocking_rows": gate.get("blocking_rows", []) if isinstance(gate.get("blocking_rows", []), list) else [],
    }
    updated["runtime_growth_preflight"] = preflight
    updated["unified_acceptance_preflight_manifest"] = _build_unified_acceptance_preflight_manifest(updated)
    if updated.get("status") == "succeeded" and preflight["status"] != "passed":
        updated["status"] = "failed"
        failures = list(updated.get("failures", []) if isinstance(updated.get("failures", []), list) else [])
        failures.append(
            {
                "status": "failed",
                "failure_type": "runtime_growth_threshold_gate",
                "error": preflight["message"] or "runtime growth threshold gate did not pass",
                "gate_result_path": preflight["gate_result_path"],
                "blocking_rows": preflight["blocking_rows"],
            }
        )
        updated["failures"] = failures
        acceptance = updated.get("acceptance_report", {})
        asset = acceptance.get("asset", {}) if isinstance(acceptance, dict) else {}
        content = asset.get("content", {}) if isinstance(asset, dict) else {}
        if isinstance(content, dict):
            content["recommendation"] = "repair_runtime_growth_before_acceptance"
            content["runtime_growth_preflight"] = preflight
            content["unified_acceptance_preflight_manifest"] = updated["unified_acceptance_preflight_manifest"]
    return updated


def _build_unified_acceptance_preflight_manifest(result: dict[str, Any]) -> dict[str, Any]:
    runtime_growth = result.get("runtime_growth_preflight", {}) if isinstance(result.get("runtime_growth_preflight", {}), dict) else {}
    rows = [
        {
            "key": "runtime_growth_threshold",
            "status": str(runtime_growth.get("status") or "missing"),
            "required_for_final_unified_acceptance": True,
            "enforced_now": True,
            "evidence_path": str(runtime_growth.get("gate_result_path") or ""),
            "operator_action": "repair runtime growth blockers before accepting the run" if runtime_growth.get("status") != "passed" else "runtime growth threshold passed",
        },
        {
            "key": "source_governance_runtime",
            "status": "deferred",
            "required_for_final_unified_acceptance": True,
            "enforced_now": False,
            "evidence_path": "",
            "operator_action": "final unified acceptance must require a passed source_governance_runtime gate",
        },
        {
            "key": "workflow_governance_drift",
            "status": "deferred",
            "required_for_final_unified_acceptance": True,
            "enforced_now": False,
            "evidence_path": "",
            "operator_action": "final unified acceptance must require clean workflow governance drift evidence",
        },
        {
            "key": "approval_request_caller_readiness",
            "status": "deferred",
            "required_for_final_unified_acceptance": True,
            "enforced_now": False,
            "evidence_path": "",
            "operator_action": "final unified acceptance must require approval caller readiness evidence",
        },
    ]
    enforced_failures = [row for row in rows if row["enforced_now"] and row["status"] != "passed"]
    missing_final = [row for row in rows if row["required_for_final_unified_acceptance"] and row["status"] in {"missing", "deferred"}]
    return {
        "contract": "v1-unified-acceptance-preflight-manifest-v1",
        "status": "failed" if enforced_failures else "review_required" if missing_final else "passed",
        "enforced_failure_count": len(enforced_failures),
        "missing_or_deferred_final_evidence_count": len(missing_final),
        "required_evidence": rows,
        "chapter_acceptance_executed_by_manifest": False,
        "operator_action": "complete deferred final preflight evidence before unified acceptance" if missing_final else "preflight evidence complete",
    }


def _persist_runtime_growth_acceptance_preflight(storage: LocalStorage, result: dict[str, Any]) -> None:
    path = str(result.get("acceptance_report_path") or "")
    preflight = result.get("runtime_growth_preflight", {}) if isinstance(result.get("runtime_growth_preflight", {}), dict) else {}
    manifest = result.get("unified_acceptance_preflight_manifest", {}) if isinstance(result.get("unified_acceptance_preflight_manifest", {}), dict) else {}
    if preflight and not manifest:
        manifest = _build_unified_acceptance_preflight_manifest(result)
        result["unified_acceptance_preflight_manifest"] = manifest
    if not path or not preflight:
        return
    try:
        data = storage.read_json(path)
    except (FileNotFoundError, ValueError):
        return
    if not isinstance(data, dict):
        return
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    content["runtime_growth_preflight"] = preflight
    if manifest:
        content["unified_acceptance_preflight_manifest"] = manifest
    if preflight.get("status") != "passed":
        content["recommendation"] = "repair_runtime_growth_before_acceptance"
        tags = [str(item) for item in data.get("tags", []) if str(item)] if isinstance(data.get("tags", []), list) else []
        data["tags"] = [item for item in tags if item != "pass"] + ["block", "runtime-growth-blocked"]
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        metadata["risk_level"] = "high"
        data["metadata"] = metadata
    data["content"] = content
    storage.write_json(path, data)
    acceptance = result.get("acceptance_report", {})
    if isinstance(acceptance, dict):
        acceptance["asset"] = data


def _next_step(result: dict[str, Any]) -> str:
    if result.get("status") == "interrupted":
        return "The run was interrupted. Inspect the per-chapter durations, keep the generated local assets as evidence, optimize the slow path, and rerun."
    preflight = result.get("runtime_growth_preflight", {}) if isinstance(result.get("runtime_growth_preflight", {}), dict) else {}
    if preflight and preflight.get("status") != "passed":
        return "Repair runtime growth threshold blockers, regenerate the preflight gate evidence, and rerun acceptance only after the gate passes."
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
