from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from novel_forge.core.constants import ASSET_DIR_BY_TYPE, DATA_DIRS
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.model_adapters import embedding_provider_health
from novel_forge.schemas import BaseAsset
from novel_forge.storage.local import LocalStorage
from novel_forge.storage.qdrant_index import qdrant_search_assets
from novel_forge.storage.vector_index import vector_search_assets

RAG_CONTEXT_VERSION = "0.1.0"
DEFAULT_RAG_TOP_K = 8
RAG_BACKENDS = {"auto", "local", "qdrant", "pgvector", "hybrid"}

RAG_BUCKETS = {
    "characters": "人物",
    "worldbuilding": "世界观",
    "previous_summaries": "前文摘要",
    "knowledge_cards": "知识卡",
    "foreshadowing": "伏笔",
    "material_cards": "素材卡",
    "writing_templates": "写作模板",
}

TYPE_BUCKETS = {
    "character_card": ["characters"],
    "character_mechanism": ["characters", "material_cards"],
    "world_bible": ["worldbuilding"],
    "continuity_bible": ["worldbuilding", "foreshadowing"],
    "foreshadowing_thread": ["foreshadowing"],
    "power_scale_rule": ["worldbuilding"],
    "platform_profile": ["material_cards"],
    "genre_market_profile": ["material_cards"],
    "genre_profile": ["material_cards"],
    "subgenre_mechanic": ["material_cards", "writing_templates"],
    "genre_strategy_pack": ["material_cards", "writing_templates", "foreshadowing"],
    "platform_genre_fit": ["material_cards"],
    "genre_template_binding": ["writing_templates", "material_cards"],
    "creative_strategy_profile": ["material_cards", "writing_templates", "foreshadowing"],
    "quality_standard_profile": ["writing_templates"],
    "quality_rubric_pack": ["writing_templates"],
    "opening_3_report": ["previous_summaries"],
    "golden_10_report": ["previous_summaries"],
    "volume_30_report": ["previous_summaries"],
    "longform_100_report": ["previous_summaries"],
    "quality_regression_report": ["previous_summaries"],
    "style_profile": ["writing_templates"],
    "style_fingerprint": ["previous_summaries"],
    "style_generation_policy": ["writing_templates"],
    "style_review_rule": ["writing_templates"],
    "style_drift_report": ["previous_summaries"],
    "style_blend_preset": ["writing_templates"],
    "fantasy_power_scale_report": ["worldbuilding", "previous_summaries"],
    "mystery_evidence_chain_report": ["foreshadowing", "previous_summaries"],
    "romance_relationship_state_report": ["characters", "previous_summaries"],
    "historical_faction_network_report": ["worldbuilding", "previous_summaries"],
    "sci_fi_rule_consistency_report": ["worldbuilding", "previous_summaries"],
    "horror_rule_contamination_report": ["foreshadowing", "previous_summaries"],
    "project_workspace_state": ["previous_summaries", "foreshadowing"],
    "outline": ["previous_summaries"],
    "chapter_plan": ["previous_summaries"],
    "draft_chapter": ["previous_summaries"],
    "revision_plan": ["previous_summaries"],
    "knowledge_card": ["knowledge_cards"],
    "material_card": ["material_cards"],
    "commercial_pattern": ["material_cards"],
    "narrative_pattern": ["material_cards"],
    "conflict_pattern": ["material_cards"],
    "emotion_curve": ["material_cards"],
    "hook_pattern": ["foreshadowing", "material_cards"],
    "writing_template": ["writing_templates", "material_cards"],
    "craft_template": ["writing_templates", "material_cards"],
    "memory_record": ["previous_summaries", "knowledge_cards"],
    "memory_chunk": ["previous_summaries", "knowledge_cards"],
    "knowledge_chunk": ["knowledge_cards"],
    "review_memory_chunk": ["previous_summaries", "writing_templates"],
    "entity_memory_chunk": ["characters", "worldbuilding"],
    "artifact_embedding": ["knowledge_cards", "material_cards"],
}

FORESHADOWING_TERMS = ("伏笔", "foreshadow", "hook", "continuity_thread", "continuity_threads", "open_issue", "open_issues")
COPYRIGHT_RISK_ORDER = {"low": 0, "medium": 1, "unknown": 1, "high": 2}
COPYRIGHT_BLOCKING_RISKS = {"high"}
GENERATION_RAG_BLOCKED_TYPES = {
    "source_document",
    "source_chunk",
    "source_deconstruction_observation",
    "source_reprocessing_plan",
    "cleaned_text",
    "decomposition_report",
    "common_novel_analysis_report",
    "web_fiction_business_analysis_report",
    "published_fiction_analysis_report",
    "classic_literary_analysis_report",
    "style_sample",
    "agent_run",
    "agent_task",
    "agent_checkpoint",
    "agent_budget",
    "agent_gate",
    "agent_metric",
    "agent_dispatch_queue",
    "agent_contract",
    "loop_run",
    "loop_step",
    "loop_checkpoint",
    "loop_report",
    "trace_span",
    "model_call_log",
    "cost_ledger",
    "workflow_run",
    "task_status",
    "knowledge_usage_binding",
    "rule_card",
    "template_card",
    "knowledge_pack",
    "knowledge_pack_item",
    "knowledge_usage_event",
    "knowledge_quality_score",
}


@dataclass
class RagContextBuilder:
    storage: LocalStorage
    default_top_k: int = DEFAULT_RAG_TOP_K
    backend: str = "auto"
    settings: IndustrialSettings | None = None

    def build(
        self,
        input_asset: BaseAsset,
        input_path: str | Path | None = None,
        query: str | None = None,
        top_k: int | None = None,
        backend: str | None = None,
        memory_levels: list[str] | None = None,
        quality_memory: bool = True,
    ) -> dict[str, Any]:
        requested_top_k = int(top_k or self.default_top_k)
        if requested_top_k < 1:
            raise ValueError("top_k must be greater than zero")
        requested_backend = _normalize_backend(backend or self.backend)
        source_path = _relative_path(self.storage, input_path) if input_path else ""
        query_text = _compact_text(query or _default_query(input_asset), limit=1200) or input_asset.title or input_asset.id
        scope = _project_scope_for_asset(self.storage, input_asset.to_dict(), source_path)
        selected_memory_levels = _normalized_memory_levels(memory_levels)
        if quality_memory and "L5" not in selected_memory_levels:
            selected_memory_levels.append("L5")
        ranked, actual_backend, backend_attempts = self._ranked_candidates(
            query_text,
            limit=max(requested_top_k * 8, 40),
            backend=requested_backend,
            project_id=str(scope.get("project_id", "")),
            memory_levels=selected_memory_levels,
        )
        items = self._select_items(ranked, input_asset, source_path, scope, requested_top_k, query_text)
        if len(items) < requested_top_k:
            items = self._fill_from_project_scan(items, input_asset, source_path, scope, requested_top_k, query_text)
        buckets = {name: [] for name in RAG_BUCKETS}
        for item in items:
            for bucket in item["categories"]:
                buckets.setdefault(bucket, []).append(item)
        filtered_assets = self._copyright_filtered_assets(input_asset, source_path, scope)
        recall_explanation = _recall_explanation(query_text, items, requested_top_k, actual_backend)
        omission_check = _omission_check(input_asset, buckets, filtered_assets)
        copyright_filter = _copyright_filter_summary(items, filtered_assets)
        source_asset_ids = _dedupe([str(item["asset_id"]) for item in items if item.get("asset_id")])
        return {
            "version": RAG_CONTEXT_VERSION,
            "query": query_text,
            "top_k": requested_top_k,
            "ranker": _ranker_name(items),
            "requested_backend": requested_backend,
            "retrieval_backend": actual_backend,
            "backend_attempts": backend_attempts,
            "memory_levels": selected_memory_levels,
            "quality_memory_enabled": bool(quality_memory),
            "project_id": scope.get("project_id", ""),
            "workspace_path": scope.get("workspace_path", ""),
            "source_asset_id": input_asset.id,
            "source_asset_type": input_asset.type,
            "source_asset_path": source_path,
            "source_asset_ids": source_asset_ids,
            "source_paths": _dedupe([str(item["path"]) for item in items if item.get("path")]),
            "items": items,
            "buckets": buckets,
            "recall_explanation": recall_explanation,
            "omission_check": omission_check,
            "copyright_filter": copyright_filter,
            "quality": {
                "recall_explanation": recall_explanation,
                "omission_check": omission_check,
                "copyright_filter": copyright_filter,
            },
        }

    def _ranked_candidates(self, query: str, limit: int, backend: str, *, project_id: str = "", memory_levels: list[str] | None = None) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
        attempts: list[dict[str, Any]] = []
        levels = memory_levels or []
        if backend == "auto":
            for candidate in _auto_backend_order():
                if candidate in {"pgvector", "hybrid"}:
                    try:
                        from novel_forge.modules.pgvector_store import hybrid_retrieve

                        report = hybrid_retrieve(
                            self.storage,
                            query=query,
                            project_id=project_id,
                            retrieval_backend="pgvector",
                            limit=limit,
                            levels=levels,
                            persist=False,
                        )
                        results = [_rag_result_from_hybrid(item) for item in report.get("results", []) if isinstance(item, dict)]
                        attempts.append({"backend": "pgvector", "ok": True, "result_count": len(results), "projection": report.get("vector_backend", "")})
                        if results:
                            return results, "pgvector", attempts
                    except Exception as exc:
                        attempts.append({"backend": "pgvector", "ok": False, "error": str(exc)})
                    continue
                if candidate == "qdrant":
                    health = embedding_provider_health(require_semantic=True)
                    if health.get("ok"):
                        try:
                            settings = self.settings or IndustrialSettings.from_env(root=self.storage.root)
                            results = _merge_ranked_results(
                                qdrant_search_assets(self.storage, settings, query=query, limit=limit),
                                _memory_ranked_results(self.storage, query=query, project_id=project_id, levels=levels, limit=limit),
                            )
                            attempts.append({"backend": "qdrant", "ok": True, "result_count": len(results)})
                            if results:
                                return results, "qdrant", attempts
                        except Exception as exc:
                            attempts.append({"backend": "qdrant", "ok": False, "error": str(exc)})
                    else:
                        attempts.append({"backend": "qdrant", "ok": False, "error": health.get("error") or health.get("message") or "embedding provider unavailable"})
                    continue
                if candidate == "local":
                    try:
                        results = _merge_ranked_results(
                            vector_search_assets(self.storage, query=query, limit=limit, auto_rebuild=False),
                            _memory_ranked_results(self.storage, query=query, project_id=project_id, levels=levels, limit=limit),
                        )
                        attempts.append({"backend": "local", "ok": True, "result_count": len(results)})
                        return results, "local", attempts
                    except Exception as exc:
                        attempts.append({"backend": "local", "ok": False, "error": str(exc)})
            return [], "scan", attempts
        if backend in {"pgvector", "hybrid"}:
            try:
                from novel_forge.modules.pgvector_store import hybrid_retrieve

                report = hybrid_retrieve(
                    self.storage,
                    query=query,
                    project_id=project_id,
                    retrieval_backend=backend,
                    limit=limit,
                    levels=levels,
                    persist=False,
                )
                results = [_rag_result_from_hybrid(item) for item in report.get("results", []) if isinstance(item, dict)]
                attempts.append({"backend": backend, "ok": True, "result_count": len(results), "projection": report.get("vector_backend", "")})
                return results, backend, attempts
            except Exception as exc:
                attempts.append({"backend": backend, "ok": False, "error": str(exc)})
                if backend == "pgvector":
                    raise
        if backend in {"auto", "qdrant"}:
            health = embedding_provider_health(require_semantic=True)
            if health.get("ok"):
                try:
                    settings = self.settings or IndustrialSettings.from_env(root=self.storage.root)
                    results = _merge_ranked_results(qdrant_search_assets(self.storage, settings, query=query, limit=limit), _memory_ranked_results(self.storage, query=query, project_id=project_id, levels=levels, limit=limit))
                    attempts.append({"backend": "qdrant", "ok": True, "result_count": len(results)})
                    return results, "qdrant", attempts
                except Exception as exc:
                    attempts.append({"backend": "qdrant", "ok": False, "error": str(exc)})
                    if backend == "qdrant":
                        raise
            else:
                attempts.append({"backend": "qdrant", "ok": False, "error": health.get("error") or health.get("message") or "embedding provider unavailable"})
                if backend == "qdrant":
                    raise RuntimeError(str(attempts[-1]["error"]))
        try:
            results = _merge_ranked_results(
                vector_search_assets(self.storage, query=query, limit=limit, auto_rebuild=False),
                _memory_ranked_results(self.storage, query=query, project_id=project_id, levels=levels, limit=limit),
            )
            attempts.append({"backend": "local", "ok": True, "result_count": len(results)})
            return results, "local", attempts
        except Exception as exc:
            attempts.append({"backend": "local", "ok": False, "error": str(exc)})
            return [], "scan", attempts

    def _select_items(
        self,
        ranked: list[dict[str, Any]],
        input_asset: BaseAsset,
        source_path: str,
        scope: dict[str, str],
        top_k: int,
        query: str,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        deferred: list[dict[str, Any]] = []
        seen: set[str] = set()
        expected_buckets = _expected_buckets_for_input(input_asset.type)
        covered_buckets: set[str] = set()
        for result in ranked:
            path_text = str(result.get("path", "")).strip()
            if not path_text:
                continue
            path = self.storage.root / path_text
            item = self._item_from_path(path, result, input_asset, source_path, scope, query)
            if not item:
                continue
            key = str(item["path"])
            if key in seen:
                continue
            seen.add(key)
            item_buckets = set(item.get("categories", []))
            adds_expected_coverage = bool(item_buckets.intersection(expected_buckets).difference(covered_buckets))
            if adds_expected_coverage or not expected_buckets:
                items.append(item)
                covered_buckets.update(item_buckets.intersection(expected_buckets))
            else:
                deferred.append(item)
            if len(items) >= top_k and all(bucket in covered_buckets for bucket in expected_buckets):
                break
        for item in deferred:
            if len(items) >= top_k:
                break
            items.append(item)
        return items

    def _fill_from_project_scan(
        self,
        items: list[dict[str, Any]],
        input_asset: BaseAsset,
        source_path: str,
        scope: dict[str, str],
        top_k: int,
        query: str,
    ) -> list[dict[str, Any]]:
        seen = {str(item["path"]) for item in items}
        deferred: list[dict[str, Any]] = []
        expected_buckets = _expected_buckets_for_input(input_asset.type)
        covered_buckets = {bucket for item in items for bucket in item.get("categories", []) if bucket in expected_buckets}
        for category in DATA_DIRS:
            for path in reversed(self.storage.list_json(category)):
                result = {"path": _relative_path(self.storage, path), "score": 0.0, "ranker": "project-scoped-asset-priority"}
                item = self._item_from_path(path, result, input_asset, source_path, scope, query)
                if not item or str(item["path"]) in seen:
                    continue
                seen.add(str(item["path"]))
                item_buckets = set(item.get("categories", []))
                adds_expected_coverage = bool(item_buckets.intersection(expected_buckets).difference(covered_buckets))
                if adds_expected_coverage or not expected_buckets:
                    items.append(item)
                    covered_buckets.update(item_buckets.intersection(expected_buckets))
                else:
                    deferred.append(item)
                if len(items) >= top_k and all(bucket in covered_buckets for bucket in expected_buckets):
                    return items
        for item in deferred:
            if len(items) >= top_k:
                break
            items.append(item)
        return items

    def _item_from_path(
        self,
        path: Path,
        result: dict[str, Any],
        input_asset: BaseAsset,
        source_path: str,
        scope: dict[str, str],
        query: str,
    ) -> dict[str, Any] | None:
        try:
            data = self.storage.read_json(path)
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        relative = _relative_path(self.storage, path)
        if data.get("id") == input_asset.id or relative == source_path:
            return None
        if not _matches_project_scope(self.storage, data, relative, scope):
            return None
        categories = _categories_for_asset(data)
        if not categories:
            return None
        copyright = _copyright_assessment(data)
        if not copyright["eligible"]:
            return None
        asset_scope = _project_scope_for_asset(self.storage, data, relative)
        summary = _asset_context_summary(data)
        return {
            "asset_id": str(data.get("id", "")),
            "path": relative,
            "type": str(data.get("type", "")),
            "title": str(data.get("title") or data.get("name") or ""),
            "categories": categories,
            "score": round(float(result.get("score", 0.0)), 6),
            "ranker": str(result.get("ranker") or "project-scoped-asset-priority"),
            "project_id": asset_scope.get("project_id", ""),
            "workspace_path": asset_scope.get("workspace_path", ""),
            "summary": summary,
            "copyright": copyright,
            "recall_explanation": _item_recall_explanation(query, data, categories, result, summary),
        }

    def _copyright_filtered_assets(
        self,
        input_asset: BaseAsset,
        source_path: str,
        scope: dict[str, str],
    ) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        seen: set[str] = set()
        for category in DATA_DIRS:
            for path in reversed(self.storage.list_json(category)):
                try:
                    data = self.storage.read_json(path)
                except Exception:
                    continue
                if not isinstance(data, dict):
                    continue
                relative = _relative_path(self.storage, path)
                if data.get("id") == input_asset.id or relative == source_path:
                    continue
                if relative in seen or not _matches_project_scope(self.storage, data, relative, scope):
                    continue
                if not _categories_for_asset(data) and data.get("type") not in GENERATION_RAG_BLOCKED_TYPES:
                    continue
                copyright = _copyright_assessment(data)
                if copyright["eligible"]:
                    continue
                seen.add(relative)
                filtered.append(
                    {
                        "asset_id": str(data.get("id", "")),
                        "path": relative,
                        "type": str(data.get("type", "")),
                        "title": str(data.get("title") or data.get("name") or ""),
                        "risk_level": copyright["risk_level"],
                        "reason": copyright["reason"],
                        "signals": copyright["signals"],
                    }
                )
        return filtered[:200]


def build_rag_context(
    storage: LocalStorage,
    input_asset: BaseAsset,
    input_path: str | Path | None = None,
    query: str | None = None,
    top_k: int = DEFAULT_RAG_TOP_K,
    backend: str = "auto",
    settings: IndustrialSettings | None = None,
    memory_levels: list[str] | None = None,
    quality_memory: bool = True,
) -> dict[str, Any]:
    return RagContextBuilder(storage, backend=backend, settings=settings).build(input_asset, input_path=input_path, query=query, top_k=top_k, memory_levels=memory_levels, quality_memory=quality_memory)


def retrieval_metadata(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "retrieved_context": context,
        "retrieval_query": context.get("query", ""),
        "retrieval_top_k": context.get("top_k", 0),
        "retrieval_ranker": context.get("ranker", ""),
        "retrieval_backend": context.get("retrieval_backend", ""),
        "retrieval_requested_backend": context.get("requested_backend", ""),
        "retrieval_backend_attempts": context.get("backend_attempts", []),
        "retrieval_source_asset_ids": context.get("source_asset_ids", []),
        "retrieval_quality": context.get("quality", {}),
        "retrieval_omissions": context.get("omission_check", {}).get("missing_buckets", []),
        "retrieval_filtered_asset_count": context.get("copyright_filter", {}).get("filtered_count", 0),
    }


def retrieval_reference_ids(input_asset_id: str, context: dict[str, Any]) -> list[str]:
    return _dedupe([input_asset_id, *[str(item) for item in context.get("source_asset_ids", []) if str(item).strip()]])


def generation_context_policy(data: dict[str, Any]) -> dict[str, Any]:
    return _copyright_assessment(data)


def _recall_explanation(query: str, items: list[dict[str, Any]], top_k: int, backend: str) -> dict[str, Any]:
    return {
        "backend": backend,
        "query_terms": _query_terms(query),
        "requested_top_k": top_k,
        "returned_count": len(items),
        "coverage_by_bucket": {bucket: len([item for item in items if bucket in item.get("categories", [])]) for bucket in RAG_BUCKETS},
        "items": [
            {
                "asset_id": item.get("asset_id", ""),
                "path": item.get("path", ""),
                "type": item.get("type", ""),
                "title": item.get("title", ""),
                "score": item.get("score", 0),
                "ranker": item.get("ranker", ""),
                "matched_terms": item.get("recall_explanation", {}).get("matched_terms", []),
                "bucket_reasons": item.get("recall_explanation", {}).get("bucket_reasons", []),
                "reason": item.get("recall_explanation", {}).get("reason", ""),
            }
            for item in items
        ],
    }


def _omission_check(input_asset: BaseAsset, buckets: dict[str, list[dict[str, Any]]], filtered_assets: list[dict[str, Any]]) -> dict[str, Any]:
    expected = _expected_buckets_for_input(input_asset.type)
    missing = [bucket for bucket in expected if not buckets.get(bucket)]
    filtered_by_bucket = _filtered_bucket_counts(filtered_assets)
    return {
        "expected_buckets": expected,
        "present_buckets": [bucket for bucket in expected if buckets.get(bucket)],
        "missing_buckets": missing,
        "missing_count": len(missing),
        "filtered_by_bucket": filtered_by_bucket,
        "status": "passed" if not missing else "warning",
        "recommendations": [_bucket_recommendation(bucket) for bucket in missing],
    }


def _copyright_filter_summary(items: list[dict[str, Any]], filtered_assets: list[dict[str, Any]]) -> dict[str, Any]:
    selected_risks = [str(item.get("copyright", {}).get("risk_level", "unknown")) for item in items]
    max_selected_risk = _max_risk(selected_risks)
    return {
        "policy": "exclude raw/analysis reports and assets with high copyright risk or explicit use_in_generation_rag=false",
        "selected_count": len(items),
        "selected_max_risk": max_selected_risk,
        "filtered_count": len(filtered_assets),
        "filtered_assets": filtered_assets,
        "status": "passed" if max_selected_risk != "high" else "blocked",
    }


def _item_recall_explanation(query: str, data: dict[str, Any], categories: list[str], result: dict[str, Any], summary: str) -> dict[str, Any]:
    matched_terms = _matched_query_terms(query, data, summary)
    bucket_reasons = [f"{data.get('type', '')} maps to {category}" for category in categories]
    return {
        "reason": "semantic/vector rank plus project-scoped bucket eligibility" if result.get("score") else "project-scoped fallback plus bucket eligibility",
        "matched_terms": matched_terms,
        "bucket_reasons": bucket_reasons,
        "ranker": str(result.get("ranker") or "project-scoped-asset-priority"),
        "score": round(float(result.get("score", 0.0)), 6),
    }


def _copyright_assessment(data: dict[str, Any]) -> dict[str, Any]:
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    signals: list[str] = []
    if data.get("type") in GENERATION_RAG_BLOCKED_TYPES:
        signals.append("blocked_asset_type")
    if metadata.get("use_in_generation_rag") is False or content.get("use_in_generation_rag") is False:
        signals.append("explicit_generation_rag_denied")
    asset_status = str(metadata.get("asset_status") or content.get("asset_status") or "").strip().lower()
    if asset_status == "stale":
        signals.append("stale_source_governance")
    if asset_status in {"quarantined", "quarantine"}:
        signals.append("quarantined_asset")
    source_repair_status = str(metadata.get("source_diff_repair_status") or content.get("source_diff_repair_status") or "").strip().lower()
    if source_repair_status.startswith("stale"):
        signals.append("source_diff_repair_stale")
    source_eligibility = content.get("source_eligibility") if isinstance(content.get("source_eligibility"), dict) else {}
    if bool(metadata.get("quarantine") or content.get("quarantine") or source_eligibility.get("quarantine")):
        signals.append("source_quarantine")
    risk_values = [
        metadata.get("copyright_risk"),
        metadata.get("risk_level"),
        metadata.get("license_risk"),
        metadata.get("commercial_risk"),
        content.get("copyright_risk"),
        content.get("risk_level"),
        content.get("license_risk"),
        content.get("commercial_risk"),
    ]
    normalized_risks = [_normalize_risk(value) for value in risk_values if str(value or "").strip()]
    risk_level = _max_risk(normalized_risks) if normalized_risks else "unknown"
    if risk_level in COPYRIGHT_BLOCKING_RISKS:
        signals.append(f"{risk_level}_copyright_risk")
    license_name = " ".join(str(value or "").lower() for value in [metadata.get("license"), metadata.get("license_name"), content.get("license"), content.get("source_license")])
    if any(marker in license_name for marker in ["non-commercial", "noncommercial", "cc by-nc", "by-nc", "nc-sa"]):
        risk_level = _max_risk([risk_level, "high"])
        signals.append("non_commercial_license")
    if any(signal in {"quarantined_asset", "source_quarantine"} for signal in signals):
        risk_level = _max_risk([risk_level, "high"])
    elif any(signal in {"stale_source_governance", "source_diff_repair_stale"} for signal in signals):
        risk_level = _max_risk([risk_level, "medium"])
    eligible = not signals or not any(
        signal
        in {
            "blocked_asset_type",
            "explicit_generation_rag_denied",
            "high_copyright_risk",
            "non_commercial_license",
            "stale_source_governance",
            "quarantined_asset",
            "source_diff_repair_stale",
            "source_quarantine",
        }
        for signal in signals
    )
    return {
        "eligible": eligible,
        "risk_level": risk_level,
        "reason": "eligible for generation RAG" if eligible else "; ".join(signals),
        "signals": signals,
    }


def _expected_buckets_for_input(asset_type: str) -> list[str]:
    if asset_type in {"chapter_plan", "draft_chapter", "draft_version", "review_report", "revision_plan"}:
        return ["characters", "worldbuilding", "previous_summaries", "knowledge_cards", "foreshadowing", "material_cards", "writing_templates"]
    if asset_type in {"outline", "outline_version"}:
        return ["characters", "worldbuilding", "knowledge_cards", "material_cards", "writing_templates"]
    return ["knowledge_cards", "material_cards"]


def _filtered_bucket_counts(filtered_assets: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in filtered_assets:
        for bucket in TYPE_BUCKETS.get(str(item.get("type", "")), []):
            counts[bucket] = counts.get(bucket, 0) + 1
    return counts


def _bucket_recommendation(bucket: str) -> str:
    labels = RAG_BUCKETS.get(bucket, bucket)
    return f"Add or bind project-scoped {labels} assets before generation if this chapter depends on that dimension."


def _query_terms(query: str) -> list[str]:
    terms: list[str] = []
    for raw in str(query or "").replace("\n", " ").replace(",", " ").replace("，", " ").split():
        term = raw.strip().lower()
        if len(term) >= 2 and term not in terms:
            terms.append(term)
        if len(terms) >= 24:
            break
    return terms


def _matched_query_terms(query: str, data: dict[str, Any], summary: str) -> list[str]:
    haystack = json.dumps({"title": data.get("title", ""), "tags": data.get("tags", []), "summary": summary}, ensure_ascii=False).lower()
    return [term for term in _query_terms(query) if term in haystack][:12]


def _normalize_risk(value: Any) -> str:
    risk = str(value or "unknown").strip().lower().replace("_", "-")
    if risk in {"low", "medium", "high", "unknown"}:
        return risk
    if risk in {"non-commercial", "noncommercial", "restricted", "blocked"}:
        return "high"
    return "unknown"


def _max_risk(values: list[str]) -> str:
    if not values:
        return "unknown"
    return max((_normalize_risk(value) for value in values), key=lambda value: COPYRIGHT_RISK_ORDER.get(value, 1))


def _default_query(asset: BaseAsset) -> str:
    payload = {
        "type": asset.type,
        "title": asset.title,
        "tags": asset.tags,
        "source": asset.source,
        "content": asset.content,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _categories_for_asset(data: dict[str, Any]) -> list[str]:
    buckets = list(TYPE_BUCKETS.get(str(data.get("type", "")), []))
    searchable = json.dumps(
        {
            "title": data.get("title", ""),
            "tags": data.get("tags", []),
            "content": data.get("content", {}),
            "metadata": data.get("metadata", {}),
        },
        ensure_ascii=False,
        sort_keys=True,
    ).lower()
    if any(term.lower() in searchable for term in FORESHADOWING_TERMS):
        buckets.append("foreshadowing")
    return _dedupe([bucket for bucket in buckets if bucket in RAG_BUCKETS])


def _asset_context_summary(data: dict[str, Any]) -> str:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    summary_fields = []
    for key in [
        "summary",
        "setting",
        "rules",
        "role",
        "external_goal",
        "internal_need",
        "motivation_chain",
        "principles",
        "usable_patterns",
        "template_kind",
        "structure",
        "usage_constraints",
        "anti_copy_rules",
        "craft_domain",
        "pattern",
        "use_cases",
        "risks",
        "do_not_copy",
        "chapter_states",
        "continuity_threads",
        "open_issues",
        "hook",
        "beats",
        "text",
    ]:
        if key in content:
            summary_fields.append({key: content[key]})
    payload = summary_fields if summary_fields else content
    return _compact_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), limit=500)


def _project_scope_for_asset(storage: LocalStorage, data: dict[str, Any], path: str = "", visited: set[str] | None = None) -> dict[str, str]:
    visited = visited or set()
    identity = path or str(data.get("id", ""))
    if identity:
        if identity in visited:
            return {"project_id": "", "workspace_id": "", "workspace_path": ""}
        visited.add(identity)
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    if data.get("type") == "project_workspace_state":
        return {
            "project_id": str(content.get("project_id") or data.get("id") or metadata.get("project_id", "")),
            "workspace_id": str(metadata.get("workspace_id") or data.get("id") or ""),
            "workspace_path": path or str(metadata.get("workspace_path", "")),
        }
    scope = {
        "project_id": str(metadata.get("project_id") or content.get("project_id") or ""),
        "workspace_id": str(metadata.get("workspace_id") or content.get("workspace_id") or ""),
        "workspace_path": str(metadata.get("workspace_path") or content.get("workspace_path") or ""),
    }
    if scope["project_id"] or scope["workspace_path"]:
        return scope
    for reference in data.get("references", []) if isinstance(data.get("references", []), list) else []:
        referenced = _read_reference(storage, str(reference))
        if referenced:
            ref_path, ref_data = referenced
            ref_scope = _project_scope_for_asset(storage, ref_data, ref_path, visited)
            if ref_scope.get("project_id") or ref_scope.get("workspace_path"):
                return ref_scope
    return scope


def _matches_project_scope(storage: LocalStorage, data: dict[str, Any], path: str, scope: dict[str, str]) -> bool:
    project_id = scope.get("project_id", "")
    workspace_path = scope.get("workspace_path", "")
    if not project_id and not workspace_path:
        return True
    candidate = _project_scope_for_asset(storage, data, path)
    return bool(
        (project_id and candidate.get("project_id") == project_id)
        or (workspace_path and candidate.get("workspace_path") == workspace_path)
        or (data.get("type") == "project_workspace_state" and path == workspace_path)
    )


def _read_reference(storage: LocalStorage, reference: str) -> tuple[str, dict[str, Any]] | None:
    reference = str(reference or "").strip()
    if not reference:
        return None
    candidate = storage.root / reference
    if not candidate.exists() and not reference.startswith("data/"):
        candidate = storage.data_root / reference
    if candidate.exists() and candidate.is_file():
        try:
            data = storage.read_json(candidate)
        except Exception:
            return None
        return (_relative_path(storage, candidate), data) if isinstance(data, dict) else None
    if "/" in reference or reference.endswith(".json"):
        return None
    for category in _candidate_categories_for_reference(reference):
        if category == "runs":
            continue
        for path in storage.list_json(category):
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            if reference in {str(data.get("id", "")), _relative_path(storage, path)}:
                return _relative_path(storage, path), data
    return None


def _candidate_categories_for_reference(reference: str) -> list[str]:
    value = str(reference or "").strip()
    categories: list[str] = []
    for asset_type, category in ASSET_DIR_BY_TYPE.items():
        prefix = asset_type.replace("_", "-")
        if value.startswith(f"{prefix}-"):
            categories.append(category)
    if value.startswith(("project-", "workspace-")):
        categories.append(ASSET_DIR_BY_TYPE.get("project_workspace_state", "workspaces"))
    return list(dict.fromkeys(categories))


def _ranker_name(items: list[dict[str, Any]]) -> str:
    rankers = _dedupe([str(item.get("ranker", "")) for item in items if str(item.get("ranker", "")).strip()])
    return "+".join(rankers) if rankers else "project-scoped-asset-priority"


def _rag_result_from_hybrid(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": str(item.get("path", "")),
        "chunk_path": str(item.get("chunk_path", "")),
        "source_asset_id": str(item.get("source_asset_id", "")),
        "score": float(item.get("score", 0.0) or 0.0),
        "ranker": str(item.get("backend", "") or "hybrid-local-projection"),
    }


def _memory_ranked_results(storage: LocalStorage, *, query: str, project_id: str, levels: list[str], limit: int) -> list[dict[str, Any]]:
    if not levels:
        return []
    try:
        from novel_forge.modules.long_memory import retrieve_memory

        report = retrieve_memory(storage, query=query, project_id=project_id, levels=levels, limit=limit, persist_report=False)
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for item in report.get("results", []) if isinstance(report.get("results", []), list) else []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "path": str(item.get("path", "")),
                "score": float(item.get("score", 0.0) or 0.0),
                "ranker": f"long_memory:{item.get('level', '')}",
            }
        )
    return rows


def _merge_ranked_results(primary: list[dict[str, Any]], memory: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_path: dict[str, dict[str, Any]] = {}
    for item in [*primary, *memory]:
        path = str(item.get("path", "")).strip()
        if not path:
            continue
        existing = by_path.get(path)
        if not existing or float(item.get("score", 0) or 0) > float(existing.get("score", 0) or 0):
            by_path[path] = item
    return sorted(by_path.values(), key=lambda row: (-float(row.get("score", 0) or 0), str(row.get("path", ""))))


def _normalized_memory_levels(levels: list[str] | None) -> list[str]:
    values = [str(item).strip().upper() for item in levels or [] if str(item).strip()]
    if not values:
        values = ["L0", "L1", "L2", "L3", "L4", "L5"]
    allowed = {"L0", "L1", "L2", "L3", "L4", "L5"}
    return [item for item in _dedupe(values) if item in allowed]


def _auto_backend_order() -> list[str]:
    raw = os.environ.get("NOVEL_FORGE_RAG_AUTO_ORDER", "")
    values = [item.strip().lower() for item in raw.split(",") if item.strip()] if raw else ["pgvector", "qdrant", "local"]
    order: list[str] = []
    for value in values:
        normalized = "pgvector" if value in {"postgres", "postgresql", "postgres_pgvector", "pgvector_online"} else value
        if normalized in {"pgvector", "hybrid", "qdrant", "local"} and normalized not in order:
            order.append(normalized)
    return order or ["pgvector", "qdrant", "local"]


def _normalize_backend(value: str) -> str:
    backend = str(value or "auto").strip().lower()
    if backend not in RAG_BACKENDS:
        raise ValueError(f"RAG backend must be one of: {', '.join(sorted(RAG_BACKENDS))}")
    return backend


def _relative_path(storage: LocalStorage, path: str | Path | None) -> str:
    if path is None:
        return ""
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = storage.root / resolved
    try:
        return str(resolved.resolve().relative_to(storage.root))
    except ValueError:
        return str(resolved)


def _compact_text(text: str, limit: int) -> str:
    compact = " ".join(str(text).split())
    return compact if len(compact) <= limit else compact[: limit - 3] + "..."


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
