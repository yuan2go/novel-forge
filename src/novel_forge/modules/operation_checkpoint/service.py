from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.schemas import AgentCheckpoint, validate_common_fields
from novel_forge.storage.local import LocalStorage

CHECKPOINT_STAGES = [
    "prepared_inputs",
    "context_built",
    "prompt_built",
    "provider_started",
    "provider_completed",
    "output_validated",
    "output_committed",
    "gates_completed",
]


def operation_checkpoint_schema(
    operation: str,
    *,
    version: str = "1.0",
    checkpoint_strategy: str = "operation_state",
    safe_to_replay: bool = True,
    idempotency_key_fields: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "version": version,
        "operation": operation,
        "strategy": checkpoint_strategy,
        "stages": list(CHECKPOINT_STAGES),
        "resume_points": [
            {"stage": "context_built", "resume_action": "resume_prompt_build"},
            {"stage": "prompt_built", "resume_action": "resume_provider_call"},
            {"stage": "provider_completed", "resume_action": "resume_output_validation"},
            {"stage": "output_committed", "resume_action": "reuse_committed_outputs"},
        ],
        "idempotency_key_fields": idempotency_key_fields
        or ["operation", "input_asset_fingerprints", "context_bundle_fingerprint", "prompt_version", "model"],
        "safe_to_replay": safe_to_replay,
        "required": ["operation", "stage", "idempotency_key", "input_assets", "output_assets"],
    }


def checkpoint_idempotency_key(
    storage: LocalStorage,
    *,
    operation: str,
    input_assets: list[str | Path] | None = None,
    context_bundle_path: str = "",
    prompt_version: str = "",
    model: str = "",
) -> str:
    payload = {
        "operation": operation,
        "input_asset_fingerprints": [_path_fingerprint(storage, item) for item in input_assets or []],
        "context_bundle_fingerprint": _path_fingerprint(storage, context_bundle_path) if context_bundle_path else {},
        "prompt_version": prompt_version,
        "model": model,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:24]
    return f"operation-checkpoint-{digest}"


def build_checkpoint_state(
    storage: LocalStorage,
    *,
    operation: str,
    stage: str,
    input_assets: list[str | Path] | None = None,
    output_assets: list[str | Path] | None = None,
    context_bundle_path: str = "",
    prompt_version: str = "",
    prompt_hash: str = "",
    model: str = "",
    provider_request_id: str = "",
    raw_output_path: str = "",
    raw_output_segments: list[str | Path] | None = None,
    gate_result_paths: list[str | Path] | None = None,
    idempotency_key: str = "",
    error: str = "",
    extra_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_stage = _normalize_stage(stage)
    inputs = [str(item) for item in input_assets or []]
    outputs = [str(item) for item in output_assets or []]
    key = idempotency_key or checkpoint_idempotency_key(
        storage,
        operation=operation,
        input_assets=inputs,
        context_bundle_path=context_bundle_path,
        prompt_version=prompt_version,
        model=model,
    )
    return {
        "operation": operation,
        "stage": normalized_stage,
        "status": normalized_stage,
        "idempotency_key": key,
        "input_assets": inputs,
        "input_asset_fingerprints": [_path_fingerprint(storage, item) for item in inputs],
        "context_bundle_path": context_bundle_path,
        "context_bundle_fingerprint": _path_fingerprint(storage, context_bundle_path) if context_bundle_path else {},
        "prompt_version": prompt_version,
        "prompt_hash": prompt_hash,
        "model": model,
        "provider_request_id": provider_request_id,
        "raw_output_path": raw_output_path,
        "raw_output_segments": [str(item) for item in raw_output_segments or []],
        "output_assets": outputs,
        "gate_result_paths": [str(item) for item in gate_result_paths or []],
        "schema": operation_checkpoint_schema(operation),
        "error": error,
        "extra_state": extra_state or {},
        "created_at": utc_now(),
    }


def validate_checkpoint_state(storage: LocalStorage, state: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(state, dict):
        return ["checkpoint state must be an object"]
    if str(state.get("stage", "")) not in CHECKPOINT_STAGES:
        errors.append(f"checkpoint stage must be one of: {', '.join(CHECKPOINT_STAGES)}")
    for key in ["operation", "idempotency_key"]:
        if not str(state.get(key, "")).strip():
            errors.append(f"checkpoint {key} must not be empty")
    for item in state.get("output_assets", []) if isinstance(state.get("output_assets", []), list) else []:
        if str(item).strip() and not _path_exists(storage, item):
            errors.append(f"checkpoint output asset does not exist: {item}")
    raw_output_path = str(state.get("raw_output_path", "") or "")
    if raw_output_path and not _path_exists(storage, raw_output_path):
        errors.append(f"checkpoint raw output path does not exist: {raw_output_path}")
    for item in state.get("raw_output_segments", []) if isinstance(state.get("raw_output_segments", []), list) else []:
        if str(item).strip() and not _path_exists(storage, item):
            errors.append(f"checkpoint raw output segment does not exist: {item}")
    return errors


def checkpoint_resume_plan(
    storage: LocalStorage,
    state: dict[str, Any],
    *,
    changed_assets: list[str | Path] | None = None,
) -> dict[str, Any]:
    errors = validate_checkpoint_state(storage, state)
    if errors:
        return {"status": "invalid", "resume_action": "restart_operation", "errors": errors}
    changed = {str(item) for item in changed_assets or [] if str(item).strip()}
    if changed and _checkpoint_inputs_changed(state, changed):
        return {"status": "stale", "resume_action": "rebuild_context", "reason": "input asset changed after checkpoint"}
    stage = str(state.get("stage", "prepared_inputs"))
    outputs = [str(item) for item in state.get("output_assets", []) if str(item).strip()] if isinstance(state.get("output_assets", []), list) else []
    existing_outputs = [item for item in outputs if _path_exists(storage, item)]
    if stage in {"output_committed", "gates_completed"} and outputs and len(existing_outputs) == len(outputs):
        return {"status": "reusable", "resume_action": "reuse_committed_outputs", "output_assets": existing_outputs}
    raw_output_path = str(state.get("raw_output_path", "") or "")
    raw_output_segments = [str(item) for item in state.get("raw_output_segments", []) if str(item).strip()] if isinstance(state.get("raw_output_segments", []), list) else []
    if stage == "provider_completed" and raw_output_path and _path_exists(storage, raw_output_path):
        return {"status": "resumable", "resume_action": "resume_output_validation", "raw_output_path": raw_output_path}
    if stage == "provider_completed" and raw_output_segments and all(_path_exists(storage, item) for item in raw_output_segments):
        manifest = assemble_raw_output_segments(storage, raw_output_segments=raw_output_segments, persist=False)
        return {
            "status": "resumable",
            "resume_action": "resume_output_validation",
            "raw_output_segments": raw_output_segments,
            "assembled_sha256": manifest.get("sha256", ""),
            "segment_count": manifest.get("segment_count", len(raw_output_segments)),
        }
    if stage in {"prompt_built", "provider_started"}:
        return {"status": "resumable", "resume_action": "resume_provider_call"}
    if stage == "context_built":
        return {"status": "resumable", "resume_action": "resume_prompt_build"}
    return {"status": "restart", "resume_action": "rebuild_context"}


def create_operation_checkpoint(
    storage: LocalStorage,
    *,
    operation: str,
    stage: str,
    agent_run_id: str = "",
    agent_run_path: str = "",
    workflow_run_id: str = "",
    workflow_run_path: str = "",
    input_assets: list[str | Path] | None = None,
    output_assets: list[str | Path] | None = None,
    context_bundle_path: str = "",
    prompt_version: str = "",
    prompt_hash: str = "",
    model: str = "",
    provider_request_id: str = "",
    raw_output_path: str = "",
    raw_output_segments: list[str | Path] | None = None,
    gate_result_paths: list[str | Path] | None = None,
    idempotency_key: str = "",
    error: str = "",
    extra_state: dict[str, Any] | None = None,
    project_id: str = "",
    workspace_path: str = "",
) -> dict[str, Any]:
    storage.ensure_layout()
    state = build_checkpoint_state(
        storage,
        operation=operation,
        stage=stage,
        input_assets=input_assets,
        output_assets=output_assets,
        context_bundle_path=context_bundle_path,
        prompt_version=prompt_version,
        prompt_hash=prompt_hash,
        model=model,
        provider_request_id=provider_request_id,
        raw_output_path=raw_output_path,
        raw_output_segments=raw_output_segments,
        gate_result_paths=gate_result_paths,
        idempotency_key=idempotency_key,
        error=error,
        extra_state=extra_state,
    )
    errors = validate_checkpoint_state(storage, state)
    status = "invalid" if errors else str(state.get("stage", "checkpointed"))
    checkpoint_id = make_id("agent_checkpoint", f"{operation}-{state.get('idempotency_key', '')}-{stage}")
    content = {
        "agent_run_id": agent_run_id or workflow_run_id or str(state.get("idempotency_key", "")),
        "agent_run_path": agent_run_path,
        "workflow_run_id": workflow_run_id,
        "workflow_run_path": workflow_run_path,
        "checkpoint_id": checkpoint_id,
        "operation": operation,
        "stage": state.get("stage", ""),
        "status": status,
        "state": state,
        "validation": {"ok": not errors, "errors": errors},
        "resume_plan": checkpoint_resume_plan(storage, state),
        "created_at": utc_now(),
    }
    asset = AgentCheckpoint(
        title=f"Operation checkpoint: {operation}/{stage}",
        source=agent_run_id or workflow_run_id or str(state.get("idempotency_key", "")),
        tags=["operation-checkpoint", operation, str(state.get("stage", "")), status],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path},
        references=filter_project_safe_references(
            storage,
            project_id,
            _dedupe([agent_run_path, workflow_run_path, context_bundle_path, raw_output_path, *[str(item) for item in raw_output_segments or []], *[str(item) for item in input_assets or []], *[str(item) for item in output_assets or []], *[str(item) for item in gate_result_paths or []]]),
        ),
    )
    data = asset.to_dict()
    validation_errors = validate_common_fields(data)
    if validation_errors:
        raise ValueError("; ".join(validation_errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path), "state": state}


def record_operation_stage_checkpoint(
    storage: LocalStorage,
    *,
    operation: str,
    stage: str,
    stage_payload: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Persist a stage-level checkpoint for long model operations.

    Draft, review, revision, analysis, and benchmark operations should call this
    before and after prompt build, provider execution, raw output validation, and
    commit. The function intentionally reuses `agent_checkpoint` so existing
    scheduler resume logic can consume the same durable asset type.
    """

    payload = dict(stage_payload or {})
    extra_state = dict(kwargs.pop("extra_state", {}) or {})
    extra_state["stage_payload"] = payload
    return create_operation_checkpoint(
        storage,
        operation=operation,
        stage=stage,
        extra_state=extra_state,
        **kwargs,
    )


def record_raw_output_segment(
    storage: LocalStorage,
    *,
    operation: str,
    idempotency_key: str,
    segment_index: int,
    text: str = "",
    raw_payload: dict[str, Any] | None = None,
    provider: str = "",
    model: str = "",
    provider_request_id: str = "",
    project_id: str = "",
    workspace_path: str = "",
) -> dict[str, Any]:
    storage.ensure_layout()
    segment_id = make_id("operation_raw_segment", f"{operation}-{idempotency_key}-{segment_index}")
    payload = {
        "type": "operation_raw_output_segment",
        "id": segment_id,
        "name": f"Raw output segment {operation} #{segment_index}",
        "version": "1.0",
        "title": f"Raw output segment {operation} #{segment_index}",
        "source": idempotency_key,
        "tags": ["operation-checkpoint", "raw-output-segment", operation],
        "content": {
            "operation": operation,
            "idempotency_key": idempotency_key,
            "segment_index": int(segment_index),
            "text": text,
            "raw_payload": raw_payload or {},
            "provider": provider,
            "model": model,
            "provider_request_id": provider_request_id,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "byte_count": len(text.encode("utf-8")),
            "created_at": utc_now(),
        },
        "metadata": {"project_id": project_id, "workspace_path": workspace_path},
        "references": [],
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    path = storage.root / "data" / "runs" / f"{segment_id}.json"
    storage.write_json(path, payload)
    return {"path": _display_path(storage.root, path), "asset": payload}


def assemble_raw_output_segments(
    storage: LocalStorage,
    *,
    operation: str = "",
    idempotency_key: str = "",
    raw_output_segments: list[str | Path] | None = None,
    persist: bool = True,
    project_id: str = "",
    workspace_path: str = "",
) -> dict[str, Any]:
    storage.ensure_layout()
    selected: list[tuple[str, dict[str, Any]]] = []
    if raw_output_segments:
        for item in raw_output_segments:
            path = resolve_path(storage.root, item)
            data = storage.read_json(path)
            if isinstance(data, dict) and data.get("type") == "operation_raw_output_segment":
                selected.append((_display_path(storage.root, path), data))
    else:
        for path in storage.list_json("runs"):
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict) or data.get("type") != "operation_raw_output_segment":
                continue
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            if operation and str(content.get("operation", "")) != operation:
                continue
            if idempotency_key and str(content.get("idempotency_key", "")) != idempotency_key:
                continue
            selected.append((_display_path(storage.root, path), data))
    selected.sort(key=lambda item: int((item[1].get("content", {}) if isinstance(item[1].get("content", {}), dict) else {}).get("segment_index", 0)))
    assembled_text = "".join(str((data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}).get("text", "")) for _, data in selected)
    first_content = selected[0][1].get("content", {}) if selected and isinstance(selected[0][1].get("content", {}), dict) else {}
    manifest = {
        "type": "operation_raw_output_manifest",
        "id": make_id("operation_raw_manifest", f"{operation}-{idempotency_key}-{len(selected)}"),
        "title": f"Raw output manifest {operation}",
        "source": idempotency_key,
        "tags": ["operation-checkpoint", "raw-output-manifest", operation],
        "content": {
            "operation": operation or str(first_content.get("operation", "")),
            "idempotency_key": idempotency_key or str(first_content.get("idempotency_key", "")),
            "segment_paths": [path for path, _ in selected],
            "segment_count": len(selected),
            "byte_count": len(assembled_text.encode("utf-8")),
            "sha256": hashlib.sha256(assembled_text.encode("utf-8")).hexdigest(),
            "text": assembled_text,
            "created_at": utc_now(),
        },
        "metadata": {"project_id": project_id, "workspace_path": workspace_path},
        "references": [path for path, _ in selected],
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    if not persist:
        return {**manifest["content"], "asset": manifest, "path": ""}
    path = storage.root / "data" / "runs" / f"{manifest['id']}.json"
    storage.write_json(path, manifest)
    return {**manifest["content"], "asset": manifest, "path": _display_path(storage.root, path)}


def operation_checkpoint_chain(
    storage: LocalStorage,
    *,
    operation: str,
    idempotency_key: str = "",
    project_id: str = "",
    workspace_path: str = "",
) -> dict[str, Any]:
    storage.ensure_layout()
    rows: list[dict[str, Any]] = []
    for path in storage.list_json("runs"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "agent_checkpoint":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        state = content.get("state", {}) if isinstance(content.get("state", {}), dict) else {}
        if str(state.get("operation", "") or content.get("operation", "")) != operation:
            continue
        if idempotency_key and str(state.get("idempotency_key", "")) != idempotency_key:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        if workspace_path and str(metadata.get("workspace_path", "")) != workspace_path:
            continue
        rows.append({"path": _display_path(storage.root, path), "asset": data, "state": state, "stage": state.get("stage", ""), "created_at": content.get("created_at", "")})
    rows.sort(key=lambda item: (str(item.get("created_at", "")), CHECKPOINT_STAGES.index(str(item.get("stage", ""))) if str(item.get("stage", "")) in CHECKPOINT_STAGES else -1))
    completed = {str(row.get("stage", "")) for row in rows}
    missing = [stage for stage in CHECKPOINT_STAGES if stage not in completed]
    latest = rows[-1] if rows else {}
    return {
        "status": "complete" if not missing else "partial" if rows else "missing",
        "operation": operation,
        "idempotency_key": idempotency_key,
        "completed_stages": [stage for stage in CHECKPOINT_STAGES if stage in completed],
        "missing_stages": missing,
        "latest": latest,
        "resume_plan": checkpoint_resume_plan(storage, latest.get("state", {})) if latest else {"status": "restart", "resume_action": "rebuild_context"},
        "checkpoints": rows,
    }


def latest_operation_checkpoint(
    storage: LocalStorage,
    *,
    operation: str,
    idempotency_key: str = "",
    project_id: str = "",
    workspace_path: str = "",
) -> dict[str, Any]:
    storage.ensure_layout()
    latest: tuple[Path, dict[str, Any]] | None = None
    for path in storage.list_json("runs"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "agent_checkpoint":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        state = content.get("state", {}) if isinstance(content.get("state", {}), dict) else {}
        if str(content.get("operation", "") or state.get("operation", "")) != operation:
            continue
        if idempotency_key and str(state.get("idempotency_key", "")) != idempotency_key:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        if workspace_path and str(metadata.get("workspace_path", "")) != workspace_path:
            continue
        if latest is None or str(content.get("created_at", "")) >= str(latest[1].get("content", {}).get("created_at", "")):
            latest = (path, data)
    if not latest:
        return {"status": "missing", "path": "", "asset": {}, "resume_plan": {"status": "restart", "resume_action": "rebuild_context"}}
    path, data = latest
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    state = content.get("state", {}) if isinstance(content.get("state", {}), dict) else {}
    return {
        "status": "found",
        "path": _display_path(storage.root, path),
        "asset": data,
        "state": state,
        "resume_plan": checkpoint_resume_plan(storage, state),
    }


def _normalize_stage(stage: str) -> str:
    value = str(stage or "").strip()
    if value not in CHECKPOINT_STAGES:
        raise ValueError(f"checkpoint stage must be one of: {', '.join(CHECKPOINT_STAGES)}")
    return value


def _checkpoint_inputs_changed(state: dict[str, Any], changed: set[str]) -> bool:
    inputs = {str(item) for item in state.get("input_assets", []) if str(item).strip()} if isinstance(state.get("input_assets", []), list) else set()
    context = str(state.get("context_bundle_path", "") or "")
    return bool(inputs.intersection(changed) or (context and context in changed))


def _path_exists(storage: LocalStorage, path_or_id: str | Path) -> bool:
    if not str(path_or_id or "").strip():
        return False
    try:
        return resolve_path(storage.root, path_or_id).exists()
    except Exception:
        return False


def _path_fingerprint(storage: LocalStorage, path_or_id: str | Path) -> dict[str, Any]:
    if not str(path_or_id or "").strip():
        return {}
    try:
        path = resolve_path(storage.root, path_or_id)
    except Exception:
        return {"path": str(path_or_id), "status": "unresolved"}
    if not path.exists() or not path.is_file():
        return {"path": str(path_or_id), "status": "missing"}
    content = path.read_bytes()
    try:
        display = str(path.resolve().relative_to(storage.root.resolve()))
    except ValueError:
        display = str(path)
    return {"path": display, "sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
