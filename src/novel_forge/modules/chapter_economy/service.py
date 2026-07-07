from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.modules.review_issue import create_review_issue
from novel_forge.schemas import ChapterEconomyReport, PleasurePoint, RevisionTask, validate_common_fields
from novel_forge.storage.local import LocalStorage


PLEASURE_MARKERS: dict[str, list[str]] = {
    "hook_or_mystery": ["线索", "真相", "发现", "秘密", "疑点", "纸条", "登记", "钟声", "门缝", "谁", "为何", "mystery", "clue", "secret"],
    "costly_choice": ["选择", "代价", "牺牲", "承责", "担责", "失去", "choice", "cost"],
    "reversal": ["反转", "却", "然而", "没想到", "忽然", "转身", "revealed", "turns out"],
    "agency": ["决定", "出手", "查明", "逼", "赌", "拒绝", "decides", "forces"],
    "payoff": ["回收", "兑现", "证明", "保住", "赢", "盖印", "payoff", "reward"],
    "pressure": ["威胁", "追", "封存", "问责", "逼近", "pressure", "threat"],
}
FILLER_MARKERS = ["其实", "总之", "换句话说", "也就是说", "可以说", "显然", "毫无疑问", "不得不说"]


def create_chapter_economy_report(
    storage: LocalStorage,
    draft_path: str | Path,
    *,
    reward_ledger_path: str | Path | None = None,
    chapter_plan_path: str | Path | None = None,
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
    text = _draft_text(draft_content)
    reward_ledger, reward_ref = _reward_ledger(storage, reward_ledger_path)
    plan_content, plan_ref = _chapter_plan_content(storage, chapter_plan_path)
    blueprint = draft_content.get("chapter_plan_blueprint", {}) if isinstance(draft_content.get("chapter_plan_blueprint"), dict) else {}
    expected_beats = _expected_beats(plan_content, blueprint)
    detected_points = _detect_pleasure_points(text, reward_ledger=reward_ledger, expected_beats=expected_beats)
    point_paths = [
        _write_pleasure_point(
            storage,
            point,
            project_id=project_id,
            workspace_path=workspace,
            chapter_no=chapter_no,
            draft=draft.to_dict(),
            draft_path=_display_path(storage.root, draft_file),
        )
        for point in detected_points
    ]
    reward_count = len(reward_ledger.get("rewards", []) if isinstance(reward_ledger.get("rewards", []), list) else [])
    cost_count = len(reward_ledger.get("costs", []) if isinstance(reward_ledger.get("costs", []), list) else [])
    repetition = _repetition_risk(storage, project_id=project_id, workspace_path=workspace, chapter_no=chapter_no, current_rewards=reward_ledger.get("rewards", []))
    water = _water_risk(text, detected_points=detected_points, reward_count=reward_count, cost_count=cost_count)
    score = _scene_value_score(detected_points, expected_beats=expected_beats, reward_count=reward_count, cost_count=cost_count, repetition=repetition, water=water)
    recommendation = "blocked" if score < 40 or water["level"] == "high" else "needs_revision" if score < 70 or repetition["level"] == "high" else "passed"
    issues = _economy_issues(score, water=water, repetition=repetition, expected_beats=expected_beats, detected_points=detected_points)
    now = utc_now()
    report = ChapterEconomyReport(
        title=f"Chapter {chapter_no} economy report",
        source=draft.id,
        tags=["chapter-economy", recommendation, "pleasure-point"],
        content={
            "report_id": make_id("chapter_economy_report", f"{draft.id}:{chapter_no}:{now}"),
            "project_id": project_id,
            "workspace_path": workspace,
            "chapter_no": chapter_no,
            "target_asset_id": draft.id,
            "target_asset_path": _display_path(storage.root, draft_file),
            "reward_ledger_path": reward_ref,
            "chapter_plan_path": plan_ref,
            "expected_beats": expected_beats,
            "pleasure_points": detected_points,
            "pleasure_point_paths": point_paths,
            "reward_count": reward_count,
            "cost_count": cost_count,
            "scene_value_score": score,
            "repetition_risk": repetition,
            "water_risk": water,
            "issues": issues,
            "blocking": recommendation == "blocked",
            "recommendation": recommendation,
            "created_at": now,
        },
        metadata={
            "project_id": project_id,
            "workspace_path": workspace,
            "draft_path": _display_path(storage.root, draft_file),
            "source_system": "chapter_economy.gate",
            "blocking": recommendation == "blocked",
        },
        references=filter_project_safe_references(storage, project_id, [_display_path(storage.root, draft_file), reward_ref, plan_ref, *point_paths]),
    )
    result = _write(storage, report)
    review_issue_paths: list[str] = []
    revision_task_path = ""
    if persist_issues and issues:
        review_issue_paths = _persist_review_issues(
            storage,
            report_path=result["path"],
            draft_path=_display_path(storage.root, draft_file),
            project_id=project_id,
            workspace_path=workspace,
            issues=issues,
        )
        revision_task_path = _write_revision_task(
            storage,
            report_path=result["path"],
            draft_path=_display_path(storage.root, draft_file),
            project_id=project_id,
            workspace_path=workspace,
            score=score,
            issues=issues,
            review_issue_paths=review_issue_paths,
        )
        data = storage.read_json(resolve_path(storage.root, result["path"]))
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        content["review_issue_paths"] = review_issue_paths
        content["revision_task_path"] = revision_task_path
        data["content"] = content
        data["references"] = filter_project_safe_references(storage, project_id, [*data.get("references", []), *review_issue_paths, revision_task_path])
        data["updated_at"] = utc_now()
        _ensure_valid(data)
        storage.write_json(resolve_path(storage.root, result["path"]), data)
        result["asset"] = storage.read_json(resolve_path(storage.root, result["path"]))
    result["status"] = recommendation
    result["review_issues"] = review_issue_paths
    result["revision_task_path"] = revision_task_path
    result["pleasure_point_paths"] = point_paths
    return result


def _write_pleasure_point(
    storage: LocalStorage,
    point: dict[str, Any],
    *,
    project_id: str,
    workspace_path: str,
    chapter_no: int,
    draft: dict[str, Any],
    draft_path: str,
) -> str:
    point_id = make_id("pleasure_point", f"{project_id}:{chapter_no}:{point.get('kind')}:{point.get('signal')}")
    asset = PleasurePoint(
        id=point_id,
        title=f"{point.get('kind')} pleasure point ch{chapter_no}",
        source=str(draft.get("id") or ""),
        tags=["pleasure-point", str(point.get("kind") or "")],
        content={
            "point_id": point_id,
            "project_id": project_id,
            "workspace_path": workspace_path,
            "chapter_no": chapter_no,
            "kind": str(point.get("kind") or "unknown"),
            "signal": str(point.get("signal") or ""),
            "evidence": str(point.get("evidence") or ""),
            "score": float(point.get("score") or 0.0),
            "source_draft_id": str(draft.get("id") or ""),
            "source_draft_path": draft_path,
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id, "workspace_path": workspace_path, "source_system": "chapter_economy.gate"},
        references=filter_project_safe_references(storage, project_id, [draft_path, str(draft.get("id") or "")]),
    )
    return _write(storage, asset)["path"]


def _detect_pleasure_points(text: str, *, reward_ledger: dict[str, Any], expected_beats: list[str]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for kind, markers in PLEASURE_MARKERS.items():
        marker = next((item for item in markers if item and _positive_marker_visible(text, item)), "")
        if marker:
            points.append({"kind": kind, "signal": marker, "evidence": _sentence_with(text, marker), "score": _score_for_kind(kind)})
    for reward in reward_ledger.get("rewards", []) if isinstance(reward_ledger.get("rewards", []), list) else []:
        if isinstance(reward, dict):
            signal = str(reward.get("type") or reward.get("description") or "").strip()
            if signal:
                points.append({"kind": "reward_ledger", "signal": signal, "evidence": str(reward.get("description") or signal), "score": 14.0})
    for cost in reward_ledger.get("costs", []) if isinstance(reward_ledger.get("costs", []), list) else []:
        signal = str(cost or "").strip()
        if signal:
            points.append({"kind": "visible_cost", "signal": signal[:32], "evidence": signal, "score": 10.0})
    for beat in expected_beats:
        if _beat_visible(text, beat):
            points.append({"kind": "blueprint_beat_visible", "signal": beat[:48], "evidence": _sentence_with(text, beat), "score": 8.0})
    return _dedupe_points(points)[:12]


def _expected_beats(plan_content: dict[str, Any], blueprint: dict[str, Any]) -> list[str]:
    beats: list[str] = []
    for source in [plan_content, blueprint]:
        beats.extend(_strings(source.get("pleasure_beats")))
        payoff = source.get("payoff_target") if isinstance(source.get("payoff_target"), dict) else {}
        beats.extend(_strings([payoff.get("local_payoff"), payoff.get("promise_payoff"), payoff.get("withheld_question")]))
        for scene in source.get("scene_beats", []) if isinstance(source.get("scene_beats", []), list) else []:
            if isinstance(scene, dict):
                beats.extend(_strings([scene.get("payoff"), scene.get("turn"), scene.get("exit_hook")]))
        for conflict in source.get("conflict_beats", []) if isinstance(source.get("conflict_beats", []), list) else []:
            if isinstance(conflict, dict):
                beats.extend(_strings([conflict.get("choice"), conflict.get("cost"), conflict.get("reversal")]))
    return _dedupe([item for item in beats if 2 <= len(item) <= 120])[:16]


def _scene_value_score(
    points: list[dict[str, Any]],
    *,
    expected_beats: list[str],
    reward_count: int,
    cost_count: int,
    repetition: dict[str, Any],
    water: dict[str, Any],
) -> float:
    expected_target = max(2, min(5, len(expected_beats) or 3))
    coverage = min(1.0, len(points) / expected_target)
    score = 30.0 + min(36.0, sum(float(point.get("score", 0.0)) for point in points)) + min(12.0, reward_count * 4.0) + min(12.0, cost_count * 4.0) + coverage * 10.0
    score -= float(repetition.get("penalty", 0.0) or 0.0)
    score -= float(water.get("penalty", 0.0) or 0.0)
    return round(max(0.0, min(100.0, score)), 2)


def _water_risk(text: str, *, detected_points: list[dict[str, Any]], reward_count: int, cost_count: int) -> dict[str, Any]:
    sentences = [item.strip() for item in re.split(r"[。！？!?；;\n]+", text) if item.strip()]
    filler_hits = sum(1 for item in sentences if any(marker in item for marker in FILLER_MARKERS))
    no_value = not detected_points and reward_count == 0 and cost_count == 0
    long_low_value = no_value and len(text) > 500
    exposition_ratio = filler_hits / max(1, len(sentences))
    if long_low_value or exposition_ratio >= 0.35:
        level = "high"
        penalty = 30.0
    elif reward_count == 0 and cost_count == 0 and len(detected_points) < 2:
        level = "medium"
        penalty = 14.0
    else:
        level = "low"
        penalty = 0.0
    return {
        "level": level,
        "penalty": penalty,
        "filler_sentence_count": filler_hits,
        "sentence_count": len(sentences),
        "reason": "no visible reward/cost/progression signal" if no_value else "filler ratio elevated" if exposition_ratio >= 0.35 else "value signals present",
    }


def _repetition_risk(
    storage: LocalStorage,
    *,
    project_id: str,
    workspace_path: str,
    chapter_no: int,
    current_rewards: Any,
) -> dict[str, Any]:
    current_types = _reward_types(current_rewards)
    if not current_types:
        return {"level": "low", "penalty": 0.0, "repeated_types": [], "window": 3}
    previous: list[str] = []
    for path in reversed(storage.list_json("continuity")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "reward_ledger":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if str(metadata.get("project_id") or "") not in {project_id, ""}:
            continue
        if workspace_path and str(metadata.get("workspace_path") or "") not in {"", workspace_path}:
            continue
        if _positive_int(content.get("chapter_no"), 0) >= chapter_no:
            continue
        previous.extend(_reward_types(content.get("rewards", [])))
        if len(previous) >= 9:
            break
    repeated = sorted({item for item in current_types if item in previous})
    if len(repeated) >= 2:
        return {"level": "high", "penalty": 16.0, "repeated_types": repeated, "window": 3}
    if repeated:
        return {"level": "medium", "penalty": 8.0, "repeated_types": repeated, "window": 3}
    return {"level": "low", "penalty": 0.0, "repeated_types": [], "window": 3}


def _economy_issues(
    score: float,
    *,
    water: dict[str, Any],
    repetition: dict[str, Any],
    expected_beats: list[str],
    detected_points: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if score < 40:
        issues.append({"dimension": "scene_value_score", "severity": "high", "blocking": True, "message": f"chapter economy score {score} is below blocking threshold", "recommendation": "add visible reward, cost, reversal, or agency beat"})
    elif score < 70:
        issues.append({"dimension": "scene_value_score", "severity": "medium", "blocking": False, "message": f"chapter economy score {score} needs revision", "recommendation": "increase chapter value density before release"})
    if water.get("level") in {"medium", "high"}:
        issues.append({"dimension": "water_risk", "severity": "high" if water.get("level") == "high" else "medium", "blocking": water.get("level") == "high", "message": str(water.get("reason") or "water risk elevated"), "recommendation": "remove filler and make each scene change state"})
    if repetition.get("level") == "high":
        issues.append({"dimension": "repetition_risk", "severity": "medium", "blocking": False, "message": f"repeated reward types: {', '.join(repetition.get('repeated_types', []))}", "recommendation": "vary payoff type or escalate the repeated payoff with new cost"})
    if expected_beats and not detected_points:
        issues.append({"dimension": "blueprint_pleasure_coverage", "severity": "high", "blocking": True, "message": "chapter blueprint pleasure beats are not visible in draft", "recommendation": "make at least one planned pleasure beat observable in prose"})
    return issues


def _persist_review_issues(
    storage: LocalStorage,
    *,
    report_path: str,
    draft_path: str,
    project_id: str,
    workspace_path: str,
    issues: list[dict[str, Any]],
) -> list[str]:
    paths: list[str] = []
    for index, issue in enumerate(issues):
        result = create_review_issue(
            storage,
            {
                "issue_type": "chapter_economy_gap",
                "severity": issue["severity"],
                "blocking": bool(issue.get("blocking")),
                "status": "open",
                "target_asset_path": draft_path,
                "target_asset_type": "draft_chapter",
                "project_id": project_id,
                "workspace_path": workspace_path,
                "source_system": "chapter_economy.gate",
                "source_issue_id": f"{report_path}:{index}:{issue.get('dimension')}",
                "review_report_path": report_path,
                "message": str(issue.get("message") or "chapter economy issue"),
                "fix_suggestion": str(issue.get("recommendation") or "increase scene value"),
                "location": {"dimension": issue.get("dimension", ""), "scope": "chapter"},
                "evidence_refs": [report_path, draft_path],
                "confidence": 0.74,
            },
        )
        if result.get("path"):
            paths.append(str(result["path"]))
    return _dedupe(paths)


def _write_revision_task(
    storage: LocalStorage,
    *,
    report_path: str,
    draft_path: str,
    project_id: str,
    workspace_path: str,
    score: float,
    issues: list[dict[str, Any]],
    review_issue_paths: list[str],
) -> str:
    now = utc_now()
    task = RevisionTask(
        title="Repair chapter economy",
        source=report_path,
        tags=["revision", "chapter-economy", "pleasure-point"],
        content={
            "task_id": make_id("revision_task", f"chapter-economy:{report_path}:{now}"),
            "review_path": report_path,
            "source_draft_path": draft_path,
            "issue_indexes": list(range(len(issues))),
            "review_issue_ids": [str(item.get("dimension") or index) for index, item in enumerate(issues)],
            "issues": [
                {
                    "issue_index": index,
                    "issue_type": "chapter_economy_gap",
                    "severity": str(issue.get("severity") or "medium"),
                    "blocking": bool(issue.get("blocking")),
                    "message": str(issue.get("message") or ""),
                    "recommendation": str(issue.get("recommendation") or ""),
                    "status": "open",
                }
                for index, issue in enumerate(issues)
            ],
            "revision_strategy_plan": {
                "strategy_ids": ["raise_chapter_economy"],
                "required_output_evidence": ["chapter_economy_report_path", "re_review_path"],
                "re_review_required": True,
                "quality_gate_required": True,
            },
            "status": "open",
            "stage": "chapter_economy_repair_required",
            "outputs": {"scene_value_score": score, "review_issue_paths": review_issue_paths},
            "created_at": now,
            "updated_at": now,
        },
        metadata={"project_id": project_id, "workspace_path": workspace_path, "source_system": "chapter_economy.gate"},
        references=filter_project_safe_references(storage, project_id, [report_path, draft_path, *review_issue_paths]),
    )
    return _write(storage, task)["path"]


def _reward_ledger(storage: LocalStorage, reward_ledger_path: str | Path | None) -> tuple[dict[str, Any], str]:
    if not reward_ledger_path:
        return {}, ""
    path = resolve_path(storage.root, reward_ledger_path)
    data = storage.read_json(path)
    content = data.get("content", {}) if isinstance(data, dict) and isinstance(data.get("content"), dict) else {}
    return content, _display_path(storage.root, path)


def _chapter_plan_content(storage: LocalStorage, chapter_plan_path: str | Path | None) -> tuple[dict[str, Any], str]:
    if not chapter_plan_path:
        return {}, ""
    path = resolve_path(storage.root, chapter_plan_path)
    data = storage.read_json(path)
    content = data.get("content", {}) if isinstance(data, dict) and isinstance(data.get("content"), dict) else {}
    return content, _display_path(storage.root, path)


def _draft_text(content: dict[str, Any]) -> str:
    return str(content.get("text") or content.get("body") or content.get("summary") or "")


def _chapter_no(asset: dict[str, Any]) -> int:
    content = asset.get("content", {}) if isinstance(asset.get("content"), dict) else {}
    metadata = asset.get("metadata", {}) if isinstance(asset.get("metadata"), dict) else {}
    return _positive_int(content.get("chapter") or content.get("chapter_no") or metadata.get("chapter") or metadata.get("chapter_no"), 1)


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _score_for_kind(kind: str) -> float:
    return {
        "hook_or_mystery": 12.0,
        "costly_choice": 14.0,
        "reversal": 12.0,
        "agency": 14.0,
        "payoff": 14.0,
        "pressure": 10.0,
    }.get(kind, 8.0)


def _reward_types(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for item in values:
        if isinstance(item, dict):
            text = str(item.get("type") or item.get("description") or "").strip()
        else:
            text = str(item or "").strip()
        if text:
            result.append(text[:48])
    return _dedupe(result)


def _sentence_with(text: str, signal: str) -> str:
    tokens = _strings(signal)
    for sentence in re.split(r"[。！？!?；;\n]+", text):
        if any(token and token.lower() in sentence.lower() for token in tokens):
            return sentence.strip()[:160]
    return signal[:160]


def _beat_visible(text: str, beat: str) -> bool:
    tokens = [item.lower() for item in re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", beat) if len(item) >= 2]
    lowered = text.lower()
    if beat and len(beat) >= 6 and beat.lower() in lowered:
        return True
    return bool(tokens) and sum(1 for token in tokens if token in lowered) >= min(2, len(tokens))


def _positive_marker_visible(text: str, marker: str) -> bool:
    lowered = text.lower()
    needle = marker.lower()
    if needle not in lowered:
        return False
    for sentence in re.split(r"[。！？!?；;\n]+", text):
        if needle not in sentence.lower():
            continue
        if f"没有{marker}" in sentence or f"无{marker}" in sentence or f"not {needle}" in sentence.lower() or f"no {needle}" in sentence.lower():
            continue
        return True
    return False


def _strings(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        rows = value
    else:
        rows = [value]
    return [str(item).strip() for item in rows if str(item).strip()]


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


def _dedupe_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for point in points:
        key = (str(point.get("kind") or ""), str(point.get("signal") or ""))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        result.append(point)
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
