from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_chain import create_draft_version
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.schemas import DraftDiffReport, EditorPatch, validate_common_fields
from novel_forge.storage.local import LocalStorage


def create_editor_patch(
    storage: LocalStorage,
    draft_path: str | Path,
    *,
    instructions: str = "",
    operations: list[dict[str, Any]] | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    storage.ensure_layout()
    path = resolve_path(storage.root, draft_path)
    draft = storage.read_asset(path)
    if draft.type != "draft_chapter":
        raise ValueError("draft_path must point to a draft_chapter asset")
    project = project_scope_from_asset(storage, draft, input_path=path, workspace_path=workspace_path)
    normalized_operations = _normalize_operations(operations or [], instructions=instructions, draft_text=str(draft.content.get("text", "")))
    with AgentExecutionContext(
        storage,
        agent_key="ai_editor",
        operation="create-editor-patch",
        input_assets=[path],
        output_types=["editor_patch"],
        workspace_path=str(project.get("workspace_path", "")),
        sla_seconds=600,
    ) as run:
        run.guard("read_asset")
        run.guard("write_editor_patch", "editor_patch")
        now = utc_now()
        asset = EditorPatch(
            title=f"Editor patch for {draft.title or draft.id}",
            source=draft.id,
            tags=["editor", "patch", "proposed"],
            content={
                "patch_id": make_id("editor_patch", draft.id),
                "target_draft_id": draft.id,
                "target_draft_path": _display_path(storage.root, path),
                "instructions": instructions,
                "operations": normalized_operations,
                "status": "proposed",
                "risk_flags": _operation_risks(normalized_operations),
                "created_at": now,
                "applied_at": "",
            },
            metadata={
                "project_id": project.get("project_id", ""),
                "workspace_path": project.get("workspace_path", ""),
                "agent_run_path": run.path,
            },
            references=filter_project_safe_references(
                storage,
                str(project.get("project_id", "")),
                [draft.id, _display_path(storage.root, path)],
            ),
        )
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"]])
        return result


def apply_editor_patch(
    storage: LocalStorage,
    patch_path: str | Path,
    *,
    apply: bool = True,
    change_summary: str = "editor patch applied",
    operation_ids: list[str] | None = None,
    operation_indexes: list[int] | None = None,
) -> dict[str, Any]:
    path = resolve_path(storage.root, patch_path)
    patch = storage.read_asset(path)
    if patch.type != "editor_patch":
        raise ValueError("patch_path must point to an editor_patch asset")
    target_path = resolve_path(storage.root, str(patch.content.get("target_draft_path", "")))
    draft = storage.read_asset(target_path)
    if draft.type != "draft_chapter":
        raise ValueError("editor_patch target must point to a draft_chapter asset")
    project = project_scope_from_asset(storage, draft, input_path=target_path)
    before_text = str(draft.content.get("text", ""))
    selected_operations = _selected_operations(
        patch.content.get("operations", []),
        operation_ids=operation_ids or [],
        operation_indexes=operation_indexes or [],
    )
    after_text = _apply_operations(before_text, selected_operations)
    with AgentExecutionContext(
        storage,
        agent_key="ai_editor",
        operation="apply-editor-patch",
        input_assets=[path, target_path],
        output_types=["draft_diff_report", "draft_version"],
        workspace_path=str(project.get("workspace_path", "")),
        sla_seconds=900,
    ) as run:
        run.guard("read_asset")
        run.guard("write_draft_diff_report", "draft_diff_report")
        diff_report = _write_diff_report(
            storage,
            base_draft=draft,
            base_path=target_path,
            target_draft=draft,
            target_path=target_path,
            before_text=before_text,
            after_text=after_text,
            operations=selected_operations,
            title=f"Patch diff for {draft.title or draft.id}",
            source=patch.id,
            project=project,
            extra_references=[patch.id, _display_path(storage.root, path)],
        )
        version: dict[str, Any] | None = None
        if apply:
            run.guard("write_draft_version", "draft_version")
            draft_data = storage.read_json(target_path)
            content = draft_data.get("content", {}) if isinstance(draft_data.get("content", {}), dict) else {}
            content["text"] = after_text
            content["last_editor_patch_id"] = patch.id
            content["last_editor_patch_path"] = _display_path(storage.root, path)
            draft_data["content"] = content
            draft_data["updated_at"] = utc_now()
            storage.write_json(target_path, draft_data)
            version = create_draft_version(storage, target_path, change_summary=change_summary, status="active")
            patch_data = storage.read_json(path)
            patch_content = patch_data.get("content", {}) if isinstance(patch_data.get("content", {}), dict) else {}
            patch_content["status"] = "partially_applied" if len(selected_operations) != len(patch.content.get("operations", [])) else "applied"
            patch_content["applied_at"] = utc_now()
            patch_content["applied_operation_ids"] = [str(operation.get("op_id", "")) for operation in selected_operations]
            patch_content["diff_report_path"] = diff_report["path"]
            patch_content["draft_version_path"] = version["path"]
            patch_data["content"] = patch_content
            patch_data["updated_at"] = utc_now()
            storage.write_json(path, patch_data)
        run.succeed(output_assets=[diff_report["path"], *( [version["path"]] if version else [] )])
        return {
            "patch_path": _display_path(storage.root, path),
            "diff_report": diff_report,
            "draft_version": version,
            "applied": apply,
            "applied_operations": [str(operation.get("op_id", "")) for operation in selected_operations],
        }


def create_draft_diff_report(
    storage: LocalStorage,
    base_path: str | Path,
    target_path: str | Path,
) -> dict[str, Any]:
    base_file = resolve_path(storage.root, base_path)
    target_file = resolve_path(storage.root, target_path)
    base = storage.read_asset(base_file)
    target = storage.read_asset(target_file)
    if base.type not in {"draft_chapter", "draft_version"}:
        raise ValueError("base_path must point to draft_chapter or draft_version")
    if target.type not in {"draft_chapter", "draft_version"}:
        raise ValueError("target_path must point to draft_chapter or draft_version")
    project = project_scope_from_asset(storage, target, input_path=target_file)
    with AgentExecutionContext(
        storage,
        agent_key="ai_editor",
        operation="create-draft-diff-report",
        input_assets=[base_file, target_file],
        output_types=["draft_diff_report"],
        workspace_path=str(project.get("workspace_path", "")),
        sla_seconds=600,
    ) as run:
        run.guard("read_asset")
        run.guard("write_draft_diff_report", "draft_diff_report")
        result = _write_diff_report(
            storage,
            base_draft=base,
            base_path=base_file,
            target_draft=target,
            target_path=target_file,
            before_text=str(base.content.get("text", "")),
            after_text=str(target.content.get("text", "")),
            operations=[],
            title=f"Draft diff: {base.title or base.id} -> {target.title or target.id}",
            source=base.id,
            project=project,
            extra_references=[target.id, _display_path(storage.root, target_file)],
        )
        run.succeed(output_assets=[result["path"]])
        return result


def list_editor_artifacts(storage: LocalStorage, *, project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for category, asset_types in {"drafts": {"editor_patch", "draft_diff_report"}}.items():
        for path in storage.list_json(category):
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict) or data.get("type") not in asset_types:
                continue
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            if project_id and str(metadata.get("project_id", "")) != project_id:
                continue
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            rows.append(
                {
                    "path": _display_path(storage.root, path),
                    "id": data.get("id", ""),
                    "type": data.get("type", ""),
                    "title": data.get("title") or data.get("name", ""),
                    "status": content.get("status", ""),
                    "target_draft_path": content.get("target_draft_path") or content.get("target_draft_path", ""),
                    "summary": content.get("diff_summary", {}),
                    "operations": content.get("operations", []),
                    "project_id": metadata.get("project_id", ""),
                    "workspace_path": metadata.get("workspace_path", ""),
                    "updated_at": data.get("updated_at", ""),
                }
            )
    return sorted(rows, key=lambda row: row.get("updated_at", ""), reverse=True)[:limit]


def _write_diff_report(
    storage: LocalStorage,
    *,
    base_draft: Any,
    base_path: Path,
    target_draft: Any,
    target_path: Path,
    before_text: str,
    after_text: str,
    operations: list[dict[str, Any]],
    title: str,
    source: str,
    project: dict[str, Any],
    extra_references: list[str] | None = None,
) -> dict[str, Any]:
    diff_lines = list(
        difflib.unified_diff(
            before_text.splitlines(),
            after_text.splitlines(),
            fromfile="before",
            tofile="after",
            lineterm="",
        )
    )
    summary = _diff_summary(before_text, after_text, diff_lines)
    asset = DraftDiffReport(
        title=title,
        source=source,
        tags=["draft", "diff", "editor"],
        content={
            "diff_id": make_id("draft_diff", f"{base_draft.id}-{target_draft.id}-{summary['changed_lines']}"),
            "base_draft_id": base_draft.id,
            "base_draft_path": _display_path(storage.root, base_path),
            "target_draft_id": target_draft.id,
            "target_draft_path": _display_path(storage.root, target_path),
            "diff_summary": summary,
            "operations": operations,
            "unified_diff": diff_lines[:400],
            "created_at": utc_now(),
        },
        metadata={
            "project_id": project.get("project_id", ""),
            "workspace_path": project.get("workspace_path", ""),
        },
        references=filter_project_safe_references(
            storage,
            str(project.get("project_id", "")),
            [
                base_draft.id,
                _display_path(storage.root, base_path),
                target_draft.id,
                _display_path(storage.root, target_path),
                *(extra_references or []),
            ],
        ),
    )
    return _write(storage, asset)


def _normalize_operations(operations: list[dict[str, Any]], *, instructions: str, draft_text: str) -> list[dict[str, Any]]:
    if operations:
        return [_normalize_operation(index, operation) for index, operation in enumerate(operations, start=1)]
    return _suggest_paragraph_operations(draft_text, instructions=instructions)


def _normalize_operation(index: int, operation: dict[str, Any]) -> dict[str, Any]:
    kind = str(operation.get("kind") or operation.get("op") or "replace_text")
    return {
        "op_id": str(operation.get("op_id") or f"op-{index}"),
        "kind": kind,
        "target": str(operation.get("target", "document")),
        "paragraph_index": operation.get("paragraph_index", index),
        "before": str(operation.get("before", "")),
        "after": str(operation.get("after", "")),
        "instruction": str(operation.get("instruction", "")),
        "status": str(operation.get("status", "proposed")),
        "risk": str(operation.get("risk", "low")),
    }


def _suggest_paragraph_operations(draft_text: str, *, instructions: str) -> list[dict[str, Any]]:
    paragraphs = _paragraphs(draft_text)
    note = instructions.strip() or "tighten paragraph while preserving continuity and originality boundary"
    if not paragraphs:
        return [
            {
                "op_id": "op-1",
                "kind": "append_text",
                "target": "document:end",
                "paragraph_index": 0,
                "before": "",
                "after": "\n\n[manual editor note] Add a concrete paragraph-level revision here after reviewing context.",
                "instruction": note,
                "status": "proposed",
                "risk": "low",
            }
        ]
    candidates = _candidate_paragraphs(paragraphs)
    operations: list[dict[str, Any]] = []
    for op_index, paragraph_index in enumerate(candidates[:5], start=1):
        before = paragraphs[paragraph_index]
        after = _paragraph_revision(before, instructions=note)
        operations.append(
            {
                "op_id": f"op-{op_index}",
                "kind": "replace_text",
                "target": f"paragraph:{paragraph_index + 1}",
                "paragraph_index": paragraph_index + 1,
                "before": before,
                "after": after,
                "instruction": note,
                "rationale": "paragraph-level tightening suggestion generated by local editor rules",
                "status": "proposed",
                "risk": _paragraph_risk(before, after),
            }
        )
    return operations


def _paragraphs(text: str) -> list[str]:
    return [part.strip() for part in text.split("\n\n") if part.strip()]


def _candidate_paragraphs(paragraphs: list[str]) -> list[int]:
    scored = sorted(
        enumerate(paragraphs),
        key=lambda item: (
            len(item[1]) > 180,
            item[1].count("，") + item[1].count(",") + item[1].count(";") + item[1].count("；"),
            len(item[1]),
        ),
        reverse=True,
    )
    return [index for index, _ in scored] or [0]


def _paragraph_revision(paragraph: str, *, instructions: str) -> str:
    text = " ".join(paragraph.split())
    if len(text) > 360:
        text = text[:330].rstrip(" ,，。.") + "..."
    if "tighten" in instructions.lower() or "收紧" in instructions:
        text = _tighten_sentence(text)
    return text


def _tighten_sentence(text: str) -> str:
    replacements = {
        "very ": "",
        "really ": "",
        "just ": "",
        "其实": "",
        "非常": "",
        "有些": "",
        "似乎": "",
    }
    result = text
    for before, after in replacements.items():
        result = result.replace(before, after)
    return result


def _paragraph_risk(before: str, after: str) -> str:
    delta = abs(len(after) - len(before))
    if delta > 800 or len(before) > 1800:
        return "medium"
    return "low"


def _selected_operations(
    operations: Any,
    *,
    operation_ids: list[str],
    operation_indexes: list[int],
) -> list[dict[str, Any]]:
    if not isinstance(operations, list):
        raise ValueError("editor_patch operations must be a list")
    normalized = [operation for operation in operations if isinstance(operation, dict)]
    selected_ids = {str(value) for value in operation_ids if str(value).strip()}
    selected_indexes = {int(value) for value in operation_indexes if int(value) > 0}
    if not selected_ids and not selected_indexes:
        return normalized
    selected: list[dict[str, Any]] = []
    for index, operation in enumerate(normalized, start=1):
        if str(operation.get("op_id", "")) in selected_ids or index in selected_indexes:
            selected.append(operation)
    if not selected:
        raise ValueError("no editor patch operations matched operation_ids or operation_indexes")
    return selected


def _apply_operations(text: str, operations: Any) -> str:
    if not isinstance(operations, list):
        raise ValueError("editor_patch operations must be a list")
    result = text
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        kind = str(operation.get("kind", "replace_text"))
        before = str(operation.get("before", ""))
        after = str(operation.get("after", ""))
        if kind == "replace_text":
            if before and before in result:
                result = result.replace(before, after, 1)
            elif before:
                raise ValueError(f"replace_text target not found for {operation.get('op_id', '')}")
        elif kind == "append_text":
            result = result + after
        elif kind == "prepend_text":
            result = after + result
        elif kind == "delete_text":
            if before and before in result:
                result = result.replace(before, "", 1)
            elif before:
                raise ValueError(f"delete_text target not found for {operation.get('op_id', '')}")
        elif kind == "noop":
            continue
        else:
            raise ValueError(f"unsupported editor operation kind: {kind}")
    return result


def _diff_summary(before: str, after: str, diff_lines: list[str]) -> dict[str, Any]:
    added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
    return {
        "before_chars": len(before),
        "after_chars": len(after),
        "char_delta": len(after) - len(before),
        "added_lines": added,
        "removed_lines": removed,
        "changed_lines": added + removed,
    }


def _operation_risks(operations: list[dict[str, Any]]) -> list[str]:
    risks = sorted({str(operation.get("risk", "low")) for operation in operations if str(operation.get("risk", "")).strip()})
    if any(operation.get("kind") in {"delete_text", "replace_text"} and len(str(operation.get("before", ""))) > 2000 for operation in operations):
        risks.append("large_rewrite")
    return risks


def _write(storage: LocalStorage, asset: EditorPatch | DraftDiffReport) -> dict[str, Any]:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "id": asset.id, "asset": asset.to_dict(), "validation": {"ok": True, "errors": []}}


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
