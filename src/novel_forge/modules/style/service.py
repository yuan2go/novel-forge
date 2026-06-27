from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from novel_forge.core.ids import utc_now
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import build_production_context
from novel_forge.schemas import StyleDecompositionReport, StyleReviewReport, validate_common_fields
from novel_forge.storage.local import LocalStorage


def create_style_decomposition_report(
    storage: LocalStorage,
    source_path: str,
    *,
    workspace_path: str | None = None,
) -> Path:
    path = resolve_path(storage.root, source_path)
    source = storage.read_asset(path)
    text = _asset_text(source)
    metrics = _style_metrics(text)
    context = build_production_context(storage, source, input_path=path, workspace_path=workspace_path)
    project = context["project"]
    with AgentExecutionContext(
        storage,
        agent_key="style",
        operation="create-style-decomposition-report",
        input_assets=[path],
        output_types=["style_decomposition_report"],
        workspace_path=str(project.get("workspace_path", "")),
        sla_seconds=300,
    ) as run:
        run.guard("read_asset")
        risk_level = "medium" if _contains_protected_source_hint(source) else "low"
        asset = StyleDecompositionReport(
            title=f"Style decomposition for {source.title}",
            source=source.id,
            tags=["style", "style-decomposition", "abstract-parameters"],
            content={
                "source_asset_id": source.id,
                "extract_level": "abstract_parameters_only",
                "style_features": metrics,
                "usable_parameters": {
                    "sentence_length": metrics["sentence_length"],
                    "paragraph_density": metrics["paragraph_density"],
                    "dialogue_ratio": metrics["dialogue_ratio"],
                    "description_ratio": metrics["description_ratio"],
                    "information_density": metrics["information_density"],
                },
                "do_not_copy": [
                    "proper nouns",
                    "signature phrases",
                    "source-specific metaphors",
                    "unique scene sequence",
                ],
                "risk_level": risk_level,
            },
            metadata={
                "workflow": "style-decomposition",
                "project_id": project.get("project_id", ""),
                "workspace_path": project.get("workspace_path", ""),
                "copyright_boundary": "abstract style parameters only; no source expression reuse",
                "risk_level": risk_level,
                "created_at": utc_now(),
            },
            references=[source.id],
        )
        run.guard("write_style_decomposition_report", "style_decomposition_report")
        output = _write(storage, "styles", asset)
        run.succeed(output_assets=[output])
        return output


def create_style_review_report(
    storage: LocalStorage,
    draft_path: str,
    *,
    style_profile_path: str | None = None,
    workspace_path: str | None = None,
) -> Path:
    path = resolve_path(storage.root, draft_path)
    draft = storage.read_asset(path)
    context = build_production_context(storage, draft, input_path=path, workspace_path=workspace_path)
    profile = _profile_from_path(storage, style_profile_path) if style_profile_path else context["profiles"].get("style_profile")
    profile_content = profile.get("content", {}) if isinstance(profile, dict) else {}
    text = _asset_text(draft)
    metrics = _style_metrics(text)
    score, drift_points = _style_score(metrics, profile_content)
    ai_taste_points = _ai_taste_points(text)
    risk = "medium" if score < 70 or ai_taste_points else "low"
    project = context["project"]
    with AgentExecutionContext(
        storage,
        agent_key="style",
        operation="create-style-review-report",
        input_assets=[path],
        output_types=["style_review_report"],
        workspace_path=str(project.get("workspace_path", "")),
        sla_seconds=300,
    ) as run:
        run.guard("read_asset")
        asset = StyleReviewReport(
            title=f"Style review for {draft.title}",
            source=draft.id,
            tags=["style", "style-review", "quality-gate"],
            content={
                "target_draft_id": draft.id,
                "expected_style_profile_id": str(profile.get("id", "style_profile_missing")) if isinstance(profile, dict) else "style_profile_missing",
                "style_match_score": score,
                "drift_points": drift_points,
                "ai_taste_points": ai_taste_points,
                "rewrite_suggestions": _rewrite_suggestions(drift_points, ai_taste_points),
                "copyright_style_risk": risk,
                "observed_parameters": metrics,
            },
            metadata={
                "workflow": "style-review",
                "project_id": project.get("project_id", ""),
                "workspace_path": project.get("workspace_path", ""),
                "style_profile_path": profile.get("path", "") if isinstance(profile, dict) else "",
                "created_at": utc_now(),
                "risk_level": risk,
            },
            references=_dedupe([draft.id, str(profile.get("id", "")) if isinstance(profile, dict) else ""]),
        )
        run.guard("write_style_review_report", "style_review_report")
        output = _write(storage, "reviews", asset)
        run.succeed(output_assets=[output])
        return output


def style_drift_trend(storage: LocalStorage, project_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("reviews")):
        data = storage.read_json(path)
        if not isinstance(data, dict) or data.get("type") != "style_review_report":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and metadata.get("project_id") != project_id:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        rows.append(
            {
                "path": _display_path(storage.root, path),
                "id": data.get("id", ""),
                "title": data.get("title") or data.get("name", ""),
                "target_draft_id": content.get("target_draft_id", ""),
                "score": content.get("style_match_score", 0),
                "risk": content.get("copyright_style_risk", metadata.get("risk_level", "unknown")),
                "drift_count": len(content.get("drift_points", [])) if isinstance(content.get("drift_points", []), list) else 0,
                "updated_at": data.get("updated_at", ""),
            }
        )
        if len(rows) >= limit:
            break
    scores = [float(row["score"]) for row in rows if isinstance(row.get("score"), (int, float))]
    return {
        "project_id": project_id or "",
        "count": len(rows),
        "average_score": round(sum(scores) / len(scores), 2) if scores else 0,
        "latest_score": scores[0] if scores else 0,
        "rows": rows,
    }


def _profile_from_path(storage: LocalStorage, path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    resolved = resolve_path(storage.root, path)
    data = storage.read_json(resolved)
    if not isinstance(data, dict):
        return {}
    return {
        "path": _display_path(storage.root, resolved),
        "id": data.get("id", ""),
        "content": data.get("content", {}) if isinstance(data.get("content", {}), dict) else {},
        "metadata": data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {},
    }


def _style_score(metrics: dict[str, Any], profile: dict[str, Any]) -> tuple[float, list[str]]:
    score = 100.0
    drift: list[str] = []
    language = profile.get("language_parameters", {}) if isinstance(profile.get("language_parameters", {}), dict) else {}
    narrative = profile.get("narrative_parameters", {}) if isinstance(profile.get("narrative_parameters", {}), dict) else {}
    expected_sentence = language.get("sentence_length")
    if expected_sentence and expected_sentence != "mixed" and metrics.get("sentence_length") != expected_sentence:
        score -= 12
        drift.append(f"sentence_length expected {expected_sentence}, observed {metrics.get('sentence_length')}")
    expected_density = language.get("paragraph_density")
    if expected_density and expected_density != "medium" and metrics.get("paragraph_density") != expected_density:
        score -= 8
        drift.append(f"paragraph_density expected {expected_density}, observed {metrics.get('paragraph_density')}")
    dialogue_ratio = language.get("dialogue_ratio")
    if isinstance(dialogue_ratio, (int, float)) and abs(float(metrics.get("dialogue_ratio", 0)) - float(dialogue_ratio)) > 0.25:
        score -= 10
        drift.append("dialogue ratio drift exceeds 0.25")
    hook_frequency = narrative.get("hook_frequency")
    if hook_frequency and metrics.get("chapter_hook") == "weak":
        score -= 15
        drift.append("chapter hook is weak for expected hook cadence")
    return max(0.0, round(score, 2)), drift


def _style_metrics(text: str) -> dict[str, Any]:
    sentences = _sentences(text)
    paragraphs = [item.strip() for item in re.split(r"\n+", text) if item.strip()]
    avg_sentence = sum(len(sentence) for sentence in sentences) / len(sentences) if sentences else 0
    dialogue_marks = text.count("“") + text.count('"')
    dialogue_ratio = min(1.0, round(dialogue_marks / max(len(sentences), 1), 2))
    concrete_hits = _keyword_count(text, ["雨", "门", "钟", "光", "声", "手", "眼", "街", "血", "风"])
    exposition_hits = _keyword_count(text, ["说明", "规则", "体系", "背景", "历史", "设定", "因为"])
    return {
        "sentence_count": len(sentences),
        "average_sentence_length": round(avg_sentence, 2),
        "sentence_length": "short" if avg_sentence < 35 else "long" if avg_sentence > 85 else "mixed",
        "paragraph_count": len(paragraphs),
        "paragraph_density": "low" if len(paragraphs) <= 2 else "high" if len(paragraphs) >= 8 else "medium",
        "dialogue_ratio": dialogue_ratio,
        "description_ratio": round(min(1.0, concrete_hits / max(len(sentences), 1) / 2), 2),
        "information_density": "high" if exposition_hits >= 3 else "medium" if exposition_hits else "low",
        "chapter_hook": "strong" if sentences and _keyword_count(sentences[-1], ["？", "?", "忽然", "传来", "发现", "打开", "线索"]) else "weak",
    }


def _asset_text(asset: Any) -> str:
    content = asset.content if hasattr(asset, "content") and isinstance(asset.content, dict) else {}
    for key in ["text", "summary", "pattern"]:
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return str(getattr(asset, "title", ""))


def _ai_taste_points(text: str) -> list[str]:
    points = []
    if "仿佛" in text and "似乎" in text and "某种" in text:
        points.append("generic atmospheric filler cluster")
    if text.count("他知道") + text.count("她知道") >= 3:
        points.append("repeated interior exposition starter")
    if len(set(_sentences(text))) < len(_sentences(text)):
        points.append("repeated sentence detected")
    return points


def _rewrite_suggestions(drift_points: list[str], ai_taste_points: list[str]) -> list[str]:
    suggestions = []
    if drift_points:
        suggestions.append("realign sentence density, dialogue ratio, and hook strength with the bound style profile")
    if ai_taste_points:
        suggestions.append("replace generic exposition with concrete action, sensory detail, and character-specific pressure")
    return suggestions or ["style is within the configured profile; preserve current direction"]


def _contains_protected_source_hint(asset: Any) -> bool:
    metadata = asset.metadata if hasattr(asset, "metadata") and isinstance(asset.metadata, dict) else {}
    rights = metadata.get("rights", {}) if isinstance(metadata.get("rights", {}), dict) else {}
    return rights.get("authorization") in {"unknown", "not_authorized"}


def _sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in re.split(r"[。！？.!?\n]+", text) if sentence.strip()]


def _keyword_count(text: str, keywords: list[str]) -> int:
    lower = text.lower()
    return sum(lower.count(keyword.lower()) for keyword in keywords)


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _write(storage: LocalStorage, category: str, asset: Any) -> Path:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    return storage.write_asset(category, asset)
