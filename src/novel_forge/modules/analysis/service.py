from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from novel_forge.core.ids import utc_now
from novel_forge.model_adapters import (
    GuardedModelAdapter,
    ModelOutputValidationError,
    model_from_env,
    validate_model_output,
)
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import resolve_path, run_metadata
from novel_forge.modules.creative_assets import create_creative_asset
from novel_forge.modules.handoff.service import create_analysis_handoff as _create_analysis_handoff
from novel_forge.modules.production_context import project_scope_from_asset
from novel_forge.schemas import (
    AnalysisConversionReport,
    BaseAsset,
    ClassicLiteraryAnalysisReport,
    CommonNovelAnalysisReport,
    PublishedFictionAnalysisReport,
    WebFictionBusinessAnalysisReport,
    validate_common_fields,
)
from novel_forge.storage.local import LocalStorage

ANALYSIS_REPORT_TYPES = {
    "common": "common_novel_analysis_report",
    "common_novel": "common_novel_analysis_report",
    "web": "web_fiction_business_analysis_report",
    "web_fiction": "web_fiction_business_analysis_report",
    "web_fiction_business": "web_fiction_business_analysis_report",
    "published": "published_fiction_analysis_report",
    "published_fiction": "published_fiction_analysis_report",
    "classic": "classic_literary_analysis_report",
    "classic_literary": "classic_literary_analysis_report",
}

_REPORT_CLASS_BY_TYPE = {
    "common_novel_analysis_report": CommonNovelAnalysisReport,
    "web_fiction_business_analysis_report": WebFictionBusinessAnalysisReport,
    "published_fiction_analysis_report": PublishedFictionAnalysisReport,
    "classic_literary_analysis_report": ClassicLiteraryAnalysisReport,
}

_REPORT_LABEL_BY_TYPE = {
    "common_novel_analysis_report": "common novel analysis",
    "web_fiction_business_analysis_report": "web fiction business analysis",
    "published_fiction_analysis_report": "published fiction craft analysis",
    "classic_literary_analysis_report": "classic literary depth analysis",
}

_DEFAULT_CONVERSION_TARGETS = {
    "common_novel_analysis_report": ["material_card", "knowledge_card", "craft_template"],
    "web_fiction_business_analysis_report": ["writing_template", "material_card", "review_rule_pack"],
    "published_fiction_analysis_report": ["craft_template", "writing_template", "review_rule_pack"],
    "classic_literary_analysis_report": ["knowledge_card", "craft_template", "review_rule_pack"],
}


def run_analysis(
    storage: LocalStorage,
    source_path: str,
    analysis_type: str,
    *,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    source_path_obj = resolve_path(storage.root, source_path)
    source_asset = storage.read_asset(source_path_obj)
    report_type = _normalize_analysis_type(analysis_type)
    project = project_scope_from_asset(storage, source_asset, input_path=source_path_obj, workspace_path=workspace_path)
    metrics = _source_metrics(source_asset)
    model = model_from_env("analyze")
    with AgentExecutionContext(
        storage,
        agent_key="analysis",
        operation=f"run-{report_type}",
        input_assets=[source_path_obj],
        output_types=[report_type],
        workspace_path=str(project.get("workspace_path", "")),
        model_provider=getattr(model, "name", "local"),
        model_name=getattr(model, "name", "local"),
        prompt_version=f"{report_type}-rubric-v2",
        token_budget=4000,
        sla_seconds=900,
    ) as run:
        run.guard("read_asset")
        run.guard("call_model_adapter")
        semantic_depth = _semantic_depth_assessment(storage, run.path, report_type, source_asset, metrics, model)
        content = _report_content(report_type, source_asset, metrics)
        content.update(semantic_depth)
        metadata = _analysis_metadata(storage, report_type, source_asset, project, source_path_obj)
        metadata["agent_run_path"] = run.path
        metadata["semantic_depth_version"] = "analysis-rubric-v2"
        metadata["semantic_provider"] = semantic_depth.get("provider_review", {}).get("provider", "")
        metadata["semantic_model"] = semantic_depth.get("provider_review", {}).get("model", "")
        references = _analysis_references(storage, source_path_obj, source_asset, project)
        cls = _REPORT_CLASS_BY_TYPE[report_type]
        asset = cls(
            title=f"{source_asset.title or source_asset.name or source_asset.id} - {_REPORT_LABEL_BY_TYPE[report_type]}",
            source=source_asset.id,
            tags=["analysis", report_type.replace("_", "-"), "abstract-only", "semantic-rubric"],
            content=content,
            metadata=metadata,
            references=references,
        )
        _validate_asset(asset)
        run.guard("write_analysis_report", report_type)
        path = storage.write_asset_auto(asset)
        result = {
            "path": _relative_path(storage, path),
            "asset": asset.to_dict(),
            "metrics": metrics,
            "report_type": report_type,
        }
        run.succeed(output_assets=[result["path"]], token_used=len(_asset_text(source_asset)))
        return result


def convert_analysis_report(
    storage: LocalStorage,
    report_path: str,
    *,
    targets: list[str] | None = None,
    workspace_path: str | None = None,
    reuse_scope: str = "project",
    human_approved: bool = False,
    approval_note: str = "",
) -> dict[str, Any]:
    report_file = resolve_path(storage.root, report_path)
    report_asset = storage.read_asset(report_file)
    report_type = str(report_asset.type)
    if report_type not in _REPORT_CLASS_BY_TYPE:
        raise ValueError(f"unsupported analysis report type: {report_type}")
    project = project_scope_from_asset(storage, report_asset, input_path=report_file, workspace_path=workspace_path)
    normalized_targets = _normalize_targets(report_type, targets or [])
    created_assets: list[dict[str, Any]] = []
    rejected_items: list[dict[str, str]] = []
    copyright_risk = _risk_from_report(report_asset)
    for target in normalized_targets:
        if copyright_risk == "high" and target in {"material_card", "writing_template"}:
            rejected_items.append(
                {
                    "target": target,
                    "reason": "high copyright risk reports cannot become production material or writing templates without manual clearance",
                }
            )
            continue
        created = _create_converted_asset(
            storage,
            report_asset,
            report_file,
            project,
            target,
            reuse_scope=reuse_scope,
            human_approved=human_approved,
            approval_note=approval_note,
        )
        created_assets.append(
            {
                "type": target,
                "id": str(created["asset"]["id"]),
                "title": str(created["asset"]["title"]),
                "path": str(created["path"]),
                "library": str(created["library"]),
            }
        )
    content = {
        "source_report_id": report_asset.id,
        "source_report_type": report_type,
        "conversion_targets": normalized_targets,
        "created_assets": created_assets,
        "rejected_items": rejected_items,
        "reuse_scope": reuse_scope,
        "copyright_risk": copyright_risk,
        "abstraction_level": "template" if created_assets else "abstract",
        "conversion_policy": "analysis reports are not inserted into generation RAG; only abstract converted assets may be selected later",
        "human_gate": {
            "required": True,
            "status": "approved" if human_approved else "waiting_human",
            "approval_note": approval_note,
            "policy": "converted analysis assets cannot enter production RAG or review rule gates until a human approves the abstraction boundary",
        },
    }
    metadata = {
        "project_id": str(project.get("project_id", "")),
        "workspace_path": str(project.get("workspace_path", "")),
        "asset_status": "active" if created_assets and human_approved else "needs_human_gate",
        "created_by": "analysis_conversion_service",
        "created_at": utc_now(),
        "source_report_path": _relative_path(storage, report_file),
        "copyright_boundary": "abstract structure conversion only; no protected text or source-specific plot copied",
        "copyright_risk": copyright_risk,
        "risk_level": copyright_risk,
        "abstraction_level": content["abstraction_level"],
        "use_in_generation_rag": False,
        "human_gate_required": True,
        "human_gate_status": "approved" if human_approved else "waiting_human",
        "approval_note": approval_note,
    }
    asset = AnalysisConversionReport(
        title=f"Analysis conversion - {report_asset.title or report_asset.name}",
        source=report_asset.id,
        tags=["analysis-conversion", report_type.replace("_", "-"), "abstract-assets"],
        content=content,
        metadata=metadata,
        references=[report_asset.id, _relative_path(storage, report_file)],
    )
    _validate_asset(asset)
    path = storage.write_asset_auto(asset)
    return {
        "path": _relative_path(storage, path),
        "asset": asset.to_dict(),
        "created_assets": created_assets,
        "rejected_items": rejected_items,
    }


def create_analysis_handoff(
    storage: LocalStorage,
    input_path: str,
    analysis_type: str,
    *,
    workspace_path: str | None = None,
    purpose: str = "",
) -> dict[str, Any]:
    path = _create_analysis_handoff(
        storage,
        input_path=input_path,
        analysis_type=analysis_type,
        workspace_path=workspace_path,
        purpose=purpose,
    )
    asset = storage.read_asset(path)
    return {"path": _relative_path(storage, path), "asset": asset.to_dict()}


def list_analysis_reports(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    report_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("limit must be greater than zero")
    normalized_type = _normalize_analysis_type(report_type) if report_type else ""
    rows: list[dict[str, Any]] = []
    for path in storage.list_json("analysis"):
        data = storage.read_json(path)
        if not isinstance(data, dict):
            continue
        if normalized_type and data.get("type") != normalized_type:
            continue
        if str(data.get("type", "")) not in {*_REPORT_CLASS_BY_TYPE, "analysis_conversion_report"}:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id") or "") not in {project_id, ""}:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        rows.append(
            {
                "path": _relative_path(storage, path),
                "id": data.get("id", ""),
                "type": data.get("type", ""),
                "title": data.get("title") or data.get("name", ""),
                "source": data.get("source", ""),
                "project_id": metadata.get("project_id", ""),
                "workspace_path": metadata.get("workspace_path", ""),
                "copyright_risk": metadata.get("copyright_risk", content.get("copyright_risk", "unknown")),
                "abstraction_level": metadata.get("abstraction_level", content.get("abstraction_level", "")),
                "use_in_generation_rag": metadata.get("use_in_generation_rag", False),
                "status": metadata.get("asset_status", ""),
                "asset_status": metadata.get("asset_status", ""),
                "human_gate_status": metadata.get(
                    "human_gate_status",
                    content.get("human_gate", {}).get("status", "") if isinstance(content.get("human_gate", {}), dict) else "",
                ),
                "created_assets": len(content.get("created_assets", []) if isinstance(content.get("created_assets"), list) else []),
                "semantic_depth": content.get("semantic_depth", {}),
                "provider_review": content.get("provider_review", {}),
                "visualization": content.get("visualization", {}),
                "mode_specific_panels": content.get("mode_specific_panels", []),
                "updated_at": data.get("updated_at", ""),
                "summary": _report_preview(content),
            }
        )
    rows.sort(key=lambda item: (str(item.get("updated_at", "")), str(item.get("path", ""))), reverse=True)
    return rows[:limit]


def _normalize_analysis_type(analysis_type: str | None) -> str:
    key = (analysis_type or "common").strip().lower().replace("-", "_")
    if key in _REPORT_CLASS_BY_TYPE:
        return key
    try:
        return ANALYSIS_REPORT_TYPES[key]
    except KeyError as exc:
        allowed = ", ".join(sorted(ANALYSIS_REPORT_TYPES))
        raise ValueError(f"unsupported analysis_type: {analysis_type}; allowed: {allowed}") from exc


def _source_metrics(asset: BaseAsset) -> dict[str, Any]:
    text = _asset_text(asset)
    normalized = " ".join(text.split())
    sentences = _split_units(normalized)
    chapters = re.findall(r"(第[一二三四五六七八九十百千万0-9]+章|Chapter\s+\d+)", text, flags=re.IGNORECASE)
    hook_hits = _count_tokens(normalized, ["忽然", "秘密", "发现", "危机", "代价", "选择", "死亡", "背叛", "真相", "?", "？", "must", "secret"])
    dialogue_marks = normalized.count("“") + normalized.count('"')
    words = re.findall(r"[\w\u4e00-\u9fff]+", normalized)
    keyword_counter = Counter(word for word in words if len(word) >= 2)
    keywords = [word for word, _ in keyword_counter.most_common(12)]
    length = len(normalized)
    return {
        "text_length": length,
        "sentence_count": len(sentences),
        "chapter_markers": len(chapters),
        "hook_signal_count": hook_hits,
        "dialogue_marker_count": dialogue_marks,
        "avg_sentence_length": round(length / max(len(sentences), 1), 2),
        "top_keywords": keywords,
        "source_content_fields": sorted(asset.content.keys()),
    }


def _report_content(report_type: str, asset: BaseAsset, metrics: dict[str, Any]) -> dict[str, Any]:
    base = {
        "source_asset_id": asset.id,
        "source_asset_type": asset.type,
        "source_title": asset.title or asset.name,
        "copyright_risk": _source_risk(asset),
        "abstraction_level": "abstract",
        "analysis_metrics": metrics,
    }
    if report_type == "common_novel_analysis_report":
        return {
            **base,
            "analysis_scope": "general narrative structure, character pressure, conflict engine, and transferable craft signals",
            "structure_map": {
                "opening": "identify reader promise and disturbance",
                "middle": "track pressure escalation and decision cost",
                "ending": "separate payoff pattern from protected plot sequence",
            },
            "character_map": {
                "roles": ["protagonist pressure source", "opposition force", "relationship mirror"],
                "motivation_chain": ["visible goal", "constraint", "choice", "cost"],
            },
            "conflict_map": {
                "external": "resource, status, survival, or mission pressure",
                "internal": "belief, fear, desire, or identity pressure",
                "systemic": "rules that repeatedly generate scenes",
            },
            "theme_map": {
                "candidate_themes": _theme_candidates(metrics),
                "safe_usage": "use as abstract thematic tension, not copied plot or phrasing",
            },
            "risk_boundary": "no source-specific character names, settings, prose, or event sequence may be reused",
            "reusable_findings": _common_findings(metrics),
        }
    if report_type == "web_fiction_business_analysis_report":
        return {
            **base,
            "platform_pattern": {
                "serialization_fit": _score_band(metrics["hook_signal_count"] + metrics["chapter_markers"]),
                "reader_retention_driver": "frequent pressure, visible promise, and chapter-end uncertainty",
            },
            "reader_promise": {
                "primary": "clear emotional payoff loop with repeatable escalation",
                "proof_points": _common_findings(metrics)[:3],
            },
            "hook_system": {
                "hook_density_signal": metrics["hook_signal_count"],
                "hook_types": ["anomaly", "choice pressure", "hidden information", "cost reveal"],
            },
            "payoff_loop": ["setup promise", "raise cost", "partial payoff", "new unresolved pressure"],
            "pacing_model": {
                "chapter_marker_count": metrics["chapter_markers"],
                "recommended_loop": "hook -> pressure -> choice -> consequence -> next hook",
            },
            "monetization_nodes": [
                "first-chapter promise clarity",
                "early conflict lock-in",
                "periodic status change or reveal",
            ],
            "abstraction_boundary": "commercial structure only; no protected scenes, names, proprietary settings, or text copied",
            "reusable_assets": ["chapter hook template", "payoff loop checklist", "reader promise review rule"],
        }
    if report_type == "published_fiction_analysis_report":
        return {
            **base,
            "craft_dimensions": {
                "scene_objective": "each scene should expose pressure, choice, and consequence",
                "subtext": "track what characters avoid saying directly",
                "transition": "use consequence-driven scene handoff instead of episodic listing",
            },
            "scene_design": {
                "scene_unit": ["objective", "obstacle", "turn", "after-effect"],
                "diagnostic_signal": f"avg sentence length {metrics['avg_sentence_length']}",
            },
            "character_arc": {
                "arc_engine": "belief under pressure changes through repeated decisions",
                "safe_transfer": "arc mechanism only, never character identity or episode sequence",
            },
            "narrative_distance": "parameterize POV distance, exposition load, and information withholding",
            "language_texture": {
                "dialogue_signal": metrics["dialogue_marker_count"],
                "recommended_control": "balance concrete detail with scene momentum",
            },
            "transferable_techniques": [
                "scene turn mapping",
                "subtext checklist",
                "character belief pressure grid",
                "transition by consequence",
            ],
            "do_not_copy": ["prose texture", "named characters", "signature scenes", "distinct plot order"],
        }
    if report_type == "classic_literary_analysis_report":
        return {
            **base,
            "deep_structure": {
                "social_pressure": "map institutions, family, class, duty, or fate as conflict systems",
                "moral_choice": "identify value collision rather than copy episodes",
            },
            "theme_system": {
                "candidate_themes": _theme_candidates(metrics),
                "dialectic": "desire vs duty, freedom vs order, memory vs change",
            },
            "symbol_system": {
                "symbol_roles": ["recurring object", "place pressure", "ritual or threshold"],
                "safe_transfer": "use symbolic function only",
            },
            "social_relation_model": {
                "nodes": ["family/order", "outsider/desire", "authority/rule", "community/gaze"],
                "edges": ["obligation", "temptation", "exclusion", "recognition"],
            },
            "fate_curve": ["initial condition", "pressure intensifies", "choice narrows", "cost clarifies", "meaning resolves"],
            "non_transferable_elements": ["specific historical scenes", "distinct characters", "recognizable set pieces", "prose style"],
            "transferable_abstractions": [
                "social pressure graph",
                "symbol-function map",
                "moral dilemma ladder",
                "fate cost curve",
            ],
        }
    raise ValueError(f"unsupported report_type: {report_type}")


def _semantic_depth_assessment(
    storage: LocalStorage,
    agent_run_path: str,
    report_type: str,
    asset: BaseAsset,
    metrics: dict[str, Any],
    model: Any,
) -> dict[str, Any]:
    rubric = _mode_rubric(report_type)
    source_text = _asset_text(asset)
    prompt = (
        "Score this reference work for Novel Forge abstract analysis. "
        "Return a schema-valid analyze response; do not copy protected expression."
    )
    provider_review: dict[str, Any]
    fallback_reason = ""
    try:
        guarded = GuardedModelAdapter(model, storage, agent_run_path)
        raw = guarded.analyze(
            prompt,
            {
                "analysis_type": report_type,
                "rubric": rubric,
                "source_metrics": metrics,
                "source_excerpt_for_analysis_only": source_text[:4000],
                "copyright_boundary": "abstract structures only; no source-specific prose, names, scenes, or event sequence may be reused",
            },
        )
        validated = validate_model_output("analyze", raw)
        provider_review = {
            "provider": str(raw.get("provider") or raw.get("model") or getattr(model, "name", "local")),
            "model": str(raw.get("model") or getattr(model, "name", "local")),
            "status": "provider_validated",
            "summary": validated.get("summary", ""),
            "patterns": validated.get("patterns", []),
            "word_count": validated.get("word_count", 0),
        }
    except (ModelOutputValidationError, RuntimeError, ValueError) as exc:
        fallback_reason = str(exc)
        provider_review = {
            "provider": "local-rubric",
            "model": "deterministic-analysis-rubric",
            "status": "fallback",
            "summary": _report_preview(_report_content(report_type, asset, metrics)),
            "patterns": _common_findings(metrics),
            "word_count": len(source_text.split()),
            "fallback_reason": fallback_reason,
        }
    rubric_scores = _rubric_scores(report_type, metrics, provider_review)
    visual = _mode_visualization(report_type, metrics, rubric_scores, provider_review)
    return {
        "semantic_depth": {
            "rubric_version": "analysis-rubric-v2",
            "overall_score": _weighted_score(rubric_scores),
            "rubric_scores": rubric_scores,
            "mode": report_type,
            "evidence": _semantic_evidence(report_type, metrics, provider_review),
            "provider_status": provider_review.get("status", ""),
            "fallback_reason": fallback_reason,
        },
        "provider_review": provider_review,
        "visualization": visual,
        "mode_specific_panels": _mode_panels(report_type, visual, rubric_scores),
    }


def _mode_rubric(report_type: str) -> dict[str, float]:
    if report_type == "web_fiction_business_analysis_report":
        return {"reader_promise": 0.25, "hook_system": 0.25, "payoff_loop": 0.2, "serialization_fit": 0.2, "abstraction_safety": 0.1}
    if report_type == "published_fiction_analysis_report":
        return {"scene_craft": 0.25, "subtext": 0.2, "character_arc": 0.2, "narrative_distance": 0.2, "abstraction_safety": 0.15}
    if report_type == "classic_literary_analysis_report":
        return {"theme_depth": 0.25, "symbol_system": 0.2, "psychological_pressure": 0.2, "social_relation_graph": 0.2, "abstraction_safety": 0.15}
    return {"structure": 0.25, "character_pressure": 0.2, "conflict_engine": 0.2, "theme": 0.2, "abstraction_safety": 0.15}


def _rubric_scores(report_type: str, metrics: dict[str, Any], provider_review: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rubric = _mode_rubric(report_type)
    patterns = [str(item).lower() for item in provider_review.get("patterns", []) if str(item).strip()]
    pattern_text = " ".join(patterns)
    hook = min(100, 45 + int(metrics.get("hook_signal_count", 0)) * 5 + int(metrics.get("chapter_markers", 0)) * 3)
    dialogue = min(100, 45 + int(metrics.get("dialogue_marker_count", 0)) * 4)
    keyword = min(100, 50 + len(metrics.get("top_keywords", []) or []) * 4)
    abstraction = 95 if _source_risk(provider_review if isinstance(provider_review, BaseAsset) else BaseAsset(id="provider", type="provider", content={}, metadata={"risk_level": "low"})) else 90
    base_by_dimension = {
        "reader_promise": hook,
        "hook_system": hook,
        "payoff_loop": 78 if "hook" in pattern_text or "conflict" in pattern_text else 66,
        "serialization_fit": min(100, hook + 8),
        "scene_craft": min(100, dialogue + 10),
        "subtext": 76 if any(token in pattern_text for token in ["subtext", "hidden", "avoid"]) else 62,
        "character_arc": 78 if any(token in pattern_text for token in ["character", "conflict", "pressure"]) else 66,
        "narrative_distance": min(100, int(100 - min(abs(float(metrics.get("avg_sentence_length", 0)) - 80), 60) * 0.4)),
        "theme_depth": keyword,
        "symbol_system": 76 if any(token in pattern_text for token in ["symbol", "recurring", "threshold"]) else 62,
        "psychological_pressure": 78 if any(token in pattern_text for token in ["pressure", "desire", "fear"]) else 64,
        "social_relation_graph": 76 if any(token in pattern_text for token in ["social", "authority", "family", "community"]) else 63,
        "structure": min(100, 55 + int(metrics.get("chapter_markers", 0)) * 8),
        "character_pressure": 76 if any(token in pattern_text for token in ["character", "pressure"]) else 64,
        "conflict_engine": 80 if any(token in pattern_text for token in ["conflict", "escalat"]) else 66,
        "theme": keyword,
        "abstraction_safety": abstraction,
    }
    results: dict[str, dict[str, Any]] = {}
    for dimension, weight in rubric.items():
        score = int(max(0, min(100, base_by_dimension.get(dimension, 70))))
        results[dimension] = {
            "score": score,
            "weight": weight,
            "evidence": _score_evidence(dimension, metrics, provider_review),
            "recommendation": _score_recommendation(dimension, score),
        }
    return results


def _mode_visualization(
    report_type: str,
    metrics: dict[str, Any],
    rubric_scores: dict[str, dict[str, Any]],
    provider_review: dict[str, Any],
) -> dict[str, Any]:
    score_points = [{"label": key, "score": value.get("score", 0), "weight": value.get("weight", 0)} for key, value in rubric_scores.items()]
    if report_type == "web_fiction_business_analysis_report":
        return {
            "kind": "retention_pipeline",
            "score_points": score_points,
            "timeline": [
                {"stage": "opening_promise", "signal": metrics.get("top_keywords", [])[:3], "score": rubric_scores.get("reader_promise", {}).get("score", 0)},
                {"stage": "pressure_loop", "signal": metrics.get("hook_signal_count", 0), "score": rubric_scores.get("hook_system", {}).get("score", 0)},
                {"stage": "payoff_reset", "signal": provider_review.get("patterns", [])[:3], "score": rubric_scores.get("payoff_loop", {}).get("score", 0)},
            ],
        }
    if report_type == "published_fiction_analysis_report":
        return {
            "kind": "craft_radar",
            "score_points": score_points,
            "scene_units": ["objective", "obstacle", "turn", "after-effect"],
            "diagnostics": {"avg_sentence_length": metrics.get("avg_sentence_length", 0), "dialogue_markers": metrics.get("dialogue_marker_count", 0)},
        }
    if report_type == "classic_literary_analysis_report":
        return {
            "kind": "theme_symbol_graph",
            "score_points": score_points,
            "nodes": [
                {"id": "theme", "label": "主题", "weight": rubric_scores.get("theme_depth", {}).get("score", 0)},
                {"id": "symbol", "label": "象征", "weight": rubric_scores.get("symbol_system", {}).get("score", 0)},
                {"id": "psychology", "label": "心理压力", "weight": rubric_scores.get("psychological_pressure", {}).get("score", 0)},
                {"id": "society", "label": "社会关系", "weight": rubric_scores.get("social_relation_graph", {}).get("score", 0)},
            ],
            "edges": [
                {"from": "theme", "to": "symbol", "relation": "expressed_by"},
                {"from": "psychology", "to": "society", "relation": "pressured_by"},
                {"from": "theme", "to": "psychology", "relation": "internalized_as"},
            ],
        }
    return {"kind": "narrative_map", "score_points": score_points, "keywords": metrics.get("top_keywords", [])}


def _mode_panels(report_type: str, visual: dict[str, Any], rubric_scores: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    labels = {
        "web_fiction_business_analysis_report": ["读者承诺", "爽点回路", "章节钩子", "平台节奏"],
        "published_fiction_analysis_report": ["场景技法", "潜台词", "人物弧光", "叙事距离"],
        "classic_literary_analysis_report": ["主题系统", "象征系统", "心理压力", "社会关系"],
        "common_novel_analysis_report": ["结构", "人物压力", "冲突引擎", "主题"],
    }.get(report_type, ["结构", "人物", "冲突", "主题"])
    score_values = list(rubric_scores.values())
    return [
        {
            "title": label,
            "score": score_values[index % len(score_values)].get("score", 0) if score_values else 0,
            "visual_kind": visual.get("kind", ""),
            "recommendation": score_values[index % len(score_values)].get("recommendation", "") if score_values else "",
        }
        for index, label in enumerate(labels)
    ]


def _semantic_evidence(report_type: str, metrics: dict[str, Any], provider_review: dict[str, Any]) -> list[str]:
    return _dedupe(
        [
            f"mode={report_type}",
            f"hook_signals={metrics.get('hook_signal_count', 0)}",
            f"chapter_markers={metrics.get('chapter_markers', 0)}",
            f"keywords={', '.join([str(item) for item in metrics.get('top_keywords', [])[:5]])}",
            f"provider_status={provider_review.get('status', '')}",
        ]
    )


def _weighted_score(scores: dict[str, dict[str, Any]]) -> int:
    total = 0.0
    weight = 0.0
    for item in scores.values():
        total += float(item.get("score", 0)) * float(item.get("weight", 0))
        weight += float(item.get("weight", 0))
    return int(round(total / max(weight, 0.01)))


def _score_evidence(dimension: str, metrics: dict[str, Any], provider_review: dict[str, Any]) -> list[str]:
    return [
        f"dimension={dimension}",
        f"hook_signal_count={metrics.get('hook_signal_count', 0)}",
        f"dialogue_marker_count={metrics.get('dialogue_marker_count', 0)}",
        f"provider_patterns={', '.join([str(item) for item in provider_review.get('patterns', [])[:3]])}",
    ]


def _score_recommendation(dimension: str, score: int) -> str:
    if score >= 85:
        return f"{dimension} is strong enough to convert into reusable abstract assets."
    if score >= 70:
        return f"{dimension} is usable but should be reviewed before becoming a production template."
    return f"{dimension} is weak; run Claude Code handoff or manual analysis before conversion."


def _analysis_metadata(storage: LocalStorage, report_type: str, asset: BaseAsset, project: dict[str, Any], source_path: Path) -> dict[str, Any]:
    source_risk = _source_risk(asset)
    return {
        "project_id": str(project.get("project_id", "")),
        "workspace_path": str(project.get("workspace_path", "")),
        "asset_status": "active",
        "analysis_type": report_type,
        "analysis_layer": True,
        "created_by": "analysis_center",
        "created_at": utc_now(),
        "source_asset_path": _relative_path(storage, source_path),
        "copyright_boundary": "abstract structure analysis only; no protected expression, names, settings, or plot sequence copied",
        "copyright_risk": source_risk,
        "risk_level": source_risk,
        "abstraction_level": "abstract",
        "use_in_generation_rag": False,
        "allowed_pipeline": ["analysis", "review", "abstract_asset_conversion"],
        "forbidden_pipeline": ["direct_generation_rag", "direct_prose_reuse", "author_imitation"],
        "runtime": run_metadata(f"run_{report_type}", asset),
    }


def _analysis_references(storage: LocalStorage, source_path: Path, source_asset: BaseAsset, project: dict[str, Any]) -> list[str]:
    refs = [source_asset.id, _relative_path(storage, source_path)]
    workspace_path = str(project.get("workspace_path", ""))
    project_id = str(project.get("project_id", ""))
    if workspace_path:
        refs.append(workspace_path)
    if project_id:
        refs.append(project_id)
    return _dedupe(refs)


def _create_converted_asset(
    storage: LocalStorage,
    report: BaseAsset,
    report_file: Path,
    project: dict[str, Any],
    target: str,
    *,
    reuse_scope: str,
    human_approved: bool,
    approval_note: str,
) -> dict[str, Any]:
    project_id = str(project.get("project_id", ""))
    workspace_path = str(project.get("workspace_path", ""))
    report_content = report.content if isinstance(report.content, dict) else {}
    title = f"{_converted_title_prefix(target)} from {report.title or report.name}"
    copyright_risk = _risk_from_report(report)
    generation_allowed = (
        human_approved
        and copyright_risk != "high"
        and target in {"material_card", "knowledge_card", "writing_template", "craft_template", "review_rule_pack"}
    )
    metadata = {
        "project_id": project_id,
        "workspace_path": workspace_path,
        "source_analysis_report_id": report.id,
        "source_analysis_report_type": report.type,
        "source_analysis_report_path": _relative_path(storage, report_file),
        "reuse_scope": reuse_scope,
        "copyright_risk": copyright_risk,
        "risk_level": copyright_risk,
        "abstraction_level": "template" if target in {"writing_template", "craft_template", "review_rule_pack"} else "mechanism",
        "copyright_boundary": "abstracted from analysis report; no protected text, names, settings, or plot sequence copied",
        "use_in_generation_rag": generation_allowed,
        "asset_status": "active" if human_approved else "needs_human_gate",
        "human_gate_required": True,
        "human_gate_status": "approved" if human_approved else "waiting_human",
        "approval_note": approval_note,
        "review_rule_gate_status": "approved" if human_approved else "waiting_human",
        "created_by": "analysis_conversion_service",
    }
    return create_creative_asset(
        storage,
        {
            "asset_type": target,
            "title": title,
            "scope": "project" if project_id else "global",
            "project_id": project_id,
            "workspace_path": workspace_path,
            "source": report.id,
            "tags": ["analysis-converted", report.type.replace("_", "-")],
            "content": _converted_content(target, report, report_content),
            "metadata": metadata,
            "references": [report.id, _relative_path(storage, report_file)],
        },
    )


def _converted_content(target: str, report: BaseAsset, content: dict[str, Any]) -> dict[str, Any]:
    findings = _findings_from_report(report.type, content)
    if target == "material_card":
        return {
            "usable_patterns": findings[:6] or ["abstract analysis-derived story mechanism"],
            "prompt_fragments": [
                "Use this abstract mechanism with original characters, original setting, and project continuity.",
            ],
            "do_not_copy": ["source prose", "proper nouns", "specific scenes", "plot sequence", "recognizable character setup"],
            "use_cases": ["outline", "chapter_plan", "context_builder", "review"],
        }
    if target == "knowledge_card":
        return {
            "principles": findings[:6] or ["abstract narrative principle from analysis"],
            "constraints": [
                "cite analysis report boundary",
                "do not use raw source text",
                "convert into original project logic before drafting",
            ],
            "review_checks": ["is the use abstract", "are protected names absent", "is the source-specific sequence avoided"],
        }
    if target == "writing_template":
        return {
            "template_id": f"analysis_template_{report.id[-8:]}",
            "name": f"Analysis-derived template: {report.title or report.name}",
            "template_kind": "chapter_structure",
            "structure": _template_structure(report.type, content),
            "usage_constraints": [
                "adapt to project canon and platform profile",
                "replace all examples with original events",
                "do not mirror source sequence",
            ],
            "anti_copy_rules": ["no protected names", "no source-specific scene order", "no source prose"],
        }
    if target == "craft_template":
        return {
            "template_id": f"craft_template_{report.id[-8:]}",
            "name": f"Analysis-derived craft template: {report.title or report.name}",
            "craft_domain": _craft_domain(report.type),
            "pattern": " -> ".join(_template_structure(report.type, content)),
            "use_cases": ["outline", "chapter_plan", "AI editor", "review"],
            "risks": ["formulaic repetition", "source overfitting", "weak original character motive"],
        }
    if target == "review_rule_pack":
        return {
            "rule_pack_id": f"analysis_rules_{report.id[-8:]}",
            "name": f"Analysis-derived review rules: {report.title or report.name}",
            "dimensions": {
                "abstraction_safety": {"weight": 0.25, "threshold": 90},
                "structure_fit": {"weight": 0.25, "threshold": 75},
                "reader_promise": {"weight": 0.2, "threshold": 75},
                "project_originality": {"weight": 0.3, "threshold": 90},
            },
            "checks": [
                "No source-specific names, settings, scenes, or plot sequence are reused.",
                "The mechanism is adapted to current project continuity.",
                "The chapter preserves reader promise and hook clarity.",
            ],
            "severity_policy": {"blocker": "must_fix", "major": "revise", "minor": "track"},
        }
    raise ValueError(f"unsupported conversion target: {target}")


def _normalize_targets(report_type: str, targets: list[str]) -> list[str]:
    allowed = {"material_card", "knowledge_card", "writing_template", "craft_template", "review_rule_pack"}
    normalized = [target.strip() for target in targets if target.strip()]
    normalized = normalized or _DEFAULT_CONVERSION_TARGETS[report_type]
    invalid = sorted(set(normalized) - allowed)
    if invalid:
        raise ValueError(f"unsupported conversion targets: {', '.join(invalid)}")
    return _dedupe(normalized)


def _asset_text(asset: BaseAsset) -> str:
    content = asset.content if isinstance(asset.content, dict) else {}
    parts: list[str] = []
    for key in ["text", "summary", "objective", "hook", "logline", "setting", "conflict_system"]:
        value = content.get(key)
        if isinstance(value, str):
            parts.append(value)
    for value in content.values():
        if isinstance(value, list):
            parts.extend(str(item) for item in value[:20])
        elif isinstance(value, dict):
            parts.extend(str(item) for item in value.values() if isinstance(item, (str, int, float)))
    return "\n".join(part for part in parts if part).strip() or asset.title or asset.name or asset.id


def _split_units(text: str) -> list[str]:
    units = [item.strip() for item in re.split(r"[。！？!?；;\n]+", text) if item.strip()]
    return units or ([text] if text else [])


def _count_tokens(text: str, tokens: list[str]) -> int:
    lowered = text.lower()
    return sum(lowered.count(token.lower()) for token in tokens)


def _theme_candidates(metrics: dict[str, Any]) -> list[str]:
    keywords = [str(item) for item in metrics.get("top_keywords", [])][:5]
    return keywords or ["choice under pressure", "identity and cost"]


def _common_findings(metrics: dict[str, Any]) -> list[str]:
    findings = [
        f"hook signal density: {metrics.get('hook_signal_count', 0)}",
        f"chapter marker signal: {metrics.get('chapter_markers', 0)}",
        f"dialogue marker signal: {metrics.get('dialogue_marker_count', 0)}",
        f"average narrative unit length: {metrics.get('avg_sentence_length', 0)}",
    ]
    keywords = [str(item) for item in metrics.get("top_keywords", [])][:4]
    if keywords:
        findings.append(f"recurring topic signals: {', '.join(keywords)}")
    return findings


def _score_band(value: int | float) -> str:
    if value >= 12:
        return "strong"
    if value >= 5:
        return "medium"
    return "weak"


def _source_risk(asset: BaseAsset) -> str:
    metadata = asset.metadata if isinstance(asset.metadata, dict) else {}
    rights = metadata.get("rights") if isinstance(metadata.get("rights"), dict) else {}
    for candidate in [metadata.get("copyright_risk"), metadata.get("risk_level"), rights.get("risk_level")]:
        if candidate in {"low", "medium", "high", "unknown"}:
            return str(candidate)
    authorization = rights.get("authorization")
    if authorization in {"owned", "public_domain", "test_fixture", "licensed", "permission_granted"}:
        return "low"
    if authorization == "unknown":
        return "high"
    return "unknown"


def _risk_from_report(report: BaseAsset) -> str:
    metadata = report.metadata if isinstance(report.metadata, dict) else {}
    content = report.content if isinstance(report.content, dict) else {}
    for value in [content.get("copyright_risk"), metadata.get("copyright_risk"), metadata.get("risk_level")]:
        if value in {"low", "medium", "high", "unknown"}:
            return str(value)
    return "unknown"


def _findings_from_report(report_type: str, content: dict[str, Any]) -> list[str]:
    if report_type == "common_novel_analysis_report":
        return [str(item) for item in content.get("reusable_findings", []) if str(item)]
    if report_type == "web_fiction_business_analysis_report":
        values = content.get("reusable_assets", [])
        return [str(item) for item in values if str(item)]
    if report_type == "published_fiction_analysis_report":
        return [str(item) for item in content.get("transferable_techniques", []) if str(item)]
    if report_type == "classic_literary_analysis_report":
        return [str(item) for item in content.get("transferable_abstractions", []) if str(item)]
    return []


def _template_structure(report_type: str, content: dict[str, Any]) -> list[str]:
    if report_type == "web_fiction_business_analysis_report":
        loop = content.get("payoff_loop")
        if isinstance(loop, list) and loop:
            return [str(item) for item in loop]
        return ["hook", "pressure", "choice", "consequence", "next hook"]
    if report_type == "published_fiction_analysis_report":
        scene = content.get("scene_design")
        if isinstance(scene, dict) and isinstance(scene.get("scene_unit"), list):
            return [str(item) for item in scene["scene_unit"]]
        return ["objective", "obstacle", "turn", "after-effect"]
    if report_type == "classic_literary_analysis_report":
        fate = content.get("fate_curve")
        if isinstance(fate, list) and fate:
            return [str(item) for item in fate]
        return ["condition", "pressure", "narrowing choice", "cost", "meaning"]
    return ["disturbance", "pressure", "decision", "cost", "changed state"]


def _craft_domain(report_type: str) -> str:
    return {
        "common_novel_analysis_report": "narrative_structure",
        "web_fiction_business_analysis_report": "serialized_reader_retention",
        "published_fiction_analysis_report": "scene_and_arc_craft",
        "classic_literary_analysis_report": "theme_symbol_structure",
    }.get(report_type, "narrative_structure")


def _converted_title_prefix(target: str) -> str:
    return {
        "material_card": "Material mechanism",
        "knowledge_card": "Knowledge principle",
        "writing_template": "Writing template",
        "craft_template": "Craft template",
        "review_rule_pack": "Review rules",
    }[target]


def _report_preview(content: dict[str, Any]) -> str:
    for key in ["analysis_scope", "reader_promise", "narrative_distance", "risk_boundary", "conversion_policy"]:
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return value[:220]
        if isinstance(value, dict) and value:
            return str(value)[:220]
    return str(content)[:220]


def _validate_asset(asset: BaseAsset) -> None:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))


def _relative_path(storage: LocalStorage, path: str | Path) -> str:
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(storage.root))
    except ValueError:
        return str(resolved)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result
