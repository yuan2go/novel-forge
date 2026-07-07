from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.modules.review_issue import create_review_issue
from novel_forge.schemas import MobileReadingReport, RevisionTask, validate_common_fields
from novel_forge.storage.local import LocalStorage


LONG_PARAGRAPH_CHARS = 220
HARD_PARAGRAPH_CHARS = 520
MIN_PARAGRAPHS_PER_1000_CHARS = 5.0


def create_mobile_reading_report(
    storage: LocalStorage,
    draft_path: str | Path,
    *,
    platform_id: str = "local",
    workspace_path: str | None = None,
    persist_issues: bool = True,
) -> dict[str, Any]:
    draft_file = resolve_path(storage.root, draft_path)
    draft = storage.read_asset(draft_file)
    draft_content = draft.content if isinstance(draft.content, dict) else {}
    draft_metadata = draft.metadata if isinstance(draft.metadata, dict) else {}
    project = project_scope_from_asset(storage, draft, input_path=draft_file, workspace_path=workspace_path)
    project_id = str(project.get("project_id") or draft_metadata.get("project_id") or draft_content.get("project_id") or "local-system")
    workspace = str(project.get("workspace_path") or workspace_path or draft_metadata.get("workspace_path") or draft_content.get("workspace_path") or "")
    chapter_no = _chapter_no(draft.to_dict())
    text = str(draft_content.get("text") or "")
    paragraphs = _paragraphs(text)
    metrics = _metrics(text, paragraphs)
    findings = _findings(metrics)
    status = _recommendation(findings)
    now = utc_now()
    report = MobileReadingReport(
        title=f"Chapter {chapter_no} mobile reading report",
        source=draft.id,
        tags=["mobile-reading", platform_id, status],
        content={
            "report_id": make_id("mobile_reading_report", f"{draft.id}:{chapter_no}:{now}"),
            "project_id": project_id,
            "workspace_path": workspace,
            "chapter_no": chapter_no,
            "platform_id": platform_id,
            "target_asset_id": draft.id,
            "target_asset_path": _display_path(storage.root, draft_file),
            "mobile_score": metrics["mobile_score"],
            "paragraph_count": metrics["paragraph_count"],
            "long_paragraph_count": metrics["long_paragraph_count"],
            "max_paragraph_chars": metrics["max_paragraph_chars"],
            "average_paragraph_chars": metrics["average_paragraph_chars"],
            "paragraphs_per_1000_chars": metrics["paragraphs_per_1000_chars"],
            "dense_paragraph_count": metrics["dense_paragraph_count"],
            "dialogue_line_ratio": metrics["dialogue_line_ratio"],
            "recommended_max_paragraph_chars": LONG_PARAGRAPH_CHARS,
            "evidence": _evidence(paragraphs),
            "findings": findings,
            "blocking": any(item.get("blocking") for item in findings),
            "recommendation": status,
            "created_at": now,
        },
        metadata={
            "project_id": project_id,
            "workspace_path": workspace,
            "draft_path": _display_path(storage.root, draft_file),
            "source_system": "mobile_reading.gate",
            "blocking": any(item.get("blocking") for item in findings),
        },
        references=filter_project_safe_references(storage, project_id, [_display_path(storage.root, draft_file)]),
    )
    written = _write(storage, report)
    review_issue_paths: list[str] = []
    revision_task_path = ""
    if persist_issues and findings:
        review_issue_paths = _persist_review_issues(
            storage,
            draft_path=_display_path(storage.root, draft_file),
            project_id=project_id,
            workspace_path=workspace,
            report_path=written["path"],
            findings=findings,
        )
        revision_task_path = _write_revision_task(
            storage,
            draft_path=_display_path(storage.root, draft_file),
            project_id=project_id,
            workspace_path=workspace,
            report_path=written["path"],
            findings=findings,
            review_issue_paths=review_issue_paths,
        )
    return {
        "status": status,
        "path": written["path"],
        "mobile_reading_report_path": written["path"],
        "paths": [written["path"]],
        "asset": written["asset"],
        "review_issues": review_issue_paths,
        "revision_task_path": revision_task_path,
    }


def _metrics(text: str, paragraphs: list[str]) -> dict[str, Any]:
    total_chars = len(_compact_text(text))
    lengths = [len(_compact_text(paragraph)) for paragraph in paragraphs]
    paragraph_count = len(lengths)
    max_chars = max(lengths) if lengths else 0
    average_chars = round(sum(lengths) / paragraph_count, 2) if paragraph_count else 0.0
    long_count = sum(1 for length in lengths if length > LONG_PARAGRAPH_CHARS)
    dense_count = sum(1 for paragraph in paragraphs if len(_sentences(paragraph)) >= 5 or len(_compact_text(paragraph)) > HARD_PARAGRAPH_CHARS)
    paragraphs_per_1000 = round(paragraph_count / max(total_chars / 1000.0, 1.0), 2) if total_chars else 0.0
    dialogue_count = sum(1 for paragraph in paragraphs if _has_dialogue_marker(paragraph))
    dialogue_ratio = round(dialogue_count / paragraph_count, 3) if paragraph_count else 0.0
    score = 100.0
    score -= long_count * 10.0
    score -= dense_count * 8.0
    if max_chars > LONG_PARAGRAPH_CHARS:
        score -= min(26.0, (max_chars - LONG_PARAGRAPH_CHARS) / 18.0)
    if total_chars >= 800 and paragraph_count <= 2:
        score -= 30.0
    if paragraphs_per_1000 < MIN_PARAGRAPHS_PER_1000_CHARS and total_chars >= 800:
        score -= 14.0
    if average_chars > 170:
        score -= 8.0
    if total_chars >= 1000 and dialogue_ratio < 0.06:
        score -= 6.0
    return {
        "total_chars": total_chars,
        "paragraph_count": paragraph_count,
        "long_paragraph_count": long_count,
        "dense_paragraph_count": dense_count,
        "max_paragraph_chars": max_chars,
        "average_paragraph_chars": average_chars,
        "paragraphs_per_1000_chars": paragraphs_per_1000,
        "dialogue_line_ratio": dialogue_ratio,
        "mobile_score": round(max(0.0, min(100.0, score)), 2),
    }


def _findings(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if metrics["total_chars"] >= 800 and metrics["paragraph_count"] <= 2:
        findings.append(_issue("paragraph_density", "high", True, "chapter has too few mobile paragraphs for its length", "split the draft into action-turn paragraphs with visible state changes"))
    if metrics["max_paragraph_chars"] > HARD_PARAGRAPH_CHARS:
        findings.append(_issue("max_paragraph_chars", "high", True, f"longest paragraph has {metrics['max_paragraph_chars']} characters", "split oversized paragraphs before and after choices, reveals, dialogue, and hooks"))
    elif metrics["long_paragraph_count"] >= 3:
        findings.append(_issue("long_paragraph_count", "medium", False, f"{metrics['long_paragraph_count']} paragraphs exceed mobile length guidance", "reflow long paragraphs into shorter mobile beats"))
    if metrics["dense_paragraph_count"] >= 2:
        findings.append(_issue("dense_paragraph_count", "medium", False, "multiple paragraphs carry too many sentence beats", "split dense paragraphs where information, emotion, or risk changes"))
    if metrics["paragraphs_per_1000_chars"] < MIN_PARAGRAPHS_PER_1000_CHARS and metrics["total_chars"] >= 800:
        findings.append(_issue("paragraphs_per_1000_chars", "medium", False, "paragraph density is low for mobile reading", "increase paragraph breaks without adding filler"))
    if metrics["mobile_score"] < 45:
        findings.append(_issue("mobile_score", "high", True, f"mobile reading score {metrics['mobile_score']} is below blocking threshold", "perform a mobile paragraph reflow and rerun the gate"))
    elif metrics["mobile_score"] < 68:
        findings.append(_issue("mobile_score", "medium", False, f"mobile reading score {metrics['mobile_score']} is weak", "tighten paragraph rhythm before publish"))
    return findings


def _issue(dimension: str, severity: str, blocking: bool, message: str, recommendation: str) -> dict[str, Any]:
    return {
        "issue_type": "mobile_reading_friction",
        "dimension": dimension,
        "severity": severity,
        "blocking": blocking,
        "message": message,
        "recommendation": recommendation,
    }


def _persist_review_issues(
    storage: LocalStorage,
    *,
    draft_path: str,
    project_id: str,
    workspace_path: str,
    report_path: str,
    findings: list[dict[str, Any]],
) -> list[str]:
    paths: list[str] = []
    for index, finding in enumerate(findings):
        result = create_review_issue(
            storage,
            {
                "issue_type": "mobile_reading_friction",
                "severity": finding["severity"],
                "blocking": bool(finding.get("blocking")),
                "status": "open",
                "target_asset_path": draft_path,
                "target_asset_type": "draft_chapter",
                "project_id": project_id,
                "workspace_path": workspace_path,
                "source_system": "mobile_reading.gate",
                "source_issue_id": f"{finding.get('dimension')}:{index}",
                "review_report_path": report_path,
                "message": str(finding.get("message") or ""),
                "fix_suggestion": str(finding.get("recommendation") or ""),
                "location": {"dimension": finding.get("dimension", ""), "scope": "paragraph_layout"},
                "evidence_refs": [draft_path, report_path],
                "confidence": 0.74,
            },
        )
        if result.get("path"):
            paths.append(str(result["path"]))
    return _dedupe(paths)


def _write_revision_task(
    storage: LocalStorage,
    *,
    draft_path: str,
    project_id: str,
    workspace_path: str,
    report_path: str,
    findings: list[dict[str, Any]],
    review_issue_paths: list[str],
) -> str:
    now = utc_now()
    task = RevisionTask(
        title="Reflow chapter for mobile reading",
        source=report_path,
        tags=["revision", "mobile-reading", "paragraph-reflow"],
        content={
            "task_id": make_id("revision_task", f"mobile-reading:{draft_path}:{now}"),
            "review_path": report_path,
            "source_draft_path": draft_path,
            "issue_indexes": list(range(len(findings))),
            "review_issue_ids": [str(item.get("dimension") or index) for index, item in enumerate(findings)],
            "issues": [
                {
                    "issue_index": index,
                    "issue_type": "mobile_reading_friction",
                    "severity": str(finding.get("severity") or "medium"),
                    "blocking": bool(finding.get("blocking")),
                    "message": str(finding.get("message") or ""),
                    "recommendation": str(finding.get("recommendation") or ""),
                    "status": "open",
                }
                for index, finding in enumerate(findings)
            ],
            "revision_strategy_plan": {
                "strategy_ids": ["mobile_paragraph_reflow"],
                "required_output_evidence": ["mobile_reading_report_path", "re_review_path"],
                "re_review_required": True,
                "quality_gate_required": True,
            },
            "status": "open",
            "stage": "mobile_reading_reflow_required",
            "outputs": {"review_issue_paths": review_issue_paths},
            "created_at": now,
            "updated_at": now,
        },
        metadata={"project_id": project_id, "workspace_path": workspace_path, "source_system": "mobile_reading.gate"},
        references=filter_project_safe_references(storage, project_id, [draft_path, report_path, *review_issue_paths]),
    )
    return _write(storage, task)["path"]


def _paragraphs(text: str) -> list[str]:
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n|\r\n\s*\r\n", text) if item.strip()]
    if len(paragraphs) == 1:
        line_paragraphs = [item.strip() for item in text.splitlines() if item.strip()]
        if len(line_paragraphs) > 1:
            paragraphs = line_paragraphs
    return paragraphs or ([text.strip()] if text.strip() else [])


def _sentences(paragraph: str) -> list[str]:
    return [item.strip() for item in re.split(r"[。！？!?；;]+", paragraph) if item.strip()]


def _has_dialogue_marker(paragraph: str) -> bool:
    return any(marker in paragraph for marker in ["“", "”", "\"", "：", ":", "问", "说", "答"])


def _evidence(paragraphs: list[str]) -> list[dict[str, Any]]:
    rows = []
    for index, paragraph in enumerate(paragraphs):
        length = len(_compact_text(paragraph))
        if length <= LONG_PARAGRAPH_CHARS:
            continue
        rows.append({"paragraph_index": index, "chars": length, "excerpt": paragraph[:160]})
    return rows[:6]


def _recommendation(findings: list[dict[str, Any]]) -> str:
    if any(item.get("blocking") for item in findings):
        return "blocked"
    return "needs_revision" if findings else "passed"


def _chapter_no(asset: dict[str, Any]) -> int:
    content = asset.get("content", {}) if isinstance(asset.get("content"), dict) else {}
    metadata = asset.get("metadata", {}) if isinstance(asset.get("metadata"), dict) else {}
    try:
        return max(1, int(content.get("chapter") or content.get("chapter_no") or metadata.get("chapter") or metadata.get("chapter_no") or 1))
    except (TypeError, ValueError):
        return 1


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


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
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "id": asset.id, "asset": data, "validation": {"ok": True, "errors": []}}


def _display_path(root: Path, path: str | Path) -> str:
    p = Path(path)
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)
