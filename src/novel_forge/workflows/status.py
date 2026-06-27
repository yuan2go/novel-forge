from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from novel_forge.core.ids import utc_now
from novel_forge.modules.workflow_nodes import record_node_run
from novel_forge.schemas import TaskStatus
from novel_forge.storage.local import LocalStorage

T = TypeVar("T")


def execute_task(
    storage: LocalStorage,
    run_id: str,
    step: str,
    input_paths: list[str | Path],
    action: Callable[[], T],
    status_collector: list[Path] | None = None,
) -> tuple[T, list[Path]]:
    status_paths: list[Path] = []
    _record_status_path(
        write_task_status(storage, run_id, step, "pending", input_paths=input_paths), status_paths, status_collector
    )
    started_at = utc_now()
    _record_status_path(
        write_task_status(storage, run_id, step, "running", input_paths=input_paths), status_paths, status_collector
    )
    try:
        result = action()
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        _record_status_path(
            write_task_status(
                storage,
                run_id,
                step,
                "failed",
                input_paths=input_paths,
                error_message=error_message,
            ),
            status_paths,
            status_collector,
        )
        record_node_run(
            storage,
            run_id=run_id,
            node_id=step,
            node_type="workflow_step",
            operation=step,
            status="failed",
            input_assets=input_paths,
            output_assets=[],
            processor={"kind": "workflow_step", "name": step},
            started_at=started_at,
            finished_at=utc_now(),
            error=error_message,
            quality_gate={"required": False, "status": "skipped"},
        )
        raise

    output_paths = [result] if isinstance(result, Path) else []
    record_node_run(
        storage,
        run_id=run_id,
        node_id=step,
        node_type="workflow_step",
        operation=step,
        status="succeeded",
        input_assets=input_paths,
        output_assets=output_paths,
        processor={"kind": "workflow_step", "name": step},
        started_at=started_at,
        finished_at=utc_now(),
        quality_gate={"required": False, "status": "not_applicable"},
    )
    _record_status_path(
        write_task_status(storage, run_id, step, "completed", input_paths=input_paths, output_paths=output_paths),
        status_paths,
        status_collector,
    )
    return result, status_paths


def write_task_status(
    storage: LocalStorage,
    run_id: str,
    step: str,
    status: str,
    input_paths: list[str | Path] | None = None,
    output_paths: list[str | Path] | None = None,
    error_message: str = "",
) -> Path:
    input_values = [_display_path(storage, path) for path in input_paths or []]
    output_values = [_display_path(storage, path) for path in output_paths or []]
    asset = TaskStatus(
        title=f"{step} {status}",
        source=run_id,
        tags=["task-status", step, status],
        content={
            "run_id": run_id,
            "step": step,
            "status": status,
            "input_paths": input_values,
            "output_paths": output_values,
            "error_message": error_message,
        },
        metadata={"recorded_at": utc_now()},
        references=[run_id, *input_values, *output_values],
    )
    return storage.write_asset("runs", asset)


def build_run_log(storage: LocalStorage, status_paths: list[Path]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in status_paths:
        try:
            asset = storage.read_asset(path)
        except Exception:
            continue
        if asset.type != "task_status":
            continue
        entries.append(
            {
                "step": asset.content.get("step", ""),
                "status": asset.content.get("status", ""),
                "input_paths": asset.content.get("input_paths", []),
                "output_paths": asset.content.get("output_paths", []),
                "error_message": asset.content.get("error_message", ""),
                "recorded_at": asset.metadata.get("recorded_at", ""),
                "status_asset": _display_path(storage, path),
            }
        )
    return entries


def build_recovery_instruction(run_log: list[dict[str, Any]], error_message: str) -> str:
    failed = next((entry for entry in reversed(run_log) if entry.get("status") == "failed"), {})
    step = failed.get("step") or "unknown"
    inputs = failed.get("input_paths") or []
    input_text = ", ".join(inputs) if inputs else "the failed step input"
    return (
        f"Recover by inspecting step '{step}' and input {input_text}. "
        f"Fix the input asset or module service, then rerun the pipeline from a clean sample run. "
        f"Original error: {error_message}"
    )


def write_recovery_note(
    storage: LocalStorage,
    run_id: str,
    run_log: list[dict[str, Any]],
    recovery_instruction: str,
) -> Path:
    storage.ensure_layout()
    path = storage.data_dir("runs") / f"{run_id}-recovery.md"
    lines = [
        f"# Recovery Note: {run_id}",
        "",
        "## Recovery Instruction",
        "",
        recovery_instruction,
        "",
        "## Run Log",
        "",
        "| Step | Status | Inputs | Outputs | Error |",
        "|---|---|---|---|---|",
    ]
    for entry in run_log:
        lines.append(
            "| {step} | {status} | {inputs} | {outputs} | {error} |".format(
                step=entry.get("step", ""),
                status=entry.get("status", ""),
                inputs=", ".join(entry.get("input_paths", [])),
                outputs=", ".join(entry.get("output_paths", [])),
                error=entry.get("error_message", ""),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _record_status_path(path: Path, status_paths: list[Path], status_collector: list[Path] | None) -> None:
    status_paths.append(path)
    if status_collector is not None:
        status_collector.append(path)


def _display_path(storage: LocalStorage, path: str | Path) -> str:
    resolved = Path(path)
    if not resolved.is_absolute():
        return str(resolved)
    try:
        return str(resolved.relative_to(storage.root))
    except ValueError:
        return str(resolved)
