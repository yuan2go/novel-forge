from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.modules.review_issue import create_review_issue
from novel_forge.schemas import ReaderPromise, ReaderPromiseLedger, RevisionTask, validate_common_fields
from novel_forge.storage.local import LocalStorage


TOKEN_RE = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]+")


def create_reader_promise(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    """Create or update a project-scoped reader promise asset."""

    normalized = _normalize_promise_payload(payload)
    existing = _find_existing_promise(storage, normalized)
    if existing:
        path, data = existing
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        content.update({key: normalized[key] for key in ["status", "payoff_due_chapter", "evidence_refs", "updated_at"]})
        for optional in ["payoff_target", "withheld_question", "last_seen_chapter", "last_status_reason"]:
            if optional in normalized:
                content[optional] = normalized[optional]
        data["content"] = content
        data["updated_at"] = normalized["updated_at"]
        _ensure_valid(data)
        storage.write_json(path, data)
        return {"path": _display_path(storage.root, path), "asset": storage.read_json(path), "created": False}
    asset = ReaderPromise(
        id=normalized["promise_id"],
        title=f"Reader promise ch{normalized['chapter_opened']}",
        source=str(normalized.get("source_asset_id") or normalized.get("source_asset_path") or ""),
        tags=["reader-promise", normalized["status"], normalized["promise_type"]],
        content=normalized,
        metadata={
            "project_id": normalized["project_id"],
            "workspace_path": normalized.get("workspace_path", ""),
            "chapter_opened": normalized["chapter_opened"],
            "asset_status": normalized["status"],
            "source_system": "reader_promise.ledger",
        },
        references=filter_project_safe_references(storage, normalized["project_id"], normalized["evidence_refs"]),
    )
    return _write(storage, asset) | {"created": True}


def build_reader_promise_ledger_for_draft(
    storage: LocalStorage,
    draft_path: str | Path,
    *,
    workspace_path: str | None = None,
    chapter_plan_path: str | Path | None = None,
    persist_issues: bool = True,
) -> dict[str, Any]:
    """Project chapter promises into a lifecycle ledger and repair queue.

    The ledger is intentionally derived from project-owned chapter plans/drafts.
    It stores short promise abstractions and evidence refs, not source corpus text.
    """

    draft_file = resolve_path(storage.root, draft_path)
    draft = storage.read_asset(draft_file)
    draft_content = draft.content if isinstance(draft.content, dict) else {}
    draft_metadata = draft.metadata if isinstance(draft.metadata, dict) else {}
    project = project_scope_from_asset(storage, draft, input_path=draft_file, workspace_path=workspace_path)
    project_id = str(project.get("project_id") or draft_metadata.get("project_id") or draft_content.get("project_id") or "local-system")
    workspace = str(project.get("workspace_path") or workspace_path or draft_metadata.get("workspace_path") or draft_content.get("workspace_path") or "")
    chapter_no = _chapter_no(draft.to_dict())
    plan_content, plan_ref = _chapter_plan_content(storage, chapter_plan_path)
    blueprint = draft_content.get("chapter_plan_blueprint", {}) if isinstance(draft_content.get("chapter_plan_blueprint"), dict) else {}
    promise_text = _first_text(plan_content.get("reader_promise"), blueprint.get("reader_promise"))
    payoff_target = _first_mapping(plan_content.get("payoff_target"), blueprint.get("payoff_target"))
    created_promise: dict[str, Any] | None = None
    evidence_refs = _dedupe([_display_path(storage.root, draft_file), plan_ref, str(draft.id)])
    if promise_text:
        created_promise = create_reader_promise(
            storage,
            {
                "project_id": project_id,
                "workspace_path": workspace,
                "chapter_opened": chapter_no,
                "promise_text": promise_text,
                "promise_type": "chapter",
                "status": "open",
                "payoff_due_chapter": _payoff_due_chapter(payoff_target, chapter_no),
                "payoff_target": payoff_target,
                "withheld_question": str(payoff_target.get("withheld_question") or ""),
                "source_asset_id": draft.id,
                "source_asset_path": _display_path(storage.root, draft_file),
                "evidence_refs": evidence_refs,
            }
        )
    current_text = _draft_text(draft_content)
    promise_rows = _project_promises(storage, project_id=project_id, workspace_path=workspace)
    evaluated = [_evaluate_promise(row, current_chapter=chapter_no, draft_text=current_text) for row in promise_rows]
    open_count = sum(1 for item in evaluated if item["status"] == "open")
    overdue_count = sum(1 for item in evaluated if item["status"] == "overdue")
    broken_count = sum(1 for item in evaluated if item["status"] == "broken")
    paid_off_count = sum(1 for item in evaluated if item["status"] == "paid_off")
    recommendation = "blocked" if broken_count else "revise" if overdue_count else "ready"
    now = utc_now()
    ledger = ReaderPromiseLedger(
        title=f"Reader promise ledger chapter {chapter_no}",
        source=draft.id,
        tags=["reader-promise", "ledger", recommendation],
        content={
            "ledger_id": make_id("reader_promise_ledger", f"{project_id}:{chapter_no}:{draft.id}"),
            "project_id": project_id,
            "workspace_path": workspace,
            "chapter_no": chapter_no,
            "source_draft_id": draft.id,
            "source_draft_path": _display_path(storage.root, draft_file),
            "source_chapter_plan_path": plan_ref,
            "promises": evaluated,
            "open_count": open_count,
            "overdue_count": overdue_count,
            "broken_count": broken_count,
            "paid_off_count": paid_off_count,
            "recommendation": recommendation,
            "created_promise_path": str((created_promise or {}).get("path", "")),
            "review_issue_paths": [],
            "revision_task_paths": [],
            "created_at": now,
        },
        metadata={
            "project_id": project_id,
            "workspace_path": workspace,
            "draft_path": _display_path(storage.root, draft_file),
            "source_system": "reader_promise.ledger",
            "blocking": recommendation == "blocked",
        },
        references=filter_project_safe_references(storage, project_id, [*evidence_refs, *[row.get("path", "") for row in promise_rows]]),
    )
    result = _write(storage, ledger)
    if persist_issues and (overdue_count or broken_count):
        issue_paths, task_paths = _persist_repair_queue(
            storage,
            ledger_path=result["path"],
            draft_path=_display_path(storage.root, draft_file),
            project_id=project_id,
            workspace_path=workspace,
            promises=[item for item in evaluated if item["status"] in {"overdue", "broken"}],
        )
        data = storage.read_json(resolve_path(storage.root, result["path"]))
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        content["review_issue_paths"] = issue_paths
        content["revision_task_paths"] = task_paths
        data["content"] = content
        data["references"] = filter_project_safe_references(storage, project_id, [*data.get("references", []), *issue_paths, *task_paths])
        data["updated_at"] = utc_now()
        _ensure_valid(data)
        storage.write_json(resolve_path(storage.root, result["path"]), data)
        result["asset"] = storage.read_json(resolve_path(storage.root, result["path"]))
        result["review_issue_paths"] = issue_paths
        result["revision_task_paths"] = task_paths
    else:
        result["review_issue_paths"] = []
        result["revision_task_paths"] = []
    return result


def _normalize_promise_payload(payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "local-system").strip()
    promise_text = str(payload.get("promise_text") or "").strip()
    if not promise_text:
        raise ValueError("promise_text is required")
    chapter_opened = _positive_int(payload.get("chapter_opened"), 1)
    status = str(payload.get("status") or "open").strip()
    if status not in {"open", "overdue", "broken", "paid_off", "closed"}:
        status = "open"
    now = utc_now()
    due = _positive_int(payload.get("payoff_due_chapter"), chapter_opened + 3)
    promise_id = str(payload.get("promise_id") or make_id("reader_promise", f"{project_id}:{chapter_opened}:{promise_text}")).strip()
    return {
        "promise_id": promise_id,
        "project_id": project_id,
        "workspace_path": str(payload.get("workspace_path") or ""),
        "chapter_opened": chapter_opened,
        "promise_text": promise_text,
        "promise_type": str(payload.get("promise_type") or "chapter").strip(),
        "status": status,
        "payoff_due_chapter": due,
        "payoff_target": payload.get("payoff_target") if isinstance(payload.get("payoff_target"), dict) else {},
        "withheld_question": str(payload.get("withheld_question") or ""),
        "source_asset_id": str(payload.get("source_asset_id") or ""),
        "source_asset_path": str(payload.get("source_asset_path") or ""),
        "evidence_refs": _strings(payload.get("evidence_refs")),
        "last_seen_chapter": _positive_int(payload.get("last_seen_chapter"), chapter_opened),
        "last_status_reason": str(payload.get("last_status_reason") or "created from chapter plan reader_promise"),
        "created_at": str(payload.get("created_at") or now),
        "updated_at": now,
    }


def _find_existing_promise(storage: LocalStorage, normalized: dict[str, Any]) -> tuple[Path, dict[str, Any]] | None:
    promise_id = normalized["promise_id"]
    for path in storage.list_json("continuity"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "reader_promise":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if data.get("id") == promise_id or content.get("promise_id") == promise_id:
            return path, data
    return None


def _project_promises(storage: LocalStorage, *, project_id: str, workspace_path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in storage.list_json("continuity"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "reader_promise":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if str(content.get("project_id") or metadata.get("project_id") or "local-system") != project_id:
            continue
        if workspace_path and str(content.get("workspace_path") or metadata.get("workspace_path") or "") not in {"", workspace_path}:
            continue
        rows.append({"path": _display_path(storage.root, path), "asset": data, "content": content})
    rows.sort(key=lambda row: (_positive_int(row["content"].get("chapter_opened"), 0), row["content"].get("promise_id", "")))
    return rows


def _evaluate_promise(row: dict[str, Any], *, current_chapter: int, draft_text: str) -> dict[str, Any]:
    content = row.get("content", {}) if isinstance(row.get("content"), dict) else {}
    due = _positive_int(content.get("payoff_due_chapter"), _positive_int(content.get("chapter_opened"), 1) + 3)
    stored_status = str(content.get("status") or "open")
    paid = stored_status == "paid_off" or _has_payoff_signal(draft_text, content)
    if paid:
        status = "paid_off"
        reason = "payoff signal found in draft or already paid off"
    elif current_chapter > due + 2:
        status = "broken"
        reason = f"promise overdue beyond grace window: current chapter {current_chapter}, due {due}"
    elif current_chapter > due:
        status = "overdue"
        reason = f"promise overdue: current chapter {current_chapter}, due {due}"
    else:
        status = "open"
        reason = "promise remains within payoff window"
    return {
        "promise_id": str(content.get("promise_id") or row.get("asset", {}).get("id") or ""),
        "promise_path": row.get("path", ""),
        "promise_text": str(content.get("promise_text") or ""),
        "promise_type": str(content.get("promise_type") or "chapter"),
        "chapter_opened": _positive_int(content.get("chapter_opened"), 1),
        "payoff_due_chapter": due,
        "current_chapter": current_chapter,
        "status": status,
        "severity": "high" if status == "broken" else "medium" if status == "overdue" else "info",
        "blocking": status == "broken",
        "payoff_target": content.get("payoff_target") if isinstance(content.get("payoff_target"), dict) else {},
        "withheld_question": str(content.get("withheld_question") or ""),
        "status_reason": reason,
        "evidence_refs": _dedupe([row.get("path", ""), *(_strings(content.get("evidence_refs")))]),
    }


def _persist_repair_queue(
    storage: LocalStorage,
    *,
    ledger_path: str,
    draft_path: str,
    project_id: str,
    workspace_path: str,
    promises: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    issue_paths: list[str] = []
    task_paths: list[str] = []
    for index, promise in enumerate(promises):
        issue = create_review_issue(
            storage,
            {
                "issue_type": "reader_promise_drop",
                "severity": promise["severity"],
                "blocking": bool(promise["blocking"]),
                "status": "open",
                "target_asset_path": draft_path,
                "target_asset_type": "draft_chapter",
                "project_id": project_id,
                "workspace_path": workspace_path,
                "source_system": "reader_promise.ledger",
                "source_issue_id": promise["promise_id"],
                "review_report_path": ledger_path,
                "message": f"Reader promise from chapter {promise['chapter_opened']} is {promise['status']}: {promise['promise_text']}",
                "fix_suggestion": "Pay off, visibly reschedule, or remind the promise with credible new pressure before continuing.",
                "location": {"chapter": promise["current_chapter"], "promise_chapter": promise["chapter_opened"]},
                "evidence_refs": _dedupe([ledger_path, draft_path, *promise.get("evidence_refs", [])]),
                "confidence": 0.76,
            },
        )
        issue_path = str(issue.get("path") or "")
        if issue_path:
            issue_paths.append(issue_path)
        task_paths.append(
            _write_revision_task(
                storage,
                ledger_path=ledger_path,
                draft_path=draft_path,
                project_id=project_id,
                workspace_path=workspace_path,
                promise=promise,
                issue_path=issue_path,
                issue_index=index,
            )
        )
    return _dedupe(issue_paths), _dedupe(task_paths)


def _write_revision_task(
    storage: LocalStorage,
    *,
    ledger_path: str,
    draft_path: str,
    project_id: str,
    workspace_path: str,
    promise: dict[str, Any],
    issue_path: str,
    issue_index: int,
) -> str:
    now = utc_now()
    issue = {
        "issue_id": promise["promise_id"],
        "issue_index": issue_index,
        "issue_type": "reader_promise_drop",
        "severity": promise["severity"],
        "blocking": bool(promise["blocking"]),
        "message": f"Reader promise is {promise['status']}: {promise['promise_text']}",
        "recommendation": "Add a bounded payoff, reschedule, or reminder beat and update the promise ledger.",
        "status": "open",
        "promise_path": promise.get("promise_path", ""),
        "review_issue_path": issue_path,
    }
    task = RevisionTask(
        title=f"Repair reader promise from chapter {promise['chapter_opened']}",
        source=ledger_path,
        tags=["revision", "reader-promise", promise["status"], "blocking" if promise["blocking"] else "nonblocking"],
        content={
            "task_id": make_id("revision_task", f"{ledger_path}:{promise['promise_id']}:{now}"),
            "review_path": ledger_path,
            "source_draft_path": draft_path,
            "issue_indexes": [issue_index],
            "review_issue_ids": [promise["promise_id"]],
            "issues": [issue],
            "revision_strategy_plan": {
                "strategy_ids": ["restore_reader_promise_payoff"],
                "required_output_evidence": ["reader_promise_ledger_path", "re_review_path"],
                "re_review_required": True,
                "quality_gate_required": True,
            },
            "status": "open",
            "stage": "reader_promise_repair_required",
            "outputs": {},
            "created_at": now,
            "updated_at": now,
        },
        metadata={
            "project_id": project_id,
            "workspace_path": workspace_path,
            "source_system": "reader_promise.ledger",
            "source_ledger_path": ledger_path,
            "source_draft_path": draft_path,
        },
        references=filter_project_safe_references(storage, project_id, [ledger_path, draft_path, issue_path, promise.get("promise_path", "")]),
    )
    return _write(storage, task)["path"]


def _chapter_plan_content(storage: LocalStorage, chapter_plan_path: str | Path | None) -> tuple[dict[str, Any], str]:
    if not chapter_plan_path:
        return {}, ""
    path = resolve_path(storage.root, chapter_plan_path)
    data = storage.read_json(path)
    content = data.get("content", {}) if isinstance(data, dict) and isinstance(data.get("content"), dict) else {}
    return content, _display_path(storage.root, path)


def _draft_text(content: dict[str, Any]) -> str:
    for key in ["text", "body", "draft_text"]:
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return value
    scenes = content.get("scenes")
    if isinstance(scenes, list):
        return "\n".join(str(scene.get("text") or scene.get("body") or scene) for scene in scenes)
    return ""


def _has_payoff_signal(draft_text: str, content: dict[str, Any]) -> bool:
    signals = _dedupe(
        [
            str(content.get("promise_text") or ""),
            str(content.get("withheld_question") or ""),
            str((content.get("payoff_target") or {}).get("promise_payoff") if isinstance(content.get("payoff_target"), dict) else ""),
            str((content.get("payoff_target") or {}).get("local_payoff") if isinstance(content.get("payoff_target"), dict) else ""),
        ]
    )
    text = draft_text.lower()
    for signal in signals:
        normalized = signal.strip().lower()
        if not normalized:
            continue
        if len(normalized) >= 6 and normalized in text:
            return True
        tokens = [token.lower() for token in TOKEN_RE.findall(normalized) if len(token) >= 2]
        if tokens and sum(1 for token in tokens if token in text) >= max(1, min(2, len(tokens))):
            return True
    return False


def _payoff_due_chapter(payoff_target: dict[str, Any], chapter_no: int) -> int:
    for key in ["payoff_due_chapter", "due_chapter", "target_chapter"]:
        if key in payoff_target:
            return _positive_int(payoff_target.get(key), chapter_no + 3)
    return chapter_no + 3


def _chapter_no(asset: dict[str, Any]) -> int:
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    for key in ["chapter", "chapter_no", "chapter_number"]:
        if key in content:
            return _positive_int(content.get(key), 1)
    metadata = asset.get("metadata", {}) if isinstance(asset.get("metadata", {}), dict) else {}
    return _positive_int(metadata.get("chapter") or metadata.get("chapter_no"), 1)


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, list):
            value = " / ".join(str(item) for item in value if str(item).strip())
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _first_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict) and value:
            return value
    return {}


def _strings(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    return [text] if text else []


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _write(storage: LocalStorage, asset: Any) -> dict[str, Any]:
    data = asset.to_dict()
    _ensure_valid(data)
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "id": asset.id, "asset": data, "validation": {"ok": True, "errors": []}}


def _ensure_valid(data: dict[str, Any]) -> None:
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))


def _display_path(root: Path, path: str | Path) -> str:
    p = Path(path)
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)
